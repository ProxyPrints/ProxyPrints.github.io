from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import PilotRunLedger
from cardpicker.modern_artist_credit import run_modern_artist_credit_backfill
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Issue #368: re-parses ImageEvidence.artist_ocr_raw_text (already stored by Stage C's "
        "OCR-group extractor - no image fetch, no OCR run here) with the new modern-bare-name "
        "artist-credit recognizer (cardpicker.modern_artist_credit) and fills artist_ocr_name "
        "wherever it is currently blank and a confident lexicon match exists. Never overwrites a "
        "non-blank artist_ocr_name. Defaults to dry-run; requires an explicit --write to persist "
        "anything, matching every other Stage 3+ command's own convention."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write ImageEvidence.artist_ocr_name. Default is dry-run: compute and "
            "count everything (including the audit sample) without writing.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--chunk-size", type=int, default=500, help="Queryset .iterator() chunk size. Default: 500."
        )
        parser.add_argument(
            "--audit-sample-size",
            type=int,
            default=20,
            help="How many (candidate, matched_name, ratio, margin) rows to print. Default: 20.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
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
        self.stdout.write(f"[{mode}] backfill_modern_artist_names run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="backfill_modern_artist_names",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_modern_artist_credit_backfill(
                run_id=run_id,
                dry_run=dry_run,
                chunk_size=kwargs["chunk_size"],
                audit_sample_size=kwargs["audit_sample_size"],
            )
            self.stdout.write(
                f"[modern-artist-credit] considered={result.considered} no_match={result.no_match} "
                f"{'would_fill' if dry_run else 'filled'}="
                f"{result.would_fill if dry_run else result.filled}"
            )
            for entry in result.audit:
                self.stdout.write(f"  sample: {entry}")

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = result.filled
            ledger.counters = {
                "considered": result.considered,
                "would_fill": result.would_fill,
                "filled": result.filled,
                "no_match": result.no_match,
            }
            ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])
            self.stdout.write(
                f"[{mode}] done. run_id={run_id} "
                f"{'would_fill' if dry_run else 'filled'}="
                f"{result.would_fill if dry_run else result.filled}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
