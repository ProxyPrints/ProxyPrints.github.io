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
(`cardpicker.image_evidence.compute_card_evidence`/`persist_evidence`, called per-card,
SEQUENTIALLY - fed by `cardpicker.image_cdn_fetch.fetch_card_image_bytes`) -> Stage D calculators
(`cardpicker.local_calculate_verdicts.run_join_key_calculator`/`run_fallback_calculator`/
`run_slow_path_calculator`, called AS-IS with the new `card_ids` scope, in the same join-key ->
fallback -> slow-path escalation order every BULK-mode command already uses) -> ledger write.
Sequential, not pooled, on purpose: PASSIVE mode's own micro-batches (§3 decision (2), a handful to
a few dozen cards) are far too small for BULK mode's process-pool concurrency to buy anything - it
would only add a fork's worth of startup overhead per batch. This matches the brief's own "a
single-worker, single-core floor mode must be correct, just slow, never a degraded/unsound mode"
requirement (§5).

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
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Optional

from django.conf import settings
from django.utils import timezone

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.local_calculate_verdicts import (
    known_set_codes,
    run_fallback_calculator,
    run_join_key_calculator,
    run_slow_path_calculator,
)
from cardpicker.models import Card, EnvelopeTrip, ImageEvidence, PilotRunLedger
from cardpicker.operating_envelope import (
    FETCH_FAILURE_WINDOW,
    EnvelopeSignals,
    check_envelope,
    current_trip,
)
from cardpicker.pilot_run_lifecycle import mark_ledger_failed, merge_counters
from cardpicker.process_metrics import get_process_rss_mb
from cardpicker.utils import get_baked_git_sha

logger = logging.getLogger(__name__)

# Placeholder pending §10(c)'s own measurement (see MPCAutofill/settings.py's own
# STAGE_E_MICRO_BATCH_SIZE comment for the full citation) - not invented precision, a
# conservative default inside the brief's own "roughly 10-100" sanity range.
DEFAULT_MICRO_BATCH_SIZE = 25


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
    stage_c_fetch_failures: int = 0
    stage_d_join_key_votes: int = 0
    stage_d_fallback_votes: int = 0
    stage_d_slow_path_routed: int = 0
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


def _select_micro_batch(seed_card_ids: Iterable[int], batch_size: int) -> list[int]:
    """
    Builds one micro-batch's own card-id list (docs/proposals/stage-e-streaming.md §3 decision (2)):
    starts with `seed_card_ids` (the event trigger's own touched card, or an empty seed for the
    backstop sweep) and fills up to `batch_size` from the general Stage C backlog - cards with a
    stable content hash but no CURRENT `ImageEvidence` row carrying every manifest extractor key
    (the SAME shape `run_image_evidence_cohort.py`'s own resume filter uses, imported not
    reimplemented - see `_stage_c_manifest_extractor_keys`). Order preserved (seed first),
    de-duplicated. Bounded reads only (`[:batch_size]`/`[:remaining]` slices, never a full-table
    materialization) - the whole point of a micro-batch is a bounded-cost dispatch (§3 decision (2)'s
    own "one batch's wall-clock cost stays in the few-seconds-to-low-tens-of-seconds range").

    Deliberately does NOT also backfill from the Stage-D-only backlog (cards whose Stage C evidence
    is already complete but that have never had a Stage D pass) - the seed card itself always gets a
    Stage D attempt regardless (`dispatch_micro_batch` scopes Stage D to the WHOLE returned batch,
    seed included), and Stage C is the dominant wall-clock cost driver `batch_size` is sized against
    (§3 decision (2)/§1's own worst-case floor), so backlog-filling from Stage C's own queue is the
    lever that matters for keeping a batch's wall-clock cost bounded.
    """
    seen: list[int] = []
    seen_set: set[int] = set()
    for card_id in seed_card_ids:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)
    if len(seen) >= batch_size:
        return seen[:batch_size]

    remaining = batch_size - len(seen)
    manifest_keys = list(_stage_c_manifest_extractor_keys())
    fully_processed_ids = ImageEvidence.objects.filter(extractor_versions__has_keys=manifest_keys).values_list(
        "card_id", flat=True
    )
    backlog_ids = (
        Card.objects.filter(content_phash__isnull=False)
        .exclude(pk__in=seen_set)
        .exclude(pk__in=fully_processed_ids)
        .order_by("pk")
        .values_list("pk", flat=True)[:remaining]
    )
    for card_id in backlog_ids:
        if card_id not in seen_set:
            seen.append(card_id)
            seen_set.add(card_id)
    return seen[:batch_size]


