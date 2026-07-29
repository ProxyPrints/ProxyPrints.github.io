"""
PR #569's own recorded open item: the collector-line artist recovery only ever reached a card
that Stage C happened to be re-extracting for some other reason, so the ~207k `ImageEvidence` rows
already carrying a blank `artist_ocr_name` (206,719 of 220,669 = 93.7% at last measurement) would
have stayed blank indefinitely.

This command closes that gap WITHOUT re-extracting anything. `collector_line_artist.
recover_artist_from_card_text` reads two STRINGS, and both are already persisted on the row
(`collector_line_raw_text`, `legal_line_raw_text`), so the whole pass is a re-read of stored
evidence - no image fetch, no tesseract call, no network access of any kind. Same posture, and
deliberately the same command shape, as `backfill_modern_artist_names` (issue #368), which does
the identical job for a different stored string.

DRY RUN IS THE DEFAULT, `--write` opts in - the convention every Stage 3+ command in this
directory follows. Every invocation writes a `PilotRunLedger` row (RUNNING at start, COMPLETED or
FAILED at the end, with the pass's counters attached) so "did this ever actually run, and what did
it do?" is answerable from the database rather than from someone's terminal scrollback. That is
not a formality: a calculator that silently never ran went undetected for 13 days this month
precisely because nothing checked the ledger.

See `collector_line_artist.py`'s own BACKFILL LAYER section for the two invariants this must not
break (the `Illus.` anchor's reading is never overwritten; every stored value is a verbatim
`CanonicalArtist.name`, never a fuzzy one) and for how the pass is chunked.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.collector_line_artist import run_collector_line_artist_backfill
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha

COMMAND_NAME = "backfill_collector_line_artist"


class Command(BaseCommand):
    help = (
        "PR #569's open item: re-reads ImageEvidence.collector_line_raw_text + "
        "legal_line_raw_text (both already stored by Stage C - no image fetch, no OCR run here) "
        "through cardpicker.collector_line_artist and fills artist_ocr_name wherever it is "
        "currently blank and exactly ONE canonical artist is compatible with the reading. Never "
        "overwrites a non-blank artist_ocr_name (the Illus. anchor's own reading always wins) and "
        "never stores a fuzzy value. Defaults to dry-run; requires an explicit --write to persist "
        "anything, matching every other Stage 3+ command's own convention."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write ImageEvidence.artist_ocr_name. Default is dry-run: compute and "
            "count everything (including the audit sample) without writing.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Rows per .iterator() read chunk, and per bulk_update write batch. Default: 500.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after considering this many eligible rows. The read-only measurement "
            "handle: --limit N with the default dry-run reports the real yield on a real sample.",
        )
        parser.add_argument(
            "--audit-sample-size",
            type=int,
            default=20,
            help="How many (card_name, candidate, matched_name, ratio) rows to print. Default: 20.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        # Same guard `backfill_modern_artist_names` opens with: a container built from older code
        # than the schema it is pointed at cannot be trusted to know which columns exist, and this
        # command reads three of them.
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        run_id = kwargs["run_id"] or generate_run_id()
        dry_run = not kwargs["write"]
        mode = "WRITE" if kwargs["write"] else "DRY RUN"
        self.stdout.write(f"[{mode}] {COMMAND_NAME} run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command=COMMAND_NAME,
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_collector_line_artist_backfill(
                run_id=run_id,
                dry_run=dry_run,
                chunk_size=kwargs["chunk_size"],
                limit=kwargs["limit"],
                audit_sample_size=kwargs["audit_sample_size"],
            )
        except Exception as exc:
            # Ledger-first on the failure path too (see this module's docstring): a FAILED row
            # carrying the reason is what makes an aborted pass visible later, and losing it to a
            # second exception here would leave a RUNNING row lying about forever.
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.counters = {"failure_reason": f"{type(exc).__name__}: {exc}"}
            ledger.save(update_fields=["status", "finished_at", "counters"])
            raise

        written = result.would_fill if dry_run else result.filled
        self.stdout.write(
            f"[collector-line-artist] considered={result.considered} no_reading={result.no_reading} "
            f"ambiguous={result.ambiguous} {'would_fill' if dry_run else 'filled'}={written}"
        )
        for entry in result.audit:
            self.stdout.write(f"  sample: {entry}")

        ledger.status = PilotRunLedger.Status.COMPLETED
        ledger.finished_at = timezone.now()
        ledger.votes_written = result.filled
        ledger.counters = {
            "considered": result.considered,
            "no_reading": result.no_reading,
            "ambiguous": result.ambiguous,
            "would_fill": result.would_fill,
            "filled": result.filled,
            "limit": kwargs["limit"],
            "chunk_size": kwargs["chunk_size"],
        }
        ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])
        self.stdout.write(f"[{mode}] done. run_id={run_id} {'would_fill' if dry_run else 'filled'}={written}")
