"""
THE GLOBAL (cross-process) fetch-rate budget - the enforcement half of the owner clarification of
2026-07-30: "the 7 fetches per second cap is a global cap, it shouldn't be per process or per
core".

WHAT WAS WRONG. `harvest_fetch_limiter._DestinationLimiter` paces with a `threading.Lock` and a
process-local `_next_allowed`, so `GOOGLE_IMAGE.rate_per_sec = 7.0` bought 7/s PER PROCESS:

  * the pooled runner (`run_image_evidence_cohort`) is single-process, so it was correct by
    accident - one limiter, one process, a genuine 7/s;
  * the conveyor is not. django-q2 workers are separate OS PROCESSES (`multiprocessing`, not
    threads - `stage_e_concurrency`'s own docstring establishes this for the concurrency cap), so
    each worker constructs its OWN limiter from the module-level registry in ITS OWN address space
    and paces independently. N concurrent dispatches therefore issued N x 7/s. At the production
    `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES = 2` that is 14/s against a 7/s ruling, and it
    scales with the cap.

This is the same per-process trap as `threading.Semaphore(config.max_concurrency)` - which this
project has now been bitten by twice, and which PR #589 deleted a false ceiling term from
`stage_e_batch_sizing` over. PR #644 established that "the rate limit, not the concurrency limit,
is what actually protects the destination", which is exactly what makes the rate limit's
GLOBALITY the load-bearing property rather than a refinement.

MECHANISM - one Postgres row per destination (`cardpicker.models.GlobalFetchPace`), advanced by a
single atomic `UPDATE ... RETURNING`:

    UPDATE cardpicker_globalfetchpace
       SET next_allowed_at = GREATEST(clock_timestamp(), next_allowed_at) + <interval>
     WHERE destination = %s
    RETURNING next_allowed_at, clock_timestamp(), backoff_multiplier

That is the SAME arithmetic `_DestinationLimiter.acquire()` already did in Python
(`next_allowed = max(now, next_allowed) + interval`), lifted verbatim into the one place every
process can see. The statement returns the slot this caller claimed; the caller then sleeps until
it LOCALLY, holding no lock and no transaction while it waits.

WHY THIS IS ATOMIC ACROSS PROCESSES, which is the whole correctness claim: two concurrent UPDATEs
against the same row serialise on Postgres's own row lock, and under READ COMMITTED (Django's
default) the blocked statement RE-EVALUATES its SET expression against the committed new row
version once it acquires the lock. So the second writer reads the first writer's advanced
`next_allowed_at`, not the stale one it originally saw, and adds its own interval on top. The
reservations therefore form a single strictly-increasing sequence spaced by the interval, no
matter how many processes are competing. Nothing here is advisory or best-effort.

WHY A ROW RATHER THAN `stage_e_concurrency`'s ADVISORY LOCKS - the alternative the owner
explicitly asked to be evaluated first, since that module is this repo's established cross-process
primitive. It cannot carry a rate, and its own reasoning inverts here:

  * An advisory lock is a BINARY held/not-held token. It expresses "how many at once"
    (concurrency); it cannot express "how many per unit time", because a rate needs a remembered
    TIMESTAMP and a lock stores no value. The only way to fake it - hold each of N locks for
    exactly 1/R seconds - turns every fetching process into a sleeper occupying a Postgres session
    for the duration, and makes the rate a function of how long a lock is HELD rather than how
    often it is ACQUIRED. That is a worse primitive in every dimension.
  * `stage_e_concurrency` rejected a DB row for CRASH SAFETY: a `kill -9`'d worker leaves a
    row-based slot claimed forever, because nothing ties a row to a process's lifetime, whereas a
    session-scoped advisory lock is auto-released when the connection dies. That objection is
    about a CLAIM. This row holds no claim - only a timestamp. A process killed mid-reservation
    leaves `next_allowed_at` at most one interval in the future, self-healing in ~143ms at 7/s
    with zero reconciliation code. The exact property that made a row unsafe for a slot makes it
    correct for a pace.

Redis was not considered a real option: `docker/docker-compose.prod.yml` runs django, worker,
nginx, postgres and elasticsearch and NO Redis, and Django's cache here is the default per-PROCESS
`LocMemCache` (the same fact `stage_e_concurrency` and `cardpicker.review_clusters` both already
establish). Postgres is the one piece of shared, process-visible state this pipeline guarantees.

THE DATABASE'S CLOCK, NEVER PYTHON'S. Every timestamp in this module comes from
`clock_timestamp()`. This is load-bearing, not stylistic: `_DestinationLimiter` uses
`time.monotonic()`, whose epoch is PER PROCESS and meaningless to compare across processes.
Persisting one process's monotonic reading for another to read would silently reintroduce exactly
the defect this module exists to remove, while LOOKING coordinated. `clock_timestamp()` (not
`now()`/`CURRENT_TIMESTAMP`, which are transaction-start times and would hand every statement in a
transaction the same instant) is the one clock every process shares.

A DEDICATED, THREAD-CACHED CONNECTION. Reservations run on a `psycopg2` connection this module
opens for itself, cached per thread for the life of the process - NOT `django.db.connection`.
Two reasons, and the first is a correctness bug rather than a preference:

  1. TRANSACTION ISOLATION. The row lock a reservation takes is released when its transaction
     commits. On `django.db.connection`, a reservation made INSIDE a caller's `atomic()` block
     would hold that lock until the caller's whole transaction committed - serialising every other
     fetching process in the deployment behind one long transaction, converting a 143ms pace into
     an unbounded stall. On a dedicated `autocommit=True` connection the lock is released the
     instant the statement returns, always, regardless of what the calling code is doing.
  2. COST. Opening a connection per request would be absurd at 7/s x N processes; opening one per
     FETCH THREAD, once, is not. The cache is a `threading.local`, so each fetch thread (one for
     the conveyor, the pool size for `run_image_evidence_cohort`) pays a single connect for the
     life of the process. See `_thread_connection`.

FAIL-OPEN TO LOCAL PACING, NEVER FAIL-STOPPED. If the reservation cannot be made (database
unreachable, connection dies mid-statement), this module raises `RateBudgetUnavailable` and
`_DestinationLimiter` falls back to its own in-process pacer. That is a DEGRADATION - the ceiling
becomes per-process again, which is where this repo already was - and it is logged as an error,
but it does not fail or halt the run. This matches the owner's own standing requirement that a
process which cannot get rate budget WAITS rather than dying, and it matches PR #644's whole
posture: rate machinery degrades, it does not shut things down. Note this is the OPPOSITE choice
from `stage_e_concurrency`'s deliberate fail-CLOSED, and for a reason: an unavailable CONCURRENCY
cap means an unbounded number of dispatches can pile onto the host, so refusing is cheaper than
proceeding; an unavailable RATE budget still leaves every process paced at the configured ceiling
by its own local limiter, so the downside of proceeding is bounded and known, while refusing would
stop the pipeline outright over a transient database blip.
"""

