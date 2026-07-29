"""
Tests for the TEST HARNESS itself (2026-07-28) - the ways concurrent agents/CI runs on one box were
corrupting each other's results:

  1. Fixed container host ports (`POSTGRES_PORT` / `ELASTICSEARCH_PORT` in `conftest.py`) made a
     second concurrent suite die at container start with "port is already allocated". Now
     overridable via `TEST_POSTGRES_PORT` / `TEST_ELASTICSEARCH_PORT`.
  2. `stage_e_dispatch._sample_envelope_signals` samples the real `os.getloadavg()`, so every Stage
     E dispatch test was a function of ambient host load - at load 8.67 they fail `halted-new-trip`
     against the ratified `HOST_LOAD_CEILING = 7.0`; at load 3.4 they pass. Now pinned by
     conftest's autouse `deterministic_host_load` fixture.
  3. The same sampler reads this process's real RSS, the envelope's OTHER ambient sensor (one gate,
     two sensors), leaving the same 37 tests a function of the pytest process's own memory against
     the ratified `RSS_MB_PER_WORKER_CEILING = 768.0`. Now pinned by conftest's autouse
     `deterministic_process_rss` fixture (2026-07-29).

These tests exist so that none of these fixes can rot into a no-op silently. A harness fix that has
stopped taking effect is worse than no fix at all: the suite still goes green, and the flakes come
back looking like product bugs.
"""

import os

import pytest

from django.conf import settings as conf_settings

from cardpicker import process_metrics, stage_e_dispatch
from cardpicker.operating_envelope import HOST_LOAD_CEILING, RSS_MB_PER_WORKER_CEILING
from cardpicker.tests.conftest import (
    ELASTICSEARCH_PORT,
    POSTGRES_PORT,
    TEST_HOST_LOAD_AVG,
    TEST_PROCESS_RSS_MB,
)


class TestPortOverrides:
    def test_postgres_port_follows_the_environment(self) -> None:
        assert POSTGRES_PORT == int(os.environ.get("TEST_POSTGRES_PORT", 47000))

    def test_elasticsearch_port_follows_the_environment(self) -> None:
        assert ELASTICSEARCH_PORT == int(os.environ.get("TEST_ELASTICSEARCH_PORT", 9300))

    def test_django_database_settings_point_at_the_overridden_postgres_port(self, db) -> None:
        """The override is worthless if the container moves but Django keeps dialling 47000."""
        assert conf_settings.DATABASES["default"]["PORT"] == POSTGRES_PORT

    def test_elasticsearch_dsl_points_at_the_overridden_elasticsearch_port(self, elasticsearch) -> None:
        assert conf_settings.ELASTICSEARCH_DSL["default"]["hosts"].endswith(f":{ELASTICSEARCH_PORT}")
        assert conf_settings.ELASTICSEARCH_PORT == ELASTICSEARCH_PORT

    def test_elasticsearch_port_is_threaded_into_the_pytest_elasticsearch_plugin(self, request) -> None:
        """
        `elasticsearch_nooproc` reads its port from the plugin's own config (defaulting to a
        hardcoded 9300), not from our constant - `conftest.pytest_configure` bridges the two. No
        test resolves that fixture today; this guards the latent trap for the one that eventually
        does.
        """
        assert request.config.getoption("elasticsearch_port") == str(ELASTICSEARCH_PORT)


class TestDeterministicHostLoad:
    def test_stub_reaches_the_production_sampler(self) -> None:
        """
        The assertion that matters: not "the fixture ran" but "the value the ENVELOPE sees is the
        pinned one". Patching the wrong seam (e.g. a name `stage_e_dispatch` does not actually read
        through) would leave this red.
        """
        assert stage_e_dispatch._sample_envelope_signals().load_avg == TEST_HOST_LOAD_AVG

    def test_pinned_load_is_under_the_ratified_ceiling(self) -> None:
        """`HOST_LOAD_CEILING` is ratified and MUST NOT be moved to accommodate tests - the pinned
        sample is what gives way, and it has to stay strictly under the bar."""
        if "TEST_HOST_LOAD_AVG" in os.environ:
            pytest.skip("TEST_HOST_LOAD_AVG deliberately overridden - this asserts the SHIPPED default")
        assert TEST_HOST_LOAD_AVG < HOST_LOAD_CEILING

    def test_other_envelope_signals_are_still_sampled_for_real(self) -> None:
        """
        Only the two AMBIENT signals (host load, and RSS since 2026-07-29) are pinned. If a future
        change stubs `_sample_envelope_signals` wholesale instead, the fetch-failure-window bar
        silently stops being exercised by the tests that drive it - so assert the rest of the sample
        still comes from the real code path.
        """
        signals = stage_e_dispatch._sample_envelope_signals(google_lockout=True)
        assert signals.google_lockout is True
        # the fetch-failure window is still read from the real module-level window, not flattened
        failures, total = stage_e_dispatch._window.failures_and_total()
        assert (signals.fetch_failures_in_window, signals.fetch_total_in_window) == (failures, total)

    @pytest.mark.real_host_load
    def test_opt_out_marker_restores_real_sampling(self) -> None:
        """
        The escape hatch has to actually work, or a test that genuinely needs the real machine
        would be silently lied to. Compared against /proc/loadavg rather than a second
        `os.getloadavg()` call so that a stub which merely *forwards* to the real function would
        still be distinguishable from no stub at all.
        """
        if not hasattr(os, "getloadavg") or not os.path.exists("/proc/loadavg"):
            pytest.skip("no real host load average available on this platform")
        with open("/proc/loadavg") as f:
            proc_load = float(f.read().split()[0])
        sampled = os.getloadavg()[0]
        assert sampled != TEST_HOST_LOAD_AVG or proc_load == TEST_HOST_LOAD_AVG
        assert abs(sampled - proc_load) < 2.0


