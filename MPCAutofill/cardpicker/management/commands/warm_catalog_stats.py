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

**SKIPS (exit 0, never an error) while a catalog sweep is in flight (owner ruling 2026-07-29).**
A sweep (`PilotRunLedger` row with `status=RUNNING` - see that model's own docstring: "the
durable, queryable record", created RUNNING at start, updated COMPLETED/FAILED at end) genuinely
contends for the same database this command's five aggregates query, so this command checks for
one BEFORE computing anything and, if found, skips the entire run rather than compute against a
catalog mid-mutation. This is the exact same "not configured" vs "broken" split
`warm_artist_external_links` already draws between an opt-in gate (quiet, exit-0 skip) and a
genuine fetch failure (`CommandError`, non-zero) - a skip here is equally NOT an error: it is this
command correctly declining to run, not a failure to run. The cache is left completely untouched
on skip, same rule this command already follows on a genuine failure - never a partial or zeroed
blob, stale-but-correct beats fresh-but-wrong here just as much as it does on the failure path.

Guarded against a crashed sweep that never reaches COMPLETED/FAILED and would otherwise leave a
`RUNNING` row - and therefore this gate - stuck forever: a `RUNNING` row older than
`settings.WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS` (default comfortably above a full sweep's
measured ~7.0h floor - see that setting's own comment in `MPCAutofill/MPCAutofill/settings.py` for the exact
number and reasoning) is ignored and does not block this run. Both the gate itself
(`settings.WARM_CATALOG_STATS_SWEEP_GATE_ENABLED`) and the staleness bound are settings-driven,
tunable without a migration or a code change - see those two settings' own comments.

The skip message names the specific blocking run (`run_id`, `started_at`, and how long it has
been running) precisely so a frozen stats page is diagnosable from the command's own log output in
one command, without a separate query against `PilotRunLedger`.

**Consequence, stated plainly (owner ruling 2026-07-29): gating the WHOLE warm run this way means
the stats page can be up to ~7h stale during a full sweep**, not the roughly-hourly cadence the
schedule alone implies - see `docs/features/catalog-stats.md`'s "Sweep gate" section for the full
write-up. This is an accepted trade, not an oversight: a fast/slow split (skip only the panels
that actually read tables a sweep mutates, keep warming the rest) would avoid this staleness, and
is a known, deliberately deferred follow-up - not designed or built here.
"""

from datetime import timedelta
from typing import Any, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.catalog_stats import warm_catalog_stats_cache
from cardpicker.models import PilotRunLedger


def _find_blocking_sweep() -> Optional[PilotRunLedger]:
    """
    The most recent `PilotRunLedger` row that is still `RUNNING` and NOT old enough to be
    considered a crashed sweep (see this command's own module docstring's "guarded against a
    crashed sweep" section) - or `None` if no such row exists, in which case this command must
    not skip.
    """
    stale_bound = timezone.now() - timedelta(hours=settings.WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS)
    return (
        PilotRunLedger.objects.filter(status=PilotRunLedger.Status.RUNNING, started_at__gte=stale_bound)
        .order_by("-started_at")
        .first()
    )


class Command(BaseCommand):
    help = (
        "Recomputes all five Proposal F catalog-stats panels and writes the catalog-stats cache "
        "blob. Intended for an hourly django-q2 schedule. Skips cleanly (exit 0) while a catalog "
        "sweep is in flight (PilotRunLedger status=RUNNING within the staleness bound), leaving "
        "the cache untouched - see this command's own module docstring for the accepted "
        "up-to-~7h staleness trade this creates. On any other failure, also leaves the existing "
        "cache untouched and exits non-zero."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        if settings.WARM_CATALOG_STATS_SWEEP_GATE_ENABLED:
            blocking_run = _find_blocking_sweep()
            if blocking_run is not None:
                running_for = timezone.now() - blocking_run.started_at
                self.stdout.write(
                    self.style.WARNING(
                        "Catalog sweep in flight - skipping this warm run, cache left untouched. "
                        f"Blocking run: run_id={blocking_run.run_id!r}, "
                        f"started_at={blocking_run.started_at.isoformat()}, "
                        f"running for {running_for.total_seconds() / 3600:.1f}h "
                        f"(gate stale bound: {settings.WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS}h). "
                        "If this message keeps recurring past that bound, the sweep likely "
                        "crashed without updating its ledger row to COMPLETED/FAILED - see "
                        "docs/features/catalog-stats.md's 'Sweep gate' section."
                    )
                )
                return

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
