"""
Schedules `warm_question_feed_remaining_estimate` (see that management command's own module
docstring, and `question_feed.warm_feed_supply_cache`'s, for the full architecture this belongs
to) to run automatically via django-q2 - same pattern `0105_question_feed_pools_schedule.py`
uses for the pool warmers, one `Schedule` row here since there is only one cadence to configure
(`settings.QUESTION_FEED_REMAINING_ESTIMATE_WARM_MINUTES`, default 4 - both caches this warms
share the same 300s TTL, so there is no per-lane split to make the way the pools have).

`get_or_create` is safe against the concurrent-migrate race `0107_..._schedule_dedupe.py`
fixed for the pool schedules: that migration added a UNIQUE constraint on `Schedule.name`
(`django_q_schedule_name_uniq`), already in place by the time this migration runs (it depends on
0114, which chains back through 0107), so a second concurrent `get_or_create` for this same name
hits `IntegrityError` and re-reads the winner's row instead of inserting a duplicate - no
separate dedupe migration needed for this one row the way the four pool rows required.

WHY `next_run` IS SET EXPLICITLY: identical reasoning to `0094_warm_catalog_stats_hourly_
schedule.py`/`0105_question_feed_pools_schedule.py`'s own docstrings - django-q2 defaults
`next_run` to "the moment this migration happens to apply" when left unset, pinning an arbitrary
wall-clock minute per-deployment. Setting it explicitly, `QUESTION_FEED_REMAINING_ESTIMATE_WARM_
MINUTES` minutes strictly after "now" at apply-time, pins a predictable slot instead.

WHAT ACTUALLY RUNS THIS: nothing in the web tier - the `worker` container's existing `qcluster`
process polls for and executes this `Schedule` row, same as every other warmer in this project.
"""

from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

_SCHEDULE_NAME = "warm_question_feed_remaining_estimate"


def create_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    minutes = settings.QUESTION_FEED_REMAINING_ESTIMATE_WARM_MINUTES
    Schedule.objects.get_or_create(
        name=_SCHEDULE_NAME,
        defaults=dict(
            func="django.core.management.call_command",
            args=f"'{_SCHEDULE_NAME}'",
            schedule_type="I",
            minutes=minutes,
            next_run=timezone.now() + timedelta(minutes=minutes),
        ),
    )


def delete_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=_SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0114_canonicalprintingmetadata_color_identity_type_line"),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
