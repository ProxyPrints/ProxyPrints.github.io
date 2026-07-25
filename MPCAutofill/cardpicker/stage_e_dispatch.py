"""
Stage E Phase 2 - the streaming dispatch loop (docs/proposals/stage-e-streaming.md, GitHub issue
#153; docs/features/stage-e-operations.md's "Phase 2" section is the operator-facing runbook this
module implements). Phase 1 (docs/proposals/stage-e-streaming.md's own header, PR #440,
`cardpicker/operating_envelope.py`) built the envelope PRIMITIVE with no caller - this module is
that caller: the CONVEYOR a card travels through once an event (card-create, evidence-change,
`cardpicker.stage_e_signals`) or the cron backstop sweep (`management/commands/
stream_backstop_sweep.py`) names it eligible.

SCOPE, per the owner-approved Phase 2 task brief: this module is the DISPATCH LOOP only - it NEVER
reimplements Stage C extraction, Stage D calculator decode logic, or consensus resolution. Every
actual decision (does this OCR read match a candidate, does this vote clear the human-backed gate)
still happens inside `cardpicker.image_evidence`/`cardpicker.local_calculate_verdicts`/
`cardpicker.printing_consensus` exactly as it does for BULK mode - this module only decides WHEN
and on WHICH cards to call those existing entry points, and records what happened. BULK-mode
commands (`run_image_evidence_cohort`, `local_calculate_verdicts`, `reparse_collector_evidence`,
`consensus_recompute`, etc.) are untouched and keep working exactly as before: none of their own
call sites pass the new `card_ids` scoping parameter `local_calculate_verdicts.py` gained for this
module's benefit (see that module's own docstring on `_eligible_cards_queryset`'s `card_ids`
parameter, `None` by default = unchanged behaviour), so BULK mode's own behaviour is byte-identical
to before this change.

DEFAULT-OFF (NOT IN SCOPE for this phase, per the task brief): `settings.STAGE_E_STREAMING_ENABLED`
gates every entry point below - `dispatch_micro_batch` is a no-op whenever it's False, and so is
every event trigger built on top of it (`cardpicker.stage_e_signals`) and the backstop sweep. Ships
default False (`MPCAutofill/settings.py`). Flipping it to True is the phase-3 shakedown's own
polled owner action - this change ships the mechanism, never turns it on.

NO SELF-RESUME (binding Tron-gate note from Phase 1's review, restated here since this is the first
caller that actually enforces it): `dispatch_micro_batch` checks `operating_envelope.current_trip()`
BEFORE doing any work and refuses to dispatch, full stop, whenever it returns non-None - no code
path in this module ever calls `acknowledge_trip` or otherwise clears a trip. Resume is
`resolve_envelope_trip`'s own management command, always a fresh, explicit owner action (see
docs/features/stage-e-operations.md's runbook) - never automatic, never from inside this module.

FETCH-FAILURE WINDOW SIZING (the second binding Tron-gate note): the rolling window this module
samples `fetch_failures_in_window`/`fetch_total_in_window` from is sized to
`operating_envelope.FETCH_FAILURE_WINDOW` (500) exactly - `check_envelope` computes its rate on
whatever it's handed, so getting this deque's `maxlen` right is entirely this module's own
responsibility, not that primitive's. See `_FetchOutcomeWindow` below. Process-local (module-level
singleton `_window`, one per worker process) - a multi-worker streaming deployment aggregating this
window across processes is a phase-3 operational concern, not a Phase 2 design gap:
`operating_envelope.EnvelopeSignals`'s own docstring already documents the caller as owning
windowing, with no cross-process aggregation promised anywhere in the ratified design (§10(a) sizes
the window, it doesn't mandate a shared store).

PIPELINE STAGES, in order, per micro-batch (task brief scope item 5): Stage C extraction
(`cardpicker.image_evidence.compute_card_evidence`/`persist_evidence`, called per-card - see
`_run_stage_c`'s own docstring for its three phases: evidence-transfer check, then a decoupled
fetch-ahead thread feeding this function's own SEQUENTIAL compute loop, issue #472) -> Stage D
calculators (`cardpicker.local_calculate_verdicts.run_join_key_calculator`/`run_fallback_calculator`/
`run_slow_path_calculator`, called AS-IS with the new `card_ids` scope, in the same join-key ->
fallback -> slow-path escalation order every BULK-mode command already uses) -> ledger write.
COMPUTE is sequential, not pooled, on purpose: PASSIVE mode's own micro-batches (§3 decision (2), a
handful to a few dozen cards) are far too small for BULK mode's process-pool concurrency to buy
anything - it would only add a fork's worth of startup overhead per batch. This matches the
brief's own "a single-worker, single-core floor mode must be correct, just slow, never a
degraded/unsound mode" requirement (§5). FETCH, as of issue #472 (2026-07-25, the ratified §4 item
3 this Phase-2-era module originally shipped without - see `_run_stage_c`'s own docstring), is
OVERLAPPED with that same sequential compute loop via one fetch-ahead thread + a bounded queue -
this is deliberately NOT the same thing as pooling compute; only I/O-bound fetch-wait is
overlapped, the OCR/extraction work itself stays exactly as sequential as the paragraph above
requires.

CONSENSUS RECOMPUTE (decision (4)) NEEDS NO SEPARATE STEP HERE: all three Stage D calculators
already call `resolve_and_persist_printing(touched_card)` internally for every card they cast a
vote on (see e.g. `run_join_key_calculator`'s own final loop, unchanged by this module) - scoping
those calculators to the micro-batch via `card_ids` already scopes their consensus recompute calls
to exactly the same set, satisfying decision (4)'s "scoped incremental per-touch" requirement for
free. This module never imports `printing_consensus`/`vote_consensus`/`tag_consensus`/
`artist_consensus` (PROTECTED CORE) directly at all.
"""

import logging
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Iterable, Optional

from django.conf import settings
from django.utils import timezone

