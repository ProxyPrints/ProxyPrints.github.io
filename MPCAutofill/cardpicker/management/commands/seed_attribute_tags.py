from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.attribute_tags import seed_attribute_tags


class Command(BaseCommand):
    help = (
        'Seeds the attribute-chip tag taxonomy for the "What\'s That Card?" questionFeed '
        "(Etched, Black/White/Silver Border, Old/Modern Border, Future Frame). Safe to re-run."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = seed_attribute_tags()
        print(f"Attribute tags: {stats['created']} created.")
