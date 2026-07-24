"""
Stage E Phase 1 - envelope enforcement primitive (docs/proposals/stage-e-streaming.md §3
decision (5) and §10(a), the owner-ratified 2026-07-24 "Ratified amendments" section - PASSIVE-
mode bars). Pure primitive: checks the four ratified bars against live signals the caller
supplies, persists an `EnvelopeTrip` row (models.py - a ledger-ADJACENT record, not a
`PilotRunLedger` row itself, see that model's own docstring for why) the moment any bar is
crossed, and exposes `current_trip()` so a caller can cheaply ask "is the envelope tripped right
now" before every dispatch decision.

NOT wired into a streaming dispatch loop yet - that's Stage E Phase 2. `docs/proposals/stage-e-
streaming.md` itself is still HOLD (owner review pending, per its own header) - only the
mechanism that brief already specced in detail (§3 decision (5), sharpened by §10(a)'s numeric
ratification) is built here. This module has no call site of its own in this change; it is a
tested, standalone primitive a future streaming loop will call before every micro-batch dispatch.
Batch commands may optionally adopt the RSS/lockout bars where they already have equivalents (see
`run_image_evidence_cohort.py`'s own pre-existing `--max-rss-mb`/lockout handling) - this module
does not change any batch command's behaviour, and nothing in this change wires it into one.

THE FOUR RATIFIED PASSIVE-MODE BARS (§10(a), verbatim numbers - none invented here):
  1. Host load average > 7.0 - the existing escalation threshold (§3 decision (3)/§1, reused
     unchanged; see docs/reports/2026-07-23-4c-pilot-dry-run.md's own "well under the 7.0
     escalation threshold" note).
  2. RSS > 512MB per worker.
  3. Fetch-failure rate > 1% over a rolling 500-card window.
  4. INSTANT pause on any Google fetch lockout signal (`GoogleFetchLockoutError` -
     harvest_fetch_limiter.py's existing `lockout_hit` bar, reused unchanged) - no threshold to
     cross, any occurrence trips immediately.

BULK mode (backfill work, polled per-batch via `pilot_run_lifecycle.py`'s forced dry-run gate) is
explicitly NOT governed by this module at all (§10(a)) - this primitive is PASSIVE-mode only.

RESUME SEMANTICS (§3 decision (5), unchanged by §10(a)'s numeric ratification): a tripped envelope
HALTS and requires a FRESH OWNER ACTION to resume - no self-resume, ever, matching #373's
`--skip-dryrun-check` posture (an override is allowed, but never silent/automatic). This module
implements the HALT+RECORD side only (`check_envelope` persists the trip; `current_trip` reports
it, gating any future caller's own dispatch decision). The RESUME path is
`resolve_envelope_trip` (a small management command requiring `--acknowledge-trip <trip-id>`,
`cardpicker/management/commands/resolve_envelope_trip.py`) - a phase-2 streaming dispatcher's own
poll loop is expected to call `current_trip()` before every micro-batch and refuse to dispatch
while it returns non-None, exactly as `enforce_dry_run_precondition` already refuses to write
without a matching prior dry run.
"""

from dataclasses import dataclass
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from cardpicker.models import EnvelopeTrip

# §10(a) ratified numeric bounds - PASSIVE mode only (see module docstring). None of these are
# invented here; every one is cited to a specific brief section in the module docstring above.
HOST_LOAD_CEILING = 7.0
RSS_MB_PER_WORKER_CEILING = 512.0
FETCH_FAILURE_RATE_CEILING = 0.01
FETCH_FAILURE_WINDOW = 500


@dataclass(frozen=True)
class EnvelopeSignals:
    """
    The live signals a caller (the phase-2 streaming dispatcher) samples before each dispatch
    decision - deliberately plain data, no I/O of its own, so this module's own bar-checking logic
    is trivially unit-testable without mocking `os.getloadavg`/`/proc` reads or a rolling-window
    data structure. The caller owns sampling (`os.getloadavg()[0]`, a per-worker RSS read - see
    `cardpicker.process_metrics.get_process_rss_mb` for the shared helper this module's own tests
    use as an example caller - and its own rolling fetch-outcome window, e.g. a
    `collections.deque(maxlen=FETCH_FAILURE_WINDOW)`), never this module.
    """

    load_avg: Optional[float] = None
    rss_mb_per_worker: Optional[float] = None
    # (failures, total) over the caller's own rolling window - caller owns the windowing, this
    # module only computes the rate and compares it to the ceiling. total=0 means "not enough data
    # yet" - never trips on an empty window (see _bar_breach below).
    fetch_failures_in_window: int = 0
    fetch_total_in_window: int = 0
    google_lockout: bool = False