from cardpicker.checksum_pairing import card_sha256_checksum
from cardpicker.evidence_transfer import find_transfer_source, transfer_evidence
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.local_calculate_verdicts import (
    known_set_codes,
    run_fallback_calculator,
    run_join_key_calculator,
    run_slow_path_calculator,
)
from cardpicker.models import (
    Card,
    EnvelopeTrip,
    ImageEvidence,
    PilotRunLedger,
    StageESweepCursor,
    StageEThrottleCounter,
)
from cardpicker.operating_envelope import (
    FETCH_FAILURE_WINDOW,
    EnvelopeSignals,
    check_envelope,
    current_trip,
)
from cardpicker.pilot_run_lifecycle import mark_ledger_failed, merge_counters
from cardpicker.process_metrics import get_process_rss_mb
from cardpicker.stage_e_concurrency import try_acquire_dispatch_slot
from cardpicker.stage_e_signals import suppress_evidence_change_echo
from cardpicker.utils import get_baked_git_sha

logger = logging.getLogger(__name__)

# Placeholder pending §10(c)'s own measurement (see MPCAutofill/settings.py's own
# STAGE_E_MICRO_BATCH_SIZE comment for the full citation) - not invented precision, a
# conservative default inside the brief's own "roughly 10-100" sanity range.
DEFAULT_MICRO_BATCH_SIZE = 25

# Persistent sweep cursor defaults (issue #458 - see MPCAutofill/settings.py's own
# STAGE_E_SELECTION_CHUNK_SIZE/STAGE_E_SELECTION_SCAN_CAP comments for the full citation) - mirrors
# DEFAULT_MICRO_BATCH_SIZE's own "getattr with a fallback constant" convention immediately above.
DEFAULT_SELECTION_CHUNK_SIZE = 250
DEFAULT_SELECTION_SCAN_CAP = 1000

# Max CAS retries a single _select_micro_batch call will spend re-claiming a chunk after losing a
# race to a concurrent dispatch (issue #458 §4) before giving up and returning whatever it already
# has - bounds a single dispatch's own worst-case cost under contention, same purpose
# STAGE_E_SELECTION_SCAN_CAP serves for a sparse backlog.
_MAX_SWEEP_CAS_RETRIES = 3


def _stage_c_manifest_extractor_keys() -> "frozenset[str]":
    """
    Lazy import (this module's own "avoid a hard import-time dependency between sibling engines"
    posture, mirrored from `local_calculate_verdicts.py`'s own `JOIN_KEY_CONFIDENCE_BOTH` comment) -
    a management-command module isn't normally imported from a library module at Django app-startup
    time (this module is imported from `cardpicker.stage_e_signals`, wired in `apps.py`'s `ready()`),
    so this stays call-time-only rather than a module-level import. `MANIFEST_EXTRACTOR_KEYS` itself
    is untouched by this change - imported, never duplicated, so the two eligibility notions (BULK
    mode's own resume filter, this module's own backlog fill) can never drift apart silently.
    """
    from cardpicker.management.commands.run_image_evidence_cohort import (
        MANIFEST_EXTRACTOR_KEYS,
    )

    return MANIFEST_EXTRACTOR_KEYS


class _FetchOutcomeWindow:
    """
    The rolling fetch-outcome window `dispatch_micro_batch` samples
    `fetch_failures_in_window`/`fetch_total_in_window` from before every envelope check - sized to
    `operating_envelope.FETCH_FAILURE_WINDOW` (500) exactly, per the binding Phase-1 Tron-gate note
    (module docstring's "FETCH-FAILURE WINDOW SIZING" section). A `deque(maxlen=...)` is the
    mechanism that actually enforces the size: once 500 outcomes have been recorded, the 501st push
    silently evicts the oldest, so `len(self._window)` can never exceed `FETCH_FAILURE_WINDOW`
    regardless of how many cards this worker process has ever touched.
    """

    def __init__(self, maxlen: int = FETCH_FAILURE_WINDOW) -> None:
        self._window: Deque[bool] = deque(maxlen=maxlen)

    def record(self, success: bool) -> None:
        self._window.append(success)

    def failures_and_total(self) -> tuple[int, int]:
        total = len(self._window)
        failures = sum(1 for success in self._window if not success)
        return failures, total

    def __len__(self) -> int:
        return len(self._window)


# Process-local singleton (module docstring's "FETCH-FAILURE WINDOW SIZING" section) - one per
# worker process, spanning that process's whole uptime, not reset per batch.
_window = _FetchOutcomeWindow()


@dataclass
class DispatchOutcome:
    """
    What `dispatch_micro_batch` returns - never raises for an ordinary halt (streaming-disabled,
    trip-open, freshly-tripped) since none of those are failures of the dispatch loop itself, only
    reasons it correctly declined to do work this call. `status` is one of:
      - "disabled" - `settings.STAGE_E_STREAMING_ENABLED` is False.
      - "halted-open-trip" - `current_trip()` was already non-None; no self-resume (module docstring).
      - "halted-new-trip" - this call's own fresh envelope sample breached a bar.
      - "empty" - streaming is enabled and the envelope is clear, but nothing was eligible.
      - "throttled-concurrency-cap" - a real batch was selected, but every
        `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` slot (`cardpicker.stage_e_concurrency`) was
        already held by another concurrent dispatch - PROACTIVE throttling, distinct from the
        envelope's own REACTIVE halted-new-trip (see that module's own docstring for why both
        exist). No `PilotRunLedger` row is written, matching the other halted statuses - but
        (2026-07-25, Tron gate observability anomaly 4) `StageEThrottleCounter.record()` DOES
        advance a singleton, always-exactly-one-row counter (`cardpicker.models.
        StageEThrottleCounter`'s own docstring has the full "why a counter, not a per-event row"
        reasoning) so the runbook's own "tune STAGE_E_MAX_CONCURRENT_DISPATCHES against the
        observed throttle rate" instruction has something queryable to check.
      - "completed" - did real work; does not itself guarantee zero failures inside the batch
        (a card can still fail its own fetch/extraction), only that the DISPATCH LOOP didn't halt.
      - "completed-with-trip" - did real work, but a `GoogleFetchLockoutError` observed mid-batch
        tripped the envelope (instant-pause bar) partway through - this batch's own already-fetched
        work still drains (ops doc's "in-flight work drains, nothing NEW starts"), but the NEXT
        `dispatch_micro_batch` call will see `current_trip()` non-None and refuse.
    """

    status: str
    run_id: Optional[str] = None
    card_ids: list[int] = field(default_factory=list)
    stage_c_completed: int = 0
    # Evidence transfer (issue #473 PR-2, folded with issue #472): a card whose evidence row this
    # batch produced via `evidence_transfer.transfer_evidence` (an md5-sibling's own current row,
    # copied - no fetch, no real extraction) rather than a real per-card extraction pass. A SUBSET
    # of `stage_c_completed` above - both counters increment together for a transferred card, this
    # one just narrows down which completions were transfers vs. real fetch+extraction work.
    stage_c_transferred: int = 0
    stage_c_fetch_failures: int = 0
    stage_d_join_key_votes: int = 0
    stage_d_fallback_votes: int = 0
    stage_d_slow_path_routed: int = 0
    # A concurrent overlapping dispatch (this worker racing another django-q worker, or the
    # backstop sweep racing an event trigger - local_calculate_verdicts._split_new_printing_tag_
    # votes' own docstring has the full incident) skipped a vote this batch computed because
    # another dispatch had already cast it for the same (card, anonymous_id) first. Counted, not
    # silently dropped - a healthy streaming deployment should see this occasionally, not never
    # (zero forever would suggest the guard itself is dead code, not that races don't happen).
    stage_d_join_key_already_voted: int = 0
    stage_d_fallback_already_voted: int = 0
    trip_id: Optional[str] = None


