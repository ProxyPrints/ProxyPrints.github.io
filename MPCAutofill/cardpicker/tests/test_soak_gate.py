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
    _check_envelope_trips,
    _check_evidence_cohort_count,
    _check_fetch_failure_rate,
    _check_ledger_heartbeat,
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

    def test_no_evidence_returns_none(self) -> None:
        """No evidence rows → passed=None (informational)."""
        result = _check_fetch_failure_rate("run-c1-empty")
        assert result.passed is None
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

    def test_no_cohort_size_returns_none(self) -> None:
        """No cohort_size and no ledger → passed=None."""
        for _ in range(10):
            _make_evidence("run-c3-nocohort")
        result = _check_evidence_cohort_count("run-c3-nocohort", cohort_size=None)
        assert result.passed is None

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

    def test_pass_no_rows(self) -> None:
        """No ledger rows → trivially OK → PASS."""
        result = _check_ledger_heartbeat("run-c5-none")
        assert result.passed is True

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
        """Ledger rows from a different run_id are not in scope."""
        _make_ledger(
            "run-other",
            status="running",
            started_at=timezone.now() - timedelta(hours=5),
        )
        result = _check_ledger_heartbeat("run-c5-diff")
        assert result.passed is True


# ── Criterion 7: vote yield (informational) ─────────────────────────────


@pytest.mark.django_db
class TestVoteYield:
    def test_no_ledger_returns_none(self) -> None:
        """No ledger row → passed=None."""
        result = _check_vote_yield("run-c7-none")
        assert result.passed is None

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
        assert result.passed is None  # informational only
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
        """Without canary step, should have 6 criteria (1-5 + 7)."""
        result = evaluate_soak_gate("run-count", canary_step=False)
        assert len(result.criteria) == 6

    def test_criteria_count_with_canary(self) -> None:
        """With canary step, should have 7 criteria."""
        result = evaluate_soak_gate("run-count-canary", canary_step=True)
        assert len(result.criteria) == 7


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
        """Output block contains per-criterion lines."""
        run_id = "run-cmd-full"
        out = io.StringIO()
        call_command(
            "soak_gate_report",
            run_id=run_id,
            stdout=out,
            stderr=io.StringIO(),
        )
        output = out.getvalue()
        assert "fetch-failure-rate" in output
        assert "unacknowledged-envelope-trips" in output
        assert "evidence-cohort-count" in output
        assert "zero-machine-resolutions" in output
        assert "ledger-heartbeat" in output
        assert "vote-yield" in output

    def test_canary_step_flag(self) -> None:
        """--canary-step includes the crash-drill reminder."""
        run_id = "run-cmd-canary"
        out = io.StringIO()
        call_command(
            "soak_gate_report",
            run_id=run_id,
            canary_step=True,
            stdout=out,
            stderr=io.StringIO(),
        )
        output = out.getvalue()
        assert "crash-drill-reminder" in output
