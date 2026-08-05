from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.models import ArtboxPhashExemplar


class Command(BaseCommand):
    help = (
        "Issue #508 phase 1: retracts ArtboxPhashExemplar rows. Nothing downstream reads this "
        "table yet (no matching calculator, no vote), so retraction here is a plain filtered "
        "delete - no consensus resync, no safety gate against a live consensus outcome (compare "
        "retract_stage_d_by_run_id, which needs both because its target table casts votes). "
        "--seed-group-key is the primary path (ArtboxPhashExemplar's own docstring): every "
        "exemplar traced to the SAME source resolution or the SAME source join-key vote shares "
        "one seed_group_key, so retracting a bad seed 'together with everything it seeded' is "
        "exactly this filter. --card-id/--illustration-id/--run-id/--source-vote-id are narrower "
        "or broader alternatives for a caller who already knows one of those instead. Exactly one "
        "selector is required per invocation; combining more than one is a CommandError, not a "
        "silent AND, since a caller reaching for two selectors at once is very likely trying to "
        "express something this command doesn't support rather than a genuine narrowing. Dry-run "
        "by default - --write required to actually delete anything."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--seed-group-key", type=str, default=None, help="Retract every exemplar sharing this seed_group_key."
        )
        parser.add_argument(
            "--card-id", type=int, default=None, help="Retract the single exemplar seeded from this card."
        )
        parser.add_argument(
            "--illustration-id",
            type=str,
            default=None,
            help="Retract every exemplar pointing at this illustration_id (UUID).",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Retract every exemplar stamped with this backfill run_id "
            "(backfill_artbox_phash_exemplars --run-id).",
        )
        parser.add_argument(
            "--source-vote-id",
            type=int,
            default=None,
            help="Retract the single exemplar seeded from this CardPrintingTag vote (JOIN_KEY_MACHINE seeds only).",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually delete the matched rows. Default is dry-run: report the count and "
            "the affected illustration_ids without deleting anything.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        selectors = {
            "seed_group_key": kwargs["seed_group_key"],
            "card_id": kwargs["card_id"],
            "illustration_id": kwargs["illustration_id"],
            "run_id": kwargs["run_id"],
            "source_vote_id": kwargs["source_vote_id"],
        }
        given = {key: value for key, value in selectors.items() if value is not None}
        if len(given) != 1:
            raise CommandError(
                "Exactly one of --seed-group-key/--card-id/--illustration-id/--run-id/"
                f"--source-vote-id is required (got {len(given)}: {sorted(given)})."
            )

        write = kwargs["write"]
        mode = "WRITE" if write else "DRY RUN"

        queryset = ArtboxPhashExemplar.objects.filter(**given)
        count = queryset.count()
        illustration_ids = sorted({str(value) for value in queryset.values_list("illustration_id", flat=True)})

        self.stdout.write(f"[{mode}] retract_artbox_phash_exemplars {given}")
        self.stdout.write(
            f"Matched {count} exemplar row(s) across {len(illustration_ids)} distinct illustration_id(s)"
            f"{': ' + ', '.join(illustration_ids[:20]) if illustration_ids else ''}"
            f"{' (truncated)' if len(illustration_ids) > 20 else ''}."
        )

        if not write:
            self.stdout.write("Dry run - nothing deleted.")
            return

        deleted_count, _ = queryset.delete()
        self.stdout.write(f"Deleted {deleted_count} row(s).")
