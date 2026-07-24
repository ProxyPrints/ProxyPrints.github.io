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

CONNECTION-LIFECYCLE CONTRACT (why "same connection acquire-to-release" holds here): Postgres
advisory locks are per-SESSION, so acquiring on one DB connection and releasing on a DIFFERENT one
is a no-op that leaks the lock. `try_acquire_dispatch_slot` is a context manager that acquires and
releases within the SAME `with` block, using Django's own per-thread `django.db.connection` proxy
throughout - confirmed safe against django-q2's own connection-recycling behavior
(`django_q.worker.py`'s `close_old_django_connections()` call, which happens ONLY immediately
BEFORE the next task starts, never mid-task or between statements within one task) by direct
inspection of the installed `django-q2` package: a single `dispatch_micro_batch` call - and
therefore a single acquire/use/release cycle of this module - always executes as one uninterrupted
segment on one connection, whether triggered via a django-q `async_task` or a direct
`stream_backstop_sweep` command-line invocation.
"""

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

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
    return getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2)


def _try_acquire_slot() -> Optional[int]:
    """
    Tries every slot index in `[0, _slot_count())` in ascending order, returning the first one
    whose `pg_try_advisory_lock` call succeeds, or `None` if every slot is already held elsewhere.
    Never blocks - `pg_try_advisory_lock` is non-blocking by design (unlike the plain
    `pg_advisory_lock`, which would queue), matching this primitive's own "refuse immediately,
    never queue" posture - the same posture `operating_envelope.check_envelope` already
    established for the envelope itself (a busy host should shed load, not build a backlog of
    blocked dispatches waiting for a slot).
    """
    with connection.cursor() as cursor:
        for slot in range(_slot_count()):
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, slot])
            (acquired,) = cursor.fetchone()
            if acquired:
                return slot
    return None


def _release_slot(slot: int) -> None:
    """Releases a slot this process previously acquired via `_try_acquire_slot` - MUST run on the
    same `django.db.connection` the acquire happened on (see module docstring's own
    "CONNECTION-LIFECYCLE CONTRACT" section). Logs rather than raises if Postgres reports the lock
    wasn't held (`pg_advisory_unlock` returns `false`, never an error, for that case) - this would
    only happen if the underlying connection was somehow recycled mid-dispatch, a condition this
    module's own docstring argues shouldn't occur but that a release path should still fail soft
    against rather than crash an otherwise-successful dispatch over.
    """
    with connection.cursor() as cursor:
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
    held - the caller is expected to treat `None` as "throttled, do no work this call", the same
    posture `current_trip() is not None` already gets in `dispatch_micro_batch`'s own no-self-resume
    gate. ALWAYS releases whatever it acquired on exit, including when the `with` block raises -
    a dispatch that crashes mid-batch must not permanently strand a slot (this module's own crash
    line of defense is the connection-level auto-release described in the module docstring; this
    `finally` is the FAST path for the ordinary "dispatch finished, successfully or not, without the
    whole process dying" case).
    """
    slot = _try_acquire_slot()
    try:
        yield slot
    finally:
        if slot is not None:
            _release_slot(slot)