def _sample_envelope_signals(google_lockout: bool = False) -> EnvelopeSignals:
    """
    Live signals sampled fresh before every dispatch decision (`operating_envelope.py`'s own module
    docstring: "the caller owns sampling"). `load_avg`/`rss_mb_per_worker` are best-effort - `None`
    on a platform without `/proc`/`os.getloadavg` (matches `get_process_rss_mb`'s own documented
    convention: a caller must treat `None` as "skip this bar", never as an error).
    """
    try:
        load_avg: Optional[float] = os.getloadavg()[0]
    except (OSError, AttributeError):
        load_avg = None
    failures, total = _window.failures_and_total()
    return EnvelopeSignals(
        load_avg=load_avg,
        rss_mb_per_worker=get_process_rss_mb(),
        fetch_failures_in_window=failures,
        fetch_total_in_window=total,
        google_lockout=google_lockout,
    )


def _cursor_chunk_walk(
    cursor_name: str,
    verify_chunk: Callable[[list[int]], Iterable[int]],
    limit: int,
) -> tuple[list[int], bool]:
    """
    THE shared chunked cursor walk (issue #460 - extends issue #458's single Stage C sweep cursor
    to a second, independently-keyed one; see `StageESweepCursor`'s own docstring for why the two
    walks need separate rows). `_select_micro_batch`'s Stage C backlog fill and
    `stream_backstop_sweep._next_stage_d_backlog_ids`'s Stage D backlog fill both call this ONE
    function, parameterized only by which `StageESweepCursor` row to walk (`cursor_name`, one of
    `StageESweepCursor.STAGE_C`/`STAGE_D`) and a per-chunk verifier callable (`verify_chunk`,
    called with a bounded, already-CAS-claimed list of candidate pks and returning the subset of
    them that are genuinely eligible) - so the two callers cannot drift apart on chunking, scan-cap,
    CAS, or wrap semantics the way two independent implementations eventually would.

    Walks `StageESweepCursor(name=cursor_name).position` forward through the Card pk space (cards
    with a stable content hash - both Stage C and Stage D eligibility presuppose one, see
    `_select_micro_batch`'s own docstring) in bounded `STAGE_E_SELECTION_CHUNK_SIZE`-sized chunks,
    each chunk claimed via an optimistic CAS (`StageESweepCursor.try_advance`) BEFORE `verify_chunk`
    ever runs against it - two concurrent dispatches walking the SAME cursor (another django-q
    worker, or the backstop sweep racing an event trigger) therefore sweep DISJOINT ranges rather
    than duplicating verification work or racing each other's cursor writes. Every query this
    function issues is shaped by CHUNK_SIZE/SCAN_CAP, never by catalog size - the incremental
    pk-index range scan (`pk__gt=position`) and `verify_chunk`'s own bounded, chunk-scoped query
    both cost the same regardless of how large the catalog grows.

    Stops filling once `limit` ids have been found, once `STAGE_E_SELECTION_SCAN_CAP` candidates
    have been examined this call (a mostly-already-processed range can need many chunks to find few
    or zero eligible cards - this caps that call's own worst case), once the walk reaches the end of
    the pk space (wraps `position` back to `0`, increments `wrap_count`, and STOPS this call without
    continuing to scan from 0 in the same call - see `StageESweepCursor`'s own docstring), or once
    `_MAX_SWEEP_CAS_RETRIES` consecutive CAS losses have been spent. Every one of these is a normal,
    expected stopping point, not a failure.

    Returns `(found_ids, exhausted)`. `found_ids` is capped at `limit`, always a valid (possibly
    partial, possibly empty) result. `exhausted` is `True` iff this call reached the end of the pk
    space and wrapped - the ONLY signal that distinguishes "this cursor's backlog is genuinely empty
    right now" from "the scan cap (or CAS retry budget) was hit with more pk space still unscanned
    ahead of `position`" (issue #460 §4) - a cap-hit-empty result must NOT be treated as exhaustion
    by a caller (see `stream_backstop_sweep.py`'s own handling of this distinction).
    """
    found: list[int] = []
    found_set: set[int] = set()
    chunk_size = getattr(settings, "STAGE_E_SELECTION_CHUNK_SIZE", DEFAULT_SELECTION_CHUNK_SIZE)
    scan_cap = getattr(settings, "STAGE_E_SELECTION_SCAN_CAP", DEFAULT_SELECTION_SCAN_CAP)

    position = StageESweepCursor.get_cursor(cursor_name).position
    examined = 0
    cas_retries = 0
    exhausted = False

    while len(found) < limit and examined < scan_cap:
        this_chunk_limit = min(chunk_size, scan_cap - examined)
        chunk = list(
            Card.objects.filter(content_phash__isnull=False, pk__gt=position)
            .order_by("pk")
            .values_list("pk", flat=True)[:this_chunk_limit]
        )
        if not chunk:
            # End of the pk space - wrap and stop THIS call outright (this function's own docstring:
            # never continue scanning from 0 in the same call). The CAS here can lose too (another
            # dispatch already wrapped it) - harmless either way, this call is stopping regardless.
            StageESweepCursor.try_wrap(cursor_name, position)
            exhausted = True
            break

        if not StageESweepCursor.try_advance(cursor_name, position, chunk[-1]):
            # Lost the race for this range to a concurrent dispatch walking the same cursor -
            # discard the chunk (never verified, so never a candidate for this call) and retry
            # against the now-current position, up to _MAX_SWEEP_CAS_RETRIES times.
            cas_retries += 1
            if cas_retries > _MAX_SWEEP_CAS_RETRIES:
                break
            position = StageESweepCursor.get_cursor(cursor_name).position
            continue

        # This call now owns [position, chunk[-1]] - verify only this bounded chunk.
        examined += len(chunk)
        eligible_ids = set(verify_chunk(chunk))
        for card_id in chunk:
            if card_id in eligible_ids and card_id not in found_set:
                found.append(card_id)
                found_set.add(card_id)
                if len(found) >= limit:
                    break
        position = chunk[-1]

    return found[:limit], exhausted


