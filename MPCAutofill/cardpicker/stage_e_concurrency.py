"""
Stage E Phase 2 companion - streaming dispatch concurrency cap (docs/features/stage-e-operations.md;
Tron gate round 1 on PR #448, "COMPANION" item). Caps the number of CONCURRENTLY-EXECUTING
`stage_e_dispatch.dispatch_micro_batch` calls, across every django-q2 worker PROCESS
(`Q_CLUSTER["workers"] = 8`, `MPCAutofill/settings.py`), to `settings.STAGE_E_MAX_CONCURRENT_
DISPATCHES` (default 2).

INCIDENT THIS ADDRESSES (2026-07-24 shakedown, distinct from PR #448's own vote-collision fix - see
that PR's own `local_calculate_verdicts._split_new_printing_tag_votes` docstring for the full
incident writeup): the shakedown's first live run had eight concurrent dispatches - all seven
django-q2 workers plus the backstop sweep, or some overlapping mix thereof - each running CPU-bound
OCR/phash extraction at once, which tripped the envelope's own host-load bar
(`envtrip-20260724T214616-be6e5db9`, observed load 11.85 against the 7.0 ceiling) 0.43s AFTER a
vote had already landed. This host has only 7 USABLE compute cores (1 of 8 OCPU is pinned to
network traffic - `docs/features/catalog-completion-plan.md` L1794/2248/2366's own hardware
citation), and that same doc's own local micro-benchmark found CPU-bound OCR work under
oversubscribed threading/concurrency measures at 0.31x-slower-than-sequential (L2226) - eight
dispatches racing for seven cores is exactly the oversubscription shape that number warns against.

WHY A CAP, NOT JUST THE ENVELOPE: `operating_envelope.check_envelope` is REACTIVE - it only trips
AFTER a fresh signal sample crosses a bar, which is necessarily after the load has already spiked
(the incident's own trip landed 0.43s after the damage was done). This module is PROACTIVE: it
refuses to even START a dispatch once its own slots are all held, so the host is never driven past
a bounded concurrency level in the first place. The two mechanisms are complementary, not
redundant - this module bounds HOW MANY dispatches can run at once; the envelope still catches
whatever load a bounded number of dispatches produces anyway (a single card's OCR pass taking
unusually long, a host already loaded by something outside Stage E entirely, etc.).

MECHANISM - Postgres session-scoped advisory locks (`pg_try_advisory_lock`/`pg_advisory_unlock`),
not a cache-based counter and not a dedicated low-worker django-q queue:

- A cache-based slot counter was rejected: this app's own cache backend is Django's default,
  per-PROCESS `LocMemCache` (`MPCAutofill/settings.py` has no `CACHES` override at all - the same
  fact `cardpicker.review_clusters`' own module docstring already establishes for a different
  feature, "the app runs a single gunicorn worker with Django's default (per-process) LocMemCache
  backend"). django-q2's 8 workers are separate OS PROCESSES (`multiprocessing`, not threads) - a
  cache-based counter would silently fail to coordinate across them, each process seeing its own
  empty cache. Adding a shared cache backend (Redis/Memcached) purely to make this primitive work
  would be new infrastructure this change has no mandate to introduce.
- A dedicated low-worker django-q queue (a second `Cluster` process pinned to a small worker count,
  exclusively for Stage E tasks) was rejected as disproportionate: it needs its own supervisor
  process/docker-compose service and deployment wiring, a much larger blast radius than a primitive
  enforced INSIDE `dispatch_micro_batch` itself, for a change whose whole point is a conservative,
  easily-tunable cap.
- A DB-row-based atomic counter (`UPDATE ... WHERE claimed_count < max_slots`) was considered and
  rejected in favor of advisory locks specifically for CRASH SAFETY: a `kill -9`'d worker process
  would leave a row-based counter's slot permanently "claimed" (nothing ties a table row to a
  process's lifetime), requiring a whole separate staleness-reconciliation mechanism to match this
  pipeline's own established "truthful ledger, idempotent re-entry, zero manual cleanup" ethos
  (`scripts/ops/crash_drill.sh`, `test_stage_e_dispatch.py`'s `TestKillSafetyResumeContract`). A
  Postgres SESSION-scoped advisory lock is tied to the underlying DB connection/session - the
  moment that connection dies (process killed, network drop), Postgres auto-releases every advisory
  lock that session held, with no reconciliation code needed. Postgres is also already the one
  piece of shared, process-visible state this pipeline guarantees present (the same reason
  `EnvelopeTrip` itself is a DB row, not a cache entry) - zero new infrastructure, zero new
  migration (this module defines no model).

CONNECTION-LIFECYCLE CONTRACT (2026-07-25 REWRITE - the ORIGINAL version of this section was WRONG,
see below): Postgres advisory locks are per-SESSION, so acquiring on one DB connection and releasing
on a DIFFERENT one is a no-op that leaks the lock. This module therefore holds its lock on a
DEDICATED `psycopg2` connection that IT ALONE owns for the duration of one `try_acquire_dispatch_
slot()` call - never `django.db.connection` (Django's shared per-thread connection proxy).

WHAT WENT WRONG IN PRODUCTION (2026-07-25T00:25Z shakedown, `envtrip-20260725T002504-73e1eb6d`,
`{'ceiling': 7.0, 'load_avg': 11.4013671875}`): the FIRST version of this module acquired and
released its advisory lock on `django.db.connection`, on the strength of a claim - made by direct
inspection of `django_q.worker` - that a single `dispatch_micro_batch` call always runs as one
uninterrupted segment on one connection. That claim was checked against the wrong code path.
`django_q.worker.close_old_django_connections()` (called only between tasks) was never the risk;
`django_q.brokers.orm.ORM.get_connection()` was. That method calls `django.db.close_old_connections()`
UNCONDITIONALLY whenever it's invoked outside an atomic block (`if transaction.get_autocommit(...)`),
and this project's `DATABASES["default"]` has no `CONN_MAX_AGE` override, so Django's own default (0)
applies - `BaseDatabaseWrapper.close_if_unusable_or_obsolete` treats `close_at = now + 0` as already
expired, so `close_old_connections()` closes `django.db.connection`'s underlying connection THE FIRST
TIME anything calls it, unconditionally, not just after some elapsed age. And something DOES call it
from squarely inside this module's own locked region: `cardpicker.stage_e_signals`'s `post_save`
receivers fire during Stage C's `persist_evidence` (INSIDE `dispatch_micro_batch`'s `with
try_acquire_dispatch_slot()` block) and call `django_q.tasks.async_task(...)`, which synchronously
calls `broker.enqueue(pack)` on the SAME thread/process - for the installed ORM broker, `enqueue`
calls `get_connection()` first, which closes the connection right then. A closed connection
auto-releases every advisory lock its session held (the same crash-safety property this module
relies on deliberately for a genuinely killed process), so the lock this module thought it was still
holding was gone mid-dispatch - EVERY worker then found EVERY slot "free", explaining the shakedown's
zero `throttled-concurrency-cap` outcomes despite eight concurrent dispatches, and the eight
`pg_advisory_unlock reported slot N was not held by this connection` warnings this module's own
defensive guard (`_release_slot`) logged when the final unlock ran against a since-reconnected
`django.db.connection` (Django transparently reopens a closed connection on next use, but that is a
NEW Postgres backend session - the unlock call executes there, not on the session that held the
lock).

THE FIX: hold the lock on a connection `stage_e_concurrency` opens for itself
(`psycopg2.connect(**connection.get_connection_params())`, `autocommit=True` so it's never left
idle-in-transaction and lock lifetime is tied to the session rather than any transaction this module
never starts) and NOTHING ELSE ever touches - not django-q's broker, not `close_old_connections`, not
any other code in the process. That connection lives for exactly one `try_acquire_dispatch_slot()`
call: opened before the acquire, held across the whole `yield` (i.e. across all of Stage C/D, exactly
where the lock needs to survive), explicitly `pg_advisory_unlock`'d AND `close()`'d in a `finally` -
the explicit unlock is the fast/clean path, the `close()` is the crash-safety backstop that fires even
if the explicit unlock itself somehow fails (Postgres auto-releases every advisory lock a closing
session held, the exact mechanism this module's own crash-safety design already leans on for a
genuinely killed process - see the DB-row-counter rejection above). The "not held by this connection"
warning guard (`_release_slot`) is KEPT UNCHANGED, not removed - it is what caught this bug in the
first place (the 8 log lines in the incident evidence), and it should now never fire again; a report
of it firing again is a signal something ELSE has broken this contract.

FAIL-CLOSED ON CONNECTION-CREATION FAILURE: if opening the dedicated connection itself raises (DB
unreachable, connection pool/limit exhausted, etc.), `try_acquire_dispatch_slot()` yields `None` -
the same "throttled, do no work this call" signal an exhausted cap already produces - rather than
letting the dispatch proceed uncapped. An uncapped dispatch is exactly the failure this module exists
to prevent; a connection-creation failure is precisely the moment this module is LEAST able to
guarantee the cap holds, so it is also the moment to be most conservative. The cost is a spuriously
throttled micro-batch (picked up again by the next event or the backstop sweep, matching the existing
"throttled dispatch defers to the sweep" convention already documented in
docs/features/stage-e-operations.md) - a strictly cheaper failure mode than a repeat of this
incident.
"""

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg2

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# Arbitrary but fixed and greppable namespace for this module's own advisory locks - the two-int
# pg_try_advisory_lock(key1, key2) form is used (not the single-bigint form) so this namespace and
# the slot index are both legible directly in a live `pg_locks` query during on-call debugging,
# rather than one opaque packed bigint. Confirmed (via grep across cardpicker/) that no other code
# in this repo uses Postgres advisory locks today, so there is no existing namespace to collide
# with.
_LOCK_NAMESPACE = 0x53746745  # "StgE" read as hex digits, chosen for exactly that mnemonic value


