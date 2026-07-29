"""
Tests for cardpicker.soak_gate and the soak_gate_report management command.

Covers all seven criteria with synthetic rows via the existing test
factories. Each criterion's PASS and FAIL paths are tested, plus the
±5% boundary for criterion 3 and the exit-code behaviour of the
management command.

Uses testcontainers (WORKS on this box; recipe: cd MPCAutofill && pytest .).
"""

import io
import math
from datetime import timedelta
from typing import Any

import pytest

from django.core.management import call_command
from django.utils import timezone

from cardpicker.models import EnvelopeTrip, ImageEvidence, PilotRunLedger
from cardpicker.soak_gate import (
    COHORT_COUNT_TOLERANCE,
    CriterionOutcome,
    CriterionResult,
    GateVerdict,
    SoakGateResult,
    _check_envelope_trips,
    _check_evidence_cohort_count,
    _check_fetch_failure_rate,
    _check_ledger_heartbeat,
    _check_run_observed,
    _check_vote_yield,
    _check_zero_machine_resolutions,
    evaluate_soak_gate,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    ImageEvidenceFactory,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_evidence(run_id: str, fetch_ok: bool = True, **kwargs: Any) -> ImageEvidence:
    """Create an ImageEvidence row with a fresh card per row."""
    card = CardFactory()
    return ImageEvidenceFactory(card=card, run_id=run_id, fetch_ok=fetch_ok, **kwargs)


def _make_ledger(
    run_id: str,
    *,
    status: str = "completed",
    started_at: timezone.datetime | None = None,
    finished_at: timezone.datetime | None = None,
    counters: dict | None = None,
    votes_written: int | None = None,
) -> PilotRunLedger:
    """Create a PilotRunLedger row."""
    ledger = PilotRunLedger.objects.create(
        run_id=run_id,
        command="run_image_evidence_cohort",
        status=status,
        started_at=started_at or timezone.now(),
        finished_at=finished_at,
        counters=counters,
        votes_written=votes_written,
    )
    # Override started_at if explicitly provided (auto_now_add prevents direct set)
    if started_at is not None:
        PilotRunLedger.objects.filter(pk=ledger.pk).update(started_at=started_at)
        ledger.refresh_from_db()
    if finished_at is not None:
        PilotRunLedger.objects.filter(pk=ledger.pk).update(finished_at=finished_at)
        ledger.refresh_from_db()
    return ledger


def _make_envelope_trip(
    run_id: str,
    *,
    acknowledged: bool = False,
    bar: str = "host_load",
) -> EnvelopeTrip:
    """Create an EnvelopeTrip row."""
    trip = EnvelopeTrip.objects.create(
        bar=bar,
        run_id=run_id,
        acknowledged_at=timezone.now() if acknowledged else None,
    )
    return trip


# ── Criterion 1: fetch-failure rate ──────────────────────────────────────


@pytest.mark.django_db
class TestFetchFailureRate:
    def test_pass_all_ok(self) -> None:
        """All evidence rows have fetch_ok=True → rate 0% → PASS."""
        for _ in range(10):
            _make_evidence("run-c1-ok", fetch_ok=True)
        result = _check_fetch_failure_rate("run-c1-ok")
        assert result.passed is True
        assert "0/10" in result.measured

    def test_pass_boundary(self) -> None:
        """1 failure in 100 rows → 1% → PASS (≤ 1%)."""
        for _ in range(99):
            _make_evidence("run-c1-bound", fetch_ok=True)
        _make_evidence("run-c1-bound", fetch_ok=False)
        result = _check_fetch_failure_rate("run-c1-bound")
        assert result.passed is True
        assert "1/100" in result.measured

    def test_fail_above_threshold(self) -> None:
        """2 failures in 100 rows → 2% → FAIL."""
        for _ in range(98):
            _make_evidence("run-c1-fail", fetch_ok=True)
        _make_evidence("run-c1-fail", fetch_ok=False)
        _make_evidence("run-c1-fail", fetch_ok=False)
        result = _check_fetch_failure_rate("run-c1-fail")
        assert result.passed is False

    def test_no_evidence_is_insufficient_data_not_a_pass(self) -> None:
        """No evidence rows → INSUFFICIENT-DATA, and it GATES.

        Regression for the gate-semantics defect: an un-taken measurement used
        to be `passed=None`, which `all_passed` filtered out of its own check.
        A step whose fetches produced no evidence rows at all is what a total
        fetch outage looks like - it must never read as a 0% failure rate.
        """
        result = _check_fetch_failure_rate("run-c1-empty")
        assert result.outcome is CriterionOutcome.INSUFFICIENT_DATA
        assert result.passed is not True
        assert result.is_gating is True
        assert "No ImageEvidence" in result.detail

    def test_single_ok_row(self) -> None:
        """Single evidence row, fetch_ok=True → 0% → PASS."""
        _make_evidence("run-c1-one", fetch_ok=True)
        result = _check_fetch_failure_rate("run-c1-one")
        assert result.passed is True


# ── Criterion 2: unacknowledged EnvelopeTrip rows ───────────────────────


@pytest.mark.django_db
class TestEnvelopeTrips:
    def test_pass_no_trips(self) -> None:
        """No trips for this run → PASS."""
        result = _check_envelope_trips("run-c2-none")
        assert result.passed is True
        assert "0 open trip" in result.measured

    def test_pass_all_acknowledged(self) -> None:
        """Trips exist but all acknowledged → PASS."""
        _make_envelope_trip("run-c2-ack", acknowledged=True)
        _make_envelope_trip("run-c2-ack", acknowledged=True, bar="rss")
        result = _check_envelope_trips("run-c2-ack")
        assert result.passed is True

    def test_fail_one_unacknowledged(self) -> None:
        """One unacknowledged trip → FAIL."""
        _make_envelope_trip("run-c2-fail", acknowledged=False)
        result = _check_envelope_trips("run-c2-fail")
        assert result.passed is False
        assert "1 open trip" in result.measured

    def test_fail_mixed(self) -> None:
        """One acknowledged + one unacknowledged → FAIL."""
        _make_envelope_trip("run-c2-mix", acknowledged=True)
        _make_envelope_trip("run-c2-mix", acknowledged=False, bar="rss")
        result = _check_envelope_trips("run-c2-mix")
        assert result.passed is False

    def test_different_run_not_counted(self) -> None:
        """Trip for a different run_id → not counted → PASS."""
        _make_envelope_trip("run-other", acknowledged=False)
        result = _check_envelope_trips("run-c2-diff")
        assert result.passed is True


# ── Criterion 3: evidence cohort count ±5% ───────────────────────────────


@pytest.mark.django_db
class TestEvidenceCohortCount:
    def test_pass_exact_match(self) -> None:
        """Evidence count exactly equals cohort_size → PASS."""
        for _ in range(100):
            _make_evidence("run-c3-exact")
        result = _check_evidence_cohort_count("run-c3-exact", cohort_size=100)
        assert result.passed is True

    def test_pass_within_lower_bound(self) -> None:
        """Evidence count at lower bound (cohort * 0.95) → PASS."""
        cohort = 100
        lower = math.floor(cohort * (1 - COHORT_COUNT_TOLERANCE))
        for _ in range(lower):
            _make_evidence("run-c3-lower")
        result = _check_evidence_cohort_count("run-c3-lower", cohort_size=cohort)
        assert result.passed is True

    def test_pass_within_upper_bound(self) -> None:
        """Evidence count at upper bound (cohort * 1.05) → PASS."""
        cohort = 100
        upper = math.ceil(cohort * (1 + COHORT_COUNT_TOLERANCE))
        for _ in range(upper):
            _make_evidence("run-c3-upper")
        result = _check_evidence_cohort_count("run-c3-upper", cohort_size=cohort)
        assert result.passed is True

    def test_fail_below_lower_bound(self) -> None:
        """Evidence count below lower bound → FAIL."""
        cohort = 100
        lower = math.floor(cohort * (1 - COHORT_COUNT_TOLERANCE))
        for _ in range(lower - 1):
            _make_evidence("run-c3-below")
        result = _check_evidence_cohort_count("run-c3-below", cohort_size=cohort)
        assert result.passed is False

    def test_fail_above_upper_bound(self) -> None:
        """Evidence count above upper bound → FAIL."""
        cohort = 100
        upper = math.ceil(cohort * (1 + COHORT_COUNT_TOLERANCE))
        for _ in range(upper + 1):
            _make_evidence("run-c3-above")
        result = _check_evidence_cohort_count("run-c3-above", cohort_size=cohort)
        assert result.passed is False

    def test_no_cohort_size_is_insufficient_data_not_a_pass(self) -> None:
        """No cohort_size and no ledger → INSUFFICIENT-DATA, and it GATES.

        "We don't know the denominator" must not resolve to "coverage was fine".
        """
        for _ in range(10):
            _make_evidence("run-c3-nocohort")
        result = _check_evidence_cohort_count("run-c3-nocohort", cohort_size=None)
        assert result.outcome is CriterionOutcome.INSUFFICIENT_DATA
        assert result.passed is not True
        assert result.is_gating is True

    def test_uses_ledger_counters_fallback(self) -> None:
        """Without --step-cohort-size, falls back to PilotRunLedger.counters."""
        for _ in range(100):
            _make_evidence("run-c3-ledger")
        _make_ledger(
            "run-c3-ledger",
            counters={"cohort_size": 100, "completed": 100},
        )
        result = _check_evidence_cohort_count("run-c3-ledger", cohort_size=None)
        assert result.passed is True


# ── Criterion 4: zero machine resolutions ────────────────────────────────


@pytest.mark.django_db
class TestZeroMachineResolutions:
    def test_pass_no_votes(self) -> None:
        """No CardPrintingTag rows for this run → vacuously PASS."""
        result = _check_zero_machine_resolutions("run-c4-novotes")
        assert result.passed is True

    def test_pass_no_resolved_cards(self) -> None:
        """Votes exist but no card resolves → PASS."""
        from cardpicker.models import CardPrintingTag, VoteSource

        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="test-anon",
            run_id="run-c4-unresolved",
            source=VoteSource.USER,
        )
        result = _check_zero_machine_resolutions("run-c4-unresolved")
        assert result.passed is True

    def test_different_run_not_counted(self) -> None:
        """Votes from a different run_id are not in scope → PASS."""
        from cardpicker.models import CardPrintingTag, VoteSource

        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="test-anon",
            run_id="run-other",
            source=VoteSource.USER,
        )
        result = _check_zero_machine_resolutions("run-c4-diff")
        assert result.passed is True


