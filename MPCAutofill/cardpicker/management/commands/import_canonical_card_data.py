from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.integrations.integrations import get_configured_game_integration


class Command(BaseCommand):
    help = "Imports canonical artists and cards for the configured game integration."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--skip-image-hash",
            action="store_true",
            default=False,
            help=(
                "Skip downloading each card's image to compute its perceptual hash, "
                "storing 0 instead. Bootstraps CanonicalCard rows from the bulk data "
                "alone, without the per-card image fetch that dominates runtime."
            ),
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        game_integration = get_configured_game_integration()
        if game_integration is None:
            raise Exception("No game integration is configured.")
        game_integration.import_canonical_expansions()
        game_integration.import_canonical_cards_and_artists(skip_image_hash=kwargs["skip_image_hash"])
