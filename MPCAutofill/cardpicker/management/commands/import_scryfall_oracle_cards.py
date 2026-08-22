from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.oracle_card_import import import_scryfall_oracle_cards


class Command(BaseCommand):
    help = (
        "Populates CanonicalOracleCard rows (oracle_text, cmc, colors, color_identity, "
        "type_line, legalities) from the cached Scryfall oracle_cards bulk data."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = import_scryfall_oracle_cards()
        print(
            f"CanonicalOracleCard sync: {stats['created']} created, {stats['updated']} updated, "
            f"{stats['deleted']} deleted, {stats['skipped']} skipped."
        )