# ── Criterion 5: ledger heartbeat ────────────────────────────────────────


@pytest.mark.django_db
class TestLedgerHeartbeat:
    def test_pass_single_row_completed(self) -> None:
        """COMPLETED ledger row → trivially OK → PASS."""
        _make_ledger("run-c5-one")
        result = _check_ledger_heartbeat("run-c5-one")
        assert result.passed is True

    def test_no_ledger_row_is_insufficient_data_not_a_pass(self) -> None:
        """No ledger rows → INSUFFICIENT-DATA (was: "trivially OK → PASS").

        The ledger row is this criterion's only instrument. A missing row means
        liveness was NOT measured, not that the run was alive - the old reading
        let a run that never started report a healthy heartbeat.
        """
        result = _check_ledger_heartbeat("run-c5-none")
        assert result.outcome is CriterionOutcome.INSUFFICIENT_DATA
        assert result.passed is not True
        assert result.is_gating is True

    def test_pass_running_recently(self) -> None:
        """RUNNING ledger with started_at 30min ago → PASS."""
        _make_ledger(
            "run-c5-recent",
            status="running",
            started_at=timezone.now() - timedelta(minutes=30),
        )
        result = _check_ledger_heartbeat("run-c5-recent")
        assert result.passed is True

    def test_fail_running_stale(self) -> None:
        """RUNNING ledger with started_at 2h ago → FAIL (stalled)."""
        _make_ledger(
            "run-c5-stale",
            status="running",
            started_at=timezone.now() - timedelta(hours=2),
        )
        result = _check_ledger_heartbeat("run-c5-stale")
        assert result.passed is False

    def test_pass_running_exact_1h(self) -> None:
        """RUNNING ledger with started_at just under 1h ago → PASS."""
        _make_ledger(
            "run-c5-exact",
            status="running",
            started_at=timezone.now() - timedelta(minutes=59),
        )
        result = _check_ledger_heartbeat("run-c5-exact")
        assert result.passed is True

    def test_pass_failed_status(self) -> None:
        """FAILED ledger row → trivially OK → PASS."""
        _make_ledger(
            "run-c5-failed",
            status="failed",
            started_at=timezone.now() - timedelta(hours=5),
            finished_at=timezone.now() - timedelta(hours=4),
        )
        result = _check_ledger_heartbeat("run-c5-failed")
        assert result.passed is True

    def test_different_run_not_counted(self) -> None:
        """A stalled ledger for ANOTHER run_id does not fail this run.

        The target run gets its own healthy (COMPLETED) ledger row, so a PASS
        here proves scoping - rather than accidentally passing because no row
        was found at all, which is now INSUFFICIENT-DATA.
        """
        _make_ledger(
            "run-other",
            status="running",
            started_at=timezone.now() - timedelta(hours=5),
        )
        _make_ledger("run-c5-diff")
        result = _check_ledger_heartbeat("run-c5-diff")
        assert result.outcome is CriterionOutcome.PASS


