from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_detect_ai_art import AI_ART_ANONYMOUS_ID, run_ai_art_detector
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.management.commands.purge_machine_votes import (
    verify_no_machine_only_resolutions,
)
from cardpicker.models import CardTagVote, PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Public issue #261: scans Stage C's already-persisted ImageEvidence OCR fields "
        "(artist_ocr_name, legal_line_raw_text, collector_line_raw_text) for known AI-image-"
        "generator marker strings (see cardpicker.local_detect_ai_art.AI_GENERATOR_MARKERS) and "
        "casts CardTagVote votes for the pre-existing 'AI-Generated' tag via the existing, "
        "unmodified vote-consensus machinery. Positive-detection only - never casts a negative "
        "vote. Never resolves a tag by itself: a single VoteSource.OCR vote can never clear the "
        "human-backed gate alone (vote_consensus.resolve_weighted_consensus), and 'AI-Generated' "
        "is additionally a SENSITIVE tag requiring a privileged moderator co-sign on top of that. "
        "Defaults to dry-run and requires an explicit --write to actually write, matching every "
        "other Stage 3+ command's own convention."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write CardTagVote/CardScanLog rows. Default is dry-run: compute and "
            "count everything without writing.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--chunk-size", type=int, default=500, help="Queryset .iterator() chunk size. Default: 500."
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
        print(f"[{mode}] local_detect_ai_art run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="local_detect_ai_art",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_ai_art_detector(run_id=run_id, dry_run=dry_run, chunk_size=kwargs["chunk_size"])
            print(
                f"[ai-art] considered={result.cards_considered} "
                f"votes={'written=' + str(result.votes_written) if not dry_run else 'would_cast=' + str(result.votes_would_cast)} "
                f"skip_counts={dict(result.skip_counts)}"
            )
            for entry in result.audit[:10]:
                print(f"  sample: {entry}")

            if not dry_run:
                touched_card_ids = list(
                    CardTagVote.objects.filter(run_id=run_id, anonymous_id=AI_ART_ANONYMOUS_ID).values_list(
                        "card_id", flat=True
                    )
                )
                violations = verify_no_machine_only_resolutions(touched_card_ids)
                if violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(violations)} card(s) are RESOLVED with only "
                        f"machine-sourced surviving votes behind that outcome, which should be "
                        f"structurally impossible per resolve_weighted_consensus's own human-"
                        f"backed gate - STOP and investigate before continuing. Affected card "
                        f"pks: {violations[:50]}" + (" (truncated)" if len(violations) > 50 else "")
                    )
                print(f"Gate check passed: 0/{len(touched_card_ids)} touched cards resolved machine-only.")

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = result.votes_written
            ledger.save(update_fields=["status", "finished_at", "votes_written"])
            print(
                f"[{mode}] done. run_id={run_id} "
                f"total_votes={'written' if not dry_run else 'would_cast'}="
                f"{result.votes_written if not dry_run else result.votes_would_cast}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