def _select_micro_batch(seed_card_ids: Iterable[int], batch_size: int) -> list[int]:
    """
    Builds one micro-batch's own card-id list (docs/proposals/stage-e-streaming.md §3 decision (2)):
    starts with `seed_card_ids` (the event trigger's own touched card, or an empty seed for the
    backstop sweep) and fills up to `batch_size` from the general Stage C backlog - cards with a
    stable content hash but no CURRENT `ImageEvidence` row carrying every manifest extractor key
    (the SAME shape `run_image_evidence_cohort.py`'s own resume filter uses, imported not
    reimplemented - see `_stage_c_manifest_extractor_keys`). Order preserved (seed first),
    de-duplicated.

    Deliberately does NOT also backfill from the Stage-D-only backlog (cards whose Stage C evidence
    is already complete but that have never had a Stage D pass) - the seed card itself always gets a
    Stage D attempt regardless (`dispatch_micro_batch` scopes Stage D to the WHOLE returned batch,
    seed included), and Stage C is the dominant wall-clock cost driver `batch_size` is sized against
    (§3 decision (2)/§1's own worst-case floor), so backlog-filling from Stage C's own queue is the
    lever that matters for keeping a batch's wall-clock cost bounded. (The Stage-D-only backlog now
    has its own cursor-backed walk too - `StageESweepCursor.STAGE_D`, driven by
    `stream_backstop_sweep._next_stage_d_backlog_ids`, issue #460 - but this function still never
    reads it; that division of responsibility is unchanged.)

    BACKLOG FILL, issue #458 (persistent sweep cursor, chunked verification), issue #460 (walk
    factored out into `_cursor_chunk_walk`, shared with the Stage D backlog fill) - replaces the old
    per-batch `Card.objects.exclude(pk__in=ImageEvidence.objects.filter(...))` anti-join, which
    re-ran a full-catalog JSONB scan from scratch on EVERY micro-batch (O(catalog), observed
    641s+-running under a completing catalog - see issue #458's own Problem section). This function's
    own behavior through `_cursor_chunk_walk` is unchanged from before the #460 refactor: same
    cursor (`StageESweepCursor.STAGE_C`), same chunking/scan-cap/CAS/wrap semantics, same "a partial
    or even empty backlog fill is a valid result" posture (`dispatch_micro_batch`'s own "empty"
    status already exists for exactly this) - this function simply doesn't need `_cursor_chunk_walk`'s
    `exhausted` return value, since it has no caller-visible distinction to make with it.
    """
    seen: list[int] = []
    seen_set: set[int] = set()
    for card_id in seed_card_ids:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)
    if len(seen) >= batch_size:
        return seen[:batch_size]

    manifest_keys = list(_stage_c_manifest_extractor_keys())

    def _verify_stage_c_chunk(chunk: list[int]) -> Iterable[int]:
        done_ids = set(
            ImageEvidence.objects.filter(card_id__in=chunk, extractor_versions__has_keys=manifest_keys).values_list(
                "card_id", flat=True
            )
        )
        return [card_id for card_id in chunk if card_id not in done_ids]

    found, _exhausted = _cursor_chunk_walk(StageESweepCursor.STAGE_C, _verify_stage_c_chunk, batch_size - len(seen))
    for card_id in found:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)

    return seen[:batch_size]


# Bounded fetch-ahead queue depth (issue #472's own design constraint: "Bounded prefetch depth
# (1-2 images) so RSS stays flat") - a plain module constant, not a settings knob, matching the
# brief's own concrete number rather than leaving it operator-tunable; PASSIVE mode's own
# micro-batches are small enough (§3 decision (2), a handful to a few dozen cards) that this never
# needs retuning the way BULK mode's own `--queue-depth` does.
_STAGE_C_FETCH_AHEAD_DEPTH = 2


@dataclass
class _StageCFetchOutcome:
    """One card's own fetch-stage result, handed from `_stage_c_fetch_ahead_worker` (the fetch-
    ahead thread) to `_run_stage_c`'s own sequential compute loop via a bounded `queue.Queue`.
    `card`/`content_hash`/`md5_checksum`/`sha256_checksum` are all read from the SAME `Card`
    instance `_run_stage_c` already loaded (and used for its own transfer check) before handing
    this card off to the fetch-ahead thread - no second `Card` query on either side of the
    boundary. `lockout=True` iff this card's OWN fetch attempt raised `GoogleFetchLockoutError` -
    the compute loop treats this as the signal to stop (module docstring's "halts NEW fetches
    immediately" bar), never a fetch failure to retry.

    `error`, if set, is a NON-`GoogleFetchLockoutError` exception the fetch attempt raised (2026-07-25,
    kill-safety fix - see `_stage_c_fetch_ahead_worker`'s own docstring for why this exists at
    all): re-raised by the compute loop IN THE MAIN THREAD the instant it's observed, so a crash
    during fetch still propagates out of `_run_stage_c`/`dispatch_micro_batch` exactly as it did
    before this module had a separate fetch thread at all - `TestKillSafetyResumeContract`'s own
    "a mid-batch crash leaves a truthful FAILED ledger row" contract does not distinguish between
    a crash during fetch and a crash during compute, and must not silently become a hang instead."""

    card_id: int
    content_hash: Optional[int]
    md5_checksum: Optional[str]
    sha256_checksum: Optional[str]
    image_bytes: Optional[bytes]
    fetch_latency_ms: float
    lockout: bool = False
    error: Optional[BaseException] = None


