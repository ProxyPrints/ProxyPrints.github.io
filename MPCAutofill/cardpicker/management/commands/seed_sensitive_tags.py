from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.sensitive_tags import seed_sensitive_tags


class Command(BaseCommand):
    help = (
        "Seeds the sensitive-tag taxonomy for the moderation layer "
        "(NSFW, low-res, incorrect-info, appropriate-bleed). Safe to re-run."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = seed_sensitive_tags()
        print(f"Sensitive tags: {stats['created']} created, {stats['updated']} updated.")