# ── Criterion 7: vote yield (informational) ─────────────────────────────


@pytest.mark.django_db
class TestVoteYield:
    def test_no_ledger_is_informational_and_never_gates(self) -> None:
        """No ledger row → INFORMATIONAL (no threshold in v1), never gating.

        The other half of the vocabulary split: this criterion is genuinely NOT
        APPLICABLE to the verdict, as distinct from criteria 1/3/5's un-taken
        measurements, so it must not block a widen.
        """
        result = _check_vote_yield("run-c7-none")
        assert result.outcome is CriterionOutcome.INFORMATIONAL
        assert result.is_gating is False

    def test_reports_counters(self) -> None:
        """Ledger row with counters → reports them."""
        _make_ledger(
            "run-c7-counters",
            counters={
                "cohort_size": 1000,
                "completed": 990,
                "fetch_failures": 10,
                "short_circuited": 5,
                "transferred": 3,
            },
            votes_written=980,
        )
        result = _check_vote_yield("run-c7-counters")
        assert result.outcome is CriterionOutcome.INFORMATIONAL  # reported, never gating
        assert result.is_gating is False
        assert "votes_written=980" in result.measured
        assert "completed=990/1000" in result.measured


# ── Overall evaluation ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestEvaluateSoakGate:
    def test_all_pass(self) -> None:
        """All criteria pass → all_passed=True."""
        run_id = "run-all-pass"
        for _ in range(100):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={"cohort_size": 100})
        result = evaluate_soak_gate(run_id, step_cohort_size=100)
        assert result.all_passed is True

    def test_one_fail_breaks_all(self) -> None:
        """One failing criterion → all_passed=False."""
        run_id = "run-one-fail"
        for _ in range(100):
            _make_evidence(run_id, fetch_ok=True)
        # Add an unacknowledged trip → criterion 2 fails
        _make_envelope_trip(run_id, acknowledged=False)
        _make_ledger(run_id, counters={"cohort_size": 100})
        result = evaluate_soak_gate(run_id, step_cohort_size=100)
        assert result.all_passed is False
        failed_names = [c.name for c in result.criteria if c.passed is False]
        assert "unacknowledged-envelope-trips" in failed_names

    def test_canary_step_includes_reminder(self) -> None:
        """canary_step=True adds criterion 6."""
        run_id = "run-canary"
        result = evaluate_soak_gate(run_id, canary_step=True)
        names = [c.name for c in result.criteria]
        assert "crash-drill-reminder" in names

    def test_no_canary_step_excludes_reminder(self) -> None:
        """canary_step=False omits criterion 6."""
        run_id = "run-nocanary"
        result = evaluate_soak_gate(run_id, canary_step=False)
        names = [c.name for c in result.criteria]
        assert "crash-drill-reminder" not in names

    def test_criteria_count_without_canary(self) -> None:
        """Without canary step: criterion 0 plus criteria 1-5 and 7 = 7 rows."""
        result = evaluate_soak_gate("run-count", canary_step=False)
        assert len(result.criteria) == 7

    def test_criteria_count_with_canary(self) -> None:
        """With canary step, criterion 6 is added = 8 rows."""
        result = evaluate_soak_gate("run-count-canary", canary_step=True)
        assert len(result.criteria) == 8


