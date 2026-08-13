"""
Tests for `cardpicker.stage_e_load_brake` - the Stage E host-load AIMD governor (2026-08-13,
replacing the 2026-08-05 three-band soft brake; see that module's own module docstring for the
control law and the incident that prompted the replacement).

`classify_load` and `run_governor` never touch `os.getloadavg`/`time.sleep`/`time.monotonic` -
every case below injects the sample/sleep/now/jitter it needs, matching the old brake's own
testability design, extended by the one new injected primitive (`now`) the sustained-trip window
needs. `apply_load_governor` IS the thin wrapper that touches those real things plus this module's
own process-global state, so its own tests monkeypatch at the `os`/`time` boundary and reset that
global state rather than reaching into the pure functions.

No `db` fixture anywhere in this file - this module does no I/O of its own (its own module
docstring), and neither do these tests.
"""

from typing import Callable, Iterator, List, Optional

import pytest

from django.test import override_settings

from cardpicker.operating_envelope import HOST_LOAD_CEILING
from cardpicker.stage_e_load_brake import (
    ADDITIVE_INCREASE,
    DEFAULT_INTERVAL_S,
    DEFAULT_SOFT_CEILING,
    HOLD,
    MULTIPLICATIVE_DECREASE,
    PROCEED,
    TRIP,
    GovernorState,
    apply_load_governor,
    classify_load,
    run_governor,
)


class TestClassifyLoad:
    def test_a_load_comfortably_below_soft_is_additive_increase(self) -> None:
        assert classify_load(3.0, soft_ceiling=6.0, hard_ceiling=7.0) == ADDITIVE_INCREASE

    def test_the_soft_boundary_itself_holds(self) -> None:
        assert classify_load(6.0, soft_ceiling=6.0, hard_ceiling=7.0) == HOLD

    def test_the_equilibrium_band_holds(self) -> None:
        assert classify_load(6.5, soft_ceiling=6.0, hard_ceiling=7.0) == HOLD

    def test_the_hard_boundary_itself_still_holds_not_decreases(self) -> None:
        # Only a load STRICTLY greater than the hard ceiling triggers a decrease - matches
        # `operating_envelope._bar_breach`'s own `load_avg > HOST_LOAD_CEILING` check exactly, so
        # the two can never disagree about where 7.0 itself falls.
        assert classify_load(7.0, soft_ceiling=6.0, hard_ceiling=7.0) == HOLD

    def test_a_load_above_hard_is_multiplicative_decrease(self) -> None:
        assert classify_load(7.1, soft_ceiling=6.0, hard_ceiling=7.0) == MULTIPLICATIVE_DECREASE

    def test_an_unreadable_load_proceeds_rather_than_blocking(self) -> None:
        assert classify_load(None, soft_ceiling=6.0, hard_ceiling=7.0) == PROCEED

    def test_the_shipped_defaults_produce_a_band_that_is_actually_reachable(self) -> None:
        # Drives `classify_load` itself with the real module-level defaults at a load between them,
        # so a future edit that moved the soft ceiling to or past 7.0 (making the band empty) fails
        # THIS test, not just a comparison.
        assert DEFAULT_SOFT_CEILING < HOST_LOAD_CEILING
        midpoint = (DEFAULT_SOFT_CEILING + HOST_LOAD_CEILING) / 2
        assert classify_load(midpoint, soft_ceiling=DEFAULT_SOFT_CEILING, hard_ceiling=HOST_LOAD_CEILING) == HOLD


def _fixed_jitter(value: float = 1.0) -> Callable[[], float]:
    return lambda: value


def _sequence_sampler(values: List[Optional[float]]) -> Callable[[], Optional[float]]:
    iterator: Iterator[Optional[float]] = iter(values)

    def _sample() -> Optional[float]:
        return next(iterator)

    return _sample


def _sequence_clock(values: List[float]) -> Callable[[], float]:
    iterator: Iterator[float] = iter(values)

    def _now() -> float:
        return next(iterator)

    return _now


def _getloadavg_sequence(one_minute_values: List[float]) -> Callable[[], "tuple[float, float, float]"]:
    iterator: Iterator[float] = iter(one_minute_values)

    def _sample() -> "tuple[float, float, float]":
        value = next(iterator)
        return (value, value, value)

    return _sample


