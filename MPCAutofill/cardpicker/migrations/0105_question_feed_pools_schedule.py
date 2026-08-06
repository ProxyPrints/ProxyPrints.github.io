"""
Schedules `warm_question_feed_pools <lane>` (see that management command's own module docstring,
and `cardpicker.question_feed_pools`'s, for the full architecture this belongs to) to run
automatically via django-q2, one `Schedule` row per lane - the same way `0094_warm_catalog_stats_
hourly_schedule.py` schedules `warm_catalog_stats`.

FOUR ROWS, FOUR CADENCES - NOT ONE GLOBAL INTERVAL (issue #727)
-----------------------------------------------------------------
Lane 1 (resolution-imminent) churns with every vote cast and wants minutes; lane 4 (cold) changes
only as the pipeline extracts new evidence and tolerates hours. All four use django-q2's MINUTES
schedule type (rather than mixing MINUTES/HOURLY) so every lane's cadence is a single settings-
driven number (`settings.QUESTION_FEED_POOL_WARM_MINUTES_*`) - the same knob shape for all four,
never a fixed-at-exactly-one-hour type for some and a tunable one for others.

WHY `next_run` IS SET EXPLICITLY, WHY IT ISN'T HARDCODED
-----------------------------------------------------------
Identical reasoning to `0094_warm_catalog_stats_hourly_schedule.py`'s own docstring, restated
here since a future reader of THIS file shouldn't have to cross-reference to understand it:
django-q2 defaults `next_run` to "the moment this migration happens to apply" when left unset,
which would pin an arbitrary wall-clock minute per-deployment and drift again on any future
re-run that recreates a row. Setting `next_run` explicitly, to `settings.QUESTION_FEED_POOL_WARM_
MINUTES_<LANE>` minutes strictly after "now" at apply-time, pins a predictable slot instead.

WHAT ACTUALLY RUNS THIS
------------------------
Nothing in the web tier, same as `0094_...`. The `worker` container already runs django-q2's
`qcluster` - this migration only inserts the four `Schedule` rows `qcluster` polls for and
executes; it does not itself invoke any command. No new container is introduced or required.
"""

from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

# (schedule name, lane argument, settings attribute naming this lane's warm cadence in minutes)
_SCHEDULES = (
    (
        "warm_question_feed_pool_resolution_imminent",
        "resolution_imminent",
        "QUESTION_FEED_POOL_WARM_MINUTES_RESOLUTION_IMMINENT",
    ),
    ("warm_question_feed_pool_confirm", "confirm", "QUESTION_FEED_POOL_WARM_MINUTES_CONFIRM"),
    ("warm_question_feed_pool_contested", "contested", "QUESTION_FEED_POOL_WARM_MINUTES_CONTESTED"),
    ("warm_question_feed_pool_cold", "cold", "QUESTION_FEED_POOL_WARM_MINUTES_COLD"),
)


def create_schedules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    now = timezone.now()
    for name, lane, minutes_setting in _SCHEDULES:
        minutes = getattr(settings, minutes_setting)
        # `get_or_create`, not `create`: a rebuilt environment or a squashed migration history
        # must not be able to produce a second row for this name - two rows means two warm runs
        # per cadence instead of one, doubling load for no benefit.
        Schedule.objects.get_or_create(
            name=name,
            defaults=dict(
                func="django.core.management.call_command",
                args=f"'warm_question_feed_pools', '{lane}'",
                schedule_type="I",
                minutes=minutes,
                next_run=now + timedelta(minutes=minutes),
            ),
        )


def delete_schedules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name__in=[name for name, _, _ in _SCHEDULES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0104_cardquestionabstention"),
    ]

    operations = [
        migrations.RunPython(create_schedules, delete_schedules),
    ]
