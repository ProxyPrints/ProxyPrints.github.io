"""
Stage B split fetch limiter tests (docs/features/catalog-completion-plan.md, "Harvest-calculate
pipeline" section). No network - `requests.get` is monkeypatched throughout via
`cardpicker.harvest_fetch_limiter.requests.get`, matching this file's own module-under-test
convention rather than reaching into `image_cdn_fetch`/`local_phash`'s call sites.
"""

import threading
import time
from typing import Any

import pytest

from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    SCRYFALL_CDN,
    SCRYFALL_REST,
    DestinationLimiterConfig,
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
    # leak pacing/trip state into each other via that same registry.
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


class TestDestinationLimiterTrip:
    def test_trips_to_degraded_rate_and_stays_tripped(self):
        limiter = get_limiter(
            DestinationLimiterConfig(
                name="test-trip",
                rate_per_sec=1000,
                max_concurrency=10,
                trip_status_codes=frozenset({403}),
                degraded_rate_per_sec=10,
            )
        )
        assert limiter.tripped is False

        limiter.trip()

        assert limiter.tripped is True
        start = time.monotonic()
        for _ in range(3):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start
        # degraded to 10/s = 0.1s interval; 2 intervals between 3 calls
        assert elapsed >= 2 * 0.1 - 0.02

    def test_no_trip_status_codes_means_never_degrades(self):
        limiter = get_limiter(DestinationLimiterConfig(name="test-no-trip", rate_per_sec=1000, max_concurrency=10))
        limiter.trip()  # calling trip() directly still no-ops without a degraded rate configured

        assert limiter.tripped is True
        start = time.monotonic()
        for _ in range(3):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start
        # still paced at the un-degraded 1000/s ceiling (~0.001s interval) since no
        # degraded_rate_per_sec was configured - fast, not the 10/s degraded rate above.
        assert elapsed < 0.1


class TestRateLimitedGet:
    def test_paces_and_trips_on_matching_status(self, monkeypatch):
        calls: list[str] = []

        def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
            calls.append(url)
            return _FakeResponse(status_code=403)

        import cardpicker.harvest_fetch_limiter as module

        monkeypatch.setattr(module.requests, "get", fake_get)
        config = DestinationLimiterConfig(
            name="test-rlg-trip",
            rate_per_sec=1000,
            max_concurrency=10,
            trip_status_codes=frozenset({403}),
            degraded_rate_per_sec=1000,
        )

        response = rate_limited_get(config, "https://example.test/image.jpg")

        assert response.status_code == 403
        assert calls == ["https://example.test/image.jpg"]
        assert get_limiter(config).tripped is True

    def test_non_matching_status_does_not_trip(self, monkeypatch):
        import cardpicker.harvest_fetch_limiter as module

        monkeypatch.setattr(module.requests, "get", lambda url, **kwargs: _FakeResponse(status_code=200))
        config = DestinationLimiterConfig(
            name="test-rlg-no-trip",
            rate_per_sec=1000,
            max_concurrency=10,
            trip_status_codes=frozenset({403}),
            degraded_rate_per_sec=1000,
        )

        rate_limited_get(config, "https://example.test/image.jpg")

        assert get_limiter(config).tripped is False

    def test_forwards_kwargs_to_requests_get(self, monkeypatch):
        received_kwargs: dict[str, Any] = {}

        def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
            received_kwargs.update(kwargs)
            return _FakeResponse(status_code=200)

        import cardpicker.harvest_fetch_limiter as module

        monkeypatch.setattr(module.requests, "get", fake_get)
        config = DestinationLimiterConfig(name="test-rlg-kwargs", rate_per_sec=1000, max_concurrency=10)

        rate_limited_get(config, "https://example.test/image.jpg", timeout=15, headers={"X": "Y"})

        assert received_kwargs == {"timeout": 15, "headers": {"X": "Y"}}


class TestLimiterRegistry:
    def test_same_config_name_returns_the_same_instance(self):
        config = DestinationLimiterConfig(name="test-registry-singleton", rate_per_sec=5, max_concurrency=1)

        first = get_limiter(config)
        second = get_limiter(config)

        assert first is second

    def test_different_destinations_have_independent_state(self):
        config_a = DestinationLimiterConfig(
            name="test-registry-a",
            rate_per_sec=1000,
            max_concurrency=10,
            trip_status_codes=frozenset({403}),
            degraded_rate_per_sec=10,
        )
        config_b = DestinationLimiterConfig(
            name="test-registry-b",
            rate_per_sec=1000,
            max_concurrency=10,
            trip_status_codes=frozenset({403}),
            degraded_rate_per_sec=10,
        )

        get_limiter(config_a).trip()

        assert get_limiter(config_a).tripped is True
        assert get_limiter(config_b).tripped is False


class TestConfiguredDestinations:
    """Sanity-checks on the real, shipped destination configs - not their exact numbers (those
    are policy, not something to lock down as a snapshot), but the invariants Stage B's design
    depends on."""

    def test_google_image_has_reactive_backoff(self):
        assert GOOGLE_IMAGE.trip_status_codes == frozenset({403})
        assert GOOGLE_IMAGE.degraded_rate_per_sec is not None
        assert GOOGLE_IMAGE.degraded_rate_per_sec < GOOGLE_IMAGE.rate_per_sec

    def test_scryfall_destinations_have_no_reactive_backoff_configured(self):
        # Deliberate (see harvest_fetch_limiter.py's own comments): no observed throttling
        # history against Scryfall's endpoints, unlike Google's undocumented lh3/lh4 ceiling.
        assert SCRYFALL_CDN.trip_status_codes == frozenset()
        assert SCRYFALL_REST.trip_status_codes == frozenset()

    def test_no_r2_destination_exists_yet(self):
        # Stage B reframe (2026-07-19): R2 is unused by the current fetch path - inventing a
        # tier with no real traffic would violate this pilot's own "measure, don't assume"
        # discipline. This test exists so a future PR adding one does so deliberately.
        import cardpicker.harvest_fetch_limiter as module

        assert not any("r2" in name.lower() for name in module.__all__)
