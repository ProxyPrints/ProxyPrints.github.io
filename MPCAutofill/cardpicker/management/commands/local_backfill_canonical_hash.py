from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_phash import (
    DEFAULT_CANONICAL_HASH_BACKFILL_BATCH_SIZE,
    DEFAULT_CANONICAL_HASH_BACKFILL_WORKERS,
    DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES,
    run_canonical_hash_backfill,
)


class Command(BaseCommand):
    help = (
        "Completes the local phash reference corpus (docs/features/catalog-completion-plan.md): "
        "computes and persists CanonicalCard.image_hash for every printing still at the unset "
        "sentinel (0). Local-only by default - CanonicalPrintingMetadata.art_crop_url covers "
        "113,224/113,224 printings (issue #339), so this needs zero calls to Scryfall's REST "
        "API, only its image CDN for the hash fetch itself. A printing with no local art-crop "
        "URL is reported and skipped, not silently routed to a live REST call - see "
        "--allow-remote. Idempotent and resumable by construction (filters on image_hash=0, so "
        "a plain re-invocation after a kill just picks up where it left off) - no separate "
        "--resume flag needed, same discipline as local_backfill_content_phash."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Fetch and hash without writing anything to the database. Reports how many "
            "printings would be hashed, how many would be skipped for a missing local URL, and "
            "an estimated wall-clock for the full backlog.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_CANONICAL_HASH_BACKFILL_BATCH_SIZE,
            help=f"Printings persisted per checkpoint-flush bulk_update. "
            f"Default: {DEFAULT_CANONICAL_HASH_BACKFILL_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_CANONICAL_HASH_BACKFILL_WORKERS,
            help="Fetch thread pool size, long-lived for the whole run - sized to "
            "SCRYFALL_CDN's own max_concurrency (harvest_fetch_limiter.py), not for raw "
            f"parallelism; a wider pool just queues behind that destination's semaphore. "
            f"Default: {DEFAULT_CANONICAL_HASH_BACKFILL_WORKERS}.",
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
            help="Only process this many candidates still at image_hash=0 (for testing/"
            "sampling). Default: no limit, process the entire backlog.",
        )
        parser.add_argument(
            "--allow-remote",
            action="store_true",
            default=False,
            help="For a printing with no local art_crop_url, fall back to a live Scryfall REST "
            "call (the pre-Stage-B behaviour) instead of skipping it. Default: off - this "
            "backfill is local-only by design; use this only to deliberately close a residual "
            "gap, not as a routine flag.",
        )
        parser.add_argument(
            "--nice",
            action="store_true",
            default=True,
            help="Lower this process's CPU scheduling priority (default: on).",
        )
        parser.add_argument("--no-nice", action="store_false", dest="nice")
        # --skip-checks is deliberately NOT defined here - see local_backfill_content_phash.py's
        # matching comment; Django's BaseCommand already adds it natively.

    def handle(self, *args: Any, **kwargs: Any) -> None:
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]
        workers = kwargs["workers"]
        queue_depth_batches = kwargs["queue_depth_batches"]
        limit = kwargs["limit"]
        allow_remote = kwargs["allow_remote"]
        nice = kwargs["nice"]

        mode = "DRY RUN" if dry_run else "WRITE"
        self.stdout.write(
            f"[{mode}] local_backfill_canonical_hash --batch-size={batch_size} "
            f"--workers={workers} --queue-depth-batches={queue_depth_batches} "
            f"--limit={limit} --allow-remote={allow_remote} --nice={nice}"
        )

        result = run_canonical_hash_backfill(
            dry_run=dry_run,
            batch_size=batch_size,
            workers=workers,
            queue_depth_batches=queue_depth_batches,
            limit=limit,
            allow_remote=allow_remote,
            nice=nice,
        )

        self.stdout.write(
            f"Selected {result.total_candidates}/{result.total_backlog} candidate/s still at " f"image_hash=0."
        )
        self.stdout.write(
            f"Hashed {result.hashed}, skipped_no_local_url={result.skipped_no_local_url}, "
            f"failed={result.failed} (failed stays at the sentinel - will retry on next "
            f"invocation)."
        )
        if result.total_candidates > 0:
            rate = result.total_candidates / result.elapsed_seconds if result.elapsed_seconds > 0 else 0.0
            self.stdout.write(f"Elapsed {result.elapsed_seconds:.1f}s ({rate:.2f} printing/s).")
            if rate > 0:
                estimated_seconds = result.total_backlog / rate
                self.stdout.write(
                    f"Estimated wall-clock for the full backlog ({result.total_backlog}): "
                    f"{estimated_seconds:.1f}s (~{estimated_seconds / 60:.1f} min)."
                )
        if dry_run:
            self.stdout.write("Dry run - nothing written.")
