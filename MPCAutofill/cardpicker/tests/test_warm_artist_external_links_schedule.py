"""
Tests for the django-q2 `Schedule` row that `0093_warm_artist_external_links_weekly_
schedule.py` creates for `warm_artist_external_links` (see that migration's own module
docstring for why the cadence is weekly and why `next_run` is pinned explicitly rather
than left to django-q2's default-to-now behaviour).

Companion to `test_shared_cache.py`'s own "region migration" - same shape (import the
migration module directly via `importlib` since its name starts with a digit, drive the
real `MigrationExecutor` backwards/forwards), applied to a `django_q.Schedule` row
instead of a cache table.

Deliberately plain `@pytest.mark.django_db`, NOT `transaction=True`: nothing here needs
another OS process to see committed data (that's what `test_shared_cache.py`'s
`transaction=True` is for). Plain `django_db` wraps each test in a transaction rolled
back afterwards, which is what makes the migration-created row visible to every test
method here without re-running `migrate` per test - `transaction=True` instead FLUSHES
all tables between tests (true `TransactionTestCase` behaviour) and does not replay data
migrations, which would silently delete the row after the first test method ran.
"""

import importlib
from datetime import timezone as dt_timezone
from types import ModuleType

import pytest

from django.apps import apps as django_apps
from django.db import connection
from django.utils import timezone

MIGRATION_NAME = "0093_warm_artist_external_links_weekly_schedule"
SCHEDULE_NAME = "warm_artist_external_links"


def migration_module() -> ModuleType:
    """
    The migration that creates the weekly schedule row, imported as a module.

    `importlib` rather than a plain `import` only because the module name starts
    with a digit and so is not a legal identifier.
    """
    return importlib.import_module(f"cardpicker.migrations.{MIGRATION_NAME}")


@pytest.mark.django_db
class TestWarmArtistExternalLinksScheduleMigration:
    def test_migration_created_exactly_one_schedule_row(self):
        """
        No operator step: this row is present in a database built purely by `migrate`,
        which is how both production (`docker/django/entrypoint.sh`) and this test
        database are built.
        """
        from django_q.models import Schedule

        assert Schedule.objects.filter(name=SCHEDULE_NAME).count() == 1

    def test_schedule_is_weekly(self):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.schedule_type == "W"

    def test_schedule_calls_the_management_command(self):
        """
        Matches the quoting convention `0048_auto_20260426_2140.py` uses for
        `import_canonical_card_data` - django-q2 evaluates `args` as a literal, so the
        inner quotes are load-bearing, not cosmetic.
        """
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.func == "django.core.management.call_command"
        assert schedule.args == "'warm_artist_external_links'"

    def test_next_run_is_exactly_midnight_utc_and_in_the_future(self):
        """
        THE point of this migration (see its own module docstring): `next_run` must be
        pinned to a real wall-clock slot, not left to django-q2's default-to-now
        behaviour, which would silently drift to whatever moment `migrate` happened to
        run.
        """
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        next_run = schedule.next_run

        assert next_run.tzinfo is not None
        assert next_run.utcoffset().total_seconds() == 0
        # Assert the wall-clock UTC time explicitly, not just the offset, so a
        # correctly-offset-but-wrong-instant value (e.g. local midnight relabelled UTC)
        # would still fail this test.
        as_utc = next_run.astimezone(dt_timezone.utc)
        assert (as_utc.hour, as_utc.minute, as_utc.second, as_utc.microsecond) == (0, 0, 0, 0)

        assert next_run > timezone.now()

    def test_applying_twice_does_not_create_a_second_row(self):
        """
        `get_or_create`, not `create`: a rebuilt environment or a squashed migration
        history must not be able to produce a second row for this name - two rows means
        two weekly calls against a partner's rate-limited endpoint.
        """
        from django_q.models import Schedule

        module = migration_module()
        module.create_schedule(django_apps, None)
        module.create_schedule(django_apps, None)

        assert Schedule.objects.filter(name=SCHEDULE_NAME).count() == 1

    def test_migration_declares_itself_reversible(self):
        operations = migration_module().Migration.operations
        assert len(operations) == 1
        assert operations[0].reversible is True

    def test_migration_reverses_and_reapplies_cleanly(self):
        """
        Drives the real migration executor backwards past 0093 and forwards again,
        asserting the row disappears and comes back. The `finally` guarantees the row is
        restored even if an assertion fails, so a failure here cannot cascade into
        unrelated tests later in the session.
        """
        from django_q.models import Schedule

        from django.db.migrations.executor import MigrationExecutor

        forwards = [("cardpicker", MIGRATION_NAME)]
        backwards = [("cardpicker", "0092_shared_cache_table")]

        assert Schedule.objects.filter(name=SCHEDULE_NAME).exists()
        try:
            MigrationExecutor(connection).migrate(backwards)
            assert not Schedule.objects.filter(name=SCHEDULE_NAME).exists()

            MigrationExecutor(connection).migrate(forwards)
            assert Schedule.objects.filter(name=SCHEDULE_NAME).exists()
        finally:
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            executor.migrate(forwards)
        assert Schedule.objects.filter(name=SCHEDULE_NAME).exists()

    def test_reverse_deletes_only_this_named_row(self):
        """
        The backwards operation filters by `name`, so it cannot collide with some other
        schedule an operator created by hand under a different name.
        """
        from django_q.models import Schedule

        Schedule.objects.create(
            name="some_unrelated_schedule",
            func="django.core.management.call_command",
            args="'import_canonical_card_data'",
            schedule_type="W",
        )

        module = migration_module()
        module.delete_schedule(django_apps, None)

        assert not Schedule.objects.filter(name=SCHEDULE_NAME).exists()
        assert Schedule.objects.filter(name="some_unrelated_schedule").exists()

        # Restore so the module-level migration state matches on-disk reality for any
        # later test in this session that assumes the schedule is present.
        module.create_schedule(django_apps, None)
        Schedule.objects.filter(name="some_unrelated_schedule").delete()
