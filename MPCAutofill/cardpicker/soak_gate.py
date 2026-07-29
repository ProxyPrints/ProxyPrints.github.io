"""
Machine-only soak gate: pure evaluation module for the owner-ratified per-width-step
criteria (issue #155). Given a run_id and optionally a step cohort size, computes an outcome
for each criterion and an overall PASS / FAIL / INSUFFICIENT-DATA verdict.

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
     the run (uses started_at/finished_at). NO ledger row at all is
     INSUFFICIENT-DATA, not a pass - see that criterion's own comment.
  6. Canary-step-only (manual): crash-drill kill-and-resume reminder. The gate does
     NOT automate this; the report just prints a reminder line.
  7. Vote yield for the step: REPORTED ONLY (votes cast / cards considered), no
     threshold in v1.

Criterion 0 (`run-observed`) is not one of the seven: it is the
precondition added by the 2026-07-29 gate-semantics fix below, and it is
what makes a run that produced no observations at all unable to pass.

Pure evaluation - performs ZERO writes. The management command
(soak_gate_report.py) is the CLI wrapper that calls this module.

THREE VERDICTS, NOT A BOOLEAN (2026-07-29 gate-semantics fix)
------------------------------------------------------------
The gate's first form aggregated a per-criterion `Optional[bool]` with
`all(c.passed is True for c in criteria if c.passed is not None)`. That
expression cannot return a negative answer for an unmeasured run. A
criterion that could not be COMPUTED was assigned `passed = None` and was
then filtered out of its own check by that `if` clause; separately, the
criteria that "pass" by counting zero rows (no open envelope trips, no
machine-only resolutions, no ledger row) pass exactly as hard for a run
that never executed as for a clean one. Evaluating a nonexistent `run_id`
therefore printed `VERDICT: PASS - safe to widen`, i.e. "we could not
measure it" read as "it was fine", on the gate that governs whether to
increase throughput against production.

`passed: Optional[bool]` is replaced by `outcome: CriterionOutcome`, which
separates the two distinct states that `None` was conflating:

  - `INSUFFICIENT_DATA` - the criterion IS a gate and its measurement could
    not be taken: no evidence rows to compute a failure rate from
    (criterion 1), no cohort count to compare against (criterion 3), no
    ledger row to read liveness off (criterion 5). Not a pass. Blocks
    widening.
  - `INFORMATIONAL` - the criterion has no threshold BY DESIGN and never
    gates anything: criterion 7 (vote yield, reported only in v1) and
    criterion 6 (the manual crash-drill reminder). Genuinely NOT
    APPLICABLE to the verdict, which is exactly why it must not share a
    value with an un-taken measurement.

`SoakGateResult.verdict` is correspondingly PASS / FAIL / INSUFFICIENT-DATA
rather than a boolean, because "it failed" and "we don't know yet" call for
different operator actions: FAIL has a rollback (`purge_machine_votes
--run-id`), INSUFFICIENT-DATA has an investigation (why did this step
produce no observations?). Both halt the ramp; only one of them has
anything to roll back, and reporting the second as the first sends an
operator to purge votes that were never written. FAIL outranks
INSUFFICIENT-DATA when both are present, so the rollback instruction is
never withheld by a co-occurring measurement gap.

`all_passed` is retained as `verdict is GateVerdict.PASS`, so the single
existing caller (`soak_gate_report`) tightens rather than changes shape.
Nothing else in the tree calls it - in particular there is no warmup-window
caller that evaluates the gate while criteria are legitimately expected to
be un-computed, so making an un-computed criterion block does not turn any
existing in-flight state into a spurious halt (checked 2026-07-29: the only
references to `soak_gate`/`all_passed` outside this module and its tests are
`soak_gate_report.py`, `docs/soak-gate.md`, `docs/MANIFEST.md` and
`docs/features/stage-e-operations.md`, all of which are the human runbook).

Criterion 0 (`run-observed`) exists solely to make the zero-observation case
impossible to pass: if a `run_id` has no `ImageEvidence`, no
`PilotRunLedger` row and no `CardPrintingTag` votes, nothing was soaked, and
the other criteria's individually-honest answers ("zero open trips", "zero
machine-only resolutions") must not be allowed to add up to "safe to
widen". Keeping it as its own criterion leaves criteria 2 and 4 truthful -
zero open trips IS a pass for a run that actually ran - rather than teaching
each of them to second-guess whether the run happened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional

from django.utils import timezone

from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    ImageEvidence,
    PilotRunLedger,
)

# ── Thresholds (issue #155 ratified values) ──────────────────────────────
FETCH_FAILURE_RATE_CEILING = 0.01  # ≤ 1%
COHORT_COUNT_TOLERANCE = 0.05  # ± 5%
LEDGER_HEARTBEAT_MAX_GAP = timedelta(hours=1)

#: `PilotRunLedger.counters` keys that record how many cards a run SET OUT to process, most
#: specific first. Criterion 3 reads its reference cohort from the first one present, which is
#: what lets `soak_gate_report --run-id X` return a real verdict with no other flags.
#:
#: Both entries are the run's own statement of INTENT, recorded independently of the
#: `ImageEvidence` table this criterion counts against them - which is the property that makes
#: the comparison meaningful rather than circular (see `_check_evidence_cohort_count`):
#:
#:   - `cohort_size` - `run_image_evidence_cohort` writes `len(cohort_ids)` at COMPLETION time
#:     (both the real-cohort and the empty-cohort paths).
#:   - `batch_size`  - `stage_e_dispatch` writes `len(batch_ids)` at ledger CREATION time,
#:     alongside `trigger_reason`. Creation-time matters: it is present on a RUNNING row and
#:     survives a crash, so a step that died halfway - the case this criterion most needs to
#:     catch - still has a reference to be measured against. It is also the ONLY intent counter
#:     the streaming Stage E dispatcher records, so without this key criterion 3 would be
#:     unmeasurable-without-a-flag for the very runs the width ramp is made of.
#:
#: DO NOT add achievement counters here (`completed`, `stage_c_completed`, `stage_c_transferred`,
#: ...) or fall back to the ImageEvidence row count. See `_check_evidence_cohort_count`'s
#: docstring: a reference derived from the outcome agrees with the outcome by construction, and
#: turns this criterion back into one that cannot fail.
COHORT_SIZE_COUNTER_KEYS: tuple[str, ...] = ("cohort_size", "batch_size")


def latest_run_id() -> Optional[str]:
    """The most recently STARTED run's id, or None if the ledger is empty.

    Backs `soak_gate_report`'s flag-free default (owner directive 2026-07-29,
    "default the default things, disable them with flags"): the gate's own
    runbook says to run it after a width-ramp step completes, so "the run that
    started most recently" is the run an operator invoking it bare means.

    Ordering is by `started_at` (`auto_now_add`, never null) rather than pk, so
    the answer does not depend on insertion order. The caller is responsible
    for REPORTING which run this picked - a soak gate that silently chooses its
    own subject is a worse failure than one that asks for a flag, and
    `stage_e_dispatch` writes one ledger row PER MICRO-BATCH, so the latest row
    is one batch of a multi-batch step rather than the whole step.
    """
    return PilotRunLedger.objects.order_by("-started_at").values_list("run_id", flat=True).first()


class CriterionOutcome(Enum):
    """
    A single criterion's verdict. See the module docstring for why
    INSUFFICIENT_DATA and INFORMATIONAL are two values and not one `None`.

    Each member's value is the label the report command prints for it, so
    the operator-facing vocabulary is defined here rather than in a
    formatting branch that can drift from the semantics.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    #: gating, but the measurement could not be taken - blocks widening
    INSUFFICIENT_DATA = "INSUFFICIENT-DATA"
    #: no threshold by design - never gates, never blocks
    INFORMATIONAL = "REPORT"


