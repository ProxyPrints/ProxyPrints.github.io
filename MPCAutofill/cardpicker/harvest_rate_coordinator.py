"""
CROSS-PROCESS rate ceiling for `harvest_fetch_limiter` - the globality half of the owner's
2026-07-30 rate ruling ("to be clear: the 7 fetches per second cap is a global cap, it shouldn't
be per process or per core").

THE DEFECT THIS FIXES. `harvest_fetch_limiter._DestinationLimiter` is a strict minimum-interval
pacer whose entire state - `_next_allowed`, the `threading.Lock` guarding it, the
`threading.Semaphore` bounding concurrency - lives in ONE Python process's memory. That is a
genuine ceiling for the pooled runner (`run_image_evidence_cohort`, a single process with a thread
pool), and it is NOT a ceiling for the conveyor: `stage_e_dispatch.dispatch_micro_batch` runs under
django-q2, whose workers are separate OS PROCESSES (`multiprocessing`, not threads -
`Q_CLUSTER["workers"]`, `MPCAutofill/settings.py`). Each such process imports this module fresh,
builds its own `_DestinationLimiter`, and paces itself in isolation. N concurrent dispatches
therefore fetch at N x `rate_per_sec`. At the production `STAGE_E_MAX_CONCURRENT_DISPATCHES = 2`
that is 14/s against a ratified 7/s, and it SCALES WITH THE CAP - raising the dispatch cap silently
raises the destination rate.

This is the third appearance of the same per-process trap in this subsystem (the `threading
.Semaphore(config.max_concurrency)` concurrency bound has it too; `stage_e_concurrency`'s own module
docstring records the 2026-07-24 incident where a per-process assumption produced eight concurrent
dispatches). PR #644 concluded that "the rate limit, not the concurrency limit, is what protects the
destination" - which makes the rate limit's GLOBALITY the load-bearing property, and it was missing.

WHY NOT THE ADVISORY-LOCK PRIMITIVE AS-IS. `stage_e_concurrency` caps CONCURRENT DISPATCHES across
processes with Postgres session-scoped advisory locks (`pg_try_advisory_lock`, `_slot_count()`), and
that is this repo's established cross-process coordination mechanism. It was read first and it does
NOT carry a rate on its own, for a reason worth stating rather than working around: an advisory lock
is a pure MUTUAL-EXCLUSION primitive. It has no payload and no time dimension - it can answer "how
many are in flight right now" and nothing else. A rate is a value (a cursor) plus a clock, so it
needs somewhere to keep the value. The two shapes that CAN be built from advisory locks alone were
both considered and rejected:

  * "K slots, each held for K/rate seconds" turns the counting primitive into a rate correctly on
    paper, but the holder must BLOCK for the full hold time, so throughput is bounded by the
    fetching thread count rather than by the ceiling (6 fetch threads x a 1s hold = 6/s under a 7/s
    ceiling - it under-delivers), and it needs a live Postgres session per in-flight fetch.
  * An advisory lock used as a mutex around shared state still needs the shared state. That is the
    design below, minus the mutex: Postgres gives the mutual exclusion for free inside a single
    statement, so the lock buys nothing here.

WHAT THIS MODULE DOES INSTEAD - one atomic statement over a shared cursor. The per-process pacer's
own arithmetic (`_next_allowed = max(now, _next_allowed) + interval`) is exactly a cursor update.
Moving that ONE expression into Postgres makes it global, with no change to its semantics:

    INSERT ... ON CONFLICT (cache_key) DO UPDATE
      SET value = (GREATEST(now, stored) + interval)
    RETURNING GREATEST(0, value - interval - now)

`INSERT ... ON CONFLICT DO UPDATE` takes a row lock for the duration of that one statement, so the
read-modify-write is atomic against every other process and every other thread with zero extra
round trips - no advisory lock, no explicit transaction, no `SELECT ... FOR UPDATE` pair. The
statement returns the caller's own wait in seconds, computed entirely against POSTGRES's clock
(`clock_timestamp()`) so no two processes are comparing different monotonic epochs. The caller then
sleeps locally. One network round trip per fetch, total.

WHERE THE CURSOR LIVES - the existing `shared_cache` table, and deliberately NOT a new migration.
`settings.SHARED_CACHE_TABLE` (migration `0092_shared_cache_table`) already exists in production, in
CI and in every developer database, is created by the `migrate` that `docker/django/entrypoint.sh`
already runs, and its own migration docstring frames it as exactly this: cross-process state backed
by the existing Postgres, needing no new service. Adding a dedicated one-row table instead would
mean a new migration, and this repo's migration graph is actively contended (PR #611's CI guard
fails a graph that forks as merged with the base) - a new leaf is a real, avoidable merge hazard for
a single numeric value.

The cursor is written as a RAW numeric string under a key (`_CURSOR_KEY_PREFIX`) that Django's own
`BaseCache.make_key` can never produce - every Django cache key in that table is prefixed
`":<version>:"`. We therefore never collide with, and never have to unpickle, anything the `"shared"`
cache alias itself wrote; we are using the table as a generic Postgres key/value row, not as a
Django cache. The two ways Django could remove our row - `cache.clear()` (TRUNCATE) and
`DatabaseCache._cull` (only above `MAX_ENTRIES = 1000`, and this table holds a handful of entries) -
are both BENIGN: a missing row is re-INSERTed by the next reservation at "now", which costs at most
one extra immediately-allowed fetch, never a burst.

DEDICATED CONNECTION, NOT `django.db.connection`. Same reasoning `stage_e_concurrency` already
established, for a different consequence. This module must never run its statement inside a caller's
open transaction: `INSERT ... ON CONFLICT DO UPDATE` holds the cursor ROW LOCK until commit, so a
long-lived enclosing `atomic()` block anywhere on the fetch path would stall EVERY other fetching
process for the length of that transaction - a global rate ceiling that occasionally becomes a
global stop. Owning one autocommit `psycopg2` connection per process makes that structurally
impossible. It is one connection per process (not per thread) held for the process's life, guarded
by a `threading.Lock`: the extra Postgres connection count stays at 1 per fetching process rather
than 1 per fetch thread, and the serialisation the lock adds costs nothing, because every thread is
contending for the same cursor row inside Postgres anyway. Connection parameters come from Django's
own `connection.get_connection_params()`, so this follows test-database prefixing automatically.

FAILURE MODE - DEGRADE, NEVER FAIL OPEN AND NEVER FAIL CLOSED. If the coordination store is
unreachable mid-run, `reserve()` returns `None` and the caller falls back to its per-process pacer
running at `rate / _degraded_divisor()` - i.e. the configured ceiling divided by the maximum number
of processes that can be fetching at once. Rationale:

  * FAIL OPEN (per-process pacing at the full rate) is precisely the defect this module exists to
    remove - it would restore N x 7/s at the exact moment nothing is watching.
  * FAIL CLOSED (refuse to fetch) kills a 230,753-card unattended pass over a transient blip, and
    contradicts the ruling's own "throttle, do not shut it down".
  * DIVIDING is the only option that keeps the aggregate ceiling intact WITHOUT a halt: worst case
    every process is fetching, and N processes x rate/N = rate. The cost is that the run fetches
    more slowly than it strictly could while coordination is down - which is a cost paid exactly
    when the database is already unhealthy, i.e. when Stage C cannot persist evidence anyway, so
    slowing the fetch side is not the binding problem. A degraded reservation still WAITS; it never
    raises, never halts, and never feeds the operating envelope's fetch-failure window
    (requirement: rate pressure is throttled, not halted - PR #644).

The divisor is DERIVED, not a new knob (owner: "default the default things, disable them with
flags"): `STAGE_E_MAX_CONCURRENT_DISPATCHES` bounds the conveyor's concurrent dispatch processes,
plus one for a pooled/manual runner (`run_image_evidence_cohort`, `stream_full_catalog`) which takes
no dispatch slot and can legitimately run alongside.

Failures are latched for `_DEGRADED_COOLDOWN_SECONDS` so a sustained outage costs one failed
connection attempt per cooldown rather than one per fetch, and are logged once per cooldown with a
running count rather than once per fetch.
"""

