"""
Refreshes `2/questionFeed/`'s two 300s-TTL "shared"-cache entries (`printing_consensus.
get_contested_card_ids`, then `question_feed.get_remaining_estimate` - see `question_feed.
warm_feed_supply_cache`'s own docstring for why both, in that order) - the body of a scheduled
django-q2 run created by migration `0115_question_feed_remaining_estimate_schedule.py`.

WHY THIS COMMAND EXISTS. Both caches above are compute-ON-MISS with the TTL as their only
invalidation (unlike `question_feed_pools`'s own warm-then-cache-only-read pools, which are
NEVER computed on the request path) - so once 300s pass with no feed traffic, the entry simply
expires, and the next real visitor pays the full uncached cost. `get_remaining_estimate`'s own
docstring measured that cost at ~9.2s against live production (2026-08-16) - that number is
`2/questionFeed/`'s own measured cold-start cost, paid entirely by whichever one voter's request
happens to land after the gap. Running this command on a cadence shorter than the 300s TTL
(`settings.QUESTION_FEED_REMAINING_ESTIMATE_WARM_MINUTES`, default 4 - comfortable margin under
5 minutes) means a scheduled warm always refreshes the entry before it lapses, so that ~9.2s is
paid on a clock instead of by a visitor.

Idempotent and safe to re-run: `warm_feed_supply_cache` only ever recomputes-and-overwrites,
same convention as `warm_catalog_stats`/`warm_question_feed_pools`.

On any failure this command exits non-zero and writes nothing new - `warm_feed_supply_cache`
resolves both values before either `.set()` call it depends on runs, so a failure partway through
leaves whichever cache entries were already warm (from an earlier successful run, or the TTL
gap's next live request) untouched, never a half-written state.

Writes the NAMED `"shared"` cache via the same functions the live view reads, not Django's
`default` (issue #538/#543) - both `get_contested_card_ids` and `get_remaining_estimate`
degrade a missing `"shared"` alias to computing live on every call rather than failing loudly,
same as their own request-path behaviour; this command's job is only to make that computation
happen on a schedule instead of on a visitor.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.question_feed import warm_feed_supply_cache


class Command(BaseCommand):
    help = (
        "Refreshes the question feed's contested-card-ids and remaining-estimate shared caches "
        "(both 300s TTL) so a live request never pays their uncached recompute cost "
        "(~9.2s, measured 2026-08-16). Intended for a django-q2 schedule shorter than 300s "
        "(cardpicker/migrations/0115_question_feed_remaining_estimate_schedule.py). On any "
        "failure, exits non-zero."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        try:
            counts = warm_feed_supply_cache()
        except Exception as e:
            raise CommandError(f"Question-feed remaining-estimate warm run failed: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                "Question-feed supply caches warmed: "
                f"total={counts.total}, confirmable={counts.confirmable}, "
                f"contested={counts.contested}, fresh={counts.fresh}."
            )
        )
