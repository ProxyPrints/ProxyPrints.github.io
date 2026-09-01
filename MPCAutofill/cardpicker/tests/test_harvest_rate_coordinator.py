"""
Cross-process rate-ceiling tests for `harvest_rate_coordinator` + `harvest_fetch_limiter`.

WHY THESE TESTS LOOK LIKE THIS. The defect they exist to catch - a rate limiter whose state lives
in one process's memory, so N processes fetch at N x the configured rate - is INVISIBLE to a
single-instance test. `test_harvest_fetch_limiter.py`'s existing pacing tests all drive ONE
`_DestinationLimiter` and they all passed throughout the defect's life, because one limiter really
does hold its own interval. Every rate assertion below therefore drives MORE THAN ONE independent
pacer at once and asserts the COMBINED rate:

  * `TestAggregateCeilingAcrossProcesses` forks real OS processes - the exact shape django-q2 uses
    for its workers, which is where the defect actually lived.
  * `TestAggregateCeilingAcrossInstances` drives several independent limiter OBJECTS from threads -
    the same discriminator, fast enough to run on every change.

Both assert an UPPER bound on the aggregate rate AND a LOWER bound on the elapsed span, because
those are the two halves of the same claim: the destination sees no more than the ceiling, and the
work genuinely took as long as a real ceiling would make it take. A per-process-only pacer fails
the elapsed-span assertion by a factor of the process count, which is what makes these tests
non-vacuous.
"""

import multiprocessing
import time
from typing import Any

import pytest

from django.test import override_settings

from cardpicker import harvest_rate_coordinator
from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    DestinationLimiterConfig,
    get_limiter,
    reset_limiters,
)


@pytest.fixture(autouse=True)
def _reset_limiter_registry():
    reset_limiters()
    yield
    reset_limiters()


def _timed_acquires(config: DestinationLimiterConfig, count: int) -> list[float]:
    """Acquires `count` times against `config`'s limiter, returning the wall-clock instant each
    acquisition was cleared. `time.time()` (not `time.monotonic()`) deliberately: these timestamps
    are merged ACROSS PROCESSES, and only a wall clock is comparable between them."""
    limiter = get_limiter(config)
    stamps = []
    for _ in range(count):
        with limiter.acquire():
            stamps.append(time.time())
    return stamps


def _aggregate_rate(stamps: list[float]) -> float:
    """Requests per second across the merged timeline. `len - 1` over the span, not `len` over the
    span: the first acquisition consumes no interval (it is the one the ceiling clears
    immediately), so N acquisitions at a ceiling of R take (N-1)/R seconds, not N/R."""
    ordered = sorted(stamps)
    span = ordered[-1] - ordered[0]
    assert span > 0, "every acquisition landed on the same instant - the pacer did nothing at all"
    return (len(ordered) - 1) / span


def _peak_windowed_rate(stamps: list[float], window: float = 1.0) -> float:
    """The worst sliding-`window` burst in the merged timeline, in requests per second. The
    aggregate average can hide a burst; a destination experiences the burst."""
    ordered = sorted(stamps)
    peak = 0
    for start_index, start in enumerate(ordered):
        count = 0
        for stamp in ordered[start_index:]:
            if stamp - start > window:
                break
            count += 1
        peak = max(peak, count)
    return peak / window


