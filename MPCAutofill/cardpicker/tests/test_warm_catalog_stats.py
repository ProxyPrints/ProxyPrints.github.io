"""
Tests for `warm_catalog_stats` management command sweep gate behaviour after the
2026-08-03 retirement (gate OFF by default, opt-in via settings flag). Covers the four
scenarios the retirement PR requires plus one default-behaviour guard.

Mirrors the existing `TestWarmCatalogStatsSweepGate` class in `test_catalog_stats.py`
and the migration-test style of `test_warm_artist_external_links_schedule.py`.
"""

import datetime as dt
from unittest.mock import patch

import pytest

from django.core.cache import caches
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

from cardpicker.catalog_stats import CACHE_KEY, SHARED_CACHE_ALIAS
from cardpicker.models import PilotRunLedger

_TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "shared": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-warm-catalog-stats-shared",
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


@pytest.mark.django_db
class TestWarmCatalogStatsDefaultBehaviour:
    """Default behaviour: gate OFF (2026-08-03 retirement)."""

    def test_running_sweep_does_not_block_when_gate_is_off_by_default(self, capsys):
        """A RUNNING PilotRunLedger within the stale bound does NOT block — all
        five panels computed, generatedAt bumped, cache written. This is the core
        fix for the bug that froze the stats page indefinitely under the streaming
        sweep's perpetually-RUNNING ledger row."""
        _create_run(
            run_id="perpetual-streaming-sweep",
            command="stage_e_streaming_dispatch",
            status=PilotRunLedger.Status.RUNNING,
        )

        call_command("warm_catalog_stats")
        output = capsys.readouterr().out

        assert "Sweep gate: disabled (default)" in output
        assert "Catalog-stats cache warmed" in output

        cached = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert cached is not None
        assert cached["generatedAt"] is not None

    def test_no_sweep_running_computes_normally_by_default(self, capsys):
        """Absent any RUNNING row at all, default behaviour is the standard full
        compute — this is the same path as when a sweep is running, but worth
        guarding explicitly so a future gate change cannot silently break the
        no-sweep path."""
        call_command("warm_catalog_stats")
        output = capsys.readouterr().out

        assert "Sweep gate: disabled (default)" in output
        assert "Catalog-stats cache warmed" in output

        cached = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert cached is not None
        assert cached["generatedAt"] is not None


@pytest.mark.django_db
class TestWarmCatalogStatsGateOptIn:
    """Opt-in gate behaviour (gate ON — the explicit override restores the
    2026-07-29 skip semantics for emergency conservatism)."""

    def test_running_sweep_within_bound_skips_when_gate_enabled(self, capsys):
        """Opt-in: a RUNNING row within the staleness bound blocks the run,
        cache untouched, exit 0 — exact 2026-07-29 behaviour preserved."""
        call_command("warm_catalog_stats")
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert good_cache is not None

        _create_run(
            run_id="opt-in-blocking-sweep",
            command="local_identify_printing_tags",
            status=PilotRunLedger.Status.RUNNING,
        )

        with override_settings(WARM_CATALOG_STATS_SWEEP_GATE_ENABLED=True):
            call_command("warm_catalog_stats")
        output = capsys.readouterr().out

        assert "opt-in-blocking-sweep" in output
        assert "skip" in output.lower()
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache

    def test_stale_sweep_does_not_block_when_gate_enabled(self):
        """Opt-in staleness guard preserved: a RUNNING row older than the
        staleness bound is ignored and the warm computes normally. This is the
        crashed-sweep guard that prevents a RUNNING row left behind by a crash
        from freezing the page permanently."""
        from django.conf import settings

        stale_started_at = timezone.now() - dt.timedelta(hours=settings.WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS + 1)
        _create_run(
            run_id="crashed-sweep-nobody-finished",
            command="local_identify_printing_tags",
            status=PilotRunLedger.Status.RUNNING,
            started_at=stale_started_at,
        )

        with override_settings(WARM_CATALOG_STATS_SWEEP_GATE_ENABLED=True):
            call_command("warm_catalog_stats")

        cached = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert cached is not None
        assert cached["generatedAt"] is not None


@pytest.mark.django_db
class TestWarmCatalogStatsFailureSemantics:
    """Failure semantics independent of gate state."""

    def test_computation_failure_leaves_cache_untouched_and_raises_command_error(self):
        """If compute_catalog_stats raises, the previous cache blob survives
        byte-for-byte and the command exits with CommandError — same contract
        regardless of gate state."""
        call_command("warm_catalog_stats")
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert good_cache is not None

        with patch(
            "cardpicker.catalog_stats.compute_catalog_stats",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(CommandError, match="left untouched"):
                call_command("warm_catalog_stats")

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache
