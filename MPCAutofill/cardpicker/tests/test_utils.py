import pytest

from cardpicker.search.sanitisation import to_searchable
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class TestUtils:
    # region tests

    @pytest.mark.parametrize(
        "input_string, output",
        [
            ("Lightning Bolt", "lightning bolt"),
            (" Lightning   BOLT ", "lightning bolt"),
            ("Lightning\t\xa0BOLT", "lightning bolt"),
            ("Adanto, the First Fort", "adanto the first fort"),
            # brackets removal
            ("Black Lotus (Masterpiece)", "black lotus"),
            ("Black Lotus (Masterpiece, But With Punctuation! )", "black lotus"),
            ("Juzám Djinn", "juzám djinn"),  # elasticsearch will handle this
            (" Expansion _ Explosion", "expansion explosion"),
            ("Kodama’s Reach", "kodamas reach"),
            ("消灭邪物", "消灭邪物"),
        ],
        ids=[
            "basic case 1",
            "basic case 2",
            "extreme whitespaces",
            "punctuation",
            "brackets removal 1",
            "brackets removal 2",
            "accents",
            "punctuation with double spaces",
            "right apostrophes are handled correctly",
            "foreign language characters",
        ],
    )
    def test_to_searchable(self, input_string, output) -> None:
        assert to_searchable(input_string) == output

    # endregion


class TestGetBakedGitSha:
    """docs/features/catalog-completion-plan.md's Part 1 - best-effort visibility, never the
    hard gate (see TestFindStaleAppliedMigrations for that)."""

    def test_returns_the_file_contents_when_present(self, tmp_path, settings):
        (tmp_path / "GIT_SHA").write_text("abc1234\n")
        settings.BASE_DIR = str(tmp_path)

        assert get_baked_git_sha() == "abc1234"

    def test_returns_none_when_the_file_is_absent(self, tmp_path, settings):
        settings.BASE_DIR = str(tmp_path)

        assert get_baked_git_sha() is None

    def test_returns_none_for_an_empty_file(self, tmp_path, settings):
        (tmp_path / "GIT_SHA").write_text("")
        settings.BASE_DIR = str(tmp_path)

        assert get_baked_git_sha() is None


class TestFindStaleAppliedMigrations:
    """docs/features/catalog-completion-plan.md's Part 1 - the actual hard gate a stale image
    (a rebuild that silently shipped old code underneath a "Successfully built" log line, the
    PR #24/#26 lesson) gets refused on. Pure DB+code introspection, independent of the git-SHA
    file above."""

    def test_empty_when_the_db_and_this_image_agree(self, db):
        assert find_stale_applied_migrations() == []

    def test_finds_a_migration_the_db_has_that_this_image_does_not(self, db, monkeypatch):
        from django.db.migrations.recorder import MigrationRecorder

        real_applied = MigrationRecorder.applied_migrations

        def fake_applied_migrations(self):
            result = dict(real_applied(self))
            result[("cardpicker", "9999_fake_future_migration")] = object()
            return result

        monkeypatch.setattr(MigrationRecorder, "applied_migrations", fake_applied_migrations)

        stale = find_stale_applied_migrations()

        assert ("cardpicker", "9999_fake_future_migration") in stale


class TestLoggingConfig:
    """2026-07-17 addendum: closes a real gap found diagnosing a live incident (see
    docs/troubleshooting.md). Every view already routes unhandled exceptions through
    ErrorWrappers.to_json's own logger.exception() call, which was already visible via Python's
    logging.lastResort fallback - verified directly, not assumed, before writing this fix.
    What this LOGGING config actually adds console visibility for: anything that reaches
    Django's own exception-to-response machinery WITHOUT going through a view's to_json wrapper
    at all - the django.request logger, which Django's own DEFAULT_LOGGING wires to
    mail_admins only when DEBUG=False."""

    def test_django_request_logger_has_a_console_handler(self):
        import logging

        from django.conf import settings

        logger = logging.getLogger("django.request")
        handler_classes = {type(h).__name__ for h in logger.handlers}
        assert "StreamHandler" in handler_classes
        # mail_admins stays wired too - this is additive, not a replacement.
        assert "AdminEmailHandler" in handler_classes
        assert settings.LOGGING["loggers"]["django.request"]["level"] == "ERROR"

    def test_an_error_on_django_request_actually_reaches_the_console_handler(self, caplog):
        import logging

        logger = logging.getLogger("django.request")
        with caplog.at_level(logging.ERROR, logger="django.request"):
            try:
                raise ValueError("simulated exception escaping a view entirely")
            except ValueError:
                logger.exception("test unhandled exception")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "ERROR"
        assert record.name == "django.request"
        assert record.exc_info is not None