def _slot_count() -> int:
    """
    Floors at 1 - `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` set to 0 or negative (a plausible ops
    typo, e.g. meant to disable Stage E via a different flag entirely) would otherwise make
    `_try_acquire_slot`'s own `range(_slot_count())` empty, so every call returns `None` - dispatches
    throttle FOREVER with no error, no envelope trip, and no visible signal beyond an ever-growing
    Stage C/D backlog. A `logger.warning` on clamp makes that typo visible instead of silent.
    """
    configured = getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2)
    if configured < 1:
        logger.warning(
            "stage_e_concurrency: STAGE_E_MAX_CONCURRENT_DISPATCHES=%s is below the floor of 1 - "
            "clamping to 1 slot instead of throttling every dispatch forever",
            configured,
        )
        return 1
    return configured


def _open_dedicated_connection() -> "psycopg2.extensions.connection":
    """
    Opens a NEW `psycopg2` connection this module alone owns for the lifetime of one
    `try_acquire_dispatch_slot()` call - see the module docstring's "CONNECTION-LIFECYCLE CONTRACT"
    section for the full incident this replaces `django.db.connection` to fix (django-q2's ORM
    broker calls `django.db.close_old_connections()` - which, with `CONN_MAX_AGE` unset, closes the
    connection UNCONDITIONALLY - from squarely inside this module's own locked region whenever a
    follow-on dispatch is enqueued via `async_task`).

    Connection PARAMETERS are read from Django's own `django.db.connection`
    (`connection.get_connection_params()`, calling `connection.ensure_connection()` first since
    `get_connection_params()` alone doesn't establish one) - not a separately-guessed host/port/
    dbname - so this always targets whatever database Django itself is actually configured against,
    including test-run database-name prefixing. `autocommit=True`: advisory locks are independent of
    transactions, and leaving this connection in Postgres's default (non-autocommit) mode would hold
    an idle-in-transaction session open for the whole dispatch for no reason, and would tie this
    lock's release semantics to a commit/rollback this module never issues.
    """
    connection.ensure_connection()
    params = connection.get_connection_params()
    raw = psycopg2.connect(**params)
    raw.autocommit = True
    return raw


