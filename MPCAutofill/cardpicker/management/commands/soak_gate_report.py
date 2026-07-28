"""
Soak-gate report management command: the CLI wrapper around
cardpicker.soak_gate.evaluate_soak_gate.

Given a run_id (and optionally a step cohort size), computes PASS/FAIL
for each owner-ratified per-width-step criterion (issue #155) and
prints one block of per-criterion results. Exit code 0 only if all
gating criteria pass.

This becomes the widen/halt decision artifact: FAIL → halt, no
widening, purge_machine_votes --run-id is the rollback.

Usage:
    python manage.py soak_gate_report --run-id <run_id>
    python manage.py soak_gate_report --run-id <run_id> --step-cohort-size 25000
    python manage.py soak_gate_report --run-id <run_id> --canary-step
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from cardpicker.soak_gate import evaluate_soak_gate


class Command(BaseCommand):
    help = (
        "Machine-only soak gate: evaluates per-width-step criteria (issue #155) "
        "for a given run_id. Prints PASS/FAIL/REPORT for each criterion; exit 0 "
        "only if all gating criteria pass. This is the widen/halt decision artifact."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-id",
            type=str,
            required=True,
            help="The run_id to evaluate (matches ImageEvidence/EnvelopeTrip/" "PilotRunLedger run_id).",
        )
        parser.add_argument(
            "--step-cohort-size",
            type=int,
            default=None,
            help="Explicit cohort count for criterion 3 (evidence count ±5%). "
            "If not provided, computed live from PilotRunLedger.counters.",
        )
        parser.add_argument(
            "--canary-step",
            action="store_true",
            default=False,
            help="Include criterion 6's crash-drill reminder (canary step only).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run_id: str = options["run_id"]
        step_cohort_size: int | None = options["step_cohort_size"]
        canary_step: bool = options["canary_step"]

        result = evaluate_soak_gate(
            run_id,
            step_cohort_size=step_cohort_size,
            canary_step=canary_step,
        )

        # Output block
        self.stdout.write(f"SOAK GATE REPORT — run_id={run_id}")
        self.stdout.write("=" * 60)

        for criterion in result.criteria:
            if criterion.passed is True:
                status = "PASS"
            elif criterion.passed is False:
                status = "FAIL"
            else:
                status = "REPORT"

            self.stdout.write(f"[{status}] {criterion.name}")
            self.stdout.write(f"  measured: {criterion.measured}")
            self.stdout.write(f"  {criterion.detail}")

        self.stdout.write("=" * 60)

        if result.all_passed:
            self.stdout.write("VERDICT: PASS — safe to widen to the next step.")
        else:
            self.stdout.write("VERDICT: FAIL — halt, no widening.")
            self.stdout.write(f"  Rollback: purge_machine_votes --run-id {run_id}")
            self.stdout.write("  Fix the failed criterion(s), then re-run this gate.")

        # Exit code: 0 only if all gating criteria pass
        if not result.all_passed:
            self.stderr.write("soak gate: FAIL — exit 1")
            raise SystemExit(1)
