from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    run_join_key_calculator,
)
from cardpicker.local_identify_printing_tags import (
    generate_run_id,
    verify_zero_resolutions,
)
from cardpicker.models import CardPrintingTag, PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Stage D (docs/features/catalog-completion-plan.md, public issue #152): the join-key "
        "calculator - the fast-path deduction step over Stage C's ImageEvidence rows (collector-"
        "line OCR + set-symbol phash tie-break) plus the on-disk Scryfall bulk data. Casts "
        "CardPrintingTag votes via the existing, unmodified vote-consensus machinery; never "
        "resolves a card by itself. Defaults to dry-run and requires an explicit --write to "
        "actually cast votes, matching local_residual_classify's own convention."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write CardPrintingTag/CardScanLog rows. Default is dry-run: compute "
            "and count everything without writing.",
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
        print(f"[{mode}] local_calculate_verdicts run_id={run_id} git_sha={get_baked_git_sha()}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="local_calculate_verdicts",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_join_key_calculator(run_id=run_id, dry_run=dry_run, chunk_size=kwargs["chunk_size"])
            votes_written = result.votes_written + result.no_match_votes_written
            would_cast = result.votes_would_cast + result.no_match_votes_would_cast
            print(
                f"[join-key] considered={result.cards_considered} "
                f"votes={'written=' + str(result.votes_written) if not dry_run else 'would_cast=' + str(result.votes_would_cast)} "
                f"no_match_votes={'written=' + str(result.no_match_votes_written) if not dry_run else 'would_cast=' + str(result.no_match_votes_would_cast)} "
                f"skip_counts={dict(result.skip_counts)}"
            )
            for entry in result.audit[:10]:
                print(f"  sample: {entry}")

            if not dry_run:
                # result.audit is capped (audit_sample_size) - the gate check needs the FULL
                # touched set, so it's re-derived from this run's own freshly-written votes
                # (scoped by run_id + anonymous_id, both exact-match) rather than the sample.
                touched_card_ids = list(
                    CardPrintingTag.objects.filter(run_id=run_id, anonymous_id=JOIN_KEY_ANONYMOUS_ID).values_list(
                        "card_id", flat=True
                    )
                )
                violations = verify_zero_resolutions(touched_card_ids)
                if violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(violations)} card(s) resolved to a printing from "
                        f"this single-anonymous_id machine pass alone, which should be "
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
                f"[{mode}] done. run_id={run_id} "
                f"total_votes={'written' if not dry_run else 'would_cast'}={votes_written if not dry_run else would_cast}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
