"""
Tests for the TEST HARNESS itself (2026-07-28) - the two ways concurrent agents/CI runs on one box
were corrupting each other's results:

  1. Fixed container host ports (`POSTGRES_PORT` / `ELASTICSEARCH_PORT` in `conftest.py`) made a
     second concurrent suite die at container start with "port is already allocated". Now
     overridable via `TEST_POSTGRES_PORT` / `TEST_ELASTICSEARCH_PORT`.
  2. `stage_e_dispatch._sample_envelope_signals` samples the real `os.getloadavg()`, so every Stage
     E dispatch test was a function of ambient host load - at load 8.67 they fail `halted-new-trip`
     against the ratified `HOST_LOAD_CEILING = 7.0`; at load 3.4 they pass. Now pinned by
     conftest's autouse `deterministic_host_load` fixture.

These tests exist so that neither fix can rot into a no-op silently. A harness fix that has stopped
taking effect is worse than no fix at all: the suite still goes green, and the flakes come back
looking like product bugs.
"""

import os

import pytest

from django.conf import settings as conf_settings

from cardpicker import stage_e_dispatch
from cardpicker.operating_envelope import HOST_LOAD_CEILING
from cardpicker.tests.conftest import (
    ELASTICSEARCH_PORT,
    POSTGRES_PORT,
    TEST_HOST_LOAD_AVG,
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
        Only the ambient host load is pinned. If a future change stubs `_sample_envelope_signals`
        wholesale instead, the fetch-failure-window bar silently stops being exercised by the tests
        that drive it - so assert the rest of the sample still comes from the real code path.
        """
        signals = stage_e_dispatch._sample_envelope_signals(google_lockout=True)
        assert signals.google_lockout is True
        # sampled from /proc by `process_metrics.get_process_rss_mb`, not a constant
        assert signals.rss_mb_per_worker is None or signals.rss_mb_per_worker > 0

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