def _bar_breach(signals: EnvelopeSignals) -> Optional[tuple[str, dict]]:
    """
    Returns `(bar, detail)` for the FIRST bar breached, checked in the priority order the brief
    itself implies (§10(a) lists the instant lockout pause distinctly from the other three's
    numeric ceilings) - lockout first, then load, then RSS, then fetch-failure rate. Returns
    `None` when nothing is breached. Priority only matters for WHICH bar gets attributed when more
    than one is breached in the exact same sample - a caller should stop dispatch regardless of
    which one is reported, so this ordering is a diagnostics/attribution choice, not a soundness
    one.
    """
    if signals.google_lockout:
        return EnvelopeTrip.Bar.GOOGLE_LOCKOUT, {}
    if signals.load_avg is not None and signals.load_avg > HOST_LOAD_CEILING:
        return EnvelopeTrip.Bar.HOST_LOAD, {"load_avg": signals.load_avg, "ceiling": HOST_LOAD_CEILING}
    if signals.rss_mb_per_worker is not None and signals.rss_mb_per_worker > RSS_MB_PER_WORKER_CEILING:
        return (
            EnvelopeTrip.Bar.RSS,
            {"rss_mb_per_worker": signals.rss_mb_per_worker, "ceiling": RSS_MB_PER_WORKER_CEILING},
        )
    if signals.fetch_total_in_window > 0:
        rate = signals.fetch_failures_in_window / signals.fetch_total_in_window
        if rate > FETCH_FAILURE_RATE_CEILING:
            return (
                EnvelopeTrip.Bar.FETCH_FAILURE_RATE,
                {
                    "fetch_failure_rate": rate,
                    "ceiling": FETCH_FAILURE_RATE_CEILING,
                    "failures": signals.fetch_failures_in_window,
                    "total": signals.fetch_total_in_window,
                },
            )
    return None


def check_envelope(signals: EnvelopeSignals, run_id: Optional[str] = None) -> Optional[EnvelopeTrip]:
    """
    The primitive itself - checks `signals` against the four ratified PASSIVE-mode bars (module
    docstring) and, on the FIRST breach found, persists a NEW `EnvelopeTrip` row and returns it.
    Returns `None` when nothing is breached (safe to dispatch).

    Deliberately does NOT consult `current_trip()` first / does not deduplicate against an
    existing open trip - the caller (a phase-2 dispatcher) is expected to check `current_trip()`
    BEFORE ever calling this (no dispatch happens while a trip is already open, so this function
    should never even be reached mid-trip in the real flow); this function's own job is narrowly
    "does THIS sample breach a bar", not "is the envelope currently open" - `current_trip` answers
    that question.
    """
    breach = _bar_breach(signals)
    if breach is None:
        return None
    bar, detail = breach
    return EnvelopeTrip.objects.create(bar=bar, detail=detail, run_id=run_id)


def current_trip(run_id: Optional[str] = None) -> Optional[EnvelopeTrip]:
    """
    The RESUME-gating query (module docstring) - the most recent UNACKNOWLEDGED `EnvelopeTrip`
    row, if any. `None` means the envelope is currently clear, safe to dispatch.

    When `run_id` is given, scoped to trips recorded under that `run_id` OR with no `run_id` at
    all - a trip recorded before this run_id existed (or by a shared/prior dispatcher instance)
    still gates, matching `enforce_dry_run_precondition`'s own "`scope=None` on the caller side
    matches any scoped or unscoped row" convention (`pilot_run_lifecycle.py`) rather than letting a
    fresh run_id silently bypass an unresolved trip from an earlier one.
    """
    queryset = EnvelopeTrip.objects.filter(acknowledged_at__isnull=True)
    if run_id is not None:
        queryset = queryset.filter(Q(run_id=run_id) | Q(run_id__isnull=True))
    return queryset.order_by("-tripped_at").first()


def acknowledge_trip(trip_id: str, note: str) -> EnvelopeTrip:
    """
    The RESUME action itself (module docstring's "requires a fresh owner action... no self-
    resume" - #373's `--skip-dryrun-check` posture: an override is allowed, but never silent).
    Called ONLY from `resolve_envelope_trip`'s own management command (its `--acknowledge-trip
    <trip-id>` flag is mandatory, never optional/defaulted) - never from anywhere in a dispatch
    path, so a streaming loop can never resume itself.

    `note` is mandatory and non-empty (enforced by the caller, `resolve_envelope_trip.py`, not
    re-validated here) so an acknowledgement always carries a human-readable reason, not just a
    timestamp.

    Raises `EnvelopeTrip.DoesNotExist` if `trip_id` doesn't match any row, and `ValueError` if the
    matched row is already acknowledged (an acknowledged trip is a closed, immutable record -
    never silently re-acknowledged/overwritten by a second call).
    """
    trip = EnvelopeTrip.objects.get(trip_id=trip_id)
    if trip.acknowledged_at is not None:
        raise ValueError(f"Trip {trip_id!r} was already acknowledged at {trip.acknowledged_at.isoformat()}.")
    trip.acknowledged_at = timezone.now()
    trip.acknowledged_note = note
    trip.save(update_fields=["acknowledged_at", "acknowledged_note"])
    return trip