def _stage_c_fetch_ahead_worker(
    cards: list[Card],
    out_queue: "queue.Queue[_StageCFetchOutcome]",
    stop_event: threading.Event,
) -> None:
    """
    THE fetch-ahead thread (issue #472) - ONE thread, sequential fetches (never pooled: the design
    brief's own "no compute pooling" bar applies equally to a fetch pool here, since a SECOND
    concurrent fetch would only race further ahead of a compute loop that's already the slower
    stage, buying nothing the bounded queue depth doesn't already buy via fetch/compute OVERLAP
    alone). Pushes one `_StageCFetchOutcome` per entry in `cards`, in order - `queue.Queue`'s own
    FIFO ordering means the compute loop always drains outcomes in the SAME order this thread
    fetched them, satisfying the design brief's own "fetch-outcome window records in completion
    order" bar for free (a single serial fetch worker's own completion order IS its submission
    order, there is no reordering possible with only one fetch in flight at a time).

    `out_queue`'s own bound (`queue.Queue(maxsize=_STAGE_C_FETCH_AHEAD_DEPTH)`, set by the caller)
    is what keeps RSS bounded independent of batch size - `put()` BLOCKS once the queue is full,
    so this thread can never race further than `_STAGE_C_FETCH_AHEAD_DEPTH` outcomes ahead of
    whatever the compute loop has actually consumed so far, regardless of how many cards remain in
    `cards` or how large a future catalog's own micro-batch could be.

    LOCKOUT (design brief's own "instant halt" bar): the moment `fetch_card_image_bytes` raises
    `GoogleFetchLockoutError` for one card, `stop_event` is set and this thread returns immediately
    WITHOUT attempting any further card in `cards` - "halts NEW fetches immediately". The card
    whose OWN fetch triggered the lockout is reported to the compute loop via this outcome's own
    `lockout=True` flag (never silently dropped), so the compute loop can record the trip itself
    and stop too. Every outcome that already made it into `out_queue` BEFORE this happened is left
    there untouched - "in-flight work drains" - the compute loop keeps consuming those (they sort
    earlier in FIFO order than the lockout outcome) before it ever reaches the lockout marker,
    exactly mirroring the pre-#472 sequential design's own "an already-fetched image still gets to
    finish its own compute+persist" property, just now genuinely overlapped rather than accidental.

    ANY OTHER EXCEPTION (2026-07-25, kill-safety fix - `TestKillSafetyResumeContract`'s own
    mid-batch-crash test caught this during review): a plain `try/except GoogleFetchLockoutError`
    here would let a non-lockout exception (a real bug, a simulated kill-drill fault, a genuine
    network error `fetch_card_image_bytes` doesn't itself wrap) kill this THREAD silently - Python
    does not propagate an uncaught exception from a spawned `threading.Thread` to its caller, so
    the compute loop's own `queue.get()` for that card would block FOREVER waiting for an outcome
    that will never arrive, turning a crash into a silent hang instead of the loud, ledger-recorded
    failure the resume contract requires. Caught here as a bare `Exception`, packaged onto the
    outcome's own `error` field, and this thread stops (same "no further cards attempted" posture
    as a lockout) - the compute loop re-raises it in the MAIN thread the instant it's seen.
    """
    from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image_bytes

    for card in cards:
        if stop_event.is_set():
            return

        fetch_started_at = time.monotonic()
        try:
            image_bytes = fetch_card_image_bytes(card, dpi=DEFAULT_FETCH_DPI)
        except GoogleFetchLockoutError:
            stop_event.set()
            out_queue.put(
                _StageCFetchOutcome(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    md5_checksum=card.md5_checksum,
                    sha256_checksum=card_sha256_checksum(card),
                    image_bytes=None,
                    fetch_latency_ms=0.0,
                    lockout=True,
                )
            )
            return
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring above
            stop_event.set()
            out_queue.put(
                _StageCFetchOutcome(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    md5_checksum=card.md5_checksum,
                    sha256_checksum=card_sha256_checksum(card),
                    image_bytes=None,
                    fetch_latency_ms=0.0,
                    error=exc,
                )
            )
            return
        fetch_latency_ms = (time.monotonic() - fetch_started_at) * 1000

        out_queue.put(
            _StageCFetchOutcome(
                card_id=card.pk,
                content_hash=card.content_phash,
                md5_checksum=card.md5_checksum,
                sha256_checksum=card_sha256_checksum(card),
                image_bytes=image_bytes,
                fetch_latency_ms=fetch_latency_ms,
            )
        )


