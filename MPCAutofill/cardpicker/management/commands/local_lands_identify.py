from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_identify_printing_tags import (
    generate_run_id,
    verify_zero_resolutions,
)
from cardpicker.local_lands_identify import run_lands_identify
from cardpicker.models import PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Part 4 (docs/features/catalog-completion-plan.md): artist-decomposed identification "
        "for names whose candidate count blocks the normal phash engine (basic lands + any "
        "over-cap name). Defaults to dry-run and requires an explicit --write to actually cast "
        "votes (HOLD #B - mirrors Part 3's --write gate convention). --sample-size defaults to "
        "300 per the plan doc's own HOLD #B ask; pass --sample-size 0 for a full-pool run once "
        "the hold clears and a real run is authorized."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write votes. Default is dry-run: compute and count everything "
            "(including real image fetches up to --fetch-budget) without writing any "
            "CardPrintingTag row.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--sample-size",
            type=int,
            default=300,
            help="How many pool cards (deterministic pk order) to actually run the fetch/OCR/"
            "artist/phash pipeline against. 0 means the whole pool. land_pool_size and "
            "per_name_candidate_counts are always computed over the whole pool regardless "
            "(both are free DB-only queries). Default: 300 (HOLD #B's sample size).",
        )
        parser.add_argument(
            "--fetch-budget",
            type=int,
            default=0,
            help="Max real image fetches to spend (shared CDN Worker rate limiter - see "
            "image-cdn/wrangler.toml's IMAGE_FULL_TIER_RATE_LIMITER). Default: 0 (land_pool_"
            "size + per_name_candidate_counts only, zero network cost).",
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
        sample_size = kwargs["sample_size"] or None
        mode = "WRITE" if kwargs["write"] else "DRY RUN"
        print(f"[{mode}] local_lands_identify run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="local_lands_identify",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_lands_identify(
                run_id=run_id,
                dry_run=dry_run,
                sample_size=sample_size,
                fetch_budget=kwargs["fetch_budget"],
            )

            print(
                f"[lands] land_pool_size={result.land_pool_size} sample_size={result.sample_size or 'ALL'} "
                f"sampled={result.sampled} fetch_budget={result.fetch_budget} "
                f"fetch_attempted={result.fetch_attempted}"
            )
            print(
                f"[lands] ocr_resolved={result.ocr_resolved} artist_extracted={result.artist_extracted} "
                f"artist_extraction_failed={result.artist_extraction_failed} "
                f"artist_extraction_rate="
                f"{result.artist_extracted / result.fetch_attempted if result.fetch_attempted else 0:.3f}"
            )
            print(
                f"[lands] singleton_votes({'would_cast' if dry_run else 'written'})={result.singleton_votes} "
                f"tiebreak_votes({'would_cast' if dry_run else 'written'})={result.tiebreak_votes} "
                f"ambiguous_phash={result.ambiguous_phash}"
            )
            print("[lands] per_name_candidate_counts (pre-artist-filter, full pool):")
            for name, count in sorted(result.per_name_candidate_counts.items(), key=lambda kv: -kv[1])[:20]:
                print(f"  {name}: {count}")
            print("[lands] per_name_post_filter_candidate_counts (sampled cards with a successful artist match):")
            for name, counts in sorted(result.per_name_post_filter_candidate_counts.items()):
                print(f"  {name}: {counts}")
            for outcome in result.outcomes:
                print(f"  sample: {outcome}")

            votes_written = result.votes_written
            touched_card_ids = [o.card_id for o in result.outcomes if o.printing_pk is not None or o.ocr_resolved_pk]

            if not dry_run and touched_card_ids:
                violations = verify_zero_resolutions(touched_card_ids)
                if violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(violations)} card(s) resolved to a printing with "
                        f"only machine-sourced votes behind that outcome, which should be "
                        f"structurally impossible per resolve_weighted_consensus's own human-"
                        f"backed gate - STOP and investigate. Affected card pks: "
                        f"{violations[:50]}" + (" (truncated)" if len(violations) > 50 else "")
                    )
                print(f"Gate check passed: 0/{len(touched_card_ids)} touched cards resolved machine-only.")

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = votes_written
            ledger.save(update_fields=["status", "finished_at", "votes_written"])
            print(
                f"[{mode}] done. run_id={run_id} total_votes="
                f"{'written' if not dry_run else 'would_cast'}={votes_written}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