import logging
import threading
from typing import Any, Optional

import psycopg2

from django.db import connection as django_connection

logger = logging.getLogger(__name__)


class RateBudgetUnavailable(Exception):
    """Raised when a reservation could not be made against the shared row - the caller
    (`harvest_fetch_limiter._DestinationLimiter.acquire`) is expected to fall back to its own
    in-process pacing and continue, never to fail or halt. See the module docstring's
    "FAIL-OPEN TO LOCAL PACING" section for why this degrades rather than stops."""


_TABLE = "cardpicker_globalfetchpace"

# One dedicated psycopg2 connection per THREAD, reused for that thread's whole life (module
# docstring's "A DEDICATED, THREAD-CACHED CONNECTION"). Not a pool and not per-request: the set of
# threads that ever fetch is small and long-lived (one fetch-ahead thread per conveyor dispatch,
# the fetch pool in `run_image_evidence_cohort`), so a `threading.local` gives one connect per
# thread rather than one per request, with no pool bookkeeping of its own.
_local = threading.local()

# Guards `_ensure_row`'s own "has this process already created the row" memo. The row creation is
# idempotent in SQL (`ON CONFLICT DO NOTHING`), so this is purely to skip a redundant round trip on
# every reservation after the first, not a correctness lock.
_ensured_lock = threading.Lock()
_ensured: set[str] = set()