class TestAggregateCeilingAcrossProcesses:
    """The proof that matters: separate OS PROCESSES, which is what django-q2's workers are and
    what the per-process pacer could never bound."""

    RATE = 20.0
    PROCESSES = 3
    ACQUIRES_EACH = 10

    @staticmethod
    def _child(name: str, rate: float, count: int, sink: Any) -> None:
        # A forked child inherits the parent's limiter registry and its coordinator connection
        # object. `harvest_rate_coordinator` drops the latter automatically via its
        # `os.register_at_fork` handler; the registry is cleared here so this child's pacer state is
        # genuinely its own, exactly as a freshly-spawned django-q2 worker's would be.
        #
        # Django's own inherited connections are ABANDONED, not `close_all()`d, for exactly the
        # reason `harvest_rate_coordinator._forget_connection_after_fork` documents: closing an
        # inherited libpq handle sends Terminate down a socket the PARENT is still using, which here
        # kills the pytest process's own database session mid-test. Nulling `.connection` leaves the
        # parent's session alone and makes the child open its own on first use.
        from django.db import connections

        for alias in list(connections):
            connections[alias].connection = None
        reset_limiters()
        config = DestinationLimiterConfig(name=name, rate_per_sec=rate, max_concurrency=10)
        sink.put(_timed_acquires(config, count))

    @pytest.mark.django_db(transaction=True)
    def test_three_processes_share_one_ceiling(self) -> None:
        """Three processes, each running its own limiter at 20/s, must together deliver 20/s - not
        60/s. With the pre-fix per-process pacer this test finishes in roughly
        `ACQUIRES_EACH / RATE` seconds instead of `(PROCESSES * ACQUIRES_EACH - 1) / RATE`, so the
        elapsed-span assertion below fails by a factor of `PROCESSES`."""
        name = "test-xproc-ceiling"
        harvest_rate_coordinator.clear_cursor(name)
        context = multiprocessing.get_context("fork")
        sink = context.Queue()

        children = [
            context.Process(target=self._child, args=(name, self.RATE, self.ACQUIRES_EACH, sink))
            for _ in range(self.PROCESSES)
        ]
        stamps: list[float] = []
        try:
            for child in children:
                child.start()
            for _ in children:
                stamps.extend(sink.get(timeout=60))
        finally:
            for child in children:
                child.join(timeout=60)
                if child.exitcode is None:
                    child.terminate()

        total = self.PROCESSES * self.ACQUIRES_EACH
        assert len(stamps) == total
        span = max(stamps) - min(stamps)
        rate = _aggregate_rate(stamps)

        # Upper bound: the destination never saw more than the ceiling (plus scheduling slop).
        assert rate <= self.RATE * 1.25, f"aggregate {rate:.2f}/s exceeded the {self.RATE}/s ceiling"
        assert _peak_windowed_rate(stamps) <= self.RATE * 1.25
        # Lower bound: the work actually took as long as a real ceiling makes it take. This is the
        # assertion a per-process pacer fails - it would finish ~PROCESSES times sooner.
        assert span >= (total - 1) / self.RATE * 0.75, f"finished in {span:.2f}s - too fast to have been paced globally"


class TestAggregateCeilingAcrossInstances:
    """Same discriminator, independent limiter OBJECTS in threads rather than forked processes.
    Independent objects means independent `_next_allowed`/lock/semaphore state - i.e. exactly what
    separate processes have - so this catches the same defect in a fraction of the time."""

    @pytest.mark.django_db(transaction=True)
    def test_four_independent_limiters_share_one_ceiling(self) -> None:
        import threading

        name = "test-xinstance-ceiling"
        rate = 25.0
        instances = 4
        acquires_each = 8
        harvest_rate_coordinator.clear_cursor(name)

        # Deliberately NOT `get_limiter` - that returns the process-wide singleton, which would
        # collapse this into the single-instance test that cannot see the defect.
        from cardpicker.harvest_fetch_limiter import _DestinationLimiter

        limiters = [
            _DestinationLimiter(DestinationLimiterConfig(name=name, rate_per_sec=rate, max_concurrency=10))
            for _ in range(instances)
        ]
        stamps: list[float] = []
        stamps_lock = threading.Lock()

        def _drive(limiter: "_DestinationLimiter") -> None:
            mine = []
            for _ in range(acquires_each):
                with limiter.acquire():
                    mine.append(time.time())
            with stamps_lock:
                stamps.extend(mine)

        threads = [threading.Thread(target=_drive, args=(limiter,)) for limiter in limiters]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        total = instances * acquires_each
        assert len(stamps) == total
        span = max(stamps) - min(stamps)
        assert _aggregate_rate(stamps) <= rate * 1.25
        assert _peak_windowed_rate(stamps) <= rate * 1.25
        assert span >= (total - 1) / rate * 0.75, f"finished in {span:.2f}s - four limiters were not sharing a ceiling"