def _run_stage_c(
    batch_ids: list[int], run_id: str, outcome: DispatchOutcome, force_stage_c_reextract: bool = False
) -> Optional[EnvelopeTrip]:
    """
    Per-card Stage C extraction over whichever of `batch_ids` still lack a full manifest - the SAME
    per-card unit (`image_evidence.compute_card_evidence` + `image_evidence.persist_evidence`, fed
    by `image_cdn_fetch.fetch_card_image_bytes`) `run_image_evidence_cohort.py`'s own fetch/compute
    stages call. Three phases per batch, in order:

    1. **Build the work list** (still fully sequential, cheap DB-only work): for each id not
       already done, load its `Card` once and check `evidence_transfer.find_transfer_source`
       BEFORE deciding whether this card needs a fetch at all (issue #473 PR-2's own scope: "check
       BEFORE fetching") - a card with an eligible md5-sibling never reaches the fetch-ahead thread
       at all, its evidence row is created via `evidence_transfer.transfer_evidence` right here and
       counted via `outcome.stage_c_transferred`/`stage_c_completed`. Every card that still needs a
       real extraction (no md5, no eligible sibling, or a loud pairing/content-hash anomaly - see
       that function's own docstring) is collected into `to_fetch`.
    2. **Decoupled fetch-ahead + sequential compute** (issue #472): `to_fetch` is handed to ONE
       fetch-ahead thread (`_stage_c_fetch_ahead_worker`) writing into a bounded
       (`_STAGE_C_FETCH_AHEAD_DEPTH`) queue; THIS function's own loop stays the sequential OCR/
       extraction compute stage the design brief mandates (no compute pooling), just now able to
       decode+extract card N while the fetch-ahead thread is already fetching card N+1's bytes,
       instead of blocking on that fetch itself. Every fetch outcome (transfer OR real fetch) is
       recorded onto `_window` regardless of whether it ends up mattering to THIS batch's own
       envelope decision - the window spans the whole worker process's uptime, not one batch.
    3. **Echo suppression** (issue #472's own fold, `cardpicker.stage_e_signals`'s own module
       docstring has the full mechanism writeup): both the transfer write in phase 1 and the
       `persist_evidence` write in phase 2 are wrapped in `suppress_evidence_change_echo()` - a
       write performed by THIS dispatch loop must never queue a fresh `dispatch_for_card` echo task
       for the same card, since Stage D (called next, over the SAME batch) already covers it.

    `force_stage_c_reextract` (issue #465, `management/commands/stage_e_shakedown.py`'s one conveyor
    change): `False` (the default) is BYTE-IDENTICAL to the pre-#465 behaviour below - the
    already-done exclusion applies and `compute_card_evidence` gets `short_circuit=None` (deferring
    to its own env-var default), exactly as before this parameter existed. `True` is passed ONLY by
    that driver, for cards whose CURRENT full-manifest `ImageEvidence` row already exists but carries
    blank values (the Bug-A tail's own signature - a card the already-done check below would
    otherwise wrongly treat as finished): it (a) skips the already-done exclusion entirely, so every
    id in `batch_ids` gets a fresh fetch + extract regardless of manifest completeness, and (b) forces
    `short_circuit=False` into `compute_card_evidence` - the same escalation-forcing effect
    `run_image_evidence_cohort.py`'s own `--no-shortcircuit` flag has (see that command's own
    docstring for the mechanism reused here, not reimplemented), so a zero-digit tier-1 read is never
    allowed to short-circuit past the fuller multi-tier escalation that could recover a real read.
    Transfer-checking (phase 1) is deliberately UNCONDITIONAL regardless of this flag - a
    force-re-extracted card with a genuinely current, good md5-sibling gets FIXED by transfer
    immediately rather than paying for a real re-fetch of what would produce the same bytes anyway;
    `evidence_transfer.find_transfer_source`'s own asserts are what keep this safe.

    Returns the `EnvelopeTrip` this call itself recorded (only possible via the instant Google
    lockout bar - see `GoogleFetchLockoutError` below), or `None`. A lockout stops Stage C
    IMMEDIATELY for this batch - in-flight work already committed stays committed (each card's
    `persist_evidence`/`transfer_evidence` call is already durable the instant it returns, matching
    the resume contract's own "one-transaction batch commit or explicit evidence-first statement" -
    here, every card's own persist is its own transaction, so there is no partial-card state to
    roll back) - and records a fresh trip via `check_envelope(google_lockout=True)` so the NEXT
    dispatch call refuses until an owner acknowledges it, matching the "instant pause" bar exactly.
    """
    from io import BytesIO

    from PIL import Image

    from cardpicker.image_evidence import compute_card_evidence, persist_evidence

    if force_stage_c_reextract:
        already_done_ids: set[int] = set()
    else:
        manifest_keys = list(_stage_c_manifest_extractor_keys())
        already_done_ids = set(
            ImageEvidence.objects.filter(card_id__in=batch_ids, extractor_versions__has_keys=manifest_keys).values_list(
                "card_id", flat=True
            )
        )
    short_circuit: Optional[bool] = False if force_stage_c_reextract else None
    lexicon = known_set_codes()

    # PHASE 1 (module docstring): build the work list, resolving evidence transfer BEFORE
    # deciding whether a card needs a fetch at all.
    to_fetch: list[Card] = []
    for card_id in batch_ids:
        if card_id in already_done_ids:
            continue
        try:
            card = Card.objects.select_related("source").get(pk=card_id)
        except Card.DoesNotExist:
            continue
        if card.content_phash is None:
            continue

        transfer_source = find_transfer_source(card)
        if transfer_source is not None:
            with suppress_evidence_change_echo():
                transfer_evidence(card, transfer_source, run_id=run_id)
            outcome.stage_c_completed += 1
            outcome.stage_c_transferred += 1
            continue

        to_fetch.append(card)

    if not to_fetch:
        return None

    # PHASE 2 (module docstring): decoupled fetch-ahead thread + this function's own sequential
    # compute loop.
    fetch_queue: "queue.Queue[_StageCFetchOutcome]" = queue.Queue(maxsize=_STAGE_C_FETCH_AHEAD_DEPTH)
    stop_event = threading.Event()
    fetch_thread = threading.Thread(
        target=_stage_c_fetch_ahead_worker, args=(to_fetch, fetch_queue, stop_event), daemon=True
    )
    fetch_thread.start()

    trip: Optional[EnvelopeTrip] = None
    try:
        for _ in range(len(to_fetch)):
            fetch_outcome = fetch_queue.get()

            if fetch_outcome.error is not None:
                # Re-raise IN THE MAIN THREAD - see _StageCFetchOutcome/_stage_c_fetch_ahead_
                # worker's own docstrings for why this exists (a spawned thread's own uncaught
                # exception never reaches the caller on its own). Propagates out of this function,
                # through dispatch_micro_batch's own `except Exception: mark_ledger_failed(...);
                # raise` - identical observable behaviour to the pre-#472 sequential design's own
                # "a fetch-time crash surfaces exactly like a compute-time one" contract.
                raise fetch_outcome.error

            if fetch_outcome.lockout:
                _window.record(success=False)
                logger.error("Stage E dispatch: GoogleFetchLockoutError observed - halting Stage C for this batch")
                trip = check_envelope(_sample_envelope_signals(google_lockout=True), run_id=run_id)
                break

            if fetch_outcome.image_bytes is None:
                _window.record(success=False)
                outcome.stage_c_fetch_failures += 1
                continue

            _window.record(success=True)
            image = Image.open(BytesIO(fetch_outcome.image_bytes))
            result = compute_card_evidence(
                fetch_outcome.card_id,
                fetch_outcome.content_hash,
                image,
                fetch_latency_ms=fetch_outcome.fetch_latency_ms,
                short_circuit=short_circuit,
                known_set_codes=lexicon,
                md5_checksum=fetch_outcome.md5_checksum,
                sha256_checksum=fetch_outcome.sha256_checksum,
            )
            with suppress_evidence_change_echo():
                persist_evidence(result, run_id=run_id)
            outcome.stage_c_completed += 1
    finally:
        # Always join, whether the loop above finished normally, broke on a lockout, or raised -
        # the fetch-ahead thread is `daemon=True` (won't block process exit on its own) but this
        # function should never RETURN while it's still mid-fetch for a card nothing will ever
        # consume; a lockout already made it return promptly on its own (module docstring), so this
        # join is a bounded wait in every reachable case, never an indefinite one.
        fetch_thread.join()

    return trip