# Every connection `_thread_connection` has ever opened, so `reset_for_tests` can close ALL of
# them, not just the calling thread's. Without this a test that drove reservations from worker
# threads left those threads' connections open after the threads themselves had exited, and
# Postgres refused to drop the test database ("is being accessed by other users") - a teardown
# failure in one test file that would surface as a confusing error in whichever file ran next.
# Production never needs this (fetch threads live as long as the process), but a registry that
# makes cleanup POSSIBLE costs one list append per thread.
_all_connections_lock = threading.Lock()
_all_connections: list[Any] = []

# Connection parameters, resolved ONCE per process and reused by every thread. Deliberately not
# re-read per thread: `django.db.connection` is itself thread-local, so touching it from a fetch
# thread OPENS A DJANGO CONNECTION on that thread which nothing will ever close (Django closes the
# request/task thread's connection, not an arbitrary worker's). In production those threads live as
# long as the process so the leak is bounded and invisible; in the test suite it left orphaned
# sessions behind and Postgres refused to drop the test database. Resolving the params once and
# never consulting Django's connection again from a fetch thread avoids the whole class of problem.
_params_lock = threading.Lock()
_params: Optional[dict[str, Any]] = None


def _thread_connection() -> "psycopg2.extensions.connection":
    """This thread's dedicated autocommit connection, opened on first use and reused thereafter.

    Connection PARAMETERS come from Django's own connection (`get_connection_params()`, after
    `ensure_connection()` since the params alone don't establish one) rather than separately-
    guessed settings, so this always targets whatever database Django is actually configured
    against - including a test run's prefixed database name. Same discipline
    `stage_e_concurrency._open_dedicated_connection` already established.

    `autocommit=True` is the load-bearing setting, not a tidiness one: it is what guarantees the
    row lock a reservation takes is released the moment the statement returns, rather than being
    held for the lifetime of whatever transaction the calling code happens to be inside (module
    docstring, "TRANSACTION ISOLATION").

    A connection that has been closed underneath us (database restart, network drop, idle
    timeout) is detected via `conn.closed` and transparently replaced - a fetch thread that has
    been alive for hours must not start failing every reservation because of one blip.
    """
    conn: Optional[Any] = getattr(_local, "conn", None)
    if conn is not None and not conn.closed:
        return conn
    raw = psycopg2.connect(**_connection_params())
    raw.autocommit = True
    _local.conn = raw
    with _all_connections_lock:
        _all_connections.append(raw)
    return raw


def _connection_params() -> dict[str, Any]:
    """Django's own connection parameters, resolved once per process and cached.

    Read from `django.db.connection.get_connection_params()` rather than separately-guessed
    settings so this always targets whatever database Django is actually configured against -
    including a test run's prefixed database name, which is written into `settings_dict` by the
    test runner before any of this executes. Same discipline
    `stage_e_concurrency._open_dedicated_connection` established, with one deliberate difference:
    NO `ensure_connection()` call. That would open a Django connection on whichever thread happened
    to ask first, and Django connections are thread-local with nothing to close a fetch thread's
    (see `_params`' own comment). `get_connection_params()` reads `settings_dict` and needs no live
    connection of its own."""
    global _params
    if _params is not None:
        return _params
    with _params_lock:
        if _params is None:
            _params = django_connection.get_connection_params()
    return _params


