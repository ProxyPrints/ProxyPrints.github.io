"""
Schedules `warm_catalog_stats` (see that management command's own module docstring, and
`cardpicker.catalog_stats`'s, for the full compute/warm/cache-only-read architecture this belongs
to) to run automatically via django-q2, the same way `0093_warm_artist_external_links_weekly_
schedule.py` schedules `warm_artist_external_links` and `0048_auto_20260426_2140.py` schedules
`import_canonical_card_data`.

WHY HOURLY (see `warm_catalog_stats`'s own docstring for the full reasoning)
-----------------------------------------------------------------------------
Unlike the MTGAC integration `0093_...` schedules, this command has no third-party rate limit and
no opt-in gate to respect - it reads only this project's own database. The cadence choice is
therefore purely about freshness vs. cost, not budget: all five panels (`cardpicker.catalog_
stats.compute_catalog_stats`) are small, indexed aggregations over this project's own tables, and
every one of them moves slowly by its own nature - vote counts, skip-log rows, and pilot-run
ledger rows accumulate at most a few dozen new rows an hour even during an active human tagging
push, and `catalog_composition`'s source/card counts change only when a source is re-scanned.
Hourly gives the public stats page same-day-visible freshness without re-running these queries on
anything close to every request - a wide margin, not a tuned-to-the-edge number. Do not tighten
this cadence without a concrete reason the data itself now moves faster than this reasoning
assumes.

WHY `next_run` IS SET EXPLICITLY, WHY IT ISN'T HARDCODED
-----------------------------------------------------------
Identical reasoning to `0093_warm_artist_external_links_weekly_schedule.py`'s own docstring,
restated here since a future reader of THIS file shouldn't have to cross-reference to understand
it: django-q2 defaults `next_run` to "the moment this migration happens to apply" when left unset,
which would pin an arbitrary wall-clock minute per-deployment and drift again on any future
re-run that recreates the row. Setting `next_run` explicitly, to the next top-of-the-hour UTC
strictly after "now" at apply-time (never a hardcoded literal - see `_next_hour_utc` below, using
`django.utils.timezone` since this project runs with `USE_TZ = True`), pins a predictable,
human-legible slot instead - and once pinned, django-q2 advances `next_run` from the PREVIOUS
`next_run` value each time the task fires (not from completion time), so the slot holds at :00
past the hour indefinitely rather than sliding forward by however long each run happens to take.

WHAT ACTUALLY RUNS THIS
------------------------
Nothing in the web tier, same as `0093_...`. The `worker` container already runs django-q2's
`qcluster` (`django-q2~=1.8.0`, `django_q` in `INSTALLED_APPS`, `Q_CLUSTER` configured in
`MPCAutofill/settings.py`) - this migration only inserts the `Schedule` row `qcluster` polls for
and executes; it does not itself invoke the command. No new container, no OS cron entry, is
introduced or required.
"""

from datetime import datetime, timedelta

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

SCHEDULE_NAME = "warm_catalog_stats"


def _next_hour_utc() -> datetime:
    """
    The next occurrence of :00 UTC strictly after "now" - computed at apply-time, never
    hardcoded (see module docstring). Timezone-aware throughout: `timezone.now()` already returns
    a UTC-based aware datetime under `USE_TZ = True`.
    """
    now = timezone.now()
    top_of_this_hour = now.replace(minute=0, second=0, microsecond=0)
    if top_of_this_hour <= now:
        return top_of_this_hour + timedelta(hours=1)
    return top_of_this_hour


def create_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    # `get_or_create`, not `create`: a rebuilt environment or a squashed migration history must
    # not be able to produce a second row for this name - two rows means two hourly recomputations
    # instead of one, doubling load for no benefit.
    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults=dict(
            func="django.core.management.call_command",
            args="'warm_catalog_stats'",
            schedule_type="H",
            next_run=_next_hour_utc(),
        ),
    )


def delete_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0093_warm_artist_external_links_weekly_schedule"),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