# ── Management command ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestSoakGateReportCommand:
    def test_exit_code_0_on_pass(self) -> None:
        """Exit code 0 when all criteria pass."""
        run_id = "run-cmd-pass"
        for _ in range(10):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={"cohort_size": 10})
        out = io.StringIO()
        call_command(
            "soak_gate_report",
            run_id=run_id,
            step_cohort_size=10,
            stdout=out,
            stderr=io.StringIO(),
        )
        output = out.getvalue()
        assert "PASS" in output
        assert "VERDICT: PASS" in output

    def test_exit_code_1_on_fail(self) -> None:
        """Exit code 1 when any criterion fails."""
        run_id = "run-cmd-fail"
        # Add unacknowledged trip → criterion 2 fails
        _make_envelope_trip(run_id, acknowledged=False)
        stderr = io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            call_command(
                "soak_gate_report",
                run_id=run_id,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        assert exc_info.value.code == 1

    def test_output_contains_all_criteria(self) -> None:
        """Output block contains per-criterion lines.

        The run is fully populated: an empty run now exits 2 before a caller
        could read the block, so a bare `call_command` here would be asserting
        on output the command never got to print.
        """
        run_id = "run-cmd-full"
        for _ in range(10):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={"cohort_size": 10})
        out = io.StringIO()
        call_command(
            "soak_gate_report",
            run_id=run_id,
            step_cohort_size=10,
            stdout=out,
            stderr=io.StringIO(),
        )
        output = out.getvalue()
        assert "run-observed" in output
        assert "fetch-failure-rate" in output
        assert "unacknowledged-envelope-trips" in output
        assert "evidence-cohort-count" in output
        assert "zero-machine-resolutions" in output
        assert "ledger-heartbeat" in output
        assert "vote-yield" in output

    def test_canary_step_flag(self) -> None:
        """--canary-step includes the crash-drill reminder, and it does not gate."""
        run_id = "run-cmd-canary"
        for _ in range(10):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={"cohort_size": 10})
        out = io.StringIO()
        call_command(
            "soak_gate_report",
            run_id=run_id,
            step_cohort_size=10,
            canary_step=True,
            stdout=out,
            stderr=io.StringIO(),
        )
        output = out.getvalue()
        assert "crash-drill-reminder" in output
        # INFORMATIONAL prints as REPORT and must not stop the widen
        assert "[REPORT] crash-drill-reminder" in output
        assert "VERDICT: PASS" in output