def _discard_thread_connection() -> None:
    """Drops this thread's cached connection after an error, so the NEXT reservation opens a fresh
    one instead of retrying forever against a connection that is already broken."""
    conn = getattr(_local, "conn", None)
    _local.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - closing a already-broken connection must never mask the
            # original failure that got us here.
            pass


def _ensure_row(conn: "psycopg2.extensions.connection", destination: str) -> None:
    """Creates this destination's row if it does not exist yet, idempotently and racelessly
    (`ON CONFLICT DO NOTHING` - two processes starting at the same instant both issue this and
    exactly one wins, with neither raising). `next_allowed_at` seeds to `clock_timestamp()`, i.e.
    "the next request may go immediately", so a fresh deployment does not pay a phantom wait.

    Memoised per process so this costs one extra round trip on the first reservation only, never
    on the 230,752 after it."""
    if destination in _ensured:
        return
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {_TABLE} (destination, next_allowed_at, backoff_multiplier, clean_streak) "
            "VALUES (%s, clock_timestamp(), 1.0, 0) ON CONFLICT (destination) DO NOTHING",
            [destination],
        )
    with _ensured_lock:
        _ensured.add(destination)


def reserve_slot(destination: str, base_interval_seconds: float) -> float:
    """
    Claim this caller's place in the GLOBAL request sequence for `destination`, and return how
    many seconds it must wait before issuing its request. The caller sleeps that long itself,
    holding nothing.

    The reservation is one atomic statement (module docstring): it advances the shared
    `next_allowed_at` by one interval and returns the slot it just claimed. Concurrent callers in
    ANY process serialise on the row lock and each get a distinct, correctly-spaced slot.

    `base_interval_seconds` is `1 / rate_per_sec` WITHOUT the backoff multiplier - the multiplier
    lives in the row and is applied in SQL, so every process paces by the same agreed value (see
    `GlobalFetchPace`'s own docstring for why a global rate ceiling requires a global backoff
    term). A returned wait is never negative: a caller that has fallen behind the shared sequence
    proceeds immediately rather than being handed a nonsensical negative sleep.

    Raises `RateBudgetUnavailable` if the reservation could not be made - see the module
    docstring's "FAIL-OPEN TO LOCAL PACING" section; the caller degrades to local pacing and keeps
    going, it never fails or halts.
    """
    try:
        conn = _thread_connection()
        _ensure_row(conn, destination)
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {_TABLE} "
                "   SET next_allowed_at = GREATEST(clock_timestamp(), next_allowed_at) "
                "                       + (%s * backoff_multiplier) * INTERVAL '1 second' "
                " WHERE destination = %s "
                "RETURNING EXTRACT(EPOCH FROM (next_allowed_at - clock_timestamp())) "
                "        - (%s * backoff_multiplier)",
                [base_interval_seconds, destination, base_interval_seconds],
            )
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - every failure mode degrades identically, see docstring
        _discard_thread_connection()
        raise RateBudgetUnavailable(f"could not reserve a global rate slot for {destination}: {exc}") from exc

    if row is None:
        # The row vanished between `_ensure_row` and the UPDATE (someone truncated the table). Drop
        # the memo so the next call recreates it, and degrade this one request to local pacing.
        with _ensured_lock:
            _ensured.discard(destination)
        raise RateBudgetUnavailable(f"no {_TABLE} row for {destination} - it was created and then removed")

    # `next_allowed_at` in RETURNING is the POST-update value (this caller's slot PLUS one
    # interval), so subtracting the interval back off yields the wait until this caller's OWN slot.
    return max(0.0, float(row[0]))


