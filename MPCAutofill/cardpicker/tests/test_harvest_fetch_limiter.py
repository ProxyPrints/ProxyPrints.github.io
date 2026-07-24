"""
Stage B split fetch limiter tests (docs/features/catalog-completion-plan.md, "Harvest-calculate
pipeline" section). No network - each destination's shared `requests.Session.get` is monkeypatched
per-test (via `get_limiter(config).session`), matching `rate_limited_get`'s own call site (one
Session per destination limiter, reused across calls - 2026-07-24 IO audit finding 2) rather than
reaching into `image_cdn_fetch`/`local_phash`'s call sites.
"""

import threading
import time
from typing import Any

import pytest
import requests

from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    SCRYFALL_CDN,
    SCRYFALL_REST,
    DestinationLimiterConfig,
    GoogleFetchLockoutError,
    get_limiter,
    rate_limited_get,
    reset_limiters,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _reset_limiter_registry():
    # The registry is process-wide/module-level by design (see harvest_fetch_limiter.py's own
    # docstring on why - one shared ceiling across every caller's thread pool) - tests must not
    # leak pacing/lockout/backoff state into each other via that same registry.
    reset_limiters()
    yield
    reset_limiters()


class TestDestinationLimiterPacing:
    def test_enforces_minimum_interval(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-pacing", rate_per_sec=20, max_concurrency=10))
        start = time.monotonic()
        for _ in range(4):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start

        assert elapsed >= 3 * 0.05 - 0.01  # 3 intervals between 4 calls, small tolerance

    def test_holds_ceiling_regardless_of_thread_count(self):
        # mirrors local_phash's own "wide pool doesn't route around pacing" test - proves this is
        # a real shared ceiling, not a per-thread throttle.
        limiter = get_limiter(DestinationLimiterConfig(name="test-wide-pool", rate_per_sec=20, max_concurrency=10))
        start = time.monotonic()

        def _acquire_once() -> None:
            with limiter.acquire():
                pass

        threads = [threading.Thread(target=_acquire_once) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - start

        assert elapsed >= 3 * 0.05 - 0.01


class TestDestinationLimiterConcurrency:
    def test_bounds_concurrent_holders(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-concurrency", rate_per_sec=1000, max_concurrency=2))
        in_flight = 0
        max_in_flight = 0
        lock = threading.Lock()

        def _hold_briefly() -> None:
            nonlocal in_flight, max_in_flight
            with limiter.acquire():
                with lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                time.sleep(0.05)
                with lock:
                    in_flight -= 1

        threads = [threading.Thread(target=_hold_briefly) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_in_flight == 2


class TestDestinationLimiterLockout:
    def test_lock_out_sets_locked_out_and_future_acquires_raise(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-lockout", rate_per_sec=1000, max_concurrency=10))
        assert limiter.locked_out is False

        limiter.lock_out()

        assert limiter.locked_out is True
        with pytest.raises(GoogleFetchLockoutError):
            with limiter.acquire():
                pass

    def test_lockout_is_permanent_for_the_life_of_the_limiter(self):
        limiter = get_limiter(
            DestinationLimiterConfig(name="test-lockout-sticky", rate_per_sec=1000, max_concurrency=10)
        )
        limiter.lock_out()
        limiter.lock_out()  # calling again must not un-set or error

        assert limiter.locked_out is True


class TestDestinationLimiterBackoff:
    def test_backoff_doubles_the_effective_interval(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-backoff", rate_per_sec=1000, max_concurrency=10))
        assert limiter.backoff_multiplier == 1.0

        limiter.backoff()

        assert limiter.backoff_multiplier == 2.0

        limiter.backoff()

        assert limiter.backoff_multiplier == 4.0

    def test_backoff_caps_at_the_maximum_multiplier(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-backoff-cap", rate_per_sec=1000, max_concurrency=10))
        for _ in range(10):
            limiter.backoff()

        assert limiter.backoff_multiplier == limiter._MAX_BACKOFF_MULTIPLIER

    def test_backoff_actually_slows_pacing(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-backoff-real", rate_per_sec=20, max_concurrency=10))
        limiter.backoff()  # interval now 2x -> 0.1s

        start = time.monotonic()
        for _ in range(3):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start

        assert elapsed >= 2 * 0.1 - 0.02


class TestRateLimitedGet:
    def test_lockout_status_raises_and_locks_out_the_limiter(self, monkeypatch):
        config = DestinationLimiterConfig(
            name="test-rlg-lockout", rate_per_sec=1000, max_concurrency=10, lockout_status_codes=frozenset({403})
        )
        limiter = get_limiter(config)
        monkeypatch.setattr(limiter.session, "get", lambda url, **kwargs: _FakeResponse(status_code=403))

        with pytest.raises(GoogleFetchLockoutError):
            rate_limited_get(config, "https://example.test/image.jpg")

        assert limiter.locked_out is True

    def test_backoff_status_does_not_raise_but_escalates(self, monkeypatch):
        config = DestinationLimiterConfig(
            name="test-rlg-backoff", rate_per_sec=1000, max_concurrency=10, backoff_status_codes=frozenset({429})
        )
        limiter = get_limiter(config)
        monkeypatch.setattr(limiter.session, "get", lambda url, **kwargs: _FakeResponse(status_code=429))

        response = rate_limited_get(config, "https://example.test/image.jpg")

        assert response.status_code == 429
        assert limiter.backoff_multiplier == 2.0

    def test_ordinary_status_neither_raises_nor_escalates(self, monkeypatch):
        config = DestinationLimiterConfig(
            name="test-rlg-ok",
            rate_per_sec=1000,
            max_concurrency=10,
            lockout_status_codes=frozenset({403}),
            backoff_status_codes=frozenset({429}),
        )
        limiter = get_limiter(config)
        monkeypatch.setattr(limiter.session, "get", lambda url, **kwargs: _FakeResponse(status_code=200))

        rate_limited_get(config, "https://example.test/image.jpg")

        assert limiter.locked_out is False
        assert limiter.backoff_multiplier == 1.0

    def test_forwards_kwargs_to_session_get(self, monkeypatch):
        received_kwargs: dict[str, Any] = {}

        def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
            received_kwargs.update(kwargs)
            return _FakeResponse(status_code=200)

        config = DestinationLimiterConfig(name="test-rlg-kwargs", rate_per_sec=1000, max_concurrency=10)
        limiter = get_limiter(config)
        monkeypatch.setattr(limiter.session, "get", fake_get)

        rate_limited_get(config, "https://example.test/image.jpg", timeout=15, headers={"X": "Y"})

        assert received_kwargs == {"timeout": 15, "headers": {"X": "Y"}}

    def test_reuses_the_same_session_across_calls(self, monkeypatch):
        # 2026-07-24 IO audit finding 2: rate_limited_get must not construct a fresh
        # requests.Session (and tear down its connection pool) per call - it should reuse the
        # one Session bound to the destination's limiter, so keep-alive connections persist
        # across the ~200k+ fetches a full harvest issues to the same host.
        config = DestinationLimiterConfig(name="test-rlg-session-reuse", rate_per_sec=1000, max_concurrency=10)
        limiter = get_limiter(config)
        sessions_seen = []

        def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
            sessions_seen.append(limiter.session)
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(limiter.session, "get", fake_get)

        rate_limited_get(config, "https://example.test/image.jpg")
        rate_limited_get(config, "https://example.test/image.jpg")

        assert len(sessions_seen) == 2
        assert sessions_seen[0] is sessions_seen[1]


class TestDestinationSession:
    def test_each_limiter_gets_a_real_session(self):
        config = DestinationLimiterConfig(name="test-session-instance", rate_per_sec=1000, max_concurrency=10)

        assert isinstance(get_limiter(config).session, requests.Session)

    def test_different_destinations_have_independent_sessions(self):
        config_a = DestinationLimiterConfig(name="test-session-a", rate_per_sec=1000, max_concurrency=10)
        config_b = DestinationLimiterConfig(name="test-session-b", rate_per_sec=1000, max_concurrency=10)

        assert get_limiter(config_a).session is not get_limiter(config_b).session

    def test_same_destination_reuses_the_same_session_instance(self):
        config = DestinationLimiterConfig(name="test-session-singleton", rate_per_sec=1000, max_concurrency=10)

        assert get_limiter(config).session is get_limiter(config).session


class TestCurrentRate:
    def test_reports_zero_before_any_requests(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-rate-zero", rate_per_sec=1000, max_concurrency=10))
        assert limiter.current_rate() == 0.0

    def test_reports_a_positive_rate_after_requests(self):
        limiter = get_limiter(
            DestinationLimiterConfig(name="test-rate-positive", rate_per_sec=1000, max_concurrency=10)
        )
        for _ in range(5):
            with limiter.acquire():
                pass

        assert limiter.current_rate() > 0.0


class TestLimiterRegistry:
    def test_same_config_name_returns_the_same_instance(self):
        config = DestinationLimiterConfig(name="test-registry-singleton", rate_per_sec=5, max_concurrency=1)

        first = get_limiter(config)
        second = get_limiter(config)

        assert first is second

    def test_different_destinations_have_independent_state(self):
        config_a = DestinationLimiterConfig(
            name="test-registry-a", rate_per_sec=1000, max_concurrency=10, lockout_status_codes=frozenset({403})
        )
        config_b = DestinationLimiterConfig(
            name="test-registry-b", rate_per_sec=1000, max_concurrency=10, lockout_status_codes=frozenset({403})
        )

        get_limiter(config_a).lock_out()

        assert get_limiter(config_a).locked_out is True
        assert get_limiter(config_b).locked_out is False


class TestConfiguredDestinations:
    """Sanity-checks on the real, shipped destination configs - not their exact numbers (those
    are policy, not something to lock down as a snapshot), but the invariants Stage B's design
    depends on."""

    def test_google_image_paced_at_probe_measured_ceiling(self):
        # 8.0/s + max_concurrency=6, not a higher number - task #165's concurrency-raise probe
        # (2026-07-19, docs/features/catalog-completion-plan.md's concurrency-probe table) is the
        # empirical basis: concurrency=6 achieved 8.116/s clean on every dimension including its
        # independent live-site canary, while concurrency=10's higher raw throughput (9.59/s) was
        # REJECTED for a 2.43x canary-p95 latency regression despite zero Google quota events (see
        # the module's own docstring). 8.0 sits a touch under the measured 8.116/s ceiling for
        # margin.
        assert GOOGLE_IMAGE.rate_per_sec == 8.0
        assert GOOGLE_IMAGE.max_concurrency == 6

    def test_google_image_has_both_lockout_and_backoff_configured(self):
        assert GOOGLE_IMAGE.lockout_status_codes == frozenset({403})
        assert GOOGLE_IMAGE.backoff_status_codes == frozenset({429})

    def test_scryfall_destinations_have_no_reactive_handling_configured(self):
        # Deliberate (see harvest_fetch_limiter.py's own comments): no observed throttling
        # history against Scryfall's endpoints, unlike Google's undocumented lh3/lh4 ceiling.
        assert SCRYFALL_CDN.lockout_status_codes == frozenset()
        assert SCRYFALL_CDN.backoff_status_codes == frozenset()
        assert SCRYFALL_REST.lockout_status_codes == frozenset()
        assert SCRYFALL_REST.backoff_status_codes == frozenset()

    def test_no_r2_destination_exists_yet(self):
        # Stage B reframe (2026-07-19): R2 is unused by the current fetch path - inventing a
        # tier with no real traffic would violate this pilot's own "measure, don't assume"
        # discipline. This test exists so a future PR adding one does so deliberately.
        import cardpicker.harvest_fetch_limiter as module

        assert not any("r2" in name.lower() for name in module.__all__)