def _run_stage_c(batch_ids: list[int], run_id: str, outcome: DispatchOutcome) -> Optional[EnvelopeTrip]:
    """
    Sequential, per-card Stage C extraction over whichever of `batch_ids` still lack a full
    manifest - the SAME per-card unit (`image_evidence.compute_card_evidence` +
    `image_evidence.persist_evidence`, fed by `image_cdn_fetch.fetch_card_image_bytes`)
    `run_image_evidence_cohort.py`'s own fetch/compute stages call, just driven one card at a time
    (module docstring's own "PIPELINE STAGES" section explains why). Every fetch outcome is recorded
    onto `_window` regardless of whether it ends up mattering to THIS batch's own envelope decision -
    the window spans the whole worker process's uptime, not one batch.

    Returns the `EnvelopeTrip` this call itself recorded (only possible via the instant Google
    lockout bar - see `GoogleFetchLockoutError` below), or `None`. A lockout stops Stage C
    IMMEDIATELY for this batch - in-flight work already committed stays committed (each card's
    `persist_evidence` call is already durable the instant it returns, matching the resume
    contract's own "one-transaction batch commit or explicit evidence-first statement" - here, every
    card's own persist is its own transaction, so there is no partial-card state to roll back) - and
    records a fresh trip via `check_envelope(google_lockout=True)` so the NEXT dispatch call refuses
    until an owner acknowledges it, matching the "instant pause" bar exactly.
    """
    from io import BytesIO

    from PIL import Image

    from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image_bytes
    from cardpicker.image_evidence import compute_card_evidence, persist_evidence

    manifest_keys = list(_stage_c_manifest_extractor_keys())
    already_done_ids = set(
        ImageEvidence.objects.filter(card_id__in=batch_ids, extractor_versions__has_keys=manifest_keys).values_list(
            "card_id", flat=True
        )
    )
    lexicon = known_set_codes()

    for card_id in batch_ids:
        if card_id in already_done_ids:
            continue
        try:
            card = Card.objects.select_related("source").get(pk=card_id)
        except Card.DoesNotExist:
            continue
        if card.content_phash is None:
            continue

        fetch_started_at = time.monotonic()
        try:
            image_bytes = fetch_card_image_bytes(card, dpi=DEFAULT_FETCH_DPI)
        except GoogleFetchLockoutError:
            _window.record(success=False)
            logger.error("Stage E dispatch: GoogleFetchLockoutError observed - halting Stage C for this batch")
            return check_envelope(_sample_envelope_signals(google_lockout=True), run_id=run_id)
        fetch_latency_ms = (time.monotonic() - fetch_started_at) * 1000

        if image_bytes is None:
            _window.record(success=False)
            outcome.stage_c_fetch_failures += 1
            continue

        _window.record(success=True)
        image = Image.open(BytesIO(image_bytes))
        result = compute_card_evidence(
            card_id, card.content_phash, image, fetch_latency_ms=fetch_latency_ms, known_set_codes=lexicon
        )
        persist_evidence(result, run_id=run_id)
        outcome.stage_c_completed += 1

    return None


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
    """
    join_key_result = run_join_key_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_join_key_votes = join_key_result.votes_written + join_key_result.no_match_votes_written

    fallback_result = run_fallback_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_fallback_votes = fallback_result.votes_written

    slow_path_result = run_slow_path_calculator(run_id=run_id, dry_run=False, card_ids=batch_ids)
    outcome.stage_d_slow_path_routed = slow_path_result.routed_written


def dispatch_micro_batch(
    card_ids: Optional[Iterable[int]] = None,
    trigger_reason: str = "event",
    run_id: Optional[str] = None,
    batch_size: Optional[int] = None,
) -> DispatchOutcome:
    """
    The CONVEYOR itself - one micro-batch dispatch decision (docs/proposals/stage-e-streaming.md
    §3, this module's own docstring). Called by `cardpicker.stage_e_signals`'s own event receivers
    (via `dispatch_for_card`, `card_ids=[the triggering card's own pk]`) and by
    `stream_backstop_sweep` (`card_ids=None`, letting `_select_micro_batch` fill the whole batch
    from the backlog).

    Ordering: default-off gate -> no-self-resume gate -> fresh envelope sample -> Stage C
    (sequential, per-card) -> Stage D (AS-IS entry points, scoped) -> ledger write. Every gate below
    returns WITHOUT touching the DB (aside from the envelope check's own trip-persist side effect)
    the instant it applies - a halted dispatch never partially starts Stage C.
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
        lockout_trip = _run_stage_c(batch_ids, dispatch_run_id, outcome)
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
                "stage_c_fetch_failures": outcome.stage_c_fetch_failures,
                "stage_d_join_key_votes": outcome.stage_d_join_key_votes,
                "stage_d_fallback_votes": outcome.stage_d_fallback_votes,
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
