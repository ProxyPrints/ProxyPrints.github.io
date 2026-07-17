from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_phash import (
    DEFAULT_BACKFILL_BATCH_SIZE,
    DEFAULT_BACKFILL_WORKERS,
    DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES,
    run_content_phash_backfill,
)


class Command(BaseCommand):
    help = (
        "One-time backfill (see docs/features/catalog-completion-plan.md's Part 2): computes "
        "and persists Card.content_phash for every existing card that doesn't have one yet. "
        "Idempotent and resumable by construction (filters on content_phash__isnull=True, so a "
        "plain re-invocation after a kill just picks up where it left off) - no separate "
        "--resume flag needed. Pipelined: one long-lived thread pool for the whole run, a "
        "sliding fetch window bounded by --batch-size * --queue-depth-batches, checkpoint-flush "
        "per batch as fetches complete (not per-batch pool spinup). Going forward, "
        "cardpicker.sources.update_database hashes newly-created cards automatically; this "
        "command is for the existing backlog and for any card an ingest-time fetch failure left "
        "unhashed. Sequencing recommendation (shared CDN rate limiter, see the plan doc): run "
        "this after the live full-catalog pilot completes, not concurrently with it - both are "
        "bottlenecked by the same ~3 req/sec limit, so running alongside buys no real extra "
        "throughput while risking contention with live user-facing traffic."
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
            help=f"Cards persisted per checkpoint-flush bulk_update. Default: {DEFAULT_BACKFILL_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_BACKFILL_WORKERS,
            help=f"Fetch thread pool size, long-lived for the whole run - size to the shared CDN "
            f"rate limiter (~3-5), not for raw parallelism. Default: {DEFAULT_BACKFILL_WORKERS}.",
        )
        parser.add_argument(
            "--queue-depth-batches",
            type=int,
            default=DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES,
            help=f"How many batches' worth of fetches can be in flight (fetched-but-not-yet-"
            f"persisted) at once - bounds memory, decoupled from --workers. "
            f"Default: {DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES}.",
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
        # --skip-checks is deliberately NOT defined here - Django's BaseCommand already adds it
        # natively (every management command gets it for free, same as local_identify_printing_
        # tags relies on without redefining it). Redefining it here collided with Django's own
        # option of the same name (argparse.ArgumentError: conflicting option string), a bug that
        # shipped silently because every test exercising this command called
        # run_content_phash_backfill() directly as a function, never through the real CLI parser
        # (call_command()/the actual `manage.py` entrypoint) - see TestBackfillCommandCLI below,
        # added specifically to close that gap.

    def handle(self, *args: Any, **kwargs: Any) -> None:
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]
        workers = kwargs["workers"]
        queue_depth_batches = kwargs["queue_depth_batches"]
        limit = kwargs["limit"]
        nice = kwargs["nice"]

        mode = "DRY RUN" if dry_run else "WRITE"
        print(
            f"[{mode}] local_backfill_content_phash --batch-size={batch_size} "
            f"--workers={workers} --queue-depth-batches={queue_depth_batches} "
            f"--limit={limit} --nice={nice}"
        )

        result = run_content_phash_backfill(
            dry_run=dry_run,
            batch_size=batch_size,
            workers=workers,
            queue_depth_batches=queue_depth_batches,
            limit=limit,
            nice=nice,
        )

        print(
            f"Hashed {result.hashed}/{result.total_candidates} "
            f"({result.failed} fetch/hash failure/s - unset, will retry on next invocation)."
        )
        if dry_run:
            print("Dry run - nothing written.")
