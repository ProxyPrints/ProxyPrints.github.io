"""
Tests for the four django-q2 `Schedule` rows `0105_question_feed_pools_schedule.py` creates -
one per question-feed pool lane (issue #727). Mirrors `test_warm_artist_external_links_schedule.
py`'s own shape exactly (import the migration module directly via `importlib` since its name
starts with a digit, drive the real `MigrationExecutor` backwards/forwards) - see that file's own
docstring for why plain `@pytest.mark.django_db` (not `transaction=True`) is the right fixture
here.
"""

import importlib
from types import ModuleType

import pytest

from django.apps import apps as django_apps
from django.test import override_settings
from django.utils import timezone

MIGRATION_NAME = "0105_question_feed_pools_schedule"

EXPECTED_SCHEDULES = {
    "warm_question_feed_pool_resolution_imminent": (
        "resolution_imminent",
        "QUESTION_FEED_POOL_WARM_MINUTES_RESOLUTION_IMMINENT",
    ),
    "warm_question_feed_pool_confirm": ("confirm", "QUESTION_FEED_POOL_WARM_MINUTES_CONFIRM"),
    "warm_question_feed_pool_contested": ("contested", "QUESTION_FEED_POOL_WARM_MINUTES_CONTESTED"),
    "warm_question_feed_pool_cold": ("cold", "QUESTION_FEED_POOL_WARM_MINUTES_COLD"),
}


def migration_module() -> ModuleType:
    return importlib.import_module(f"cardpicker.migrations.{MIGRATION_NAME}")


@pytest.mark.django_db
class TestQuestionFeedPoolsScheduleMigration:
    def test_migration_created_exactly_one_row_per_lane(self):
        from django_q.models import Schedule

        for schedule_name in EXPECTED_SCHEDULES:
            assert Schedule.objects.filter(name=schedule_name).count() == 1

    def test_each_schedule_is_minutes_type_with_the_matching_settings_cadence(self):
        from django_q.models import Schedule

        from django.conf import settings

        for schedule_name, (_, minutes_setting) in EXPECTED_SCHEDULES.items():
            schedule = Schedule.objects.get(name=schedule_name)
            assert schedule.schedule_type == "I"
            assert schedule.minutes == getattr(settings, minutes_setting)

    def test_each_schedule_calls_the_management_command_with_its_own_lane(self):
        from django_q.models import Schedule

        for schedule_name, (lane, _) in EXPECTED_SCHEDULES.items():
            schedule = Schedule.objects.get(name=schedule_name)
            assert schedule.func == "django.core.management.call_command"
            assert schedule.args == f"'warm_question_feed_pools', '{lane}'"

    def test_next_run_is_in_the_future(self):
        from django_q.models import Schedule

        for schedule_name in EXPECTED_SCHEDULES:
            schedule = Schedule.objects.get(name=schedule_name)
            assert schedule.next_run > timezone.now()

    def test_applying_twice_does_not_create_a_second_row_per_lane(self):
        from django_q.models import Schedule

        module = migration_module()
        module.create_schedules(django_apps, None)
        module.create_schedules(django_apps, None)

        for schedule_name in EXPECTED_SCHEDULES:
            assert Schedule.objects.filter(name=schedule_name).count() == 1

    def test_migration_declares_itself_reversible(self):
        operations = migration_module().Migration.operations
        assert len(operations) == 1
        assert operations[0].reversible is True

    def test_migration_reverses_and_reapplies_cleanly(self):
        from django_q.models import Schedule

        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        forwards = [("cardpicker", MIGRATION_NAME)]
        backwards = [("cardpicker", "0104_cardquestionabstention")]

        for schedule_name in EXPECTED_SCHEDULES:
            assert Schedule.objects.filter(name=schedule_name).exists()
        try:
            MigrationExecutor(connection).migrate(backwards)
            for schedule_name in EXPECTED_SCHEDULES:
                assert not Schedule.objects.filter(name=schedule_name).exists()

            MigrationExecutor(connection).migrate(forwards)
            for schedule_name in EXPECTED_SCHEDULES:
                assert Schedule.objects.filter(name=schedule_name).exists()
        finally:
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            executor.migrate(forwards)
        for schedule_name in EXPECTED_SCHEDULES:
            assert Schedule.objects.filter(name=schedule_name).exists()

    def test_reverse_deletes_only_these_named_rows(self):
        from django_q.models import Schedule

        Schedule.objects.create(
            name="some_unrelated_schedule",
            func="django.core.management.call_command",
            args="'import_canonical_card_data'",
            schedule_type="W",
        )

        module = migration_module()
        module.delete_schedules(django_apps, None)

        for schedule_name in EXPECTED_SCHEDULES:
            assert not Schedule.objects.filter(name=schedule_name).exists()
        assert Schedule.objects.filter(name="some_unrelated_schedule").exists()

        # Restore so the module-level migration state matches on-disk reality for any later
        # test in this session that assumes the schedules are present.
        module.create_schedules(django_apps, None)
        Schedule.objects.filter(name="some_unrelated_schedule").delete()

    def test_a_custom_cadence_setting_is_honoured_at_apply_time(self):
        """The cadence is a settings-driven knob, not hardcoded - re-running `create_schedules`
        (as the migration's `RunPython` op does) against a different
        `QUESTION_FEED_POOL_WARM_MINUTES_*` value must not be possible to observe as a stuck
        row: this asserts the value read at row-creation time really does come from settings,
        by deleting one row and recreating it under an overridden setting."""
        from django_q.models import Schedule

        Schedule.objects.filter(name="warm_question_feed_pool_confirm").delete()
        with override_settings(QUESTION_FEED_POOL_WARM_MINUTES_CONFIRM=42):
            migration_module().create_schedules(django_apps, None)

        schedule = Schedule.objects.get(name="warm_question_feed_pool_confirm")
        assert schedule.minutes == 42

        # Restore the default-cadence row for any later test in this session.
        Schedule.objects.filter(name="warm_question_feed_pool_confirm").delete()
        migration_module().create_schedules(django_apps, None)


