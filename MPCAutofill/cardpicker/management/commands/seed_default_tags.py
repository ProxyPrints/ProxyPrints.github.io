from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.default_tags import seed_default_tags


class Command(BaseCommand):
    help = "Seeds the default descriptor Tag taxonomy (Borderless, Extended, Showcase, etc.). Safe to re-run."

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = seed_default_tags()
        print(f"Default tags: {stats['created']} created, {stats['updated']} updated.")