def _real_rss_mb_from_proc() -> float:
    """This process's real RSS, read straight from /proc rather than through
    `process_metrics.get_process_rss_mb` - so a stub that merely FORWARDS to the real helper is
    still distinguishable from no stub at all (same reasoning as the /proc/loadavg read above)."""
    with open("/proc/self/status") as status_file:
        for line in status_file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    raise AssertionError("no VmRSS line in /proc/self/status")


class TestDeterministicProcessRss:
    def test_stub_reaches_the_production_sampler(self) -> None:
        """
        The assertion that matters, and the one that catches the seam mistake: not "the fixture ran"
        but "the value the ENVELOPE sees is the pinned one". `stage_e_dispatch` binds
        `get_process_rss_mb` into its own namespace with a `from ... import`, so a fixture that
        patched `process_metrics.get_process_rss_mb` instead would leave this red.
        """
        assert stage_e_dispatch._sample_envelope_signals().rss_mb_per_worker == TEST_PROCESS_RSS_MB

    def test_patching_process_metrics_instead_would_not_bite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The negative half of the seam, asserted directly so the reasoning behind the fixture's
        target survives in executable form: rebinding the name on `process_metrics` does NOT change
        what the envelope samples, because `stage_e_dispatch` resolved that name once at import.
        """
        monkeypatch.setattr(process_metrics, "get_process_rss_mb", lambda: 999_999.0)
        assert stage_e_dispatch._sample_envelope_signals().rss_mb_per_worker == TEST_PROCESS_RSS_MB

    def test_pinned_rss_is_under_the_ratified_ceiling(self) -> None:
        """`RSS_MB_PER_WORKER_CEILING` is ratified and MUST NOT be moved to accommodate tests - the
        pinned sample is what gives way, and it has to stay strictly under the bar."""
        if "TEST_PROCESS_RSS_MB" in os.environ:
            pytest.skip("TEST_PROCESS_RSS_MB deliberately overridden - this asserts the SHIPPED default")
        assert TEST_PROCESS_RSS_MB < RSS_MB_PER_WORKER_CEILING

    def test_the_ledgers_peak_rss_consumer_is_pinned_by_the_same_name(self) -> None:
        """`stage_e_dispatch` reads the helper twice - the envelope sample and the ledger's
        `peak_rss_mb` counter. Both go through the one module-local name, so pinning it covers both;
        this asserts that rather than leaving it as a comment."""
        assert stage_e_dispatch.get_process_rss_mb() == TEST_PROCESS_RSS_MB

    @pytest.mark.real_process_rss
    def test_opt_out_marker_restores_real_sampling(self) -> None:
        """The escape hatch has to actually work, or a test that genuinely needs this process's real
        memory would be silently lied to."""
        if not os.path.exists("/proc/self/status"):
            pytest.skip("no /proc/self/status on this platform")
        sampled = stage_e_dispatch._sample_envelope_signals().rss_mb_per_worker
        assert sampled is not None
        assert sampled != TEST_PROCESS_RSS_MB
        assert abs(sampled - _real_rss_mb_from_proc()) < 32.0

    def test_process_metrics_own_tests_still_sample_real_rss(self) -> None:
        """
        The primitive itself must stay honestly tested. `test_process_metrics.py` imports
        `get_process_rss_mb` from `process_metrics` directly and never reaches `stage_e_dispatch`,
        so the pin cannot reach it and no opt-out marker is needed there - assert that the
        `process_metrics` path really is untouched, with the fixture active, so nobody "helpfully"
        widens the patch to the shared module later.
        """
        assert process_metrics.get_process_rss_mb() != TEST_PROCESS_RSS_MB
        assert abs(process_metrics.get_process_rss_mb() - _real_rss_mb_from_proc()) < 32.0
