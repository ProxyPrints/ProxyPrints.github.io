"""
Per-channel run report: what did every channel in this pipeline produce?

The command form of
`docs/reports/2026-07-29-pipeline-coverage-composition-audit.md`'s
per-channel table. See `cardpicker.channel_report` for the outcome model
and `cardpicker.channel_roster` for how the roster is derived from code
rather than typed out.

FLAGS ARE ALL OPTIONAL (owner directive: "default the default things,
disable them with flags"). A bare `channel_report` derives the roster,
picks the most recently started ledger run, reports every channel, and
gates. Every flag NARROWS or reformats that; none is a precondition.

THREE VERDICTS, THREE EXIT CODES - the same split
`soak_gate_report` adopted, and for the same reason ("we could not measure
it" is not allowed to print as "safe"):

    0  PASS              - every channel produced something, or is
                           explicitly declared silent with a reason.
    1  FAIL              - at least one channel produced NOTHING and is not
                           declared, or a declared-silent channel started
                           producing. The findings list says which and why.
    2  INSUFFICIENT-DATA - the ROSTER ITSELF could not be derived. Nothing
                           was measured, so nothing can be reported as
                           healthy. An instrument that measures nothing must
                           never print "all clear".

Usage:
    python manage.py channel_report
    python manage.py channel_report --run-id <run_id>
    python manage.py channel_report --family vote
    python manage.py channel_report --json
    python manage.py channel_report --no-gate
"""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from cardpicker.channel_report import DidState, build_channel_report

EXIT_FAIL = 1
EXIT_INSUFFICIENT_DATA = 2

FAMILY_TITLES = {
    "vote": "VOTE CHANNELS (positive / negative, by identity and TAG)",
    "extractor": "STAGE C EXTRACTOR CHANNELS (values written, not manifest keys)",
    "abstention": "ABSTENTION CHANNELS (CardScanLog writers)",
}