def _run_stage_d(batch_ids: list[int], run_id: str, outcome: DispatchOutcome) -> None:
    """
    Stage D over the SAME micro-batch, scoped via the `card_ids` parameter
    `local_calculate_verdicts.py` gained for this module (see that module's own docstring) - the
    join-key -> fallback -> slow-path escalation order every BULK-mode command already uses,
    unchanged (module docstring's "PIPELINE STAGES" section explains the consensus-recompute
    piece). Runs unconditionally for every card in `batch_ids`, including ones Stage C never
    reached this round (e.g. a lockout stopped Stage C partway, or the card already had current
    evidence and never needed Stage C at all this dispatch) - each calculator's own eligibility
    query simply finds nothing to do for a card with no current evidence (a "no-evidence" named
    skip, not an error), so this is always safe to call.

    CONCURRENT-DISPATCH VOTE COLLISION (2026-07-24, shakedown run tripping envelope trip
    envtrip-20260724T214616-be6e5db9): this is the FIRST caller ever to invoke
    `run_join_key_calculator`/`run_fallback_calculator` concurrently (django-q2 runs
    `Q_CLUSTER["workers"] = 8`, and the cron backstop sweep can overlap an event-driven dispatch
    too) - two dispatches scoped to the same card can both pass that calculator's own eligibility
    check before either commits, race to `bulk_create` the same (card, anonymous_id) vote, and the
    loser used to hit an `IntegrityError` that aborted its WHOLE micro-batch (seven of the eight
    concurrent dispatches that run hit this; see `local_calculate_verdicts._split_new_printing_tag_
    votes`' own docstring for the exact incident numbers). Both calculators now carry their own
    pre-write skip-if-exists guard PLUS `bulk_create(..., ignore_conflicts=True)` as the actual
    crash-proofing (the pre-write check alone still leaves a narrow race window - see that
    function's own docstring) - a losing race is now a counted no-op (`already_voted`, surfaced on
    `DispatchOutcome`/this batch's own `PilotRunLedger` row), not a guaranteed-impossible one, but
    no longer a crash either way. `run_slow_path_calculator` was checked too and needs no
    equivalent guard - it writes only `CardScanLog` rows, which carry no DB uniqueness constraint
    at all (see that calculator's own docstring).

    THIS DOES NOT ADDRESS THE HOST-LOAD ENVELOPE TRIP the same shakedown run also hit
    (`envtrip-20260724T214616-be6e5db9`, `bar=host_load`, 11.85 observed against the 7.0 ceiling,
    tripped 0.43s after the winning vote landed) - that trip is HOST RESOURCE CONTENTION from eight
    concurrent OCR/phash dispatches on this box's 7 usable cores, a completely separate failure mode
    from the vote-write race this function's own guard closes. Fixing the vote collision does not
    stop eight concurrent dispatches from re-tripping the load bar the moment streaming resumes -
    see `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` (companion change) for the actual fix to that,
    and `docs/features/stage-e-operations.md`'s runbook for acknowledging the open trip itself.
    """
    join_key_result = run_join_key_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_join_key_votes = join_key_result.votes_written + join_key_result.no_match_votes_written
    outcome.stage_d_join_key_already_voted = join_key_result.already_voted

    fallback_result = run_fallback_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_fallback_votes = fallback_result.votes_written
    outcome.stage_d_fallback_already_voted = fallback_result.already_voted

    slow_path_result = run_slow_path_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_slow_path_routed = slow_path_result.routed_written