class TestRunGovernorAdditiveIncrease:
    def test_a_load_below_soft_increases_concurrency_by_one_without_sleeping(self) -> None:
        sleeps: List[float] = []
        outcome = run_governor(
            sample=lambda: 3.0,
            sleep=sleeps.append,
            now=lambda: 0.0,
            state=GovernorState(concurrency=2, above_ceiling_since=None),
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.action == ADDITIVE_INCREASE
        assert outcome.state.concurrency == 3
        assert outcome.state.above_ceiling_since is None
        assert outcome.trip is False
        assert sleeps == []

    def test_concurrency_never_exceeds_the_cap(self) -> None:
        outcome = run_governor(
            sample=lambda: 3.0,
            sleep=lambda _s: None,
            now=lambda: 0.0,
            state=GovernorState(concurrency=8, above_ceiling_since=None),
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.state.concurrency == 8

    def test_repeated_quiet_calls_climb_by_one_per_call_and_clamp_at_the_cap(self) -> None:
        state = GovernorState(concurrency=1, above_ceiling_since=None)
        for _ in range(5):
            outcome = run_governor(
                sample=lambda: 3.0,
                sleep=lambda _s: None,
                now=lambda: 0.0,
                state=state,
                soft_ceiling=6.0,
                hard_ceiling=7.0,
                concurrency_cap=4,
                interval_s=15.0,
                max_wait_s=240.0,
                sustained_trip_window_s=120.0,
                jitter=_fixed_jitter(),
            )
            state = outcome.state
        assert state.concurrency == 4  # 1 -> 2 -> 3 -> 4 -> 4 -> 4, clamped at the cap


class TestRunGovernorHold:
    def test_the_in_band_path_holds_concurrency_and_waits_the_specific_expected_amount(self) -> None:
        sleeps: List[float] = []
        outcome = run_governor(
            sample=_sequence_sampler([6.5, 6.5, 5.0]),
            sleep=sleeps.append,
            now=lambda: 0.0,
            state=GovernorState(concurrency=3, above_ceiling_since=None),
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        # Third sample (5.0) is below soft - the loop exits via ADDITIVE_INCREASE, so the two
        # earlier HOLD waits plus the concurrency bump both land on the same returned outcome.
        assert outcome.waits == 2
        assert outcome.seconds == 30.0
        assert sleeps == [15.0, 15.0]
        assert outcome.state.concurrency == 4

    def test_the_in_band_path_proceeds_after_its_cap_rather_than_deadlocking(self) -> None:
        sleeps: List[float] = []
        outcome = run_governor(
            sample=lambda: 6.5,
            sleep=sleeps.append,
            now=lambda: 0.0,
            state=GovernorState(concurrency=3, above_ceiling_since=None),
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=100.0,
            max_wait_s=150.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.action == HOLD
        assert outcome.waits == 2
        assert outcome.seconds == 200.0
        assert outcome.state.concurrency == 3  # HOLD never changes concurrency
        assert outcome.trip is False
        assert sleeps == [100.0, 100.0]


class TestRunGovernorMultiplicativeDecrease:
    def test_a_transient_spike_above_the_hard_ceiling_does_not_trip(self) -> None:
        # Halves concurrency, sleeps proportionally to the overshoot once, then the recovered
        # reading (well below soft) returns immediately - no trip, and no second sleep.
        sleeps: List[float] = []
        outcome = run_governor(
            sample=_sequence_sampler([7.5, 3.0]),
            sleep=sleeps.append,
            now=lambda: 0.0,
            state=GovernorState(concurrency=4, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.trip is False
        assert outcome.action == ADDITIVE_INCREASE
        assert outcome.waits == 1
        assert sleeps == [7.5]  # interval_s(15) * overage(0.5) * jitter(1.0)
        # concurrency 4 -(halved)-> 2 -(additive increase)-> 3
        assert outcome.state.concurrency == 3
        assert outcome.state.above_ceiling_since is None

    def test_concurrency_halves_repeatedly_and_floors_at_one_rather_than_zero(self) -> None:
        # concurrency 5: halved to 2 on the first over-hard read (max(1, 5 // 2)), then to 1 on
        # the second (max(1, 2 // 2)) - odd numbers floor via integer division, never rounding
        # down past 1.
        outcome = run_governor(
            sample=_sequence_sampler([9.0, 9.0, 3.0]),
            sleep=lambda _s: None,
            now=lambda: 0.0,
            state=GovernorState(concurrency=5, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=999999.0,  # never reached within this one call
            jitter=_fixed_jitter(),
        )
        # 5 -(halved)-> 2 -(halved)-> 1 -(additive increase, recovered)-> 2
        assert outcome.state.concurrency == 2

    def test_halving_never_goes_below_one_once_already_at_the_floor(self) -> None:
        outcome = run_governor(
            sample=_sequence_sampler([9.0, 3.0]),
            sleep=lambda _s: None,
            now=_sequence_clock([0.0]),
            state=GovernorState(concurrency=1, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=999999.0,
            jitter=_fixed_jitter(),
        )
        # already at the floor - max(1, 1 // 2) would still be 1, and the recovered second read
        # (3.0) then applies its own additive increase on top of that unchanged floor.
        assert outcome.state.concurrency == 2

    def test_sustained_overload_at_concurrency_one_does_trip(self) -> None:
        # Already at the floor; two consecutive above-hard reads separated by 130s (>= the 120s
        # window) trip on the second one, without an extra sleep on the trip iteration itself.
        sleeps: List[float] = []
        outcome = run_governor(
            sample=_sequence_sampler([8.0, 8.0]),
            sleep=sleeps.append,
            now=_sequence_clock([0.0, 130.0]),
            state=GovernorState(concurrency=1, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.trip is True
        assert outcome.action == TRIP
        assert outcome.state.concurrency == 1
        assert outcome.state.above_ceiling_since == 0.0
        # one sleep before the trip iteration (the first above-hard read starts the clock but
        # cannot itself have elapsed the window), none on the trip iteration itself.
        assert outcome.waits == 1
        assert sleeps == [15.0]  # interval_s(15) * overage(1.0) * jitter(1.0)

    def test_a_brief_overload_that_never_reaches_the_window_never_trips(self) -> None:
        outcome = run_governor(
            sample=_sequence_sampler([8.0, 3.0]),
            sleep=lambda _s: None,
            now=_sequence_clock([0.0]),
            state=GovernorState(concurrency=1, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=15.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert outcome.trip is False
        assert outcome.action == ADDITIVE_INCREASE

    def test_it_resamples_on_every_iteration_rather_than_reusing_a_stale_reading(self) -> None:
        calls = {"count": 0}

        def _sample() -> float:
            calls["count"] += 1
            return 8.0 if calls["count"] < 3 else 3.0

        outcome = run_governor(
            sample=_sample,
            sleep=lambda _s: None,
            now=lambda: 0.0,
            state=GovernorState(concurrency=4, above_ceiling_since=None),
            soft_ceiling=4.5,
            hard_ceiling=7.0,
            concurrency_cap=8,
            interval_s=1.0,
            max_wait_s=240.0,
            sustained_trip_window_s=120.0,
            jitter=_fixed_jitter(),
        )
        assert calls["count"] == 3
        assert outcome.action == ADDITIVE_INCREASE


class TestApplyLoadGovernor:
    def test_below_soft_with_real_settings_increases_concurrency_without_sleeping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("os.getloadavg", lambda: (3.0, 3.0, 3.0))
        sleeps: List[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=2, STAGE_E_GOVERNOR_CONCURRENCY_CAP=8):
            outcome = apply_load_governor()
        assert outcome.action == ADDITIVE_INCREASE
        assert outcome.state.concurrency == 3  # seeded at 2, +1
        assert sleeps == []

    def test_the_shipped_defaults_actually_engage_the_governor_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Drives the real settings.py defaults through the real wrapper, proving the shipped
        # configuration - not a hand-picked test value - produces an engageable equilibrium band.
        monkeypatch.setattr("cardpicker.stage_e_load_brake.random.uniform", lambda a, b: 1.0)
        monkeypatch.setattr("os.getloadavg", _getloadavg_sequence([6.0, 3.0]))
        sleeps: List[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        outcome = apply_load_governor()
        assert outcome.waits == 1
        assert outcome.seconds == DEFAULT_INTERVAL_S
        assert sleeps == [DEFAULT_INTERVAL_S]

    def test_load_above_the_hard_ceiling_halves_concurrency_with_real_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A single over-hard read halves concurrency and sleeps once; the following recovered read
        # (well below soft) returns via ADDITIVE_INCREASE - this call never reaches the
        # concurrency-floor/sustained-trip path, so it needs no fake clock: `apply_load_governor`
        # always drives the real `time.monotonic`, and that path is only reachable after minutes of
        # genuine elapsed wall-clock time (`STAGE_E_LOAD_GOVERNOR_SUSTAINED_TRIP_WINDOW_S`).
        monkeypatch.setattr("cardpicker.stage_e_load_brake.random.uniform", lambda a, b: 1.0)
        monkeypatch.setattr("os.getloadavg", _getloadavg_sequence([7.5, 3.0]))
        monkeypatch.setattr("time.sleep", lambda _s: None)
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=4, STAGE_E_GOVERNOR_CONCURRENCY_CAP=8):
            outcome = apply_load_governor()
        assert outcome.state.concurrency == 3  # 4 halved to 2, then +1 on the recovered read
        assert outcome.trip is False

    def test_a_malformed_setting_degrades_to_unbraked_rather_than_raising(self) -> None:
        # "a typo'd env var must not be able to take the run down" - matches
        # `stage_e_batch_sizing.resolve_micro_batch_size`'s own stated posture for the same class
        # of failure.
        with override_settings(STAGE_E_HOST_LOAD_SOFT_CEILING="not-a-number"):
            outcome = apply_load_governor()
        assert outcome.action == PROCEED
        assert outcome.trip is False
        assert outcome.state.concurrency >= 1

    def test_an_unreadable_loadavg_degrades_to_unbraked_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> "tuple[float, float, float]":
            raise OSError("no such syscall on this platform")

        monkeypatch.setattr("os.getloadavg", _raise)
        outcome = apply_load_governor()
        assert outcome.action == PROCEED

    def test_concurrency_state_survives_across_calls_within_a_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.getloadavg", lambda: (3.0, 3.0, 3.0))
        monkeypatch.setattr("time.sleep", lambda _s: None)
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1, STAGE_E_GOVERNOR_CONCURRENCY_CAP=8):
            first = apply_load_governor()
            second = apply_load_governor()
        assert first.state.concurrency == 2  # seeded at 1, +1
        assert second.state.concurrency == 3  # picks up where the first call left off, +1 again
