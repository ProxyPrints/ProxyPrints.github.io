"""
Tests for the GLOBAL (cross-process) fetch-rate budget - `cardpicker.harvest_rate_budget` and the
`_DestinationLimiter` wiring that consumes it.

THE POINT OF THIS FILE, stated plainly because a weaker version of it is what let the defect
through: every meaningful test here runs MORE THAN ONE limiter instance concurrently, each with its
own pacing state and its own database connection. A single-instance test CANNOT detect a
per-process rate cap - `test_harvest_fetch_limiter.py`'s existing pacing tests all passed against a
limiter that gave N x the configured rate across N processes, because each of them only ever
exercised one. The multi-instance shape is the test, not an implementation detail of it.

Independent `_DestinationLimiter` objects on separate threads are a faithful stand-in for separate
OS processes here: each has its own `_next_allowed`/`_backoff_multiplier` (exactly what a forked
django-q2 worker gets), and `harvest_rate_budget`'s connection cache is a `threading.local`, so
each thread also reserves on its own database connection. The coordination surface under test - one
shared row, N independent reservers - is identical.
"""

import threading
import time
from typing import Any, List

import pytest

from cardpicker import harvest_rate_budget
from cardpicker.harvest_fetch_limiter import (
    DestinationLimiterConfig,
    _DestinationLimiter,
    reset_limiters,
)
from cardpicker.harvest_rate_budget import (
    current_state,
    record_backoff,
    record_clean_response,
    reserve_slot,
)


@pytest.fixture(autouse=True)
def _reset_shared_state(db: Any):
    from cardpicker.models import GlobalFetchPace

    reset_limiters()
    harvest_rate_budget.reset_for_tests()
    GlobalFetchPace.objects.all().delete()
    yield
    reset_limiters()
    harvest_rate_budget.reset_for_tests()


def _drive(limiters: List[_DestinationLimiter], requests_each: int) -> float:
    """Run every limiter concurrently, `requests_each` acquisitions apiece, and return the wall
    time the whole thing took. Each limiter runs on its own thread, so each reserves on its own
    database connection - the multi-process shape this file exists to exercise."""
    barrier = threading.Barrier(len(limiters))
    errors: List[BaseException] = []

    def _run(limiter: _DestinationLimiter) -> None:
        try:
            barrier.wait()  # all threads start together, so the measured window is the real one
            for _ in range(requests_each):
                with limiter.acquire():
                    pass
        except BaseException as exc:  # noqa: BLE001 - surfaced in the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(limiter,)) for limiter in limiters]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started
    if errors:
        raise errors[0]
    return elapsed


def _independent_limiters(count: int, name: str, rate_per_sec: float) -> List[_DestinationLimiter]:
    """`count` limiter instances for the SAME destination, each constructed separately so none of
    them shares pacing state with any other - i.e. what N separate django-q2 worker processes
    actually get from the module-level registry in their own address spaces. Deliberately NOT
    `get_limiter()`, which would hand back one shared instance and quietly turn this into a
    single-process test."""
    config = DestinationLimiterConfig(name=name, rate_per_sec=rate_per_sec, max_concurrency=10)
    return [_DestinationLimiter(config) for _ in range(count)]