class TestSharedCursor:
    @pytest.mark.django_db(transaction=True)
    def test_reserve_returns_zero_on_a_fresh_cursor_then_a_real_wait(self) -> None:
        name = "test-cursor-fresh"
        harvest_rate_coordinator.clear_cursor(name)

        first = harvest_rate_coordinator.reserve(name, 0.5)
        second = harvest_rate_coordinator.reserve(name, 0.5)

        assert first == pytest.approx(0.0, abs=0.05)
        assert 0.4 <= (second or 0.0) <= 0.55

    @pytest.mark.django_db(transaction=True)
    def test_destinations_do_not_share_a_cursor(self) -> None:
        for name in ("test-cursor-sep-a", "test-cursor-sep-b"):
            harvest_rate_coordinator.clear_cursor(name)

        harvest_rate_coordinator.reserve("test-cursor-sep-a", 0.5)
        harvest_rate_coordinator.reserve("test-cursor-sep-a", 0.5)

        # b's budget must be untouched by a's traffic.
        assert harvest_rate_coordinator.reserve("test-cursor-sep-b", 0.5) == pytest.approx(0.0, abs=0.05)

    @pytest.mark.django_db(transaction=True)
    def test_clear_cursor_forgets_the_budget(self) -> None:
        name = "test-cursor-clear"
        harvest_rate_coordinator.clear_cursor(name)
        harvest_rate_coordinator.reserve(name, 2.0)
        assert (harvest_rate_coordinator.reserve(name, 2.0) or 0.0) > 1.0

        harvest_rate_coordinator.clear_cursor(name)

        assert harvest_rate_coordinator.reserve(name, 2.0) == pytest.approx(0.0, abs=0.05)

    @pytest.mark.django_db(transaction=True)
    def test_a_widened_interval_is_honoured(self) -> None:
        """PR #644's backoff stays per-process and reaches the shared cursor as a bigger gap. The
        cursor must honour it - a global ceiling that ignored a backing-off process's widened
        interval would silently undo throttling for everyone else.

        Note which caller pays: a reservation's own gap delays the NEXT caller, not itself (that is
        the pre-existing pacer semantic - `wait = next_allowed - now` is read before
        `next_allowed += interval`). So the backing-off process is not punished twice; what its
        backoff buys is a wider gap in front of whoever fetches after it, which is exactly the
        aggregate slowdown the destination asked for."""
        name = "test-cursor-backoff"
        harvest_rate_coordinator.clear_cursor(name)

        harvest_rate_coordinator.reserve(name, 0.1)  # a normal process: contributes a 0.1s gap
        after_normal = harvest_rate_coordinator.reserve(name, 0.8) or 0.0  # backing off; waits 0.1s
        after_widened = harvest_rate_coordinator.reserve(name, 0.1) or 0.0  # pays the widened gap

        assert 0.05 <= after_normal <= 0.15
        # These reservations are issued back-to-back with no sleeping, so the third caller's wait is
        # the whole accumulated backlog. The BACKOFF's contribution is the difference between the
        # two waits, which is the 0.8s gap the widened reservation put into the shared cursor -
        # observed by a DIFFERENT caller, which is the property being proven.
        assert 0.75 <= after_widened - after_normal <= 0.85