MIGRATION_NAME_0107 = "0107_question_feed_pools_schedule_dedupe"


def dedupe_migration_module() -> ModuleType:
    return importlib.import_module(f"cardpicker.migrations.{MIGRATION_NAME_0107}")


@pytest.mark.django_db
class TestDedupeQuestionFeedPoolsSchedules:
    """Tests for `0107_question_feed_pools_schedule_dedupe.py` - the fix for the duplicate
    django-q2 `Schedule` rows in production (ids 6/7, 8/9, 10/11, 12/13 in the 2026-08-06 deploy
    wave: two concurrent `migrate` runs raced 0105's `get_or_create`). The migration collapses
    each duplicated name back to its earliest row and adds a UNIQUE constraint on `name` so the
    race cannot recur. Same shape as the 0105 tests above: drive the real `MigrationExecutor`
    backwards/forwards."""

    DUPLICATED_NAME = "warm_question_feed_pool_confirm"

    def test_dedupe_collapses_duplicate_rows_keeping_the_earliest(self):
        from django_q.models import Schedule

        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        forwards = [("cardpicker", MIGRATION_NAME_0107)]
        backwards = [("cardpicker", "0105_question_feed_pools_schedule")]

        original = Schedule.objects.get(name=self.DUPLICATED_NAME)
        original_id = original.id
        try:
            # Reverse past 0106: the UNIQUE constraint is dropped, putting the database back in
            # the pre-fix state where a racing `migrate` could insert a second row per name.
            MigrationExecutor(connection).migrate(backwards)
            Schedule.objects.create(
                name=self.DUPLICATED_NAME,
                func="django.core.management.call_command",
                args="'warm_question_feed_pools', 'confirm'",
                schedule_type="I",
                minutes=15,
            )
            assert Schedule.objects.filter(name=self.DUPLICATED_NAME).count() == 2

            MigrationExecutor(connection).migrate(forwards)
            rows = Schedule.objects.filter(name=self.DUPLICATED_NAME).order_by("id")
            assert rows.count() == 1
            assert rows.first().id == original_id  # the earliest row was kept
        finally:
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            executor.migrate(forwards)
        assert Schedule.objects.filter(name=self.DUPLICATED_NAME).count() == 1

    def test_dedupe_leaves_singleton_names_untouched(self):
        from django_q.models import Schedule

        before = {s.name: s.id for s in Schedule.objects.all()}
        dedupe_migration_module().dedupe_schedules(django_apps, None)
        after = {s.name: s.id for s in Schedule.objects.all()}
        assert before == after

    def test_unique_constraint_blocks_a_second_row_for_an_existing_name(self):
        from django_q.models import Schedule

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            Schedule.objects.create(
                name=self.DUPLICATED_NAME,
                func="django.core.management.call_command",
                args="'warm_question_feed_pools', 'confirm'",
                schedule_type="I",
                minutes=15,
            )

    def test_migration_declares_itself_reversible(self):
        operations = dedupe_migration_module().Migration.operations
        assert len(operations) == 2
        assert all(operation.reversible for operation in operations)