# ── Criterion 0 + verdict vocabulary (2026-07-29 gate-semantics fix) ─────
#
# These are the regression tests for the defect the rest of this file could not
# have caught: the gate's aggregate could not return a negative answer for a run
# that was never observed. `all_passed` was
#
#     all(c.passed is True for c in self.criteria if c.passed is not None)
#
# which drops every un-computable criterion from its own check and then, on the
# remaining zero-row "passes", reports PASS over what is effectively an empty
# sequence. Each test below fails against that implementation.


@pytest.mark.django_db
class TestRunObserved:
    def test_unobserved_run_is_insufficient_data(self) -> None:
        """A run_id with no evidence, no ledger and no votes → INSUFFICIENT-DATA."""
        result = _check_run_observed("run-c0-never-happened")
        assert result.outcome is CriterionOutcome.INSUFFICIENT_DATA
        assert result.is_gating is True

    def test_evidence_alone_is_an_observation(self) -> None:
        _make_evidence("run-c0-evidence")
        assert _check_run_observed("run-c0-evidence").outcome is CriterionOutcome.PASS

    def test_ledger_alone_is_an_observation(self) -> None:
        _make_ledger("run-c0-ledger")
        assert _check_run_observed("run-c0-ledger").outcome is CriterionOutcome.PASS

    def test_votes_alone_are_an_observation(self) -> None:
        from cardpicker.models import CardPrintingTag, VoteSource

        CardPrintingTag.objects.create(
            card=CardFactory(),
            printing=CanonicalCardFactory(),
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            run_id="run-c0-votes",
            source=VoteSource.OCR,
        )
        assert _check_run_observed("run-c0-votes").outcome is CriterionOutcome.PASS

    def test_other_runs_observations_do_not_count(self) -> None:
        """Another run's rows must not make THIS run look observed."""
        _make_evidence("run-c0-other")
        _make_ledger("run-c0-other-ledger")
        assert _check_run_observed("run-c0-mine").outcome is CriterionOutcome.INSUFFICIENT_DATA


