"""
Tests for cardpicker.catalog_stats (Proposal F's public stats aggregate, pass 1 - see that
module's own docstring) and cardpicker.views.get_catalog_stats.

Cache setup mirrors cardpicker.tests.test_artist_external_links.py exactly: this feature reads/
writes the NAMED `"shared"` cache alias, never Django's `default` - `_shared_cache_configured`
(autouse) provisions a real `"shared"` LocMemCache alias for every test in this file by default;
`TestSharedCacheNotConfigured` overrides this per-test to cover the pre-#538/#543 state.
"""

import datetime as dt
from unittest.mock import patch

import pytest

from django.core.cache import caches
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from cardpicker.catalog_stats import (
    CACHE_KEY,
    HUMAN_SOURCES,
    SHARED_CACHE_ALIAS,
    compute_catalog_composition,
    compute_catalog_stats,
    compute_contributions_over_time,
    compute_participation,
    compute_run_history,
    compute_skip_breakdown,
    get_cached_catalog_stats,
    warm_catalog_stats_cache,
    zeroed_catalog_stats,
)
from cardpicker.models import CardScanLog, CardTypes, PilotRunLedger, VoteSource
from cardpicker.schema_types import CatalogStatsResponse
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    SourceFactory,
    TagFactory,
)

_TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "shared": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-catalog-stats-shared",
    },
}


@pytest.fixture(autouse=True)
def _shared_cache_configured():
    with override_settings(CACHES=_TEST_CACHES):
        caches["default"].clear()
        caches[SHARED_CACHE_ALIAS].clear()
        yield
        caches["default"].clear()
        caches[SHARED_CACHE_ALIAS].clear()


def _set_created_at(instance, when: dt.datetime) -> None:
    """`created_at`/`started_at` are `auto_now_add=True` - any value passed at construction time
    is silently overwritten. This bypasses that via a direct `.update()`, then refreshes the
    in-memory instance so callers see the value they asked for."""
    type(instance).objects.filter(pk=instance.pk).update(created_at=when)
    instance.refresh_from_db()


def _create_run(
    run_id: str,
    command: str = "local_identify_printing_tags",
    status: str = PilotRunLedger.Status.COMPLETED,
    started_at: dt.datetime = None,
    finished_at: dt.datetime = None,
    votes_written=None,
) -> PilotRunLedger:
    run = PilotRunLedger.objects.create(run_id=run_id, command=command, status=status, votes_written=votes_written)
    if finished_at is not None:
        run.finished_at = finished_at
        run.save(update_fields=["finished_at"])
    if started_at is not None:
        PilotRunLedger.objects.filter(pk=run.pk).update(started_at=started_at)
    run.refresh_from_db()
    return run


@pytest.fixture
def source(db):
    return SourceFactory()


@pytest.fixture
def canonical_printing(db):
    return CanonicalCardFactory()


class TestComputeContributionsOverTime:
    def test_human_user_vote_with_surface_is_counted(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(
            card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface="question-feed"
        )
        _set_created_at(vote, timezone.now())

        result = compute_contributions_over_time()
        assert sum(week["bySurface"].get("question-feed", 0) for week in result["series"]) == 1

    def test_admin_and_federated_are_also_human(self, db, source, canonical_printing):
        card1 = CardFactory(source=source)
        card2 = CardFactory(source=source)
        v1 = CardPrintingTagFactory(
            card=card1, printing=canonical_printing, source=VoteSource.ADMIN, vote_surface="moderation"
        )
        v2 = CardPrintingTagFactory(
            card=card2, printing=canonical_printing, source=VoteSource.FEDERATED, vote_surface="moderation"
        )
        _set_created_at(v1, timezone.now())
        _set_created_at(v2, timezone.now())

        result = compute_contributions_over_time()
        assert sum(week["bySurface"].get("moderation", 0) for week in result["series"]) == 2

    def test_implicit_vote_is_excluded_even_though_it_sets_vote_surface(self, db, source, canonical_printing):
        # VoteSource.IMPLICIT DOES write vote_surface (views.IMPLICIT_VOTE_SURFACE) but is
        # machine-derived under this module's own HUMAN_SOURCES split - see
        # compute_contributions_over_time's own docstring for why this matters.
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(
            card=card, printing=canonical_printing, source=VoteSource.IMPLICIT, vote_surface="display-editor-filter"
        )
        _set_created_at(vote, timezone.now())

        result = compute_contributions_over_time()
        total = sum(sum(week["bySurface"].values()) for week in result["series"])
        assert total == 0

    def test_machine_vote_without_surface_is_excluded(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(card=card, printing=canonical_printing, source=VoteSource.OCR, vote_surface=None)
        _set_created_at(vote, timezone.now())

        result = compute_contributions_over_time()
        total = sum(sum(week["bySurface"].values()) for week in result["series"])
        assert total == 0

    def test_null_vote_surface_is_excluded(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface=None)
        _set_created_at(vote, timezone.now())

        result = compute_contributions_over_time()
        total = sum(sum(week["bySurface"].values()) for week in result["series"])
        assert total == 0

    def test_blank_vote_surface_is_excluded(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface="")
        _set_created_at(vote, timezone.now())

        result = compute_contributions_over_time()
        total = sum(sum(week["bySurface"].values()) for week in result["series"])
        assert total == 0

    def test_vote_outside_lookback_window_is_excluded(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        vote = CardPrintingTagFactory(
            card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface="question-feed"
        )
        _set_created_at(vote, timezone.now() - dt.timedelta(weeks=52))

        result = compute_contributions_over_time(weeks=12)
        total = sum(sum(week["bySurface"].values()) for week in result["series"])
        assert total == 0

    def test_aggregates_across_all_three_vote_tables(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        tag = TagFactory()
        artist = CanonicalArtistFactory()
        v1 = CardPrintingTagFactory(
            card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface="question-feed"
        )
        v2 = CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER, vote_surface="question-feed")
        v3 = CardTagVoteFactory(card=card, tag=tag, source=VoteSource.USER, vote_surface="question-feed")
        for v in (v1, v2, v3):
            _set_created_at(v, timezone.now())

        result = compute_contributions_over_time()
        assert sum(week["bySurface"].get("question-feed", 0) for week in result["series"]) == 3

    def test_bucket_days_is_seven(self, db):
        assert compute_contributions_over_time()["bucketDays"] == 7


class TestComputeSkipBreakdown:
    def test_groups_by_reason(self, db, source):
        card1 = CardFactory(source=source)
        card2 = CardFactory(source=source)
        CardScanLog.objects.create(card=card1, anonymous_id="local-ocr-v1", skip_reason="no-clear-winner")
        CardScanLog.objects.create(card=card2, anonymous_id="local-ocr-v1", skip_reason="no-clear-winner")

        result = compute_skip_breakdown()
        assert {"reason": "no-clear-winner", "count": 2} in result["byReason"]

    def test_distinct_reasons_are_separate_rows(self, db, source):
        card1 = CardFactory(source=source)
        card2 = CardFactory(source=source)
        CardScanLog.objects.create(card=card1, anonymous_id="local-ocr-v1", skip_reason="no-clear-winner")
        CardScanLog.objects.create(card=card2, anonymous_id="local-ocr-v1", skip_reason="ambiguous")

        result = compute_skip_breakdown()
        reasons = {row["reason"] for row in result["byReason"]}
        assert reasons == {"no-clear-winner", "ambiguous"}

    def test_groups_by_reason_and_engine(self, db, source):
        card1 = CardFactory(source=source)
        card2 = CardFactory(source=source)
        CardScanLog.objects.create(card=card1, anonymous_id="local-ocr-v1", skip_reason="no-text")
        CardScanLog.objects.create(card=card2, anonymous_id="local-phash-v1", skip_reason="no-text")

        result = compute_skip_breakdown()
        by_engine = {(row["reason"], row["engine"]): row["count"] for row in result["byReasonAndEngine"]}
        assert by_engine[("no-text", "local-ocr-v1")] == 1
        assert by_engine[("no-text", "local-phash-v1")] == 1

    def test_empty_table_returns_empty_lists(self, db):
        result = compute_skip_breakdown()
        assert result == {"byReason": [], "byReasonAndEngine": []}


class TestComputeRunHistory:
    def test_most_recent_first(self, db):
        _create_run("run-1", started_at=timezone.now() - dt.timedelta(days=2))
        _create_run("run-2", started_at=timezone.now() - dt.timedelta(days=1))

        result = compute_run_history()
        run_ids = [row["runId"] for row in result["recent"]]
        assert run_ids.index("run-2") < run_ids.index("run-1")

    def test_duration_computed_when_finished(self, db):
        start = timezone.now() - dt.timedelta(hours=1)
        end = start + dt.timedelta(minutes=30)
        _create_run("run-3", started_at=start, finished_at=end)

        result = compute_run_history()
        row = next(r for r in result["recent"] if r["runId"] == "run-3")
        assert row["durationSeconds"] == pytest.approx(1800.0)

    def test_duration_is_none_while_running(self, db):
        _create_run("run-4", status=PilotRunLedger.Status.RUNNING, started_at=timezone.now(), finished_at=None)

        result = compute_run_history()
        row = next(r for r in result["recent"] if r["runId"] == "run-4")
        assert row["durationSeconds"] is None
        assert row["finishedAt"] is None

    def test_votes_written_passes_through_including_none(self, db):
        _create_run("run-5", started_at=timezone.now(), votes_written=42)
        _create_run("run-6", started_at=timezone.now(), votes_written=None)

        result = compute_run_history()
        by_id = {r["runId"]: r["votesWritten"] for r in result["recent"]}
        assert by_id["run-5"] == 42
        assert by_id["run-6"] is None

    def test_limit_is_respected(self, db):
        for i in range(5):
            _create_run(f"run-limit-{i}", started_at=timezone.now() - dt.timedelta(minutes=i))

        result = compute_run_history(limit=2)
        assert len(result["recent"]) == 2

    def test_empty_table_returns_empty_list(self, db):
        assert compute_run_history() == {"recent": []}


class TestComputeCatalogComposition:
    def test_matches_summarise_contributions(self, db, source):
        CardFactory(source=source)
        CardFactory(source=source)

        result = compute_catalog_composition()
        assert result["cardCountByType"][CardTypes.CARD] == 2
        assert len(result["sources"]) == 1
        assert result["sources"][0]["name"] == source.name
        # sourceType must serialise to a plain string (mode="json"), not an Enum instance whose
        # class identity could drift across a deploy.
        assert isinstance(result["sources"][0]["sourceType"], str)

    def test_empty_database(self, db):
        result = compute_catalog_composition()
        assert result["sources"] == []
        assert result["totalDatabaseSize"] == 0


class TestComputeParticipation:
    def test_human_vote_counts_only_include_human_sources(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTagFactory(card=card, printing=canonical_printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=CardFactory(source=source), printing=canonical_printing, source=VoteSource.OCR)
        CardPrintingTagFactory(card=CardFactory(source=source), printing=canonical_printing, source=VoteSource.IMPLICIT)

        result = compute_participation()
        assert result["humanVotes"]["printingTag"] == 1
        assert result["humanVotes"]["total"] == 1

    def test_human_sources_constant_is_user_admin_federated(self):
        assert set(HUMAN_SOURCES) == {VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED}

    def test_distinct_human_voters_deduplicated_across_tables(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        tag = TagFactory()
        CardPrintingTagFactory(card=card, printing=canonical_printing, source=VoteSource.USER, anonymous_id="voter-a")
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.USER, anonymous_id="voter-a")
        CardPrintingTagFactory(
            card=CardFactory(source=source),
            printing=canonical_printing,
            source=VoteSource.USER,
            anonymous_id="voter-b",
        )

        result = compute_participation()
        assert result["distinctHumanVoters"] == 2

    def test_md5_groups_with_multiple_cards_are_counted(self, db, source):
        CardFactory(source=source, md5_checksum="abc123")
        CardFactory(source=source, md5_checksum="abc123")
        CardFactory(source=source, md5_checksum="abc123")
        CardFactory(source=source, md5_checksum="def456")  # group of one - excluded

        result = compute_participation()
        assert result["md5Groups"]["groupsWithMultipleCards"] == 1
        assert result["md5Groups"]["cardsInMultiCardGroups"] == 3
        assert result["md5Groups"]["largestGroupSize"] == 3

    def test_null_and_blank_md5_checksums_are_never_grouped(self, db, source):
        CardFactory(source=source, md5_checksum=None)
        CardFactory(source=source, md5_checksum=None)
        CardFactory(source=source, md5_checksum="")
        CardFactory(source=source, md5_checksum="")

        result = compute_participation()
        assert result["md5Groups"]["groupsWithMultipleCards"] == 0
        assert result["md5Groups"]["largestGroupSize"] == 0

    def test_empty_database_has_zero_md5_groups(self, db):
        result = compute_participation()
        assert result["md5Groups"] == {
            "groupsWithMultipleCards": 0,
            "cardsInMultiCardGroups": 0,
            "largestGroupSize": 0,
        }

    def test_no_percent_complete_field_is_emitted(self, db):
        result = compute_participation()
        assert "percentComplete" not in result
        assert "percent" not in result


class TestZeroedCatalogStats:
    def test_shape_matches_catalog_stats_response_schema(self):
        # Constructed with **kwargs (the same call shape views.get_catalog_stats actually uses) -
        # proves the zeroed skeleton is a valid CatalogStatsResponse, not merely "looks right".
        response = CatalogStatsResponse(**zeroed_catalog_stats())
        assert response.generatedAt is None
        assert response.contributionsOverTime.series == []
        assert response.participation.humanVotes.total == 0

    def test_generated_at_is_none(self):
        assert zeroed_catalog_stats()["generatedAt"] is None


class TestComputeCatalogStats:
    def test_all_five_panels_present(self, db):
        result = compute_catalog_stats()
        assert set(result.keys()) == {
            "generatedAt",
            "contributionsOverTime",
            "skipBreakdown",
            "runHistory",
            "catalogComposition",
            "participation",
        }
        assert result["generatedAt"] is not None

    def test_round_trips_through_catalog_stats_response(self, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTagFactory(
            card=card, printing=canonical_printing, source=VoteSource.USER, vote_surface="question-feed"
        )
        blob = compute_catalog_stats()
        response = CatalogStatsResponse(**blob)
        assert response.model_dump()["participation"]["humanVotes"]["total"] == 1


class TestGetCachedCatalogStats:
    def test_returns_zeroed_when_cache_is_entirely_empty(self):
        assert get_cached_catalog_stats() == zeroed_catalog_stats()

    def test_returns_cached_blob_on_hit(self, db):
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, compute_catalog_stats())
        result = get_cached_catalog_stats()
        assert result["generatedAt"] is not None


_CACHES_WITHOUT_SHARED = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class TestSharedCacheNotConfigured:
    """Covers the pre-#538/#543 state - mirrors test_artist_external_links.py's own class of the
    same name exactly."""

    def test_read_path_returns_zeroed_without_raising(self):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            assert get_cached_catalog_stats() == zeroed_catalog_stats()

    def test_endpoint_returns_zeroed_shape_not_a_500(self, client, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            response = client.get(reverse("get_catalog_stats"))
        assert response.status_code == 200
        assert response.json()["generatedAt"] is None

    def test_warm_function_raises_a_clear_runtime_error_before_computing_anything(self, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with patch("cardpicker.catalog_stats.compute_catalog_stats") as mock_compute:
                with pytest.raises(RuntimeError, match="shared.*not configured"):
                    warm_catalog_stats_cache()
                mock_compute.assert_not_called()

    def test_warm_command_exits_non_zero_with_a_comprehensible_message(self, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with pytest.raises(CommandError, match="shared.*not configured"):
                call_command("warm_catalog_stats")


class TestWarmCatalogStatsCache:
    def test_writes_blob_to_shared_cache(self, db):
        warm_catalog_stats_cache()
        cached = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert cached is not None
        assert cached["generatedAt"] is not None

    def test_idempotent_on_repeat_runs(self, db):
        first = warm_catalog_stats_cache()
        second = warm_catalog_stats_cache()
        # generatedAt legitimately differs between two real runs - compare everything else.
        first_without_timestamp = {k: v for k, v in first.items() if k != "generatedAt"}
        second_without_timestamp = {k: v for k, v in second.items() if k != "generatedAt"}
        assert first_without_timestamp == second_without_timestamp

    def test_failure_leaves_prior_cache_untouched(self, db):
        warm_catalog_stats_cache()
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

        with patch("cardpicker.catalog_stats.compute_catalog_stats", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                warm_catalog_stats_cache()

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache


class TestWarmCatalogStatsCommand:
    def test_success_prints_a_summary(self, db, capsys):
        call_command("warm_catalog_stats")
        output = capsys.readouterr().out
        assert "Catalog-stats cache warmed" in output

    def test_failure_exits_non_zero_and_leaves_cache_untouched(self, db):
        call_command("warm_catalog_stats")
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

        with patch("cardpicker.catalog_stats.compute_catalog_stats", side_effect=RuntimeError("boom")):
            with pytest.raises(CommandError):
                call_command("warm_catalog_stats")

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache

    def test_re_running_after_success_is_safe(self, db):
        call_command("warm_catalog_stats")
        call_command("warm_catalog_stats")
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) is not None


class TestGetCatalogStatsView:
    def test_cache_hit_returns_the_blob(self, client, db):
        blob = compute_catalog_stats()
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, blob)

        response = client.get(reverse("get_catalog_stats"))

        assert response.status_code == 200
        assert response.json()["generatedAt"] == blob["generatedAt"]

    def test_cache_miss_returns_zeroed_skeleton_and_makes_no_aggregate_query(self, client, db):
        """The core guarantee (Proposal F: "zero live aggregate queries from public traffic") -
        patching compute_catalog_stats to explode if called proves the endpoint never reaches it
        on a cache miss, not merely that the response happens to look right."""
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) is None

        with patch("cardpicker.catalog_stats.compute_catalog_stats") as mock_compute:
            response = client.get(reverse("get_catalog_stats"))
            mock_compute.assert_not_called()

        assert response.status_code == 200
        assert response.json() == zeroed_catalog_stats()

    def test_post_is_rejected(self, client, db):
        response = client.post(reverse("get_catalog_stats"))
        assert response.status_code == 400

    def test_anonymous_access_works(self, client, db):
        response = client.get(reverse("get_catalog_stats"))
        assert response.status_code == 200


class TestMigration0094:
    MIGRATION_NAME = "0094_warm_catalog_stats_hourly_schedule"

    def _module(self):
        import importlib

        return importlib.import_module(f"cardpicker.migrations.{self.MIGRATION_NAME}")

    def test_schedule_row_created(self, db):
        from django_q.models import Schedule

        assert Schedule.objects.filter(name="warm_catalog_stats").exists()

    def test_schedule_is_hourly(self, db):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name="warm_catalog_stats")
        assert schedule.schedule_type == Schedule.HOURLY

    def test_schedule_invokes_the_warm_command(self, db):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name="warm_catalog_stats")
        assert schedule.func == "django.core.management.call_command"
        assert schedule.args == "'warm_catalog_stats'"

    def test_create_schedule_is_idempotent(self, db):
        from django_q.models import Schedule

        from django.apps import apps as global_apps

        module = self._module()
        module.create_schedule(global_apps, None)
        module.create_schedule(global_apps, None)
        assert Schedule.objects.filter(name="warm_catalog_stats").count() == 1

    def test_migration_declares_itself_reversible(self):
        module = self._module()
        operations = module.Migration.operations
        assert len(operations) == 1
        assert operations[0].reversible is True

    def test_migration_reverses_and_reapplies_cleanly(self, db):
        from django_q.models import Schedule

        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        forwards = [("cardpicker", self.MIGRATION_NAME)]
        backwards = [("cardpicker", "0093_warm_artist_external_links_weekly_schedule")]

        assert Schedule.objects.filter(name="warm_catalog_stats").exists()
        try:
            MigrationExecutor(connection).migrate(backwards)
            assert not Schedule.objects.filter(name="warm_catalog_stats").exists()

            MigrationExecutor(connection).migrate(forwards)
            assert Schedule.objects.filter(name="warm_catalog_stats").exists()
        finally:
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            executor.migrate(forwards)
