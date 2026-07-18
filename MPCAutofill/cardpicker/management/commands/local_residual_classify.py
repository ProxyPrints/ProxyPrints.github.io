from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.local_residual_classify import (
    run_d0_sibling_artist_propagation,
    run_frame_mismatch_recovery,
    verify_no_single_machine_vote_resolutions,
)
from cardpicker.models import PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Part 3 (docs/features/catalog-completion-plan.md): the shared evidence-recovery "
        "module's dual-yield frame-mismatch recovery (CardArtistVote + altered-frame "
        "CardTagVote) plus d=0 sibling artist propagation (CardArtistVote). Defaults to "
        "dry-run and requires an explicit --write to actually cast votes (HOLD #P3 - a "
        "deliberate deviation from purge_machine_votes' opt-out convention)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write votes. Default is dry-run: compute and count everything "
            "(including real OCR-refetch network calls up to --ocr-refetch-budget) without "
            "writing any CardArtistVote/CardTagVote row.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--skip-frame-mismatch", action="store_true", default=False, help="Skip the frame-mismatch dual-yield pass."
        )
        parser.add_argument(
            "--skip-d0-sibling", action="store_true", default=False, help="Skip the d=0 sibling propagation pass."
        )
        parser.add_argument(
            "--ocr-refetch-budget",
            type=int,
            default=0,
            help="Max real CDN fetches to spend recovering OCR-flagged frame-mismatch rows "
            "(phash-flagged rows are always free and unbounded). Default: 0 (phash-only).",
        )
        parser.add_argument(
            "--fallback-refetch-budget",
            type=int,
            default=0,
            help="Max real CDN fetches to spend recovering fallback-flagged frame-mismatch rows. " "Default: 0.",
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
        print(f"[{mode}] local_residual_classify run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="local_residual_classify",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            votes_written = 0
            touched_card_ids: set[int] = set()

            if not kwargs["skip_frame_mismatch"]:
                frame_result = run_frame_mismatch_recovery(
                    run_id=run_id,
                    dry_run=dry_run,
                    ocr_refetch_budget=kwargs["ocr_refetch_budget"],
                    fallback_refetch_budget=kwargs["fallback_refetch_budget"],
                )
                recovered_total = (
                    frame_result.phash_recovered
                    + frame_result.ocr_refetch_recovered
                    + frame_result.fallback_refetch_recovered
                )
                print(
                    f"[frame-mismatch] considered={frame_result.cards_considered} "
                    f"phash_recovered={frame_result.phash_recovered} "
                    f"ocr_refetch_attempted={frame_result.ocr_refetch_attempted} "
                    f"ocr_refetch_recovered={frame_result.ocr_refetch_recovered} "
                    f"fallback_refetch_attempted={frame_result.fallback_refetch_attempted} "
                    f"fallback_refetch_recovered={frame_result.fallback_refetch_recovered} "
                    f"unrecovered={frame_result.unrecovered} "
                    f"artist_votes={'written=' + str(frame_result.artist_votes_written) if not dry_run else 'would_cast=' + str(recovered_total)} "
                    f"tag_votes={'written=' + str(frame_result.tag_votes_written) if not dry_run else 'would_cast=' + str(recovered_total)}"
                )
                for outcome in frame_result.outcomes[:10]:
                    print(f"  sample: {outcome}")
                votes_written += frame_result.artist_votes_written + frame_result.tag_votes_written
                if not dry_run:
                    touched_card_ids.update(o.card_id for o in frame_result.outcomes if o.artist_vote_would_cast)

            if not kwargs["skip_d0_sibling"]:
                d0_result = run_d0_sibling_artist_propagation(run_id=run_id, dry_run=dry_run)
                print(
                    f"[d0-sibling] considered={d0_result.cards_considered} "
                    f"votes_would_cast={d0_result.votes_would_cast} votes_written={d0_result.votes_written}"
                )
                votes_written += d0_result.votes_written

            if not dry_run and touched_card_ids:
                violations = verify_no_single_machine_vote_resolutions(sorted(touched_card_ids))
                if violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(violations)} card(s) resolved to RESOLVED artist "
                        f"status with only machine-sourced votes behind that outcome, which "
                        f"should be structurally impossible per resolve_weighted_consensus's own "
                        f"human-backed gate - STOP and investigate. Affected card pks: "
                        f"{violations[:50]}" + (" (truncated)" if len(violations) > 50 else "")
                    )
                print(f"Gate check passed: 0/{len(touched_card_ids)} touched cards resolved machine-only.")

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = votes_written
            ledger.save(update_fields=["status", "finished_at", "votes_written"])
            print(
                f"[{mode}] done. run_id={run_id} total_votes={'written' if not dry_run else 'would_cast'}={votes_written}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
