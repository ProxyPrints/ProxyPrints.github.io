from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.artbox_exemplar_backfill import (
    DEFAULT_BACKFILL_BATCH_SIZE,
    dry_run_candidate_exemplar_hashes,
    measure_unresolved_coverage,
    run_artbox_exemplar_backfill,
)
from cardpicker.models import ArtboxPhashExemplar


class Command(BaseCommand):
    help = (
        "Issue #508 phase 1: seeds ArtboxPhashExemplar from our own DB - every current-evidence "
        "card with a human-backed printing resolution, plus every card carrying a join-key "
        "machine vote at or above the confidence floor (see artbox_exemplar_backfill.py's own "
        "JOIN_KEY_SEED_CONFIDENCE_FLOOR comment). Never fetches Scryfall images. Idempotent and "
        "resumable by construction (filters out cards that already have an exemplar row, so a "
        "plain re-invocation after a kill just picks up where it left off) - no separate "
        "--resume flag needed. Also reports the phase-2 coverage estimate: of every currently-"
        "UNRESOLVED card carrying a current artbox_phash, how many would match the exemplar "
        "index at d=0 and at d<=2 - computed read-only, every invocation, dry-run or not."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Compute and report every counter, including the coverage estimate, without "
            "writing any ArtboxPhashExemplar row.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BACKFILL_BATCH_SIZE,
            help=f"Rows persisted per bulk_create flush, and rows per join-key evidence-lookup "
            f"chunk. Default: {DEFAULT_BACKFILL_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only create this many exemplar rows total, across both seed passes combined "
            "(for testing/sampling). Default: no limit, process the entire backlog.",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Stamped onto every row this invocation creates, for later retraction via "
            "retract_artbox_phash_exemplars --run-id. Default: none stamped.",
        )
        parser.add_argument(
            "--skip-coverage",
            action="store_true",
            default=False,
            help="Skip the phase-2 coverage measurement pass (unresolved-card matching) - "
            "useful for a fast seeding-only run; the coverage pass is a full scan of every "
            "UNRESOLVED card's current artbox_phash and is the more expensive half of this "
            "command.",
        )
        # --skip-checks is deliberately NOT defined here - Django's BaseCommand already adds it
        # natively (see local_backfill_canonical_hash.py's own matching comment).

    def handle(self, *args: Any, **kwargs: Any) -> None:
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]
        limit = kwargs["limit"]
        run_id = kwargs["run_id"]
        skip_coverage = kwargs["skip_coverage"]

        mode = "DRY RUN" if dry_run else "WRITE"
        self.stdout.write(
            f"[{mode}] backfill_artbox_phash_exemplars --batch-size={batch_size} " f"--limit={limit} --run-id={run_id}"
        )

        result = run_artbox_exemplar_backfill(dry_run=dry_run, batch_size=batch_size, limit=limit, run_id=run_id)

        self.stdout.write(
            f"Seeded human_backed={result.human_backed_seeded} machine={result.machine_seeded} "
            f"(machine_skipped_stale_or_missing_evidence="
            f"{result.machine_skipped_stale_or_missing_evidence}), "
            f"distinct_illustration_ids={result.distinct_illustration_ids}."
        )
        self.stdout.write(f"Elapsed {result.elapsed_seconds:.1f}s.")
        if dry_run:
            self.stdout.write("Dry run - nothing written.")

        if skip_coverage:
            self.stdout.write("Coverage measurement skipped (--skip-coverage).")
            return

        if dry_run:
            exemplar_hashes = dry_run_candidate_exemplar_hashes(batch_size)
        else:
            exemplar_hashes = list(ArtboxPhashExemplar.objects.values_list("artbox_phash", flat=True))

        coverage = measure_unresolved_coverage(exemplar_hashes)
        self.stdout.write(
            f"COVERAGE (phase-2 estimate): unresolved_candidates_considered="
            f"{coverage.unresolved_candidates_considered} matches_at_d0={coverage.matches_at_d0} "
            f"matches_at_d_le_2={coverage.matches_at_d_le_2}."
        )
