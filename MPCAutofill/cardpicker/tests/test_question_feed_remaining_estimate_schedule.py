"""
Tests for the single django-q2 `Schedule` row `0115_question_feed_remaining_estimate_schedule.py`
creates - mirrors `test_question_feed_pools_schedule.py`'s own shape exactly (import the migration
module directly via `importlib` since its name starts with a digit, drive the real
`MigrationExecutor` backwards/forwards).
"""

import importlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import ModuleType
from unittest.mock import patch

import pytest

from django.apps import apps as django_apps
from django.test import override_settings

MIGRATION_NAME = "0115_question_feed_remaining_estimate_schedule"
SCHEDULE_NAME = "warm_question_feed_remaining_estimate"


def migration_module() -> ModuleType:
    return importlib.import_module(f"cardpicker.migrations.{MIGRATION_NAME}")


@pytest.mark.django_db
class TestQuestionFeedRemainingEstimateScheduleMigration:
    def test_migration_created_exactly_one_row(self):
        from django_q.models import Schedule

        assert Schedule.objects.filter(name=SCHEDULE_NAME).count() == 1

    def test_schedule_is_minutes_type_with_the_settings_cadence(self):
        from django_q.models import Schedule

        from django.conf import settings

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.schedule_type == "I"
        assert schedule.minutes == settings.QUESTION_FEED_REMAINING_ESTIMATE_WARM_MINUTES

    def test_schedule_calls_the_management_command(self):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.func == "django.core.management.call_command"
        assert schedule.args == f"'{SCHEDULE_NAME}'"

    def test_next_run_is_set_to_apply_time_plus_the_cadence(self):
        from django_q.models import Schedule

        frozen_now = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)
        module = migration_module()

        Schedule.objects.filter(name=SCHEDULE_NAME).delete()
        with patch.object(module.timezone, "now", return_value=frozen_now):
            module.create_schedule(django_apps, None)

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.next_run == frozen_now + timedelta(minutes=schedule.minutes)

        # Restore the real-time row for any later test in this session.
        Schedule.objects.filter(name=SCHEDULE_NAME).delete()
        module.create_schedule(django_apps, None)

    def test_applying_twice_does_not_create_a_second_row(self):
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
        from django_q.models import Schedule

        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        forwards = [("cardpicker", MIGRATION_NAME)]
        backwards = [("cardpicker", "0114_canonicalprintingmetadata_color_identity_type_line")]

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

    def test_a_custom_cadence_setting_is_honoured_at_apply_time(self):
        from django_q.models import Schedule

        Schedule.objects.filter(name=SCHEDULE_NAME).delete()
        with override_settings(QUESTION_FEED_REMAINING_ESTIMATE_WARM_MINUTES=7):
            migration_module().create_schedule(django_apps, None)

        schedule = Schedule.objects.get(name=SCHEDULE_NAME)
        assert schedule.minutes == 7

        # Restore the default-cadence row for any later test in this session.
        Schedule.objects.filter(name=SCHEDULE_NAME).delete()
        migration_module().create_schedule(django_apps, None)
