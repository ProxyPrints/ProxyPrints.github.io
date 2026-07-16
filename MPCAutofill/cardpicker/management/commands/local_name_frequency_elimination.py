from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.local_identify_printing_tags import run_name_frequency_elimination


class Command(BaseCommand):
    help = (
        "Fast-follow (see docs/features/printing-tags.md Stage 8): casts OCR-weight votes for "
        "cards whose name has exactly one uncovered printing AND exactly one unresolved "
        "pilot-eligible card - a pure structural deduction, no image fetch or OCR/phash "
        "involved. Never resolves a card by itself (the human-backed consensus gate still "
        "applies) - see run_name_frequency_elimination's own docstring for the safety gate "
        "that makes this deduction sound."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Evaluate without writing anything or running the gate check.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=25,
            help="Flush votes to the DB (and run the gate check) every this many cards, same "
            "checkpointing convention as local_identify_printing_tags. Default: 25.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]

        mode = "DRY RUN" if dry_run else "WRITE"
        print(f"[{mode}] local_name_frequency_elimination --batch-size={batch_size}")

        result = run_name_frequency_elimination(dry_run=dry_run, batch_size=batch_size)

        print(f"votes written: {result.votes_written}")

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        if result.gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) resolved after a "
                f"machine-only vote, which should be structurally impossible - STOP and "
                f"investigate before continuing. Affected card pks: {result.gate_violations[:50]}"
                + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        print(f"Gate check passed: 0/{result.votes_written} affected cards resolved.")