@pytest.mark.django_db
class TestSoakWithNoObservationsIsNotSafeToWiden:
    """THE regression test the brief requires: a soak with zero observations."""

    def test_nonexistent_run_does_not_pass(self) -> None:
        result = evaluate_soak_gate("run-that-never-happened")
        assert result.verdict is GateVerdict.INSUFFICIENT_DATA
        assert result.all_passed is False

    def test_nonexistent_run_with_canary_step_does_not_pass(self) -> None:
        """The manual crash-drill reminder must not dilute an unobserved run."""
        result = evaluate_soak_gate("run-that-never-happened-canary", canary_step=True)
        assert result.verdict is GateVerdict.INSUFFICIENT_DATA
        assert result.all_passed is False

    def test_command_exits_2_and_says_not_a_pass(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            call_command("soak_gate_report", run_id="run-cmd-unobserved", stdout=out, stderr=err)
        assert exc_info.value.code == 2
        output = out.getvalue()
        assert "VERDICT: INSUFFICIENT-DATA" in output
        assert "VERDICT: PASS" not in output
        assert "safe to widen" not in output
        assert "run-observed" in output
        # No rollback advice: there are no votes from this run to purge.
        assert "purge_machine_votes" not in output

    def test_empty_criteria_list_is_not_a_pass(self) -> None:
        """`all()` over an empty sequence is True - that must not leak back in."""
        assert SoakGateResult().verdict is GateVerdict.INSUFFICIENT_DATA
        assert SoakGateResult().all_passed is False


@pytest.mark.django_db
class TestVerdictVocabulary:
    """PASS / FAIL / INSUFFICIENT-DATA are three distinct operator actions."""

    def _observed_run(self, run_id: str, *, rows: int = 10) -> None:
        for _ in range(rows):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={"cohort_size": rows})

    def test_healthy_run_still_passes(self) -> None:
        """The positive case: the fix must not make a good soak unwidenable."""
        self._observed_run("run-v-pass")
        result = evaluate_soak_gate("run-v-pass", step_cohort_size=10)
        assert result.verdict is GateVerdict.PASS
        assert result.all_passed is True
        assert all(c.outcome is not CriterionOutcome.INSUFFICIENT_DATA for c in result.criteria)

    def test_measured_bad_run_fails(self) -> None:
        self._observed_run("run-v-fail")
        _make_envelope_trip("run-v-fail", acknowledged=False)
        result = evaluate_soak_gate("run-v-fail", step_cohort_size=10)
        assert result.verdict is GateVerdict.FAIL
        assert result.all_passed is False

    def test_unmeasurable_criterion_blocks_an_otherwise_clean_run(self) -> None:
        """Observed run, clean criteria, but cohort size unknowable → not a PASS.

        This is the narrow case the old aggregate silently widened on: every
        criterion it could compute was fine, and the one it could not was
        dropped from the check.
        """
        run_id = "run-v-unmeasurable"
        for _ in range(10):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={})  # ledger exists, but carries no cohort_size
        result = evaluate_soak_gate(run_id, step_cohort_size=None)
        assert result.verdict is GateVerdict.INSUFFICIENT_DATA
        assert result.all_passed is False
        unmeasured = [c.name for c in result.criteria if c.outcome is CriterionOutcome.INSUFFICIENT_DATA]
        assert unmeasured == ["evidence-cohort-count"]

    def test_fail_outranks_insufficient_data(self) -> None:
        """Both halt, but only FAIL carries the rollback instruction."""
        run_id = "run-v-both"
        for _ in range(10):
            _make_evidence(run_id, fetch_ok=True)
        _make_ledger(run_id, counters={})  # → criterion 3 INSUFFICIENT-DATA
        _make_envelope_trip(run_id, acknowledged=False)  # → criterion 2 FAIL
        result = evaluate_soak_gate(run_id, step_cohort_size=None)
        assert result.verdict is GateVerdict.FAIL

        out = io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            call_command("soak_gate_report", run_id=run_id, stdout=out, stderr=io.StringIO())
        assert exc_info.value.code == 1
        assert "purge_machine_votes" in out.getvalue()

    def test_informational_criteria_never_gate(self) -> None:
        """A run whose only non-PASS rows are INFORMATIONAL still passes."""
        self._observed_run("run-v-info")
        result = evaluate_soak_gate("run-v-info", step_cohort_size=10, canary_step=True)
        informational = [c.name for c in result.criteria if not c.is_gating]
        assert set(informational) == {"crash-drill-reminder", "vote-yield"}
        assert result.verdict is GateVerdict.PASS

    def test_passed_property_never_reports_true_for_a_non_verdict(self) -> None:
        """The compat shim must not resurrect the defect through the back door."""
        for outcome in CriterionOutcome:
            result = CriterionResult(name="x", outcome=outcome, measured="", detail="")
            assert (result.passed is True) == (outcome is CriterionOutcome.PASS)
            assert (result.passed is False) == (outcome is CriterionOutcome.FAIL)
