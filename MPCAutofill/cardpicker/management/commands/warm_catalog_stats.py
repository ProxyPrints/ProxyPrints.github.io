"""
Refreshes the Proposal F catalog-stats cache (see `cardpicker.catalog_stats`'s own module
docstring for the full compute/warm/cache-only-read architecture this belongs to, and
`docs/features/catalog-stats.md` for the page-facing summary).

Intended for an HOURLY django-q2 schedule (see migration `0094_...`'s own docstring for the
cadence justification - these five aggregates move slowly, by their own nature: vote counts,
skip-log rows, and pilot-run ledger entries accumulate at most a few dozen new rows an hour even
during an active human tagging push, and `catalog_composition`'s source/card counts change only
when a source is re-scanned. Hourly is generous headroom, not a tuned-to-the-edge number).

Idempotent and safe to re-run: every call recomputes all five panels FRESH from the live database
and overwrites the cache with the new blob, never merges with or diffs against the previous run -
running this command twice in a row (or ten times) leaves the cache in exactly the same state a
single run would.

**Unlike `warm_artist_external_links`, there is no third-party rate limit and no opt-in gate
here.** This command reads only this project's OWN database (five `SELECT`-only aggregations, no
outbound HTTP call to anything) - it always runs, on every instance, unconditionally, the moment
the `Schedule` row this command's own migration creates first fires.

**On any failure this command changes NOTHING and exits non-zero.** See
`warm_catalog_stats_cache`'s own docstring: `compute_catalog_stats()` is a pure read, and only its
return value is ever written to the cache - a partial or unexpected failure mid-computation simply
raises before reaching the one `.set()` call, so the previous cache entry (an earlier run's good
blob, or nothing at all on a first run) is left untouched. A run that fails today and isn't
retried until the next scheduled hourly invocation is the desired behaviour, not a bug to paper
over.

**Writes a NAMED `"shared"` cache, not Django's `default` (issue #538/#543) - and FAILS LOUDLY if
it isn't configured.** Same split as `warm_artist_external_links`: this command writes
`caches["shared"]`, resolved BEFORE any aggregation runs, and exits non-zero with a clear
`CommandError` if it isn't configured (unlike the read endpoint, which degrades a missing
`"shared"` cache to its zeroed skeleton, never a 500 - see `cardpicker.catalog_stats`'s own module
docstring). A cron/schedule run that silently writes nowhere and reports success is exactly the
bug issue #538 exists to prevent, and this command must not repeat it a second way.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.catalog_stats import warm_catalog_stats_cache


class Command(BaseCommand):
    help = (
        "Recomputes all five Proposal F catalog-stats panels and writes the catalog-stats cache "
        "blob. Intended for an hourly django-q2 schedule. On any failure, leaves the existing "
        "cache untouched and exits non-zero."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        try:
            blob = warm_catalog_stats_cache()
        except Exception as e:
            raise CommandError(f"Catalog-stats warm run failed, cache left untouched: {e}")

        contributions_weeks = len(blob["contributionsOverTime"]["series"])
        skip_reasons = len(blob["skipBreakdown"]["byReason"])
        recent_runs = len(blob["runHistory"]["recent"])
        sources = len(blob["catalogComposition"]["sources"])
        human_votes = blob["participation"]["humanVotes"]["total"]

        self.stdout.write(
            self.style.SUCCESS(
                "Catalog-stats cache warmed: "
                f"{contributions_weeks} weeks of contributions, {skip_reasons} skip reasons, "
                f"{recent_runs} recent pilot runs, {sources} sources, {human_votes} total human votes."
            )
        )