def dispatch_micro_batch(
    card_ids: Optional[Iterable[int]] = None,
    trigger_reason: str = "event",
    run_id: Optional[str] = None,
    batch_size: Optional[int] = None,
    force_stage_c_reextract: bool = False,
) -> DispatchOutcome:
    """
    The CONVEYOR itself - one micro-batch dispatch decision (docs/proposals/stage-e-streaming.md
    §3, this module's own docstring). Called by `cardpicker.stage_e_signals`'s own event receivers
    (via `dispatch_for_card`, `card_ids=[the triggering card's own pk]`), by `stream_backstop_sweep`
    (`card_ids=None`, letting `_select_micro_batch` fill the whole batch from the backlog), and by
    `management/commands/stage_e_shakedown.py` (issue #465, `card_ids=<its own driven chunk>`,
    `force_stage_c_reextract=True`).

    `force_stage_c_reextract` (issue #465): `False` (the default) is BYTE-IDENTICAL to this
    function's pre-#465 behaviour - forwarded straight through to `_run_stage_c` (see that function's
    own docstring for the two things `True` changes). Only the shakedown driver ever passes `True`.

    Ordering: default-off gate -> no-self-resume gate -> fresh envelope sample -> batch selection ->
    concurrency-cap slot acquire (`cardpicker.stage_e_concurrency`) -> Stage C (sequential, per-card)
    -> Stage D (AS-IS entry points, scoped) -> ledger write -> slot release. Every gate below returns
    WITHOUT touching the DB (aside from the envelope check's own trip-persist side effect, and the
    concurrency-cap check's own advisory-lock round trip, plus - 2026-07-25 - a throttled outcome's
    `StageEThrottleCounter.record()` call, a single-row atomic counter update, never a growing
    table) the instant it applies - a halted or throttled dispatch never partially starts Stage C.
    """
    if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
        return DispatchOutcome(status="disabled", run_id=run_id)

    # NO SELF-RESUME (binding Phase-1 Tron-gate note, module docstring): refuse outright while a
    # trip is already open - checked BEFORE sampling/spending a fresh envelope check, per
    # operating_envelope.current_trip's own docstring ("the caller is expected to check
    # current_trip() BEFORE ever calling [check_envelope]").
    existing_trip = current_trip(run_id=run_id)
    if existing_trip is not None:
        logger.info(
            "Stage E dispatch refused - envelope trip %s (%s) is still open, no self-resume",
            existing_trip.trip_id,
            existing_trip.bar,
        )
        return DispatchOutcome(status="halted-open-trip", run_id=run_id, trip_id=existing_trip.trip_id)

    signals = _sample_envelope_signals()
    fresh_trip = check_envelope(signals, run_id=run_id)
    if fresh_trip is not None:
        logger.warning(
            "Stage E dispatch halted - envelope bar %s breached (%s), trip %s persisted",
            fresh_trip.bar,
            fresh_trip.detail,
            fresh_trip.trip_id,
        )
        return DispatchOutcome(status="halted-new-trip", run_id=run_id, trip_id=fresh_trip.trip_id)

    effective_batch_size = (
        batch_size
        if batch_size is not None
        else getattr(settings, "STAGE_E_MICRO_BATCH_SIZE", DEFAULT_MICRO_BATCH_SIZE)
    )
    batch_ids = _select_micro_batch(card_ids or (), effective_batch_size)
    if not batch_ids:
        return DispatchOutcome(status="empty", run_id=run_id)

    # CONCURRENCY CAP (companion to PR #448's vote-collision fix - cardpicker.stage_e_concurrency's
    # own module docstring has the full incident/mechanism writeup): acquired around exactly the
    # CPU-heavy segment below (ledger create through Stage C/D completion), not around the cheap
    # batch-selection query above - holding a scarce slot while doing nothing but a bounded read
    # would only starve other dispatches for no benefit. `slot is None` means every
    # `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` slot is already held elsewhere - PROACTIVE
    # throttling, distinct from the envelope's own REACTIVE halted-new-trip below.
    with try_acquire_dispatch_slot() as slot:
        if slot is None:
            logger.info(
                "Stage E dispatch throttled - all %s concurrency-cap slots already held",
                getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2),
            )
            # Observability signal (Tron gate anomaly 4, 2026-07-25): a throttled dispatch writes
            # no PilotRunLedger row (see the comment above this `with` block for why), so this
            # singleton counter (StageEThrottleCounter's own docstring has the full "why a
            # counter, not a per-event row" reasoning) is the ONLY durable, queryable record that
            # throttling happened - the runbook's "tune STAGE_E_MAX_CONCURRENT_DISPATCHES against
            # the observed throttle rate" instruction has nothing else to check against.
            StageEThrottleCounter.record()
            return DispatchOutcome(status="throttled-concurrency-cap", run_id=run_id)

        dispatch_run_id = run_id or f"stage-e-stream-{timezone.now().strftime('%Y%m%dT%H%M%S%f')}Z"

        # Micro-batch ledger row convention (task brief scope item 6, docs/features/stage-e-operations.md's
        # "Phase 2" section): one PilotRunLedger row per micro-batch dispatch, `command=
        # "stage_e_streaming_dispatch"`, `dry_run=False` always (PASSIVE mode has no dry-run leg - the
        # per-envelope-change dry run §3 decision (5) describes is a one-off owner review of the
        # envelope bounds themselves, not a per-batch gate the way BULK mode's forced-dry-run guard is).
        ledger = PilotRunLedger.objects.create(
            run_id=dispatch_run_id,
            command="stage_e_streaming_dispatch",
            dry_run=False,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters={"trigger_reason": trigger_reason, "batch_size": len(batch_ids)},
        )

        outcome = DispatchOutcome(status="completed", run_id=dispatch_run_id, card_ids=batch_ids)
        batch_start = time.monotonic()

        try:
            lockout_trip = _run_stage_c(
                batch_ids, dispatch_run_id, outcome, force_stage_c_reextract=force_stage_c_reextract
            )
            # Stage D still runs even after a mid-batch lockout trip - "in-flight work drains, nothing
            # NEW starts" (docs/features/stage-e-operations.md's HALT semantics) - see _run_stage_d's
            # own docstring for why this is always safe to call regardless of how far Stage C got.
            _run_stage_d(batch_ids, dispatch_run_id, outcome)

            if lockout_trip is not None:
                outcome.status = "completed-with-trip"
                outcome.trip_id = lockout_trip.trip_id

            peak_rss_mb = get_process_rss_mb()
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(
                ledger.counters,
                {
                    "elapsed_s": round(time.monotonic() - batch_start, 3),
                    "stage_c_completed": outcome.stage_c_completed,
                    "stage_c_transferred": outcome.stage_c_transferred,
                    "stage_c_fetch_failures": outcome.stage_c_fetch_failures,
                    "stage_d_join_key_votes": outcome.stage_d_join_key_votes,
                    "stage_d_join_key_already_voted": outcome.stage_d_join_key_already_voted,
                    "stage_d_fallback_votes": outcome.stage_d_fallback_votes,
                    "stage_d_fallback_already_voted": outcome.stage_d_fallback_already_voted,
                    "stage_d_slow_path_routed": outcome.stage_d_slow_path_routed,
                    "peak_rss_mb": peak_rss_mb,
                    "lockout_trip_id": lockout_trip.trip_id if lockout_trip is not None else None,
                },
            )
            ledger.save(update_fields=["status", "finished_at", "counters"])
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed) - a
            # no-op if this invocation already reached the COMPLETED save above, otherwise records a
            # triage-able counters["failure_reason"] alongside FAILED (docs/proposals/
            # stage-e-streaming.md §3 decision (6)'s "empty-failed-row" gap fix, reused here rather than
            # duplicated). A crash mid-Stage-C-loop leaves every already-`persist_evidence`-committed
            # card durably written (each card's own persist is its own transaction) - the resume
            # contract (docs/features/stage-e-operations.md) holds: a fresh dispatch over the same or an
            # overlapping card set skips whatever's already current and picks up the rest, exactly the
            # same "truthful ledger, idempotent re-entry" property the batch kill-test already proves.
            # The concurrency-cap slot is still released (try_acquire_dispatch_slot's own `finally`)
            # even though this exception propagates past this `with` block.
            mark_ledger_failed(ledger, exc)
            raise

        return outcome


def dispatch_for_card(card_id: int, reason: str = "event") -> None:
    """
    The django-q `async_task` entry point (`cardpicker.stage_e_signals`'s own event receivers,
    docs/proposals/stage-e-streaming.md §3 decision (1)) - a thin wrapper around
    `dispatch_micro_batch` scoping the seed to exactly the one card that triggered this task. A
    bare module-level function (not a closure/lambda): `async_task` needs a string dotted path it
    can re-import inside the worker process (`"cardpicker.stage_e_dispatch.dispatch_for_card"` -
    see `cardpicker.stage_e_signals` for the exact call site).
    """
    dispatch_micro_batch(card_ids=[card_id], trigger_reason=reason)
