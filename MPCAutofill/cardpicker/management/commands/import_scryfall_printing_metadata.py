from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.printing_metadata_import import import_scryfall_printing_metadata


class Command(BaseCommand):
    help = "Enriches CanonicalCard rows with Scryfall printing metadata (full art, frame, promo types, etc.)."

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = import_scryfall_printing_metadata()
        print(
            f"CanonicalPrintingMetadata sync: {stats['created']} created, {stats['updated']} updated, "
            f"{stats['deleted']} deleted, {stats['skipped']} skipped."
        )