class TestLimiterWiring:
    def test_acquire_takes_its_pacing_from_the_shared_cursor_not_the_local_one(self, monkeypatch) -> None:
        """Direct proof of the wiring, independent of any timing. `acquire()` must consult the
        coordinator on EVERY acquisition and must pass its own current interval (post-backoff), so
        a future refactor cannot quietly fall back to `_next_allowed` while the timing tests still
        pass on a fast machine."""
        seen: list[tuple[str, float]] = []

        def _record(destination: str, interval: float) -> float:
            seen.append((destination, interval))
            return 0.0

        monkeypatch.setattr(harvest_rate_coordinator, "reserve", _record)
        config = DestinationLimiterConfig(name="test-wiring", rate_per_sec=50.0, max_concurrency=4)
        limiter = get_limiter(config)

        with limiter.acquire():
            pass
        limiter.backoff()  # x2 - the widened interval must reach the coordinator, not stay local
        with limiter.acquire():
            pass

        assert [destination for destination, _ in seen] == ["test-wiring", "test-wiring"]
        assert [interval for _, interval in seen] == [pytest.approx(0.02), pytest.approx(0.04)]

    def test_the_semaphore_is_not_leaked_if_pacing_blows_up(self, monkeypatch) -> None:
        """`acquire()` takes the concurrency semaphore BEFORE it reserves budget. If anything
        between the two raised without releasing, the destination would permanently lose a
        concurrency slot per occurrence and eventually deadlock the whole fetch pool."""

        def _explode(destination: str, interval: float) -> float:
            raise RuntimeError("coordination exploded in a way reserve() does not cover")

        monkeypatch.setattr(harvest_rate_coordinator, "reserve", _explode)
        config = DestinationLimiterConfig(name="test-semaphore-leak", rate_per_sec=1000.0, max_concurrency=1)
        limiter = get_limiter(config)

        for _ in range(3):
            with pytest.raises(RuntimeError):
                limiter.acquire()

        # The single slot is still free - i.e. all three failed acquisitions gave it back.
        assert limiter._semaphore.acquire(blocking=False) is True
        limiter._semaphore.release()


class TestGracefulDegradation:
    """Requirement: a process that cannot obtain rate budget WAITS. It does not fail, does not
    halt, and does not feed the operating envelope's fetch-failure window."""

    def test_reserve_returns_none_instead_of_raising_when_the_store_is_unreachable(self, monkeypatch) -> None:
        harvest_rate_coordinator.reset_connection()
        monkeypatch.setattr(
            harvest_rate_coordinator,
            "_open_connection",
            lambda: (_ for _ in ()).throw(RuntimeError("postgres is gone")),
        )

        assert harvest_rate_coordinator.reserve("test-degrade-none", 0.01) is None

        harvest_rate_coordinator.reset_connection()

    def test_acquire_still_paces_and_never_raises_when_coordination_is_down(self, monkeypatch) -> None:
        """The fallback is the ORIGINAL per-process pacer widened by `degraded_divisor()`, so the
        aggregate ceiling still holds with every process fetching. Proven here by the elapsed time:
        four acquisitions at 20/s cost 3 divided intervals, not 3 full ones."""
        monkeypatch.setattr(harvest_rate_coordinator, "reserve", lambda destination, interval: None)
        config = DestinationLimiterConfig(name="test-degrade-pacing", rate_per_sec=20.0, max_concurrency=10)
        limiter = get_limiter(config)
        divisor = harvest_rate_coordinator.degraded_divisor()

        start = time.monotonic()
        for _ in range(4):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start

        assert elapsed >= 3 * 0.05 * divisor * 0.8

    def test_a_sustained_outage_is_latched_rather_than_retried_every_fetch(self, monkeypatch) -> None:
        """A coordination outage must cost one connection attempt per cooldown, not one per fetch -
        otherwise a dead Postgres turns every fetch into a connect timeout and the run stalls
        harder than the outage itself warrants."""
        harvest_rate_coordinator.reset_connection()
        attempts = {"count": 0}

        def _boom() -> Any:
            attempts["count"] += 1
            raise RuntimeError("postgres is gone")

        monkeypatch.setattr(harvest_rate_coordinator, "_open_connection", _boom)

        for _ in range(25):
            assert harvest_rate_coordinator.reserve("test-degrade-latch", 0.001) is None

        assert attempts["count"] == 1
        harvest_rate_coordinator.reset_connection()

    def test_the_degraded_divisor_covers_every_process_that_can_fetch(self) -> None:
        """Derived from the conveyor's own cross-process dispatch cap plus one for a pooled or
        manual runner, which holds no dispatch slot. Not a new setting - see the module docstring."""
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=2):
            assert harvest_rate_coordinator.degraded_divisor() == 3
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=8):
            assert harvest_rate_coordinator.degraded_divisor() == 9
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=0):
            assert harvest_rate_coordinator.degraded_divisor() == 2  # floored, never a divide by zero