import logging
import os
import re
import threading
import time
from typing import Optional

import psycopg2

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# Key namespace for the per-destination cursor rows. Django's own `BaseCache.make_key` always emits
# `"<KEY_PREFIX>:<version>:<key>"`, so a key that starts with a letter and contains no leading colon
# can never be produced by the `"shared"` cache alias itself - we cannot collide with it, and it
# cannot hand our raw numeric string to `pickle.loads`.
_CURSOR_KEY_PREFIX = "harvest-rate-cursor:"

# How long a cursor row is kept alive. Only meaningful against `DatabaseCache._base_set`'s
# expired-row sweep (it deletes `WHERE expires < now` whenever anything else writes to this table);
# far enough out that a live run's cursor is never swept, and short enough that an abandoned
# destination's row does not outlive the code that wrote it forever.
_CURSOR_TTL_DAYS = 30

# After a coordination failure, skip the Postgres round trip entirely for this long and pace
# locally at the divided rate. Bounds both the cost and the log volume of a sustained outage; short
# enough that a transient blip costs at most this much degraded throughput.
_DEGRADED_COOLDOWN_SECONDS = 5.0

# Guards the identifier interpolated into the SQL below. `settings.SHARED_CACHE_TABLE` is a
# hardcoded literal today, but it is a setting, and a setting is interpolated into SQL here because
# a table name cannot be a bound parameter. Asserting the shape is cheaper than trusting it.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# The whole primitive, in one statement.
#
# * The VALUES row carries `now + gap`, so `EXCLUDED.value - gap` IS Postgres's own reading of "now"
#   for this call - available inside the conflict branch without evaluating `clock_timestamp()` a
#   second time, and without a CTE that `ON CONFLICT DO UPDATE` may not reference.
# * The SET expression is `GREATEST(now, stored) + gap` - byte-for-byte the pacer arithmetic
#   `_next_allowed = max(now, _next_allowed) + interval`, just evaluated where every process can see
#   it.
# * RETURNING yields THIS caller's wait: the cursor value it was handed, minus its own gap (that is
#   the instant it is cleared to fetch), minus now. Floored at zero. The `clock_timestamp()` in
#   RETURNING is evaluated a few microseconds after the one in VALUES, which can only shorten the
#   reported wait by that same few microseconds - it can never overstate the caller's budget.
# * `ON CONFLICT DO UPDATE` takes the row lock for the statement's duration, which is what makes the
#   read-modify-write atomic across processes without any explicit locking of our own.
_RESERVE_SQL = """
INSERT INTO {table} (cache_key, value, expires)
VALUES (
    %(key)s,
    (EXTRACT(EPOCH FROM clock_timestamp())::numeric + %(gap)s::numeric)::text,
    clock_timestamp() + %(ttl)s::interval
)
ON CONFLICT (cache_key) DO UPDATE SET
    value = (
        GREATEST(
            EXCLUDED.value::numeric - %(gap)s::numeric,
            {table}.value::numeric
        ) + %(gap)s::numeric
    )::text,
    expires = EXCLUDED.expires
RETURNING GREATEST(
    0::numeric,
    {table}.value::numeric - %(gap)s::numeric - EXTRACT(EPOCH FROM clock_timestamp())::numeric
)::float8
"""