def _try_acquire_slot(conn: "psycopg2.extensions.connection") -> Optional[int]:
    """
    Tries every slot index in `[0, _slot_count())` in ascending order, on the given (dedicated)
    connection, returning the first one whose `pg_try_advisory_lock` call succeeds, or `None` if
    every slot is already held elsewhere. Never blocks - `pg_try_advisory_lock` is non-blocking by
    design (unlike the plain `pg_advisory_lock`, which would queue), matching this primitive's own
    "refuse immediately, never queue" posture - the same posture `operating_envelope.check_envelope`
    already established for the envelope itself (a busy host should shed load, not build a backlog of
    blocked dispatches waiting for a slot).
    """
    with conn.cursor() as cursor:
        for slot in range(_slot_count()):
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, slot])
            (acquired,) = cursor.fetchone()
            if acquired:
                return slot
    return None


def _release_slot(conn: "psycopg2.extensions.connection", slot: int) -> None:
    """Releases a slot this process previously acquired via `_try_acquire_slot` - MUST run on the
    SAME dedicated connection the acquire happened on (see module docstring's own
    "CONNECTION-LIFECYCLE CONTRACT" section). Logs rather than raises if Postgres reports the lock
    wasn't held (`pg_advisory_unlock` returns `false`, never an error, for that case) - KEPT
    UNCHANGED from the pre-fix version deliberately: this is the exact guard that caught the
    production incident (2026-07-25T00:25Z shakedown, 8 occurrences) this rewrite fixes, and it
    should now never fire again - a fresh report of it firing is a signal that something else has
    broken the dedicated-connection contract, not something to remove because "the incident is
    fixed now"."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_LOCK_NAMESPACE, slot])
        (released,) = cursor.fetchone()
    if not released:
        logger.warning(
            "stage_e_concurrency: pg_advisory_unlock reported slot %s was not held by this "
            "connection - possible connection recycling mid-dispatch",
            slot,
        )


@contextmanager
def try_acquire_dispatch_slot() -> Iterator[Optional[int]]:
    """
    The primitive `stage_e_dispatch.dispatch_micro_batch` calls. Yields the acquired slot index (an
    `int` in `[0, settings.STAGE_E_MAX_CONCURRENT_DISPATCHES)`), or `None` if every slot was already
    held (or the dedicated connection itself couldn't be opened - see "FAIL-CLOSED ON
    CONNECTION-CREATION FAILURE" in the module docstring) - the caller is expected to treat `None` as
    "throttled, do no work this call", the same posture `current_trip() is not None` already gets in
    `dispatch_micro_batch`'s own no-self-resume gate.

    Opens a DEDICATED connection for this call (`_open_dedicated_connection`) and ALWAYS closes it on
    exit, in a `finally`, whether the `with` block raises or not, and whether or not a slot was ever
    acquired - a dispatch that crashes mid-batch must not leak either the slot or the connection.
    Explicitly `pg_advisory_unlock`s before closing (the fast/clean path, and what makes
    `_release_slot`'s "not held" warning guard meaningful); the `close()` itself is the crash-safety
    backstop - Postgres auto-releases every advisory lock a closing session held, so even if the
    explicit unlock somehow failed to run, closing the connection still frees the slot.
    """
    try:
        conn = _open_dedicated_connection()
    except Exception:
        logger.exception(
            "stage_e_concurrency: failed to open the dedicated advisory-lock connection - "
            "failing CLOSED (treating this dispatch as throttled) rather than proceeding uncapped"
        )
        yield None
        return

    slot: Optional[int] = None
    try:
        slot = _try_acquire_slot(conn)
        yield slot
    finally:
        try:
            if slot is not None:
                _release_slot(conn, slot)
        finally:
            conn.close()
