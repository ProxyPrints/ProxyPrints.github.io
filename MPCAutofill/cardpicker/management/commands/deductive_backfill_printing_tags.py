from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.deductive_backfill import run_backfill


class Command(BaseCommand):
    help = (
        "Casts AI-weight (source=ai) CardPrintingTag votes for cards whose printing is "
        "logically entailed by existing catalog data (see cardpicker/deductive_backfill.py "
        "and docs/features/printing-tags.md). These are suggestions, never resolutions - the "
        "human-backed gate in vote_consensus.resolve_weighted_consensus means AI-only votes "
        "can never resolve a card by themselves. Idempotent: a card that already has any "
        "printing_tags vote (from this command or otherwise) is never revisited, so an "
        "interrupted run can simply be re-invoked to resume."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tier",
            choices=["d1", "d2", "all"],
            default="all",
            help="Which confidence tier to backfill. d1=0.95 (unique name match), "
            "d2=0.90 (name + expansion_hint narrows to one printing). Default: all "
            "(d1 fully, then d2).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the number of votes written in this invocation. Useful for staged "
            "rollout or a quick --dry-run sample.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Select and count candidates without writing anything or running the gate check.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="CardPrintingTag rows per bulk_create batch. Default: 2000.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        tier = kwargs["tier"]
        limit = kwargs["limit"]
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]

        mode = "DRY RUN" if dry_run else "WRITE"
        print(f"[{mode}] deductive_backfill_printing_tags --tier={tier} --limit={limit} --batch-size={batch_size}")

        result = run_backfill(tier=tier, limit=limit, dry_run=dry_run, batch_size=batch_size)

        print(f"D1 votes: {result.d1_written}")
        print(f"D2 votes: {result.d2_written}")
        print(f"Total: {result.total_written}")

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        if result.gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) resolved after an AI-only "
                f"vote, which should be structurally impossible - STOP and investigate before "
                f"continuing this backfill. Affected card pks: {result.gate_violations[:50]}"
                + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        print(f"Gate check passed: 0/{result.total_written} affected cards resolved.")