_connection: Optional["psycopg2.extensions.connection"] = None
_connection_lock = threading.Lock()
_degraded_until = 0.0
_degraded_failures = 0


def _cursor_table() -> str:
    table = getattr(settings, "SHARED_CACHE_TABLE", "shared_cache")
    if not _SAFE_IDENTIFIER.match(table):
        raise ValueError(f"SHARED_CACHE_TABLE is not a bare SQL identifier: {table!r}")
    return table


def degraded_divisor() -> int:
    """The number the configured rate is divided by while coordination is unavailable - see the
    module docstring's "FAILURE MODE" section. Derived from `STAGE_E_MAX_CONCURRENT_DISPATCHES`
    (the conveyor's own cross-process cap on concurrently-executing dispatches) plus one for a
    pooled or manual runner, which holds no dispatch slot and can run alongside them. Never a new
    setting of its own: a second knob for the same fact would just be a way for the two to disagree.
    """
    dispatches = getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2)
    return max(1, dispatches) + 1


def _open_connection() -> "psycopg2.extensions.connection":
    """Opens the process's own autocommit `psycopg2` connection - see the module docstring's
    "DEDICATED CONNECTION" section for why this is never `django.db.connection`. Parameters are
    read from Django's own connection (`ensure_connection()` first, since `get_connection_params()`
    alone establishes nothing), so this always targets the database Django is configured against,
    including pytest-django's prefixed test database."""
    connection.ensure_connection()
    raw = psycopg2.connect(**connection.get_connection_params())
    raw.autocommit = True
    return raw


def _note_failure(exc: BaseException) -> None:
    global _degraded_until, _degraded_failures
    now = time.monotonic()
    _degraded_failures += 1
    if now >= _degraded_until:
        logger.warning(
            "harvest_rate_coordinator: cross-process rate coordination unavailable (%s: %s) - "
            "degrading to per-process pacing at 1/%d of the configured ceiling for the next %.0fs "
            "(%d failure(s) so far). The aggregate ceiling still holds; the run continues.",
            type(exc).__name__,
            exc,
            degraded_divisor(),
            _DEGRADED_COOLDOWN_SECONDS,
            _degraded_failures,
        )
    _degraded_until = now + _DEGRADED_COOLDOWN_SECONDS


