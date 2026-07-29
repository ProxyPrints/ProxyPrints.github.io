"""
Soak-gate report management command: the CLI wrapper around
cardpicker.soak_gate.evaluate_soak_gate.

Computes an outcome for each owner-ratified per-width-step criterion
(issue #155) and prints one block of per-criterion results.

This is the widen/halt decision artifact. THREE verdicts, three exit
codes (2026-07-29 - see `cardpicker.soak_gate`'s module docstring for
why "we could not measure it" is no longer allowed to print as "safe to
widen"):

    0  PASS              - widen to the next step.
    1  FAIL              - halt. A criterion was measured and was bad.
                           Rollback: purge_machine_votes --run-id <run_id>.
    2  INSUFFICIENT-DATA - halt. A gating criterion could NOT be measured
                           (in the limit: the run produced no observations
                           at all). There is nothing to roll back - find
                           out why the step produced no data, then re-run.

Anything non-zero halts the ramp, so an existing caller that only tests
`if $? -ne 0` keeps working unchanged; the split exists so the operator
is sent to the right action rather than told to purge votes that were
never written.

FLAGS ARE ALL OPTIONAL (owner directive 2026-07-29: "default the default
things, disable them with flags"). A bare `soak_gate_report` evaluates the
most recently started ledger run, deriving the criterion-3 cohort from that
run's own counters, and says in its output which run it picked. Every flag
NARROWS or OVERRIDES that default; none is a precondition for a verdict.

Usage:
    python manage.py soak_gate_report
    python manage.py soak_gate_report --run-id <run_id>
    python manage.py soak_gate_report --run-id <run_id> --step-cohort-size 25000
    python manage.py soak_gate_report --run-id <run_id> --canary-step
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cardpicker.models import PilotRunLedger
from cardpicker.soak_gate import (
    CriterionOutcome,
    GateVerdict,
    evaluate_soak_gate,
    latest_run_id,
)

#: Exit code for the "a gating criterion could not be measured" verdict. Distinct from FAIL's
#: 1 because the operator action differs (investigate vs. roll back), and emphatically
#: distinct from 0 because it is not a pass.
EXIT_INSUFFICIENT_DATA = 2


class Command(BaseCommand):
    help = (
        "Machine-only soak gate: evaluates per-width-step criteria (issue #155) "
        "for a given run_id. Prints PASS/FAIL/INSUFFICIENT-DATA/REPORT for each "
        "criterion; exits 0 only when every gating criterion PASSES (1 on FAIL, "
        "2 when a gating criterion could not be measured). This is the widen/halt "
        "decision artifact."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="The run_id to evaluate (matches ImageEvidence/EnvelopeTrip/PilotRunLedger "
            "run_id). OPTIONAL: defaults to the most recently started PilotRunLedger run, "
            "which is reported in the output. Pass it to pin a specific run - note "
            "stage_e_dispatch writes one ledger row PER MICRO-BATCH, so the default is one "
            "batch of a multi-batch step.",
        )
        parser.add_argument(
            "--step-cohort-size",
            type=int,
            default=None,
            help="OVERRIDE the cohort count for criterion 3 (evidence count ±5%%). Not "
            "required: the cohort is derived from this run's own ledger counters "
            "(cohort_size/batch_size) by default. Pass it when you know better, or when the "
            "gate reports it could not derive one.",
        )
        parser.add_argument(
            "--canary-step",
            action="store_true",
            default=False,
            help="Include criterion 6's crash-drill reminder (canary step only). Purely "
            "informational - it never affects the verdict.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        step_cohort_size: int | None = options["step_cohort_size"]
        canary_step: bool = options["canary_step"]

        # `--run-id` is optional so a fresh instance owner gets a real verdict from a bare
        # `soak_gate_report` (owner directive 2026-07-29: "default the default things, disable
        # them with flags"). The resolution is announced below rather than applied silently -
        # a safety gate that picks its own subject without saying so trades one failure mode
        # for a worse one.
        run_id: str | None = options["run_id"]
        run_id_source = "--run-id"
        if run_id is None:
            run_id = latest_run_id()
            run_id_source = "auto-selected (most recently started ledger run)"
            if run_id is None:
                raise CommandError(
                    "No --run-id given and PilotRunLedger is empty, so there is no run to "
                    "evaluate and none to default to. Pass --run-id <run_id> explicitly."
                )

        result = evaluate_soak_gate(
            run_id,
            step_cohort_size=step_cohort_size,
            canary_step=canary_step,
        )

        # Output block
        self.stdout.write(f"SOAK GATE REPORT — run_id={run_id}")
        self.stdout.write(f"  run_id source: {run_id_source}")
        if run_id_source != "--run-id":
            ledger = PilotRunLedger.objects.filter(run_id=run_id).first()
            if ledger is not None:
                self.stdout.write(
                    f"  ledger: command={ledger.command} status={ledger.status} "
                    f"started_at={ledger.started_at.isoformat()}"
                )
            self.stdout.write("  Pass --run-id to pin a different run.")
        self.stdout.write("=" * 60)

        for criterion in result.criteria:
            # The label IS the outcome's own value (see CriterionOutcome), not a re-derivation
            # from a tri-state boolean - the formatting cannot drift from the semantics.
            self.stdout.write(f"[{criterion.outcome.value}] {criterion.name}")
            self.stdout.write(f"  measured: {criterion.measured}")
            self.stdout.write(f"  {criterion.detail}")

        self.stdout.write("=" * 60)

        verdict = result.verdict

        if verdict is GateVerdict.PASS:
            self.stdout.write("VERDICT: PASS — safe to widen to the next step.")
            return

        if verdict is GateVerdict.FAIL:
            failed = [c.name for c in result.criteria if c.passed is False]
            self.stdout.write("VERDICT: FAIL — halt, no widening.")
            self.stdout.write(f"  Failed criteria: {', '.join(failed)}")
            self.stdout.write(f"  Rollback: purge_machine_votes --run-id {run_id}")
            self.stdout.write("  Fix the failed criterion(s), then re-run this gate.")
            self.stderr.write("soak gate: FAIL — exit 1")
            raise SystemExit(1)

        unmeasured = [c.name for c in result.criteria if c.outcome is CriterionOutcome.INSUFFICIENT_DATA]
        self.stdout.write("VERDICT: INSUFFICIENT-DATA — halt, no widening.")
        self.stdout.write(f"  Unmeasurable gating criteria: {', '.join(unmeasured) or '(none evaluated)'}")
        self.stdout.write(
            "  This is NOT a pass: the gate could not observe this run, so it cannot "
            "certify it. Nothing to roll back — establish why the step produced no "
            "data (wrong run_id? step never executed? wrong database?), then re-run."
        )
        self.stderr.write(f"soak gate: INSUFFICIENT-DATA — exit {EXIT_INSUFFICIENT_DATA}")
        raise SystemExit(EXIT_INSUFFICIENT_DATA)