def record_backoff(destination: str, factor: float, ceiling: float) -> Optional[float]:
    """Multiply the SHARED backoff multiplier (capped at `ceiling`) and reset the shared clean
    streak - the global half of `_DestinationLimiter.backoff()`. A 429 observed by ONE process
    must slow every process, or the shared `next_allowed_at` is being advanced by intervals the
    processes disagree about and the effective rate is whatever the least-backed-off process
    believes.

    Returns the new multiplier, or `None` if the update could not be made (the caller keeps its
    own local multiplier and continues - same degradation posture as `reserve_slot`)."""
    return _update_multiplier(
        destination,
        "SET backoff_multiplier = LEAST(backoff_multiplier * %s, %s), clean_streak = 0",
        [factor, ceiling],
    )


def record_clean_response(destination: str, streak_target: int, floor: float) -> Optional[float]:
    """Advance the SHARED clean streak and, once it reaches `streak_target`, halve the shared
    multiplier (floored at `floor`) and reset the streak - the global half of
    `_DestinationLimiter.note_clean_response()`.

    The streak MUST be shared, not per-process, for the same reason the multiplier is: N processes
    each counting their own streak would reach the target N times over and decay the shared
    multiplier N times faster than the single agreed schedule intends, quietly accelerating
    recovery in exactly the situation (many workers, sustained pressure) where it should be
    slowest. Done in one atomic statement so two processes crossing the threshold together cannot
    both halve.

    Returns the current multiplier, or `None` if the update could not be made."""
    return _update_multiplier(
        destination,
        "SET clean_streak = CASE WHEN backoff_multiplier <= %s THEN 0 "
        "                        WHEN clean_streak + 1 >= %s THEN 0 "
        "                        ELSE clean_streak + 1 END, "
        "    backoff_multiplier = CASE WHEN backoff_multiplier > %s AND clean_streak + 1 >= %s "
        "                              THEN GREATEST(backoff_multiplier / 2.0, %s) "
        "                              ELSE backoff_multiplier END",
        [floor, streak_target, floor, streak_target, floor],
    )


def _update_multiplier(destination: str, set_clause: str, params: list[Any]) -> Optional[float]:
    """Shared plumbing for the two mutators above - one atomic UPDATE returning the resulting
    multiplier, degrading to `None` (never raising at the caller) on any failure."""
    try:
        conn = _thread_connection()
        _ensure_row(conn, destination)
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {_TABLE} {set_clause} WHERE destination = %s RETURNING backoff_multiplier",
                [*params, destination],
            )
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - degrade, never raise into the fetch path
        _discard_thread_connection()
        logger.exception("harvest_rate_budget: could not update the shared backoff state for %s", destination)
        return None
    return None if row is None else float(row[0])


def current_state(destination: str) -> Optional[tuple[float, int]]:
    """`(backoff_multiplier, clean_streak)` for this destination, or `None` if there is no row yet.
    Read-only observability for tests and on-call inspection - nothing in the fetch path calls
    this."""
    try:
        conn = _thread_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT backoff_multiplier, clean_streak FROM {_TABLE} WHERE destination = %s", [destination]
            )
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001
        _discard_thread_connection()
        return None
    return None if row is None else (float(row[0]), int(row[1]))


def reset_for_tests() -> None:
    """Test-only: drops this process's row-existence memo and closes EVERY connection this module
    has opened on any thread, so a test that truncated the table (or swapped databases) starts
    clean and Postgres can actually drop the test database afterwards. Mirrors
    `harvest_fetch_limiter.reset_limiters`' own purpose for the in-process registry.

    Closing all of them, not just the calling thread's, is the point: a test that drove
    reservations from worker threads leaves those threads' connections open after the threads have
    exited, and the test-database teardown then fails with "is being accessed by other users"."""
    global _params
    with _ensured_lock:
        _ensured.clear()
    with _params_lock:
        _params = None
    _local.conn = None
    with _all_connections_lock:
        connections, _all_connections[:] = list(_all_connections), []
    for conn in connections:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - a connection that is already gone is already clean
            pass


__all__ = [
    "RateBudgetUnavailable",
    "current_state",
    "record_backoff",
    "record_clean_response",
    "reserve_slot",
    "reset_for_tests",
]
