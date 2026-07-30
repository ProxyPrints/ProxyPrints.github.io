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

CONSENSUS RECOMPUTE (decision (4)) NEEDS NO SEPARATE STEP HERE: all Stage D calculators
already call `resolve_and_persist_printing(touched_card)` internally for every card they cast a
vote on (see e.g. `run_join_key_calculator`'s own final loop, unchanged by this module) - scoping
those calculators to the micro-batch via `card_ids` already scopes their consensus recompute calls
to exactly the same set, satisfying decision (4)'s "scoped incremental per-touch" requirement for
free. This module never imports `printing_consensus`/`vote_consensus`/`tag_consensus`/
`artist_consensus` (PROTECTED CORE) directly at all.

ILLUSTRATION CALCULATOR (issue #507, PR #509): `cardpicker.local_illustration.
run_illustration_calculator` is wired into `_run_stage_d` after the fallback calculator and before
the slow-path router, in the same `card_ids`-scoped, `dry_run=False` shape the other calculators
use. Its result fields (`votes_written`, `already_voted`) are aggregated onto the same
`DispatchOutcome`/`PilotRunLedger` counters the other Stage D calculators produce. The calculator
is imported lazily (same pattern as `_stage_c_manifest_extractor_keys`) to avoid a hard
import-time dependency between sibling engines.
"""

import logging
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Iterable, Optional

from django.conf import settings
from django.utils import timezone

from cardpicker.collector_line_artist import (
    build_name_artist_lookup,
    build_printing_artist_lookup,
    load_artist_lexicon,
)
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
from cardpicker.stage_e_batch_sizing import MODE_INCREMENTAL, resolve_micro_batch_size
from cardpicker.stage_e_concurrency import try_acquire_dispatch_slot
from cardpicker.stage_e_signals import suppress_evidence_change_echo
from cardpicker.utils import get_baked_git_sha

logger = logging.getLogger(__name__)

# RETAINED FOR BACKWARD COMPATIBILITY ONLY (2026-07-29). This module no longer reads it: batch
# size is now decided by `cardpicker.stage_e_batch_sizing` (see that module's docstring for the
# rule and the measurements behind it), and its `MIN_BATCH_SIZE`/`INCREMENTAL_BATCH_SIZE` carry
# this same 25 forward with a stated reason rather than as the §10(c) placeholder it used to be.
# Left in place because three management commands import it by name for their `--help` text.
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


def _stage_c_manifest_versions() -> "dict[str, str]":
    """
    Lazy import of the single-source version map (2026-07-28, issue #509) - same lazy-import
    posture as `_stage_c_manifest_extractor_keys` immediately above. Returns the dict mapping each
    manifest extractor key to its CURRENT expected version string, used by `_select_micro_batch` and
    `_run_stage_c` to reject stale `ImageEvidence` rows whose keys are present but whose values
    carry an old version tag. Imported from the same module as `MANIFEST_EXTRACTOR_KEYS` (the
    single source of truth) so the two can never drift apart.
    """
    from cardpicker.management.commands.run_image_evidence_cohort import (
        MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
    )

    return MANIFEST_EXTRACTOR_CURRENT_VERSIONS


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
    # Cards this batch DEFERRED because the destination answered 429/503 (2026-07-30 owner rate
    # ruling). Deliberately NOT folded into `stage_c_fetch_failures`, and deliberately NOT recorded
    # on the operating envelope's fetch-outcome window: a throttled card is not a FAILED card, it
    # is an UNPROCESSED one that the next pass's own Stage C backlog walk picks up, at a pace the
    # limiter has already slowed. A non-zero value here is the run reporting "I am being rate-
    # limited and I am still going" - the graceful degradation the ruling asks for, and what an
    # operator now reads instead of an exit-3 envelope trip.
    stage_c_fetch_throttled: int = 0
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
    stage_d_illustration_votes: int = 0
    stage_d_illustration_already_voted: int = 0
    # ATTRIBUTE-CHIP CASTERS (2026-07-30, the 2026-07-29 composition audit's §1 Q1 items 1-3).
    # All three chip families were reachable from NEITHER engine: the border caster only via the
    # standalone `local_layout_class_cast` command, and frame-style/bleed-edge only via the
    # live-fetch pilot and via `image_evidence.extract_card_evidence`, which has no production
    # callers at all - which is why frame-style and bleed-edge sat at literally zero machine rows
    # after the 2026-07-29 purge with nothing able to re-derive them. Both casters read stored
    # `ImageEvidence` and fetch nothing, so they cost the conveyor no network budget.
    stage_d_border_chip_votes: int = 0
    stage_d_frame_chip_votes: int = 0
    stage_d_bleed_chip_votes: int = 0
    # Stage C BACKLOG WALK status for this dispatch (issue #468 - `_select_micro_batch` used to
    # discard it, leaving "the Stage C backlog is empty" and "the scan cap was spent finding
    # nothing" indistinguishable to a caller). `stage_c_backlog_found` is how many ids the Stage C
    # cursor walk contributed to this batch; `stage_c_backlog_wrapped` is whether that walk crossed
    # a LAP BOUNDARY (ran off the end of the pk space and reset the cursor to 0) - NOT a claim that
    # the backlog is empty, see `_cursor_chunk_walk`/`SweepLapTracker`. Both are 0/False when the
    # walk never ran (a seed that already filled the batch, or a gate that returned before
    # selection).
    stage_c_backlog_found: int = 0
    stage_c_backlog_wrapped: bool = False
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

    THE CLAIM IS SIZED TO WHAT THIS CALL ACTUALLY CONSUMES, NOT TO THE CHUNK IT READ (2026-07-29 -
    the "dense backlog drains ~`limit/CHUNK_SIZE` per lap" defect). Before this fix the CAS claimed
    the WHOLE chunk (`chunk[-1]`) and the fill loop then stopped the instant `limit` ids had been
    found: with `STAGE_E_SELECTION_CHUNK_SIZE=250` and a `limit` of `STAGE_E_MICRO_BATCH_SIZE=25`,
    a chunk holding 250 eligible cards yielded 25 and the cursor had ALREADY moved past the other
    225 - which were then not revisited until the cursor lapped the entire pk space, so a dense
    backlog drained at ~10% per lap and each lap cost a full traversal. The order is now
    READ -> VERIFY -> DECIDE THE CONSUMPTION BOUNDARY -> CAS-CLAIM EXACTLY THAT BOUNDARY: the walk
    claims up to the last pk it actually takes (`chunk[-1]` whenever the whole chunk is consumed,
    which is every chunk that does not reach `limit`), so an unconsumed chunk tail is simply NEVER
    CLAIMED and the very next call resumes at the first candidate it did not take.

    WHY VERIFY-BEFORE-CLAIM IS STILL RACE-SAFE, and what it costs: the CAS on `position` remains the
    one and only ownership mechanism, still forward-only (`chunk` holds pks strictly `> position`,
    so a claim can never be a no-op self-CAS), and still serialized by the single-row UPDATE - two
    concurrent walkers can never both win a claim over overlapping ranges, so the ids this function
    RETURNS (and therefore the cards a caller dispatches) stay disjoint between walkers exactly as
    before. What moved is only WHERE the wasted work lands when a claim is lost: the loser has now
    already spent one bounded `verify_chunk` query on a range it doesn't own, and discards it. That
    duplicate verification is bounded by `STAGE_E_SELECTION_CHUNK_SIZE` per attempt and by
    `_MAX_SWEEP_CAS_RETRIES` attempts per call - never by catalog size - and is the deliberate price
    of never over-claiming. The alternative (keep claiming the whole chunk, then SHRINK the cursor
    back to the consumed boundary with a second CAS) was rejected: it needs a second write per
    limit-reaching chunk, it moves `position` BACKWARD - the one direction the claim protocol has
    never had to reason about - and its shrink CAS can itself lose to a walker that already claimed
    forward from the over-claimed position, silently reinstating the very skip this fix removes.

    Returns `(found_ids, wrapped)`. `found_ids` is capped at `limit`, always a valid (possibly
    partial, possibly empty) result. `wrapped` is `True` iff this call reached the end of the pk
    space and wrapped the cursor back to 0 - i.e. iff a LAP BOUNDARY was crossed. It is emphatically
    NOT "the backlog is empty": cards can remain eligible behind the cursor (claimed by a concurrent
    walker this call never verified, or - before this call's own next lap - simply not yet re-reached),
    and a wrap says nothing about how much work the lap that just ended dispatched. It is still the
    signal that separates "the pk space ended here" from "the scan cap (or CAS retry budget) was hit
    with more pk space still unscanned ahead of `position`" (issue #460 §4), and callers that need
    "is this backlog actually empty?" must accumulate it into a full-lap judgement - see
    `SweepLapTracker` immediately below, and `stream_backstop_sweep.py`'s own use of it.
    """
    found: list[int] = []
    found_set: set[int] = set()
    chunk_size = getattr(settings, "STAGE_E_SELECTION_CHUNK_SIZE", DEFAULT_SELECTION_CHUNK_SIZE)
    scan_cap = getattr(settings, "STAGE_E_SELECTION_SCAN_CAP", DEFAULT_SELECTION_SCAN_CAP)

    position = StageESweepCursor.get_cursor(cursor_name).position
    examined = 0
    cas_retries = 0
    wrapped = False

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
            wrapped = True
            break

        # Verify the bounded chunk, then decide how far this call will actually consume BEFORE
        # claiming anything (docstring's "THE CLAIM IS SIZED TO WHAT THIS CALL ACTUALLY CONSUMES").
        eligible_ids = set(verify_chunk(chunk))
        take: list[int] = []
        claim_index = len(chunk) - 1
        for index, card_id in enumerate(chunk):
            if card_id in eligible_ids and card_id not in found_set:
                take.append(card_id)
                if len(found) + len(take) >= limit:
                    # `limit` reached mid-chunk: claim exactly up to this card and leave the rest of
                    # the chunk unclaimed for the next call, which resumes at `pk__gt=card_id`.
                    claim_index = index
                    break
        claim_to = chunk[claim_index]

        if not StageESweepCursor.try_advance(cursor_name, position, claim_to):
            # Lost the race for this range to a concurrent dispatch walking the same cursor -
            # discard everything read/verified for it (never claimed, so never a candidate for this
            # call) and retry against the now-current position, up to _MAX_SWEEP_CAS_RETRIES times.
            cas_retries += 1
            if cas_retries > _MAX_SWEEP_CAS_RETRIES:
                break
            position = StageESweepCursor.get_cursor(cursor_name).position
            continue

        # This call now owns (position, claim_to] - and consumed all of it.
        examined += claim_index + 1
        found.extend(take)
        found_set.update(take)
        position = claim_to

    return found[:limit], wrapped


@dataclass
class _CursorLapState:
    """One sweep cursor's own lap bookkeeping inside a single `SweepLapTracker` - see that class's
    own docstring for what each field means and why none of them live in the database."""

    # Has this tracker observed a wrap for this cursor yet? Until it has, the cursor was mid-lap
    # when the tracker started, so the next wrap closes a PARTIAL lap that proves nothing.
    lap_started: bool = False
    # Ids this cursor's walks have yielded since the last wrap this tracker observed.
    found_since_wrap: int = 0
    # Latched once a COMPLETE lap (wrap -> wrap) yielded zero ids; cleared the moment a later walk
    # of the same cursor yields anything again.
    empty_lap_observed: bool = False


class SweepLapTracker:
    """
    LAP-COMPLETION EVIDENCE for the cursor walks above (2026-07-29 - the "a completed lap is
    reported as an empty backlog" defect; the other half of the same defect is issue #468's
    Stage-C leg, fixed by `_select_micro_batch_with_backlog_status` below).

    `_cursor_chunk_walk`'s `wrapped` flag means ONE thing: this call ran off the end of the pk space
    and reset the cursor to 0. `stream_backstop_sweep` used to read that as "the backlog is empty"
    and end the sweep. It is not the same claim, and the difference is not academic - a production
    run on 2026-07-28 dispatched 41 batches and stopped on "Backlog exhausted" with the stage_c
    cursor sitting at position 46,297 and `wrap_count` 7, i.e. mid-catalog after seven laps of a
    230,753-card catalog, leaving the rest of the backlog for nobody (the sweep is the ONLY recovery
    path for a dispatch that returned `throttled-concurrency-cap`, since `Q_CLUSTER["max_attempts"]
    = 1` records those successful and never retries them - see `stream_backstop_sweep.py`'s own
    module docstring).

    THE EVIDENCE BAR THIS CLASS ENFORCES: a backlog counts as empty only when a COMPLETE lap of its
    cursor - from one observed wrap through to the next - yielded ZERO eligible cards. Nothing else
    qualifies. In particular the FIRST wrap a tracker sees is deliberately not evidence: the cursor
    was somewhere mid-pk-space when this sweep started, so the stretch it just finished is a partial
    lap that never examined the pk range behind its own starting position. That first wrap only
    ARMS the tracker (the cursor is now at 0, so the next wrap does close a full lap).

    WHY PROCESS-LOCAL RATHER THAN A CURSOR COLUMN: a `found_since_wrap` field on `StageESweepCursor`
    would be the durable version of this, and would additionally let two concurrent walkers pool
    their evidence - but adding it is a migration, and a sweep invocation is exactly the scope that
    needs the answer ("may I stop now?"). A tracker that starts cold every invocation is also the
    CONSERVATIVE direction: the worst it can do is decline to conclude emptiness and keep sweeping
    until `--max-batches`, never conclude emptiness on less evidence than a full observed lap.

    CONCURRENCY CAVEAT, stated rather than papered over: another walker on the same cursor can claim
    (and dispatch) ranges during this tracker's lap, which this tracker never sees. Such a lap can
    therefore report "no work found" while a sibling walker was busy - the conclusion "this sweep
    has nothing left to do" stays true (the work is another dispatch's, and the next scheduled sweep
    re-checks anyway), but the operator-facing wording must not overstate it, which is why the
    sweep's message says a full lap dispatched nothing rather than that the catalog is clean.
    """

    def __init__(self) -> None:
        self._states: dict[str, _CursorLapState] = {}

    def record(self, cursor_name: str, found: int, wrapped: bool) -> bool:
        """Folds one `_cursor_chunk_walk` result for `cursor_name` into this tracker and returns
        whether a complete, empty lap has been observed for that cursor (i.e. whether the caller may
        treat this backlog as empty). `found` is how many ids that walk yielded, `wrapped` is its
        own second return value."""
        state = self._states.setdefault(cursor_name, _CursorLapState())
        if found:
            state.found_since_wrap += found
            # Work exists again - whatever an earlier lap proved is stale.
            state.empty_lap_observed = False
        if wrapped:
            if state.lap_started and state.found_since_wrap == 0:
                state.empty_lap_observed = True
            state.lap_started = True
            state.found_since_wrap = 0
        return state.empty_lap_observed

    def empty_lap_observed(self, cursor_name: str) -> bool:
        """Read-only view of the same latch `record` returns, for a caller that needs to ask about a
        cursor it did not walk this iteration."""
        state = self._states.get(cursor_name)
        return state.empty_lap_observed if state is not None else False


@dataclass
class _StageCBacklogFill:
    """What `_select_micro_batch_with_backlog_status` reports about the Stage C cursor walk it ran
    (issue #468). `found` is how many ids that walk contributed to this batch (0 when the seed alone
    already filled the batch and the cursor was never touched at all); `wrapped` is
    `_cursor_chunk_walk`'s own second return value for that walk - a LAP BOUNDARY, not emptiness
    (see that function's own docstring, and `SweepLapTracker` for how a caller turns a sequence of
    these into an actual emptiness judgement)."""

    found: int = 0
    wrapped: bool = False


def _select_micro_batch(seed_card_ids: Iterable[int], batch_size: int) -> list[int]:
    """Batch-only view of `_select_micro_batch_with_backlog_status` below - every caller that has no
    use for the Stage C backlog walk's own status (and every test asserting purely on batch
    composition) goes through this one. See that function's docstring for the whole design."""
    batch, _fill = _select_micro_batch_with_backlog_status(seed_card_ids, batch_size)
    return batch


def _select_micro_batch_with_backlog_status(
    seed_card_ids: Iterable[int], batch_size: int
) -> tuple[list[int], _StageCBacklogFill]:
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
    status already exists for exactly this).

    THE WALK'S STATUS IS NO LONGER DISCARDED (issue #468). This function used to drop
    `_cursor_chunk_walk`'s second return value on the floor (`found, _exhausted = ...`), so
    `dispatch_micro_batch` returned the SAME "empty" status for "the Stage C backlog is genuinely
    empty" and "the scan cap was spent examining ineligible cards and there is more pk space ahead"
    - the exact conflation issue #460 §4 removed from the Stage D leg, left in place on this one.
    Both are now reported, via `_StageCBacklogFill`, up through `DispatchOutcome`
    (`stage_c_backlog_found`/`stage_c_backlog_wrapped`) to the one caller that has a decision to
    make with them, `stream_backstop_sweep`. Nothing about which cards land in the batch changes.
    """
    fill = _StageCBacklogFill()
    seen: list[int] = []
    seen_set: set[int] = set()
    for card_id in seed_card_ids:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)
    if len(seen) >= batch_size:
        # Seed alone fills the batch - the cursor is never read, so this call contributes NO lap
        # evidence either way (a default `_StageCBacklogFill` is exactly "walk not run").
        return seen[:batch_size], fill

    manifest_versions = _stage_c_manifest_versions()

    def _verify_stage_c_chunk(chunk: list[int]) -> Iterable[int]:
        done_ids = set(
            ImageEvidence.objects.filter(card_id__in=chunk, extractor_versions__contains=manifest_versions).values_list(
                "card_id", flat=True
            )
        )
        return [card_id for card_id in chunk if card_id not in done_ids]

    found, wrapped = _cursor_chunk_walk(StageESweepCursor.STAGE_C, _verify_stage_c_chunk, batch_size - len(seen))
    fill.found = len(found)
    fill.wrapped = wrapped
    for card_id in found:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)

    return seen[:batch_size], fill


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
    # 2026-07-29 (`collector_line_artist`'s CARD-NAME NARROWING): the card's own uploaded name,
    # read off the SAME already-loaded `Card` instance every other field here comes from - no
    # second query on either side of the fetch/compute boundary. The compute loop resolves it to
    # this card's real artists via the batch's own `NameArtistLookup`; it is deliberately NOT
    # resolved on the fetch thread, which must stay purely I/O-bound. Defaulted (like every field
    # after `lockout` here) so the two error/lockout constructions above stay keyword-complete.
    card_name: str = ""
    # `throttled=True` iff this card's own fetch raised `harvest_fetch_limiter
    # .DestinationThrottledError` (a 429/503 from the destination) - RATE PRESSURE, the third and
    # mildest of this dataclass's three failure severities, added 2026-07-30 under the owner rate
    # ruling ("the limit needs to throttle not shut it down"). The other two both STOP the fetch
    # thread (`lockout` and `error` each set `stop_event` and return); this one does NOT - the
    # thread proceeds to the next card, and the limiter's own already-widened pacing interval is
    # what makes that next fetch slower. The compute loop must NOT record a throttled outcome onto
    # the fetch-outcome window: doing so is exactly what used to let sustained rate pressure trip
    # `EnvelopeTrip.Bar.FETCH_FAILURE_RATE` and hard-stop the whole unattended pass.
    throttled: bool = False


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

    A THROTTLE (2026-07-30 owner rate ruling: "the limit needs to throttle not shut it down") is
    the one severity that does NOT stop this thread. `DestinationThrottledError` means the
    destination answered 429/503 and `harvest_fetch_limiter` has ALREADY widened its own pacing
    interval; the correct response is to mark this one card deferred (`throttled=True`) and CARRY
    ON to the next card, whose fetch will now be slower because of that widening. `stop_event` is
    deliberately NOT set, no error is packaged, and the run continues at a degraded rate. Note the
    ordering constraint this creates: `except DestinationThrottledError` must sit ABOVE the broad
    `except Exception`, or the throttle is swallowed into the stop-the-thread path and the whole
    conversion is undone.
    """
    from cardpicker.harvest_fetch_limiter import DestinationThrottledError
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
                    sha256_checksum=card.sha256_checksum,
                    image_bytes=None,
                    fetch_latency_ms=0.0,
                    card_name=card.name,
                    lockout=True,
                )
            )
            return
        except DestinationThrottledError:
            # NOT a stop - see this function's own docstring. No `stop_event.set()`, no `return`:
            # the loop proceeds to the next card at the limiter's newly-widened pace.
            logger.warning(
                "Stage E dispatch: throttled fetching card %s - deferring it and continuing at a slower pace",
                card.pk,
            )
            out_queue.put(
                _StageCFetchOutcome(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    md5_checksum=card.md5_checksum,
                    sha256_checksum=card.sha256_checksum,
                    image_bytes=None,
                    fetch_latency_ms=0.0,
                    card_name=card.name,
                    throttled=True,
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring above
            stop_event.set()
            out_queue.put(
                _StageCFetchOutcome(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    md5_checksum=card.md5_checksum,
                    sha256_checksum=card.sha256_checksum,
                    image_bytes=None,
                    fetch_latency_ms=0.0,
                    card_name=card.name,
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
                sha256_checksum=card.sha256_checksum,
                image_bytes=image_bytes,
                fetch_latency_ms=fetch_latency_ms,
                card_name=card.name,
            )
        )


def _run_stage_c(
    batch_ids: list[int],
    run_id: str,
    outcome: DispatchOutcome,
    force_stage_c_reextract: bool = False,
    short_circuit: Optional[bool] = None,
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
    already-done exclusion applies, exactly as before this parameter existed. `True` skips the
    already-done exclusion entirely, so every id in `batch_ids` gets a fresh fetch + extract
    regardless of manifest completeness - built for cards whose CURRENT full-manifest
    `ImageEvidence` row already exists but carries blank values (the Bug-A tail's own signature, a
    card the already-done check below would otherwise wrongly treat as finished). Transfer-checking
    (phase 1) is deliberately UNCONDITIONAL regardless of this flag - a force-re-extracted card with
    a genuinely current, good md5-sibling gets FIXED by transfer immediately rather than paying for
    a real re-fetch of what would produce the same bytes anyway;
    `evidence_transfer.find_transfer_source`'s own asserts are what keep this safe.

    `short_circuit` (2026-07-28, `management/commands/stream_full_catalog.py`'s one conveyor
    change - DECOUPLED from `force_stage_c_reextract`, see below): forwarded verbatim to
    `image_evidence.compute_card_evidence`'s own parameter of the same name. `None` (the default)
    is that function's own "resolve from the `STAGE_C_NO_SHORTCIRCUIT` env var AT CALL TIME"
    behaviour (`image_evidence._short_circuit_enabled_by_env`); an explicit `False` disables the
    collector-line OCR tier-1 short-circuit so every card runs the full extractor escalation ladder
    (the same effect `run_image_evidence_cohort.py`'s own `--no-shortcircuit` flag has - that
    command's mechanism reused here, not reimplemented); an explicit `True` forces the
    short-circuit on regardless of the env var.

    WHY THE TWO WERE CONFLATED, AND WHY THEY NO LONGER ARE: issue #465 introduced
    `force_stage_c_reextract` for exactly ONE caller (`stage_e_shakedown`) with exactly ONE cohort
    (the issue-#418 Bug-A blank-tier-1 tail). For that cohort the two settings genuinely co-vary -
    every card in it is a card whose tier-1 read came back blank, so re-extracting it while still
    permitting the tier-1 short-circuit would reproduce the very blank read that put it in the
    cohort. `force_stage_c_reextract=True` therefore hardcoded `short_circuit=False` alongside it,
    and one parameter carried two independent meanings ("ignore the already-done manifest check"
    and "run the full escalation ladder") purely because the sole caller wanted both.
    A FULL-CATALOG pass (`stream_full_catalog`, 2026-07-28) is the first caller that wants the
    first meaning WITHOUT the second: it re-extracts every card in the catalog, the overwhelming
    majority of which read fine at tier 1, and forcing 6 extra tesseract calls per card across
    230k cards is a multiple of the run's whole compute budget for no recovery benefit. The two
    are now separate parameters with separate defaults, and `stage_e_shakedown` passes
    `short_circuit=False` EXPLICITLY (its behaviour is unchanged - the value it always got, now
    stated at the call site instead of inferred from a sibling flag).

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
        manifest_versions = _stage_c_manifest_versions()
        already_done_ids = set(
            ImageEvidence.objects.filter(
                card_id__in=batch_ids, extractor_versions__contains=manifest_versions
            ).values_list("card_id", flat=True)
        )
    lexicon = known_set_codes()
    # COLLECTOR-LINE ARTIST GATE (2026-07-29 - see `image_evidence.compute_card_evidence`'s own
    # `artist_lexicon` docstring paragraph): built once per batch and threaded through, the same
    # shape `known_set_codes()` immediately above already has, so `compute_card_evidence` keeps
    # issuing no DB query of its own. `build_printing_artist_lookup()` returns a stateful resolver
    # that caches one query per EXPANSION (not per card) across this whole batch.
    artist_lexicon = load_artist_lexicon()
    printing_artist_lookup = build_printing_artist_lookup()

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

        # `run_id=run_id` (2026-07-29): this call can write a durable CardScanLog anomaly row,
        # and until the run_id audit that row was the one machine-written scan log in the app
        # carrying no run stamp - invisible to every run-scoped reconciliation report.
        transfer_source = find_transfer_source(card, run_id=run_id)
        if transfer_source is not None:
            with suppress_evidence_change_echo():
                transfer_evidence(card, transfer_source, run_id=run_id)
            outcome.stage_c_completed += 1
            outcome.stage_c_transferred += 1
            continue

        to_fetch.append(card)

    if not to_fetch:
        return None

    # CARD-NAME NARROWING (2026-07-29 - see `collector_line_artist`'s own docstring section): the
    # third batch-scoped resolver on this same "build once, thread through" convention, but built
    # HERE rather than alongside the other two - after the transfer pass has already established
    # that this batch really does have cards to extract. It is backed by
    # `local_calculate_verdicts._get_cached_candidate_name_index()` (the single process-cached
    # entry point that module documents as mandatory for every batch-reachable caller, so a worker
    # that also runs Stage D shares the one index rather than building a second), and building
    # that index is the most expensive of the three - a batch whose cards were all satisfied by
    # evidence transfer must not pay for it, the same laziness `run_join_key_calculator`'s own
    # `index` already practises.
    name_artist_lookup = build_name_artist_lookup()

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

            if fetch_outcome.throttled:
                # THE HALT->THROTTLE CONVERSION (2026-07-30 owner rate ruling). This branch MUST
                # sit above the `image_bytes is None` one below (a throttled outcome also carries
                # `image_bytes=None`) and MUST NOT touch `_window`. Recording a throttle as a
                # fetch FAILURE is what used to make sustained rate pressure indistinguishable
                # from a broken dependency: at >1% of a rolling 500-card window it tripped
                # `EnvelopeTrip.Bar.FETCH_FAILURE_RATE`, which is a HARD STOP requiring a human
                # `resolve_envelope_trip` acknowledgement and exits `stream_full_catalog` with
                # code 3 - killing a 230,753-card unattended pass over a condition whose correct
                # answer is "go slower". The card is simply not processed this pass; the Stage C
                # backlog walk re-selects it later, by which time the limiter's pacing has either
                # decayed back toward the ceiling or settled at a rate the destination tolerates.
                # The OTHER three bars are untouched: host load, RSS and a 403 lockout still halt.
                outcome.stage_c_fetch_throttled += 1
                continue

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
                artist_lexicon=artist_lexicon,
                printing_artist_lookup=printing_artist_lookup,
                card_artist_names=name_artist_lookup(fetch_outcome.card_name),
                md5_checksum=fetch_outcome.md5_checksum,
                sha256_checksum=fetch_outcome.sha256_checksum,
            )
            with suppress_evidence_change_echo():
                persist_evidence(result, run_id=run_id)
            outcome.stage_c_completed += 1
    finally:
        # Always signal-then-drain-then-join, whether the loop above finished normally, broke on
        # a lockout, or raised - the fetch-ahead thread is `daemon=True` (won't block process exit
        # on its own) but this function should never RETURN while it's still mid-fetch for a card
        # nothing will ever consume.
        #
        # `stop_event.set()` MUST happen BEFORE the drain+join below (Tron §8 gate condition,
        # 2026-07-25, HIGH severity - found on review): a bare `fetch_thread.join()` here, with
        # neither `stop_event.set()` nor a queue drain first, left the fetch-ahead thread wedged
        # FOREVER the moment COMPUTE (not fetch) raised mid-batch - e.g. a corrupt download that
        # decodes far enough to pass the fetch stage but raises a PIL error inside
        # `compute_card_evidence`/`persist_evidence` above. Once this loop stops calling
        # `fetch_queue.get()` (it exited via the exception), a fetch-ahead thread already blocked
        # on `out_queue.put(...)` for its own next outcome (the queue is bounded at
        # `_STAGE_C_FETCH_AHEAD_DEPTH`) never unblocks on its own - `stop_event` alone does
        # nothing for a thread that isn't back at its own loop-top `if stop_event.is_set(): return`
        # check yet, and nothing else will ever call `.get()` again to free room for that `put()`
        # to complete. The observable failure mode was silent and total: `join()` blocks
        # indefinitely, so this function (and `dispatch_micro_batch`'s own `except Exception:
        # mark_ledger_failed(...); raise` around it) never even reaches the point of recording the
        # crash - the `PilotRunLedger` row stays lying at `RUNNING` forever, and the concurrency-cap
        # slot this dispatch holds (`stage_e_concurrency.try_acquire_dispatch_slot`) never gets
        # released either, wedging the whole worker process's dispatch capacity over ONE corrupt
        # image. Fixed by (1) `stop_event.set()` first, so the thread returns the instant it's back
        # at its own loop-top, and (2) draining `fetch_queue` below, which is what actually
        # unblocks a `put()` already in progress - after at most one more successful put (the one
        # the drain makes room for), the thread reaches its own stop_event check and returns.
        stop_event.set()
        while True:
            try:
                fetch_queue.get_nowait()
            except queue.Empty:
                break
        fetch_thread.join()

    return trip


def _run_illustration_calculator(run_id: str, card_ids: list[int]) -> Any:
    """
    Lazy-import wrapper for `cardpicker.local_illustration.run_illustration_calculator` - mirrors
    `_stage_c_manifest_extractor_keys`'s own posture of avoiding a hard import-time dependency
    between sibling engines (that function's own docstring has the full rationale). The actual
    calculator is the same `run_illustration_calculator` the bulk-management command
    (`local_calculate_verdicts`) already uses, called here with `dry_run=False` and the micro-batch
    `card_ids` scope parameter `local_illustration.py` gained for this module's benefit.
    """
    from cardpicker.local_illustration import run_illustration_calculator

    return run_illustration_calculator(run_id=run_id, dry_run=False, card_ids=card_ids)


def _run_attribute_chip_casters(run_id: str, card_ids: list[int], outcome: DispatchOutcome) -> None:
    """
    THE ATTRIBUTE-CHIP CASTERS, wired into the conveyor (2026-07-30, closing the 2026-07-29
    composition audit's §1 Q1 items 1-3). Same lazy-import posture as
    `_run_illustration_calculator` above, same reasoning.

    WHAT THIS FIXES. The three attribute-chip families - border colour, frame style, bleed edge -
    were reachable from NEITHER engine. `local_fallback`'s three casters are called only from
    `local_identify_printing_tags.run_pilot` (a live-FETCH pilot with ONE completed run in its
    history, 2026-07-16) and from `image_evidence.extract_card_evidence`, which has ZERO production
    callers because both engines call `compute_card_evidence` + `persist_evidence` directly. Border
    colour survived the 2026-07-29 purge only because `local_layout_class_cast` independently
    re-derives it, and even that was reachable only from its own standalone management command.
    Frame style and bleed edge had no such twin and sat at literally zero machine rows.

    BOTH CASTERS READ STORED EVIDENCE AND FETCH NOTHING, which is why they can run inside a
    micro-batch at all: the conveyor's fetch budget and the operating envelope's bars are about
    network and host load, and these two consume neither. Re-deriving these chips through the only
    pre-existing path (the pilot) would instead have meant re-fetching ~220,000 images to recompute
    facts already sitting in the database.

    ORDER IS IRRELEVANT HERE, deliberately, unlike the four printing calculators above: no chip
    caster reads any other calculator's output. Each reads `ImageEvidence` and its own identity's
    prior votes/scan-log rows, so there is no dependency to sequence and no empty-upstream-pool
    failure mode of the kind `_fallback_eligible_cards_queryset`'s docstring describes. They run
    after Stage D's printing calculators only because the printing verdict is the higher-value work
    and should not be delayed behind chips.

    A MISSING TAG SEED MUST NOT DESTROY A MICRO-BATCH. Both casters raise `RuntimeError` when their
    attribute-chip `Tag` rows have not been seeded - the right behaviour for a standalone management
    command an operator is watching, and the wrong behaviour here: by the time this runs, the four
    printing calculators above have ALREADY written their votes, and letting the exception out would
    mark the whole dispatch FAILED (`mark_ledger_failed`) over an operator setup gap in an advisory
    chip. So the seed gap is caught, logged at ERROR, and leaves the three counters at 0. It is NOT
    silently swallowed - a persistent zero on a chip counter is precisely the signal the 2026-07-29
    audit says to read as "this channel never ran", and the log line names the fix. Only that
    `RuntimeError` is caught; every other exception propagates exactly as the printing calculators'
    already do.
    """
    from cardpicker.local_attribute_chip_cast import run_attribute_chip_cast
    from cardpicker.local_layout_class_cast import run_layout_class_cast

    try:
        border_result = run_layout_class_cast(run_id=run_id, dry_run=False, card_ids=card_ids)
        outcome.stage_d_border_chip_votes = border_result.votes_written

        chip_result = run_attribute_chip_cast(run_id=run_id, dry_run=False, card_ids=card_ids)
        outcome.stage_d_frame_chip_votes = chip_result.frame_votes_written
        outcome.stage_d_bleed_chip_votes = chip_result.bleed_votes_written
    except RuntimeError as exc:
        logger.error(
            "Attribute-chip casters skipped for run_id=%s: %s Stage D's printing votes for this "
            "batch are unaffected and already written. Run `seed_default_tags`/`seed_attribute_tags`"
            "/`seed_sensitive_tags` to close this - until then the border/frame/bleed chip counters "
            "stay at zero on every dispatch.",
            run_id,
            exc,
        )


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

    illustration_result = _run_illustration_calculator(run_id=run_id, card_ids=batch_ids)
    outcome.stage_d_illustration_votes = illustration_result.votes_written
    outcome.stage_d_illustration_already_voted = illustration_result.already_voted

    slow_path_result = run_slow_path_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_slow_path_routed = slow_path_result.routed_written

    # See `_run_attribute_chip_casters`' own docstring: three chip families that were reachable
    # from neither engine, two of them at zero rows with no substitute. Zero image fetches.
    _run_attribute_chip_casters(run_id=run_id, card_ids=batch_ids, outcome=outcome)


def dispatch_micro_batch(
    card_ids: Optional[Iterable[int]] = None,
    trigger_reason: str = "event",
    run_id: Optional[str] = None,
    batch_size: Optional[int] = None,
    force_stage_c_reextract: bool = False,
    short_circuit: Optional[bool] = None,
) -> DispatchOutcome:
    """
    The CONVEYOR itself - one micro-batch dispatch decision (docs/proposals/stage-e-streaming.md
    §3, this module's own docstring). Called by `cardpicker.stage_e_signals`'s own event receivers
    (via `dispatch_for_card`, `card_ids=[the triggering card's own pk]`), by `stream_backstop_sweep`
    (`card_ids=None`, letting `_select_micro_batch` fill the whole batch from the backlog), by
    `management/commands/stage_e_shakedown.py` (issue #465, `card_ids=<its own driven chunk>`,
    `force_stage_c_reextract=True, short_circuit=False`), and by
    `management/commands/stream_full_catalog.py` (2026-07-28, `card_ids=<its own driven chunk>`,
    both of those two settings independently operator-selected per invocation).

    `force_stage_c_reextract` (issue #465) and `short_circuit` (2026-07-28): both forwarded
    straight through to `_run_stage_c` - see that function's own docstring for what each one does,
    and for the "WHY THE TWO WERE CONFLATED, AND WHY THEY NO LONGER ARE" note. Their defaults
    (`False`/`None`) together reproduce this function's pre-#465 behaviour BYTE-IDENTICALLY: the
    already-done manifest check applies, and `compute_card_evidence` resolves its short-circuit
    from the `STAGE_C_NO_SHORTCIRCUIT` env var at call time.

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

    # BATCH SIZE (2026-07-29 - `cardpicker.stage_e_batch_sizing`'s own module docstring carries the
    # rule, the measurements it was read off, and the precedence order). An explicit `batch_size`
    # still wins outright, exactly as before. What changed is the FALLBACK: it used to be a flat
    # `settings.STAGE_E_MICRO_BATCH_SIZE` read, and is now MODE_INCREMENTAL - because the only
    # caller that ever reaches this fallback is `dispatch_for_card`, the event echo, whose single
    # triggering card must not turn into a bulk-sized django-q task. Every DRIVER
    # (`stream_full_catalog`, `stream_backstop_sweep`, `stage_e_shakedown`) resolves its own size
    # up front and passes it explicitly, so none of them lands here.
    effective_batch_size = resolve_micro_batch_size(explicit=batch_size, mode=MODE_INCREMENTAL).batch_size
    batch_ids, stage_c_fill = _select_micro_batch_with_backlog_status(card_ids or (), effective_batch_size)
    if not batch_ids:
        # "empty" now CARRIES the Stage C walk's own status (issue #468) instead of flattening
        # "genuinely empty" and "scan cap spent finding nothing" into one indistinguishable result.
        return DispatchOutcome(
            status="empty",
            run_id=run_id,
            stage_c_backlog_found=stage_c_fill.found,
            stage_c_backlog_wrapped=stage_c_fill.wrapped,
        )

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
            return DispatchOutcome(
                status="throttled-concurrency-cap",
                run_id=run_id,
                stage_c_backlog_found=stage_c_fill.found,
                stage_c_backlog_wrapped=stage_c_fill.wrapped,
            )

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

        outcome = DispatchOutcome(
            status="completed",
            run_id=dispatch_run_id,
            card_ids=batch_ids,
            stage_c_backlog_found=stage_c_fill.found,
            stage_c_backlog_wrapped=stage_c_fill.wrapped,
        )
        batch_start = time.monotonic()

        try:
            lockout_trip = _run_stage_c(
                batch_ids,
                dispatch_run_id,
                outcome,
                force_stage_c_reextract=force_stage_c_reextract,
                short_circuit=short_circuit,
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
                    # Rate-pressure deferrals (2026-07-30 owner rate ruling) - recorded alongside, never
                    # inside, the failure count. See `DispatchOutcome.stage_c_fetch_throttled`.
                    "stage_c_fetch_throttled": outcome.stage_c_fetch_throttled,
                    "stage_d_join_key_votes": outcome.stage_d_join_key_votes,
                    "stage_d_join_key_already_voted": outcome.stage_d_join_key_already_voted,
                    "stage_d_fallback_votes": outcome.stage_d_fallback_votes,
                    "stage_d_fallback_already_voted": outcome.stage_d_fallback_already_voted,
                    "stage_d_illustration_votes": outcome.stage_d_illustration_votes,
                    "stage_d_illustration_already_voted": outcome.stage_d_illustration_already_voted,
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