class GateVerdict(Enum):
    """The gate's overall answer. PASS is the ONLY value that permits widening."""

    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT-DATA"


@dataclass(frozen=True)
class CriterionResult:
    """Result of a single soak-gate criterion evaluation."""

    name: str
    outcome: CriterionOutcome
    measured: str  # human-readable measured value
    detail: str  # explanation or diagnostic

    @property
    def is_gating(self) -> bool:
        """Whether this criterion's outcome can affect the overall verdict."""
        return self.outcome is not CriterionOutcome.INFORMATIONAL

    @property
    def passed(self) -> Optional[bool]:
        """
        Tri-state read of `outcome`, kept for readers that only care whether
        this criterion returned a positive/negative verdict at all.

        `None` means "no verdict" and covers BOTH non-verdict outcomes, so it
        must never be used to decide whether widening is safe - that is the
        precise mistake this module's docstring documents. Use `outcome` (or
        `SoakGateResult.verdict`) for anything that gates.
        """
        if self.outcome is CriterionOutcome.PASS:
            return True
        if self.outcome is CriterionOutcome.FAIL:
            return False
        return None


@dataclass
class SoakGateResult:
    """Aggregated result of the soak-gate criteria (criterion 0 plus the seven)."""

    criteria: list[CriterionResult] = field(default_factory=list)

    @property
    def verdict(self) -> GateVerdict:
        """
        PASS only when EVERY gating criterion is PASS. A gate with no criteria
        at all is INSUFFICIENT_DATA, not PASS - `all()` over an empty sequence
        being `True` is half of the original defect and is not reintroduced
        here by omission.

        FAIL outranks INSUFFICIENT_DATA (see the module docstring): both halt,
        but only FAIL carries a rollback, and an operator must not be denied
        that instruction because some other criterion also failed to measure.
        """
        gating = [c for c in self.criteria if c.is_gating]
        if not gating:
            return GateVerdict.INSUFFICIENT_DATA
        if any(c.outcome is CriterionOutcome.FAIL for c in gating):
            return GateVerdict.FAIL
        if any(c.outcome is CriterionOutcome.INSUFFICIENT_DATA for c in gating):
            return GateVerdict.INSUFFICIENT_DATA
        return GateVerdict.PASS

    @property
    def all_passed(self) -> bool:
        """True only on a PASS verdict - INSUFFICIENT-DATA is not a pass."""
        return self.verdict is GateVerdict.PASS


