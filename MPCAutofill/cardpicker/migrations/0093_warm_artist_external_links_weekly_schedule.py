"""
Schedules `warm_artist_external_links` (see that management command's own module
docstring, and `cardpicker.artist_external_links`'s, for the full daily-cached-bulk-
consumer architecture this belongs to) to run automatically via django-q2, the same
way `0048_auto_20260426_2140.py` already schedules `import_canonical_card_data`.

WHY WEEKLY (owner ruling)
--------------------------
MTGAC's disclosed limit on the bulk endpoint this command calls is 12 requests/hour
(as of 2026-07-29 - see the command's own docstring and
`docs/features/artist-support-links.md`'s rate-limit table). One call per week is
deliberately far inside that budget, not a tuned-to-the-edge number: the whole point
of a bulk-cached consumer is that steady-state traffic against a partner's API is
negligible, and a wide margin costs nothing here since the underlying MTGAC data
(artist rosters, link fields) does not change fast enough to need more frequent
refreshes. Do not tighten this cadence without re-reading that rate-limit table
first - see the command's own docstring for why a failed run is also never retried,
which is the actual exposure, not steady-state call volume.

WHY `next_run` IS SET EXPLICITLY
----------------------------------
django-q2's `Schedule.schedule_type` means "every N [DAILY/WEEKLY/...] starting from
`next_run`" - and when `next_run` is left unset, django-q2 defaults it to the moment
the `Schedule` row is created (i.e. whenever this migration happens to run). Left
alone, that means the weekly slot silently drifts to an arbitrary wall-clock moment
- whatever second `migrate` happened to execute at in this deployment - and drifts
AGAIN on any future re-run that recreates the row. Setting `next_run` explicitly, to
the next midnight UTC strictly after "now" at migration time, pins a predictable,
human-legible slot instead. django-q2 advances `next_run` from the PREVIOUS
`next_run` value each time the task fires, not from completion time, so once pinned
this slot holds indefinitely (00:00 UTC, every week) rather than sliding forward by
however long each run happens to take.

The date itself is intentionally NOT hardcoded - a literal date would already be in
the past by the time this migration actually deploys (migrations are written once
and applied later, on an unknown schedule). Instead this file computes "the next
00:00 UTC strictly after now" at apply-time, using `django.utils.timezone` (this
project runs with `USE_TZ = True`, so a naive datetime here would be a bug - Django
would either reject it or silently reinterpret it against the wrong zone).

WHAT ACTUALLY RUNS THIS
------------------------
Nothing in the web tier. The `worker` container already runs django-q2's `qcluster`
(`django-q2~=1.8.0`, `django_q` in `INSTALLED_APPS`, `Q_CLUSTER` configured in
`MPCAutofill/settings.py`) - this migration only inserts the `Schedule` row `qcluster`
polls for and executes; it does not itself invoke the command. No new container, no
OS cron entry, is introduced or required.
"""

from datetime import datetime, timedelta

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

SCHEDULE_NAME = "warm_artist_external_links"


def _next_midnight_utc() -> datetime:
    """
    The next occurrence of 00:00 UTC strictly after "now" - computed at apply-time,
    never hardcoded (see module docstring). Timezone-aware throughout: `timezone.now()`
    already returns a UTC-based aware datetime under `USE_TZ = True`.
    """
    now = timezone.now()
    midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if midnight_today <= now:
        return midnight_today + timedelta(days=1)
    return midnight_today


def create_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    # `get_or_create`, not `create`: a rebuilt environment or a squashed migration
    # history must not be able to produce a second row for this name - two rows
    # means two weekly calls against a partner's rate-limited endpoint.
    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults=dict(
            func="django.core.management.call_command",
            args="'warm_artist_external_links'",
            schedule_type="W",
            next_run=_next_midnight_utc(),
        ),
    )


def delete_schedule(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0092_shared_cache_table"),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
