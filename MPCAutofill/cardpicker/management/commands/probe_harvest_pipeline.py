from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.harvest_probe import run_stage_a_probe

DEFAULT_SAMPLE_SIZE = 30


class Command(BaseCommand):
    help = (
        "Harvest-calculate pipeline Stage A (docs/features/catalog-completion-plan.md): "
        "instrumented wall-clock probe over a real sample. Fetches real images (real network "
        "cost) and runs OCR/phash exactly as the real pipeline would; the DB-write timing is a "
        "real bulk_create() rolled back inside a savepoint - no votes/residue are ever "
        "persisted by this command."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help=f"Number of cards to probe (default: {DEFAULT_SAMPLE_SIZE}).",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        sample_size = kwargs["sample_size"]
        result = run_stage_a_probe(sample_size=sample_size)

        print(
            f"[stage-a-probe] sample_size={result.sample_size} attempted={result.attempted} "
            f"fetched={result.fetched}"
        )

        totals = result.totals
        percentages = result.percentages
        grand_total = sum(totals.values())
        print(f"[stage-a-probe] wall-clock split (total={grand_total:.2f}s across {result.fetched} fetched cards):")
        for stage in ("fetch", "ocr", "phash", "db"):
            mean = totals[stage] / result.fetched if result.fetched else 0.0
            print(f"  {stage}: total={totals[stage]:.2f}s ({percentages[stage]:.1f}%) mean={mean:.3f}s/card")

        if result.fetched == 0:
            print("[stage-a-probe] WARNING: zero cards fetched successfully - no timing signal.")
