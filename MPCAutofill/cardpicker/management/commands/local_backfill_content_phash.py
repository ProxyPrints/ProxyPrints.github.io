from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_phash import (
    DEFAULT_BACKFILL_BATCH_SIZE,
    DEFAULT_BACKFILL_WORKERS,
    run_content_phash_backfill,
)


class Command(BaseCommand):
    help = (
        "One-time backfill (see docs/features/printing-tags.md's hash-at-ingest architecture): "
        "computes and persists Card.content_phash for every existing card that doesn't have "
        "one yet. Idempotent and resumable by construction (filters on content_phash__isnull="
        "True, so a plain re-invocation after a kill just picks up where it left off) - no "
        "separate --resume flag needed. Going forward, cardpicker.sources.update_database "
        "hashes newly-created cards automatically; this command is for the existing backlog "
        "and for any card an ingest-time fetch failure left unhashed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Fetch and hash without writing anything to the database.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BACKFILL_BATCH_SIZE,
            help=f"Cards fetched+hashed concurrently, then persisted in one bulk_update. "
            f"Default: {DEFAULT_BACKFILL_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_BACKFILL_WORKERS,
            help=f"Thread pool size for concurrent image fetches within a batch. "
            f"Default: {DEFAULT_BACKFILL_WORKERS}.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only process this many NULL-content_phash cards (for testing/sampling). "
            "Default: no limit, process the entire backlog.",
        )
        parser.add_argument(
            "--nice",
            action="store_true",
            default=True,
            help="Lower this process's CPU scheduling priority (default: on).",
        )
        parser.add_argument("--no-nice", action="store_false", dest="nice")
        parser.add_argument(
            "--skip-checks",
            action="store_true",
            default=False,
            help="Passed through to Django's own --skip-checks (unattended-run convention "
            "matching local_identify_printing_tags).",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]
        workers = kwargs["workers"]
        limit = kwargs["limit"]
        nice = kwargs["nice"]

        mode = "DRY RUN" if dry_run else "WRITE"
        print(
            f"[{mode}] local_backfill_content_phash --batch-size={batch_size} "
            f"--workers={workers} --limit={limit} --nice={nice}"
        )

        result = run_content_phash_backfill(
            dry_run=dry_run,
            batch_size=batch_size,
            workers=workers,
            limit=limit,
            nice=nice,
        )

        print(
            f"Hashed {result.hashed}/{result.total_candidates} "
            f"({result.failed} fetch/hash failure/s - unset, will retry on next invocation)."
        )
        if dry_run:
            print("Dry run - nothing written.")