class TestCoordinationCost:
    """Requirement: do not regress the pooled runner. The pooled path is the monolith's Stage C and
    its throughput is why it was chosen, so the per-request Postgres round trip this change adds has
    to be MEASURED against the interval it is amortised into, not assumed to be cheap."""

    @pytest.mark.django_db(transaction=True)
    def test_a_reservation_costs_a_small_fraction_of_the_google_interval(self) -> None:
        name = "test-cost"
        harvest_rate_coordinator.clear_cursor(name)
        # A gap of zero makes every reservation return 0.0, so this times the COORDINATION round
        # trip alone with no pacing sleep mixed in.
        harvest_rate_coordinator.reserve(name, 0.0)  # warm the connection; not measured

        samples = 200
        start = time.monotonic()
        for _ in range(samples):
            assert harvest_rate_coordinator.reserve(name, 0.0) == pytest.approx(0.0, abs=0.05)
        per_call = (time.monotonic() - start) / samples

        google_interval = 1.0 / 7.0
        print(
            f"\ncoordination cost: {per_call * 1000:.3f} ms/reservation, "
            f"{per_call / google_interval * 100:.2f}% of the 7/s interval"
        )
        # Loose on purpose - this is a regression guard against the round trip becoming structurally
        # expensive (a transaction pair, an advisory-lock round trip, a retry storm), not a
        # benchmark. Measured locally at ~0.3ms against a container Postgres; 10ms is 30x that and
        # still only 7% of the 143ms interval a 7/s ceiling already imposes.
        assert per_call < 0.010, f"a reservation cost {per_call * 1000:.1f} ms - that is no longer amortisable"

    @pytest.mark.django_db(transaction=True)
    def test_the_round_trip_does_not_become_the_binding_term_at_the_google_ceiling(self) -> None:
        """The cost question that actually matters for the pooled runner: does coordination slow
        fetching DOWN, or is it amortised into a pacing interval that already exists? Driven at the
        real shipped ceiling (7/s), 8 acquisitions must still take the 7 intervals the ceiling
        alone imposes - if the round trip were the binding term this would run measurably long."""
        name = "test-cost-throughput"
        harvest_rate_coordinator.clear_cursor(name)
        config = DestinationLimiterConfig(name=name, rate_per_sec=GOOGLE_IMAGE.rate_per_sec, max_concurrency=6)
        limiter = get_limiter(config)

        start = time.monotonic()
        for _ in range(8):
            with limiter.acquire():
                pass
        elapsed = time.monotonic() - start

        ceiling_only = 7 / GOOGLE_IMAGE.rate_per_sec
        print(
            f"\n8 acquisitions at {GOOGLE_IMAGE.rate_per_sec}/s: {elapsed:.3f}s "
            f"vs {ceiling_only:.3f}s for the ceiling alone ({(elapsed / ceiling_only - 1) * 100:+.1f}%)"
        )
        assert elapsed <= ceiling_only * 1.20


class TestForkSafety:
    def test_a_forked_child_does_not_inherit_the_parents_connection_object(self) -> None:
        """`os.register_at_fork` disposal, checked directly. A child that kept the parent's
        connection object would interleave two processes' statements down one libpq socket; a child
        that `close()`d it would terminate the parent's session. It must simply forget it."""
        harvest_rate_coordinator._connection = object()  # a stand-in; never used, only forgotten

        harvest_rate_coordinator._forget_connection_after_fork()

        assert harvest_rate_coordinator._connection is None

    def test_reset_connection_clears_the_degraded_latch(self, monkeypatch) -> None:
        monkeypatch.setattr(
            harvest_rate_coordinator,
            "_open_connection",
            lambda: (_ for _ in ()).throw(RuntimeError("postgres is gone")),
        )
        assert harvest_rate_coordinator.reserve("test-latch-clear", 0.001) is None
        assert harvest_rate_coordinator._degraded_until > 0.0

        harvest_rate_coordinator.reset_connection()

        assert harvest_rate_coordinator._degraded_until == 0.0