class TestTheAggregateRateIsCapped:
    """Requirement 1: the aggregate across all fetching processes must not exceed the ceiling."""

    @pytest.mark.django_db(transaction=True)
    def test_four_independent_limiters_share_one_budget(self) -> None:
        """THE TEST THIS CHANGE EXISTS FOR. Four independent limiters (= four worker processes) at
        a configured 50/s must together take at least (40-1)/50 = 0.78s to issue 40 requests.

        Under the per-process pacing this replaces, each limiter would pace itself independently
        and the whole thing would finish in about (10-1)/50 = 0.18s at an aggregate ~220/s - which
        is exactly the 4x overshoot the owner's clarification identified. The margin between the
        two outcomes is 4x, far outside any timing noise this assertion tolerates."""
        rate = 50.0
        processes, each = 4, 10
        limiters = _independent_limiters(processes, "test-global-aggregate", rate)

        elapsed = _drive(limiters, each)

        total = processes * each
        floor = (total - 1) / rate
        assert elapsed >= floor * 0.9, (
            f"{total} requests across {processes} independent limiters took {elapsed:.3f}s; a global "
            f"{rate}/s cap requires at least {floor:.3f}s. A per-process cap would finish in "
            f"~{(each - 1) / rate:.3f}s - that is the defect this asserts against."
        )
        achieved = total / elapsed
        assert achieved <= rate * 1.2, f"aggregate {achieved:.1f}/s exceeded the {rate}/s ceiling"

    @pytest.mark.django_db(transaction=True)
    def test_a_single_limiter_still_paces_correctly(self) -> None:
        """The one-process case must not regress: the same ceiling, reached the same way."""
        rate = 50.0
        limiters = _independent_limiters(1, "test-global-single", rate)

        elapsed = _drive(limiters, 10)

        assert elapsed >= (10 - 1) / rate * 0.9

    @pytest.mark.django_db(transaction=True)
    def test_reservations_are_a_single_strictly_increasing_sequence(self) -> None:
        """The mechanism, asserted directly rather than through wall time: concurrent reservers
        each get a DISTINCT slot spaced by the interval, because the blocked UPDATE re-evaluates
        against the committed row under READ COMMITTED. If two reservers could read the same
        `next_allowed_at` and both add to it, waits would collide and the sum would be short."""
        interval = 0.05
        slots: List[float] = []
        slots_lock = threading.Lock()
        barrier = threading.Barrier(8)

        def _reserve() -> None:
            barrier.wait()
            wait = reserve_slot("test-global-sequence", interval)
            # The ABSOLUTE instant this reserver was granted, not the relative wait it was handed.
            # The two differ by however long the OS delayed this thread between the reservation
            # returning and this line, and asserting on relative waits would fold that scheduling
            # jitter straight into the measurement - a thread descheduled for 50ms reports a wait
            # 50ms shorter than the slot it actually holds, which makes correctly-spaced slots look
            # bunched. Absolute instants are immune to that: a late thread records a late `now` and
            # a correspondingly smaller `wait`, and their sum is the same slot either way.
            granted = time.monotonic() + wait
            with slots_lock:
                slots.append(granted)

        threads = [threading.Thread(target=_reserve) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        ordered = sorted(slots)
        assert len(ordered) == 8
        # Eight reservations at a 50ms interval span at least 7 intervals end to end.
        assert ordered[-1] - ordered[0] >= interval * 7 * 0.9
        # And no two reservers were handed the same slot - the property that fails if two
        # concurrent UPDATEs could both read the same pre-update `next_allowed_at`.
        for earlier, later in zip(ordered, ordered[1:]):
            assert later - earlier >= interval * 0.9


class TestDegradationNeverFails:
    """Requirement 4: a process that cannot get rate budget WAITS, it does not fail or halt."""

    @pytest.mark.django_db(transaction=True)
    def test_an_unavailable_budget_degrades_to_local_pacing_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the shared row unreachable, `acquire()` must still pace (locally) and still
        return - never raise, never halt. The ceiling degrades from global to per-process, which
        is where this repo already was; that is a documented, logged degradation, not a failure."""
        import cardpicker.harvest_fetch_limiter as limiter_module

        def _unavailable(destination: str, interval: float) -> float:
            raise harvest_rate_budget.RateBudgetUnavailable("simulated outage")

        monkeypatch.setattr(limiter_module, "reserve_slot", _unavailable)
        limiter = _independent_limiters(1, "test-global-degraded", 50.0)[0]

        started = time.monotonic()
        for _ in range(5):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - started

        # Still paced - the fallback is the original per-process arithmetic, not "no limit".
        assert elapsed >= (5 - 1) / 50.0 * 0.9

    @pytest.mark.django_db(transaction=True)
    def test_a_missing_row_is_recreated_rather_than_failing_forever(self) -> None:
        """Someone truncating the table mid-run must not wedge every fetcher permanently."""
        from cardpicker.models import GlobalFetchPace

        reserve_slot("test-global-recreate", 0.01)
        GlobalFetchPace.objects.all().delete()
        harvest_rate_budget.reset_for_tests()

        assert reserve_slot("test-global-recreate", 0.01) >= 0.0
        assert GlobalFetchPace.objects.filter(destination="test-global-recreate").exists()


class TestSharedBackoffState:
    """PR #644's throttle/decay semantics, preserved but now agreed across processes - a global
    rate ceiling requires a global backoff term, or processes write conflicting paces into the
    same row."""

    @pytest.mark.django_db(transaction=True)
    def test_backoff_from_one_process_is_visible_to_another(self) -> None:
        record_backoff("test-global-backoff", 2.0, 16.0)
        assert current_state("test-global-backoff") == (2.0, 0)

        record_backoff("test-global-backoff", 2.0, 16.0)
        assert current_state("test-global-backoff") == (4.0, 0)

    @pytest.mark.django_db(transaction=True)
    def test_backoff_is_capped(self) -> None:
        for _ in range(10):
            record_backoff("test-global-cap", 2.0, 16.0)
        multiplier, _ = current_state("test-global-cap")
        assert multiplier == 16.0

    @pytest.mark.django_db(transaction=True)
    def test_the_clean_streak_is_shared_so_decay_is_not_n_times_faster(self) -> None:
        """The reason the STREAK had to move into the row too, not just the multiplier: N processes
        each counting their own streak would cross the decay threshold N times over and recover N
        times faster than the single agreed schedule intends."""
        record_backoff("test-global-decay", 2.0, 16.0)
        record_backoff("test-global-decay", 2.0, 16.0)
        assert current_state("test-global-decay")[0] == 4.0

        target = 5
        for _ in range(target - 1):
            record_clean_response("test-global-decay", target, 1.0)
        assert current_state("test-global-decay")[0] == 4.0  # not yet

        record_clean_response("test-global-decay", target, 1.0)
        assert current_state("test-global-decay") == (2.0, 0)

    @pytest.mark.django_db(transaction=True)
    def test_decay_never_overshoots_the_configured_ceiling(self) -> None:
        for _ in range(50):
            record_clean_response("test-global-floor", 2, 1.0)
        assert current_state("test-global-floor")[0] == 1.0

    @pytest.mark.django_db(transaction=True)
    def test_a_shared_backoff_actually_slows_the_shared_sequence(self) -> None:
        """The multiplier is not just recorded, it is applied - by the SQL that advances the row,
        so a backoff recorded by one process paces every other process."""
        interval = 0.02
        record_backoff("test-global-applied", 2.0, 16.0)  # x2

        reserve_slot("test-global-applied", interval)  # claim the current slot
        wait = reserve_slot("test-global-applied", interval)

        assert wait >= interval * 2 * 0.9, "the shared multiplier was not applied to the shared pace"
