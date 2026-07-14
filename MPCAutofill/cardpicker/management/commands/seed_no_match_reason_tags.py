from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.reason_tags import seed_no_match_reason_tags


class Command(BaseCommand):
    help = "Seeds the 'why no match?' reason-code Tag taxonomy (custom-art, altered-frame, ...). Safe to re-run."

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stats = seed_no_match_reason_tags()
        print(f"No-match reason tags: {stats['created']} created, {stats['updated']} display_name backfilled.")