def _check_run_observed(run_id: str) -> CriterionResult:
    """Criterion 0: this run produced observations at all.

    The precondition behind every other criterion. `ImageEvidence`,
    `PilotRunLedger` and `CardPrintingTag` are the three tables a width-ramp
    step writes into under its own `run_id`; a run_id present in none of them
    was never soaked (a typo'd run_id, a step that died before its first
    write, or a gate run against the wrong environment). Every other
    criterion answers honestly for such a run - there genuinely are zero open
    envelope trips and zero machine-only resolutions - and those honest
    answers previously summed to "safe to widen". This criterion is what
    turns that into INSUFFICIENT-DATA.

    Three `.count()`s on indexed `run_id` columns, short-circuited via
    `.exists()` semantics only where the count is not also reported.
    """
    evidence_count = ImageEvidence.objects.filter(run_id=run_id).count()
    ledger_count = PilotRunLedger.objects.filter(run_id=run_id).count()
    vote_count = CardPrintingTag.objects.filter(run_id=run_id).count()
    measured = f"{evidence_count} evidence, {ledger_count} ledger, {vote_count} vote row(s)"

    if evidence_count == 0 and ledger_count == 0 and vote_count == 0:
        return CriterionResult(
            name="run-observed",
            outcome=CriterionOutcome.INSUFFICIENT_DATA,
            measured=measured,
            detail=(
                f"No ImageEvidence, PilotRunLedger or CardPrintingTag rows exist for "
                f"run_id={run_id!r} - this run produced no observations, so the gate has "
                f"nothing to evaluate. This is NOT a pass: check the run_id is correct and "
                f"that the step actually executed against this database."
            ),
        )

    return CriterionResult(
        name="run-observed",
        outcome=CriterionOutcome.PASS,
        measured=measured,
        detail="Run wrote at least one observation row - the remaining criteria are evaluable.",
    )


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
            # INSUFFICIENT_DATA, not INFORMATIONAL: this criterion HAS a threshold and is
            # gating, we simply have nothing to apply it to. A step whose fetches produced no
            # evidence rows at all is the shape a total fetch outage takes, which is the
            # last thing that should read as a 0% failure rate.
            outcome=CriterionOutcome.INSUFFICIENT_DATA,
            measured="0/0",
            detail="No ImageEvidence rows found for this run_id - gate cannot compute fetch-failure rate.",
        )

    failures = evidence_qs.filter(fetch_ok=False).count()
    rate = failures / total

    return CriterionResult(
        name="fetch-failure-rate",
        outcome=CriterionOutcome.PASS if rate <= FETCH_FAILURE_RATE_CEILING else CriterionOutcome.FAIL,
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

    # Genuinely computable for any run_id (a `.count()` always has an answer), so this stays a
    # plain PASS/FAIL. "Zero open trips" for a run that never happened is not this criterion's
    # problem to detect - criterion 0 (`run-observed`) owns that question, which is what keeps
    # this one honest instead of defensive.
    return CriterionResult(
        name="unacknowledged-envelope-trips",
        outcome=CriterionOutcome.PASS if count == 0 else CriterionOutcome.FAIL,
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
    step's eligible cohort count.

    The reference cohort is DERIVED FROM THE RUN'S OWN LEDGER by default;
    `--step-cohort-size` is an OVERRIDE for when the operator knows better, not
    a precondition (owner directive, 2026-07-29: "default the default things,
    disable them with flags" - an instance owner must get a real verdict from
    `soak_gate_report --run-id X` with no other flags). Never hardcoded: every
    reference below is read live off this run's own row.

    WHERE THE REFERENCE MAY COME FROM, AND THE ONE PLACE IT MUST NOT
    ---------------------------------------------------------------
    `COHORT_SIZE_COUNTER_KEYS` are the counters recording what the run SET OUT
    to process. A reference may only ever come from one of those, because this
    criterion's whole content is "did the run's output cover its intent".

    It must NOT be derived from the run's ACHIEVEMENT counters (`completed`,
    `stage_c_completed`, ...) and must NOT be derived from the ImageEvidence
    count itself. Both are the same mistake in different clothing: a reference
    computed from the outcome makes the criterion compare the run against
    itself, so it agrees by construction and can never fail. A step that
    silently processed half its cohort reports half the evidence AND half the
    completions, the two agree perfectly, and the gate certifies it. That is
    precisely the defect class this module's docstring exists to document -
    "count the run's actual observations and call that the cohort" would buy
    flag-free operation by re-introducing an unfailable gate, which is a worse
    trade than the flag it removes.

    If no intent counter is present the criterion is INSUFFICIENT-DATA and the
    detail NAMES `--step-cohort-size`, so a first-time instance maintainer can
    act on the message rather than be handed an uninterpretable verdict.
    """
    evidence_count = ImageEvidence.objects.filter(run_id=run_id).count()
    ledger = PilotRunLedger.objects.filter(run_id=run_id).first()

    # COVERAGE IS NOT DECIDABLE WHILE THE RUN IS STILL GOING, and this check must precede the
    # reference resolution below because it holds no matter where the reference came from.
    # `batch_size` is recorded at ledger CREATION, so a healthy in-flight dispatch has its full
    # intent on record while its evidence rows are still accumulating - comparing the two
    # mid-run reports a shortfall that is simply work not done YET. Left as a FAIL that would
    # be wrong twice over: it accuses a healthy run, and the FAIL verdict's rollback advice
    # would tell an operator to `purge_machine_votes` against a live run. INSUFFICIENT-DATA
    # still halts the ramp (never widen off an in-flight step) while naming the real action.
    # A run stuck RUNNING is not let through by this: criterion 5 fails it once stale.
    if ledger is not None and ledger.status == PilotRunLedger.Status.RUNNING:
        return CriterionResult(
            name="evidence-cohort-count",
            outcome=CriterionOutcome.INSUFFICIENT_DATA,
            measured=f"{evidence_count} evidence rows, run still RUNNING",
            detail=(
                f"Run {run_id!r} has not finished (PilotRunLedger.status=running, "
                f"finished_at unset), so its evidence count is still climbing and cohort "
                f"coverage cannot be judged yet. Not a pass, and nothing to roll back - "
                f"wait for the step to finish, then re-run this gate."
            ),
        )

    if cohort_size is not None and cohort_size > 0:
        reference = cohort_size
        source = "--step-cohort-size override"
    else:
        counters = (ledger.counters if ledger is not None else None) or {}
        for key in COHORT_SIZE_COUNTER_KEYS:
            if isinstance(counters.get(key), (int, float)):
                reference = int(counters[key])
                source = f"PilotRunLedger.counters[{key}]"
                break
        else:
            present = ", ".join(sorted(counters)) if counters else "(none)"
            return CriterionResult(
                name="evidence-cohort-count",
                # INSUFFICIENT_DATA: gating, unmeasurable. Without a reference cohort there is
                # no statement to make about whether the step covered its cohort - and "we
                # don't know the denominator" must not resolve to "the coverage was fine".
                outcome=CriterionOutcome.INSUFFICIENT_DATA,
                measured=f"{evidence_count} evidence rows, cohort size unknown",
                detail=(
                    f"Could not derive this run's intended cohort size: none of "
                    f"{list(COHORT_SIZE_COUNTER_KEYS)} is present in "
                    f"PilotRunLedger.counters for run_id={run_id!r} "
                    f"(keys present: {present}). "
                    f"FIX: re-run with --step-cohort-size <n> to supply it explicitly. "
                    f"The gate deliberately will NOT substitute this run's own evidence or "
                    f"completion counts for the cohort - a reference taken from the outcome "
                    f"agrees with the outcome by construction and could never fail."
                ),
            )

    lower = math.floor(reference * (1 - COHORT_COUNT_TOLERANCE))
    upper = math.ceil(reference * (1 + COHORT_COUNT_TOLERANCE))
    in_range = lower <= evidence_count <= upper

    return CriterionResult(
        name="evidence-cohort-count",
        outcome=CriterionOutcome.PASS if in_range else CriterionOutcome.FAIL,
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
    voted_card_ids = list(CardPrintingTag.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct())

    if not voted_card_ids:
        # A TRUE vacuity, not an unmeasured value, and the distinction is why this stays PASS
        # while criteria 1/3/5's empty cases became INSUFFICIENT-DATA: zero votes cast means
        # zero cards can have been resolved BY those votes. The proposition is decided, not
        # unknown. Whether the run should have cast votes at all is criterion 0's question.
        return CriterionResult(
            name="zero-machine-resolutions",
            outcome=CriterionOutcome.PASS,
            measured="0 voted cards",
            detail="No CardPrintingTag rows found for this run - vacuously passes.",
        )

    violations = _verify_zero_resolutions(voted_card_ids)

    return CriterionResult(
        name="zero-machine-resolutions",
        outcome=CriterionOutcome.PASS if not violations else CriterionOutcome.FAIL,
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
        # WAS `passed=True, "heartbeat trivially OK"` - changed 2026-07-29. There is nothing
        # trivially OK about it: the ledger row IS this criterion's only instrument, so a
        # missing row means liveness was not measured, not that the run was alive. The old
        # reading is what let a run that never started report a healthy heartbeat. Distinct
        # from criterion 0, which fires only when NO table has a row for this run - a run with
        # evidence rows but no ledger row reaches here, and is exactly the stalled/crashed
        # shape a heartbeat check exists to catch.
        return CriterionResult(
            name="ledger-heartbeat",
            outcome=CriterionOutcome.INSUFFICIENT_DATA,
            measured="no ledger row",
            detail=(
                "No PilotRunLedger row found for this run_id - the gate has no activity "
                "timestamps to read, so run liveness could not be measured. Not a pass."
            ),
        )

    if ledger.status != PilotRunLedger.Status.RUNNING:
        return CriterionResult(
            name="ledger-heartbeat",
            outcome=CriterionOutcome.PASS,
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
        outcome=CriterionOutcome.PASS if passed else CriterionOutcome.FAIL,
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
        # INFORMATIONAL, not INSUFFICIENT_DATA: this criterion has no threshold in v1, so it
        # gates nothing whether or not it can be computed. Reporting a missing ledger as an
        # unmet gate here would double-count criterion 5's own INSUFFICIENT-DATA for the same
        # missing row.
        return CriterionResult(
            name="vote-yield",
            outcome=CriterionOutcome.INFORMATIONAL,
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
        outcome=CriterionOutcome.INFORMATIONAL,  # no threshold in v1 - reported, never gating
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
        SoakGateResult with per-criterion outcomes and an overall `verdict`
        (PASS / FAIL / INSUFFICIENT-DATA; `all_passed` is `verdict is PASS`).
        The management command wraps this with CLI output formatting.

    Every criterion is ALWAYS evaluated, including when criterion 0 already
    reports INSUFFICIENT-DATA: the operator gets the full picture of what the
    gate could and could not see, rather than one line that stops the report
    early. The verdict, not the presence of rows, is what halts the ramp.
    """
    result = SoakGateResult()

    # Criterion 0: did this run produce any observations at all? (see module docstring)
    result.criteria.append(_check_run_observed(run_id))

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
                # INFORMATIONAL: the gate deliberately does NOT automate the crash drill, so
                # it has no measurement to be insufficient. The operator records DRILL-PASS
                # out of band; this line only reminds them to.
                outcome=CriterionOutcome.INFORMATIONAL,
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
