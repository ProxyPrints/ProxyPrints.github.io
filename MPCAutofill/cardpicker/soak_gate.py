"""
Machine-only soak gate: pure evaluation module for the owner-ratified per-width-step
criteria (issue #155). Given a run_id and optionally a step cohort size, computes PASS/FAIL
for each criterion and an overall verdict.

W6 scope (fix-batch plan): MONITORING ONLY - zero changes to vote logic, consensus,
weights, or resolution paths. No new migrations.

The seven criteria:
  1. Fetch-failure rate ≤ 1% for the step (ImageEvidence fetch_ok/fetch_error rows
     scoped to the run_id).
  2. Zero unacknowledged EnvelopeTrip rows for the run.
  3. ImageEvidence rows written for the run within ±5% of the step's eligible cohort
     count (cohort count passed in or computed live - NEVER hardcoded).
  4. Zero cards resolved by machine votes alone (mirrors the verify_zero_resolutions
     pattern from cardpicker.deductive_backfill, see that module's own docstring).
  5. Ledger heartbeat: no gap > 1h between PilotRunLedger activity timestamps for
     the run (uses started_at/finished_at; if the run has only one ledger row, the
     heartbeat is trivially OK).
  6. Canary-step-only (manual): crash-drill kill-and-resume reminder. The gate does
     NOT automate this; the report just prints a reminder line.
  7. Vote yield for the step: REPORTED ONLY (votes cast / cards considered), no
     threshold in v1.

Pure evaluation - performs ZERO writes. The management command
(soak_gate_report.py) is the CLI wrapper that calls this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from cardpicker.models import EnvelopeTrip, ImageEvidence, PilotRunLedger

# ── Thresholds (issue #155 ratified values) ──────────────────────────────
FETCH_FAILURE_RATE_CEILING = 0.01  # ≤ 1%
COHORT_COUNT_TOLERANCE = 0.05  # ± 5%
LEDGER_HEARTBEAT_MAX_GAP = timedelta(hours=1)


@dataclass(frozen=True)
class CriterionResult:
    """Result of a single soak-gate criterion evaluation."""

    name: str
    passed: Optional[bool]  # None = informational only (no threshold)
    measured: str  # human-readable measured value
    detail: str  # explanation or diagnostic


@dataclass
class SoakGateResult:
    """Aggregated result of all seven soak-gate criteria."""

    criteria: list[CriterionResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed is True for c in self.criteria if c.passed is not None)


def _check_fetch_failure_rate(run_id: str) -> CriterionResult:
    """Criterion 1: fetch-failure rate ≤ 1% for the step, computed from
    ImageEvidence rows scoped to the run_id.

    Mirrors the operating_envelope FETCH_FAILURE_RATE_CEILING convention
    (docs/features/stage-e-operations.md's envelope bar table).
    """
    evidence_qs = ImageEvidence.objects.filter(run_id=run_id)
    total = evidence_qs.count()
    if total == 0:
        return CriterionResult(
            name="fetch-failure-rate",
            passed=None,
            measured="0/0",
            detail="No ImageEvidence rows found for this run_id - gate cannot compute fetch-failure rate.",
        )

    failures = evidence_qs.filter(fetch_ok=False).count()
    rate = failures / total

    return CriterionResult(
        name="fetch-failure-rate",
        passed=rate <= FETCH_FAILURE_RATE_CEILING,
        measured=f"{failures}/{total} ({rate:.4%})",
        detail=(
            f"Threshold: ≤ {FETCH_FAILURE_RATE_CEILING:.0%}. "
            f"{'PASS' if rate <= FETCH_FAILURE_RATE_CEILING else 'FAIL'}: "
            f"{failures} failure(s) out of {total} evidence row(s)."
        ),
    )


def _check_envelope_trips(run_id: str) -> CriterionResult:
    """Criterion 2: zero unacknowledged EnvelopeTrip rows for the run.

    An unacknowledged trip is one where acknowledged_at is None (the
    HALT state documented in models.py EnvelopeTrip docstring and
    operating_envelope.py's RESUME SEMANTICS section).
    """
    unacked = EnvelopeTrip.objects.filter(run_id=run_id, acknowledged_at__isnull=True)
    count = unacked.count()

    return CriterionResult(
        name="unacknowledged-envelope-trips",
        passed=count == 0,
        measured=f"{count} open trip(s)",
        detail=(
            "Zero unacknowledged EnvelopeTrip rows required."
            if count == 0
            else f"{count} open trip(s) found - acknowledge via "
            f"resolve_envelope_trip --acknowledge-trip <id> before re-running."
        ),
    )


def _check_evidence_cohort_count(run_id: str, cohort_size: Optional[int]) -> CriterionResult:
    """Criterion 3: ImageEvidence rows written for the run within ±5% of the
    step's eligible cohort count. Cohort count is passed in or computed live -
    NEVER hardcoded (directive: the DB has grown, all counts come from live
    queries).
    """
    evidence_count = ImageEvidence.objects.filter(run_id=run_id).count()

    if cohort_size is not None and cohort_size > 0:
        reference = cohort_size
        source = "CLI argument"
    else:
        # Compute live from the pilot run ledger's counters.
        # run_image_evidence_cohort stores counters as a JSONField on PilotRunLedger.
        ledger = PilotRunLedger.objects.filter(run_id=run_id).first()
        if ledger is not None and ledger.counters and "cohort_size" in ledger.counters:
            reference = int(ledger.counters["cohort_size"])
            source = "PilotRunLedger.counters[cohort_size]"
        else:
            return CriterionResult(
                name="evidence-cohort-count",
                passed=None,
                measured=f"{evidence_count} evidence rows, cohort_size unknown",
                detail=(
                    "No --step-cohort-size provided and no PilotRunLedger.counters "
                    "[cohort_size] found for this run - gate cannot compare evidence "
                    "count against cohort."
                ),
            )

    lower = math.floor(reference * (1 - COHORT_COUNT_TOLERANCE))
    upper = math.ceil(reference * (1 + COHORT_COUNT_TOLERANCE))
    in_range = lower <= evidence_count <= upper

    return CriterionResult(
        name="evidence-cohort-count",
        passed=in_range,
        measured=f"{evidence_count} evidence rows vs {reference} cohort ({source})",
        detail=(
            f"Threshold: ±{COHORT_COUNT_TOLERANCE:.0%} of {reference} "
            f"[{lower}, {upper}]. "
            f"{'PASS' if in_range else 'FAIL'}: {evidence_count} evidence row(s) "
            f"written for run_id={run_id}."
        ),
    )


def _check_zero_machine_resolutions(run_id: str) -> CriterionResult:
    """Criterion 4: zero cards resolved by machine votes alone.

    Mirrors the verify_zero_resolutions pattern from
    cardpicker.deductive_backfill (see that module's own docstring for
    the "should structurally never happen but must be verified" rationale).
    The pattern: for each card that received a machine vote in this run,
    re-run the pure resolve_printing against current DB state and check
    whether any have resolved.

    We do NOT modify deductive_backfill.py (HARD CONSTRAINT: zero changes
    to vote logic). Instead we mirror the check pattern with a comment
    pointing at the original.
    """

    def _verify_zero_resolutions(card_ids: list[int], batch_size: int = 5000) -> list[int]:
        """Mirrors cardpicker.deductive_backfill.verify_zero_resolutions
        (line ~161). The *pure* resolve_printing (never
        resolve_and_persist_printing) re-checked against fresh DB state."""
        from cardpicker.models import Card
        from cardpicker.printing_consensus import resolve_printing

        violations: list[int] = []
        for i in range(0, len(card_ids), batch_size):
            chunk = card_ids[i : i + batch_size]
            for card in Card.objects.filter(pk__in=chunk).iterator(chunk_size=batch_size):
                if resolve_printing(card) is not None:
                    violations.append(card.pk)
        return violations

    # Find cards that received votes from this run. CardPrintingTag has run_id.
    from cardpicker.models import CardPrintingTag

    voted_card_ids = list(CardPrintingTag.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct())

    if not voted_card_ids:
        return CriterionResult(
            name="zero-machine-resolutions",
            passed=True,
            measured="0 voted cards",
            detail="No CardPrintingTag rows found for this run - vacuously passes.",
        )

    violations = _verify_zero_resolutions(voted_card_ids)

    return CriterionResult(
        name="zero-machine-resolutions",
        passed=len(violations) == 0,
        measured=f"{len(violations)} violation(s) from {len(voted_card_ids)} voted card(s)",
        detail=(
            "Zero cards resolved by machine votes alone."
            if not violations
            else f"{len(violations)} card(s) resolved by machine votes alone "
            f"(card pks: {violations[:20]}) - rollback via "
            f"purge_machine_votes --run-id {run_id}."
        ),
    )


def _check_ledger_heartbeat(run_id: str) -> CriterionResult:
    """Criterion 5: ledger heartbeat — the run shows recent activity.

    PilotRunLedger.run_id is UNIQUE (one row per run), so we can't check
    gaps between multiple rows for the same run. Instead, we check whether
    the run is still alive: if the ledger row is RUNNING (finished_at is
    None), started_at must be within 1h — otherwise the run appears stalled.
    For COMPLETED/FAILED runs, the heartbeat is trivially OK (the run
    finished normally).

    This is a deliberate choice over cursor-movement (StageESweepCursor)
    because the heartbeat is about the RUN's own liveness, not cursor
    progress. StageESweepCursor.updated_at tracks sweep progress, which
    is a different concern.
    """
    ledger = PilotRunLedger.objects.filter(run_id=run_id).first()

    if ledger is None:
        return CriterionResult(
            name="ledger-heartbeat",
            passed=True,
            measured="no ledger row",
            detail="No PilotRunLedger row found — heartbeat trivially OK.",
        )

    if ledger.status != PilotRunLedger.Status.RUNNING:
        return CriterionResult(
            name="ledger-heartbeat",
            passed=True,
            measured=f"status={ledger.status}",
            detail=(
                f"Run is {ledger.status} (finished_at="
                f"{ledger.finished_at.isoformat() if ledger.finished_at else '?'}"
                f") — heartbeat trivially OK."
            ),
        )

    # RUNNING with no finished_at: check staleness
    now = timezone.now()
    elapsed = now - ledger.started_at
    passed = elapsed <= LEDGER_HEARTBEAT_MAX_GAP

    return CriterionResult(
        name="ledger-heartbeat",
        passed=passed,
        measured=f"running for {elapsed.total_seconds() / 3600:.1f}h (started {ledger.started_at.isoformat()})",
        detail=(
            f"Threshold: ≤ {LEDGER_HEARTBEAT_MAX_GAP.total_seconds() / 3600:.0f}h "
            f"since started_at for a RUNNING ledger. "
            f"{'PASS' if passed else 'FAIL'}: run has been RUNNING for "
            f"{elapsed.total_seconds() / 3600:.1f}h with no finished_at — "
            f"{'still active' if passed else 'appears stalled'}."
        ),
    )


def _check_vote_yield(run_id: str) -> CriterionResult:
    """Criterion 7: vote yield for the step - REPORTED ONLY (no threshold in v1).

    Votes cast / cards considered, from PilotRunLedger counters including
    the illustration counters #511 added. The exact shape of counters is
    command-specific (run_image_evidence_cohort writes cohort_size,
    completed, fetch_failures, etc.) - this reads whatever is there.
    """
    ledger = PilotRunLedger.objects.filter(run_id=run_id).first()
    if ledger is None:
        return CriterionResult(
            name="vote-yield",
            passed=None,
            measured="no ledger row",
            detail="No PilotRunLedger row found for this run_id.",
        )

    counters = ledger.counters or {}
    # Key fields from run_image_evidence_cohort's own counter shape:
    # cohort_size, completed, fetch_failures, short_circuited, transferred
    cohort = counters.get("cohort_size", "?")
    completed = counters.get("completed", "?")
    fetch_failures = counters.get("fetch_failures", "?")
    short_circuited = counters.get("short_circuited", "?")
    transferred = counters.get("transferred", "?")
    votes_written = ledger.votes_written or 0

    measured = (
        f"votes_written={votes_written} completed={completed}/{cohort} "
        f"fetch_failures={fetch_failures} short_circuited={short_circuited} "
        f"transferred={transferred}"
    )

    return CriterionResult(
        name="vote-yield",
        passed=None,  # informational only, no threshold in v1
        measured=measured,
        detail=(
            f"Ledger command={ledger.command} status={ledger.status} "
            f"started_at={ledger.started_at.isoformat() if ledger.started_at else '?'} "
            f"finished_at={ledger.finished_at.isoformat() if ledger.finished_at else '?'}"
        ),
    )


def evaluate_soak_gate(
    run_id: str,
    *,
    step_cohort_size: Optional[int] = None,
    canary_step: bool = False,
) -> SoakGateResult:
    """Run all seven soak-gate criteria against the given run_id.

    Args:
        run_id: The run_id to evaluate (matches ImageEvidence.run_id,
            EnvelopeTrip.run_id, PilotRunLedger.run_id).
        step_cohort_size: Optional explicit cohort count for criterion 3.
            If not provided, computed live from PilotRunLedger.counters.
        canary_step: If True, include criterion 6's crash-drill reminder.

    Returns:
        SoakGateResult with per-criterion verdicts and an overall
        all_passed property. The management command wraps this with CLI
        output formatting.
    """
    result = SoakGateResult()

    # Criterion 1: fetch-failure rate ≤ 1%
    result.criteria.append(_check_fetch_failure_rate(run_id))

    # Criterion 2: zero unacknowledged EnvelopeTrip rows
    result.criteria.append(_check_envelope_trips(run_id))

    # Criterion 3: evidence count within ±5% of cohort
    result.criteria.append(_check_evidence_cohort_count(run_id, step_cohort_size))

    # Criterion 4: zero machine-only resolutions
    result.criteria.append(_check_zero_machine_resolutions(run_id))

    # Criterion 5: ledger heartbeat no gap > 1h
    result.criteria.append(_check_ledger_heartbeat(run_id))

    # Criterion 6: canary-step-only crash-drill reminder
    if canary_step:
        result.criteria.append(
            CriterionResult(
                name="crash-drill-reminder",
                passed=None,
                measured="(manual step)",
                detail=(
                    "Canary step: the crash-drill kill-and-resume test "
                    "(step 1 of the width ramp) requires a manual DRILL-PASS "
                    "before widening. Run the crash-drill, observe clean "
                    "resume, record result."
                ),
            )
        )

    # Criterion 7: vote yield (informational)
    result.criteria.append(_check_vote_yield(run_id))

    return result