class Command(BaseCommand):
    help = (
        "Per-channel post-run report: for one run_id, what every vote channel, Stage C "
        "extractor and abstention channel actually produced. Roster derived from code. "
        "Gates on channels that produced nothing at all."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-id",
            dest="run_id",
            default=None,
            help="Run to scope run-column counts to. Defaults to the most recently started ledger run.",
        )
        parser.add_argument(
            "--family",
            dest="family",
            default=None,
            choices=sorted(FAMILY_TITLES),
            help="Report only one channel family. Default: all of them.",
        )
        parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON.")
        parser.add_argument(
            "--no-gate",
            dest="gate",
            action="store_false",
            help="Report without failing the exit code. The gate is ON by default.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = build_channel_report(run_id=options["run_id"])

        if not report.measurable:
            # The loudest case in the whole command. A derivation that comes
            # back empty means the roster compared nothing to nothing; printing
            # a clean table here is the exact defect this repo has been
            # removing, so it is a distinct, non-zero, non-FAIL verdict.
            self.stderr.write(self.style.ERROR("INSUFFICIENT-DATA - the channel roster could not be derived."))
            for finding in report.derivation_findings:
                self.stderr.write(self.style.ERROR(f"  * {finding}"))
            self.stderr.write(
                self.style.ERROR(
                    "NOTHING WAS MEASURED. This is not a pass. Fix the derivation in "
                    "cardpicker/channel_roster.py before trusting any channel reading."
                )
            )
            raise SystemExit(EXIT_INSUFFICIENT_DATA)

        outcomes = [o for o in report.outcomes if options["family"] in (None, o.channel.family)]

        if options["as_json"]:
            self.stdout.write(json.dumps(_as_json(report, outcomes), indent=2, sort_keys=True))
        else:
            self._write_text(report, outcomes)

        if options["gate"] and report.findings:
            raise SystemExit(EXIT_FAIL)

    def _write_text(self, report: Any, outcomes: list[Any]) -> None:
        write = self.stdout.write
        write("=" * 100)
        write("PER-CHANNEL RUN REPORT")
        write(f"run_id: {report.run_id or '(none - no ledger rows exist)'}")
        if report.ledger is not None:
            write(f"command: {report.ledger.command}   status: {report.ledger.status}")
            write(f"votes_written (self-reported by the run): {report.ledger.votes_written}")
            # The run's OWN counters, printed beside the row counts this report
            # derived independently. They are a self-report and are shown for
            # comparison only - where the two disagree, the row counts are the
            # fact and the counters are the claim.
            for key, value in sorted((report.ledger.counters or {}).items()):
                write(f"  counter {key}: {value}")
        roster = report.roster
        write(
            f"roster derived from code: {len(roster.vote)} vote / {len(roster.extractor)} extractor / "
            f"{len(roster.abstention)} abstention channels, {len(roster.skip_reason)} declared skip reasons"
        )
        write("=" * 100)

        for family in sorted(FAMILY_TITLES):
            rows = [o for o in outcomes if o.channel.family == family]
            if not rows:
                continue
            write("")
            write(FAMILY_TITLES[family])
            write("-" * 100)
            for outcome in sorted(rows, key=lambda o: o.channel.key):
                self._write_row(outcome)

        write("")
        write("=" * 100)
        if report.findings:
            write(self.style.ERROR(f"FAIL - {len(report.findings)} finding(s):"))
            for finding in report.findings:
                write(self.style.ERROR(f"  * {finding}"))
        else:
            write(self.style.SUCCESS("PASS - every channel in the derived roster produced something, "))
            write(self.style.SUCCESS("       or is explicitly declared silent with a written reason."))
        write("=" * 100)

    def _write_row(self, outcome: Any) -> None:
        channel = outcome.channel
        marker = {
            DidState.PRODUCED: "  ok  ",
            DidState.SILENT: " FAIL ",
            DidState.DECLARED_SILENT: " decl ",
            DidState.DECLARED_SILENT_NOW_PRODUCING: " CHNG ",
        }[outcome.did]
        headline = f"[{marker}] {channel.key}"
        if outcome.did in (DidState.SILENT, DidState.DECLARED_SILENT_NOW_PRODUCING):
            headline = self.style.ERROR(headline)
        self.stdout.write(headline)

        parts = []
        if channel.family == "vote":
            parts.append(f"positive={outcome.positive}")
            parts.append(f"negative={outcome.negative}")
        if channel.family == "extractor":
            parts.append(f"values_written={outcome.values_written}")
            if outcome.reconciliation is not None:
                rec = outcome.reconciliation
                parts.append(f"attempted={rec.attempted}")
                parts.append(f"ran={rec.voted}")
                parts.append(f"dropped={rec.dropped}")
                if not rec.is_consistent():
                    parts.append("RECONCILIATION-INCONSISTENT")
        parts.append(f"abstentions={outcome.abstentions}")
        parts.append(f"why={outcome.why}")
        if outcome.commands:
            parts.append(f"commands={','.join(outcome.commands)}")
        self.stdout.write("           " + "  ".join(parts))

        if outcome.abstained_by_reason:
            by_reason = ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(outcome.abstained_by_reason.items(), key=lambda kv: -kv[1])
            )
            self.stdout.write(f"           abstained by reason: {by_reason}")
        if outcome.values_by_field:
            by_field = ", ".join(f"{name}={count}" for name, count in sorted(outcome.values_by_field.items()))
            self.stdout.write(f"           values by field: {by_field}")
        for note in outcome.notes:
            self.stdout.write(f"           note: {note}")
        if outcome.declaration is not None:
            self.stdout.write(
                f"           declared silent by {outcome.declaration.ratified_by}: {outcome.declaration.reason}"
            )


def _as_json(report: Any, outcomes: list[Any]) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "measurable": report.measurable,
        "ledger": (
            {
                "command": report.ledger.command,
                "status": report.ledger.status,
                "votes_written": report.ledger.votes_written,
                "counters": report.ledger.counters,
            }
            if report.ledger is not None
            else None
        ),
        "findings": report.findings,
        "roster_sizes": {
            "vote": len(report.roster.vote),
            "extractor": len(report.roster.extractor),
            "abstention": len(report.roster.abstention),
            "skip_reason": len(report.roster.skip_reason),
        },
        "channels": [
            {
                "key": o.channel.key,
                "family": o.channel.family,
                "identity": o.channel.identity,
                "model": o.channel.model,
                "tag": o.channel.tag,
                "positive": o.positive,
                "negative": o.negative,
                "abstained_by_reason": o.abstained_by_reason,
                "values_by_field": o.values_by_field,
                "evidence": o.evidence(),
                "why": o.why,
                "did": o.did,
                "commands": list(o.commands),
                "notes": list(o.notes),
                "sites": list(o.channel.sites),
            }
            for o in sorted(outcomes, key=lambda o: o.channel.key)
        ],
    }