def reserve(destination: str, interval_seconds: float) -> Optional[float]:
    """Reserves this caller's turn on the GLOBAL cursor for `destination` and returns how long it
    must wait, in seconds, before fetching (0.0 = go now).

    Returns `None` - never raises - when coordination is unavailable, which the caller must treat as
    "pace yourself locally at the divided rate" (see `degraded_divisor()`), NOT as a failure, a halt,
    or a fetch outcome. This is the only return value that is not a wait, and it is deliberately
    distinguishable from `0.0`.

    `interval_seconds` is the caller's CURRENT pacing gap - the configured `1 / rate_per_sec` already
    multiplied by whatever backoff the caller has accumulated. Backoff therefore stays per-process,
    exactly as PR #644 built it: a process that has seen a 429 widens its OWN contribution to the
    shared cursor, which can only ever slow the aggregate down, never speed it past the ceiling.
    """
    global _connection

    if time.monotonic() < _degraded_until:
        return None

    key = f"{_CURSOR_KEY_PREFIX}{destination}"
    params = {"key": key, "gap": interval_seconds, "ttl": f"{_CURSOR_TTL_DAYS} days"}
    sql = _RESERVE_SQL.format(table=_cursor_table())

    try:
        with _connection_lock:
            if _connection is None or _connection.closed:
                _connection = _open_connection()
            try:
                with _connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    (wait_seconds,) = cursor.fetchone()
            except psycopg2.Error:
                # A connection that died between calls (Postgres restart, idle timeout, network
                # blip) is the ordinary case here, and it is recoverable within this same call:
                # drop it, open a fresh one, run the statement once more. Anything that fails twice
                # falls through to the degraded path below.
                try:
                    _connection.close()
                except Exception:
                    pass
                _connection = _open_connection()
                with _connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    (wait_seconds,) = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see the module docstring
        _note_failure(exc)
        return None

    return float(wait_seconds)


def clear_cursor(destination: str) -> None:
    """Test/ops helper: forgets the shared cursor for one destination, so the next reservation
    starts from "now". Never raises - a coordination store that is unreachable has, from this
    function's point of view, already forgotten it."""
    global _connection

    try:
        with _connection_lock:
            if _connection is None or _connection.closed:
                _connection = _open_connection()
            with _connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {_cursor_table()} WHERE cache_key = %s",
                    [f"{_CURSOR_KEY_PREFIX}{destination}"],
                )
    except Exception:
        logger.debug("harvest_rate_coordinator: clear_cursor(%s) could not reach the store", destination)


def reset_connection() -> None:
    """Drops this process's dedicated connection (closing it properly) and clears the degraded
    latch. For tests between cases, and for any caller that wants a guaranteed-fresh session.

    NOT for a forked child - see `_forget_connection_after_fork` below for why closing an INHERITED
    connection is actively harmful."""
    global _connection, _degraded_until, _degraded_failures
    with _connection_lock:
        if _connection is not None:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None
    _degraded_until = 0.0
    _degraded_failures = 0


def _forget_connection_after_fork() -> None:
    """Registered as an `os.register_at_fork(after_in_child=...)` handler, because this subsystem's
    two real deployments BOTH fork: django-q2's `Cluster` forks its worker processes, and the pooled
    runner's own pool is a `multiprocessing` context away from doing the same.

    A forked child inherits the parent's connection OBJECT, pointing at a socket the PARENT still
    owns. Two processes writing down one libpq socket interleaves the wire protocol and corrupts
    both. The child must therefore ABANDON the object - and specifically must NOT `close()` it, the
    way `reset_connection` does: `PQfinish` sends a Terminate message to the server before closing
    the fd, which would kill the session the PARENT is still using. Dropping the reference and
    letting the child's copy of the fd close on exit is the correct disposal; the parent's session
    is untouched, and the child opens its own on its next reservation.

    Deliberately automatic rather than a documented obligation on callers: the failure it prevents
    is silent, intermittent, and looks like unrelated Postgres protocol errors, so "every fork site
    must remember" is not a contract worth relying on.

    `_connection_lock` is REPLACED, not reused: `fork()` clones only the calling thread, so a lock
    another thread happened to hold at fork time is inherited already-locked with no owner left
    alive to release it - the child would deadlock on its first reservation."""
    global _connection, _connection_lock, _degraded_until, _degraded_failures
    _connection = None
    _connection_lock = threading.Lock()
    _degraded_until = 0.0
    _degraded_failures = 0


os.register_at_fork(after_in_child=_forget_connection_after_fork)


__all__ = ["clear_cursor", "degraded_divisor", "reserve", "reset_connection"]
