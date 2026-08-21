"""
Refreshes one lane of the question-feed candidate-pool cache (issue #727 - see
`cardpicker.question_feed_pools`'s own module docstring for the full compute/warm/cache-only-read
architecture this belongs to).

Takes the lane as a required positional argument so a single command backs all four django-q2
`Schedule` rows created by migration `0105_question_feed_pools_schedule.py`, each firing on its
own cadence (`settings.QUESTION_FEED_POOL_WARM_MINUTES_*`) - see that migration's own docstring
for why lane 1 warms in minutes and lane 4 in hours, never one global interval.

Idempotent and safe to re-run: every call recomputes the named lane's pool FRESH from the live
database and overwrites its cache entry, never merges with the previous run - same convention as
`warm_catalog_stats`.

On any failure this command changes NOTHING and exits non-zero: `question_feed_pools.
warm_pool_cache` only calls `.set()` once, after the pool is fully built, so a failure partway
through leaves the previous cache entry (an earlier run's good pool, or nothing at all on a first
run) untouched.

Writes a NAMED `"shared"` cache, not Django's `default` (issue #538/#543) - and FAILS LOUDLY if it
isn't configured, same split as `warm_catalog_stats`/`warm_artist_external_links`.
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cardpicker.question_feed_pools import LANES, warm_pool_cache, warm_pool_images

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Recomputes one question-feed candidate pool (issue #727) and writes its cache entry. "
        f"Lane must be one of: {', '.join(LANES)}. Intended for a per-lane django-q2 schedule "
        "(cardpicker/migrations/0105_question_feed_pools_schedule.py). On any failure, leaves "
        "the existing cache untouched and exits non-zero."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("lane", choices=LANES)

    def handle(self, *args: Any, **kwargs: Any) -> None:
        lane = kwargs["lane"]
        try:
            count = warm_pool_cache(lane)
        except Exception as e:
            raise CommandError(f"Question-feed pool warm run failed for lane {lane!r}, cache left untouched: {e}")

        # Second, separate step (see warm_pool_images's own docstring for why it isn't folded
        # into warm_pool_cache above): re-images this lane's freshly-cached pool through the
        # image CDN Worker's small tier, so the R2 bucket entry a voter's next draw would need
        # is already populated. Best-effort, unlike the pool warm above: the pool cache write
        # already succeeded by this point and is the part that matters for correctness (a voter
        # can still be served correctly from an unwarmed image, just slower) - an image-warm
        # failure is logged, not raised, so it never masks or reverts the pool warm's own success.
        try:
            images_warmed = warm_pool_images(lane)
        except Exception:
            logger.exception("Question-feed pool image warm failed for lane %r (pool warm itself succeeded)", lane)
            images_warmed = 0

        self.stdout.write(
            self.style.SUCCESS(
                f"Question-feed pool warmed: lane={lane!r}, {count} candidates, {images_warmed} images warmed."
            )
        )
