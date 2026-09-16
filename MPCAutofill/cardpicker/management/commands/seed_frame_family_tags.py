from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.frame_family_tags import seed_frame_family_tags


class Command(BaseCommand):
    help = (
        "Seeds frame-family tag taxonomy (children of Showcase) for the "
        "What's That Card? questionFeed. Safe to re-run."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = seed_frame_family_tags()
        print(f"Frame-family tags: {stats['created']} created.")
