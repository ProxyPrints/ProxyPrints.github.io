from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_identify_printing_tags import (
    generate_run_id,
    run_name_frequency_elimination,
)
from cardpicker.models import PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


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
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code (see docs/features/catalog-completion-plan.md's rebuild command) before "
                "running this command."
            )
        git_sha = get_baked_git_sha()
        print(f"[GIT_SHA] {git_sha or 'unknown (not baked - non-Docker run?)'}")

        dry_run = kwargs["dry_run"]
        batch_size = kwargs["batch_size"]

        mode = "DRY RUN" if dry_run else "WRITE"
        run_id = generate_run_id()
        print(f"[{mode}] local_name_frequency_elimination --batch-size={batch_size} run_id={run_id}")

        ledger_entry = None
        if not dry_run:
            ledger_entry = PilotRunLedger.objects.create(
                run_id=run_id,
                command="local_name_frequency_elimination",
                dry_run=dry_run,
                git_sha=git_sha,
            )

        try:
            result = run_name_frequency_elimination(dry_run=dry_run, batch_size=batch_size, run_id=run_id)
        except Exception:
            if ledger_entry is not None:
                ledger_entry.status = PilotRunLedger.Status.FAILED
                ledger_entry.finished_at = timezone.now()
                ledger_entry.save(update_fields=["status", "finished_at"])
            raise

        print(f"votes written: {result.votes_written}")

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        if result.gate_violations:
            if ledger_entry is not None:
                ledger_entry.status = PilotRunLedger.Status.FAILED
                ledger_entry.finished_at = timezone.now()
                ledger_entry.votes_written = result.votes_written
                ledger_entry.save(update_fields=["status", "finished_at", "votes_written"])
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) resolved after a "
                f"machine-only vote, which should be structurally impossible - STOP and "
                f"investigate before continuing. Affected card pks: {result.gate_violations[:50]}"
                + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        if ledger_entry is not None:
            ledger_entry.status = PilotRunLedger.Status.COMPLETED
            ledger_entry.finished_at = timezone.now()
            ledger_entry.votes_written = result.votes_written
            ledger_entry.save(update_fields=["status", "finished_at", "votes_written"])

        print(f"run_id: {run_id}")
        print(f"Gate check passed: 0/{result.votes_written} affected cards resolved.")
