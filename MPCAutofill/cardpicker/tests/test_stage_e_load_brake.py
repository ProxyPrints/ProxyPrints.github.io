"""
Tests for `cardpicker.stage_e_load_brake` (added 2026-08-05).

`brake_decision` and `run_load_brake` never touch `os.getloadavg`/`time.sleep` - every case below
injects the sample/sleep/jitter it needs, matching that module's own `EnvelopeSignals`-precedent
testability design. `apply_load_brake` IS the thin wrapper that touches those real things, so its
own tests monkeypatch at the `os`/`time` boundary rather than reaching into the pure functions.

No `db` fixture anywhere in this file - this module does no I/O of its own (its own module
docstring), and neither do these tests.
"""

from typing import Callable, Iterator, List, Optional

import pytest

from django.test import override_settings

from cardpicker.operating_envelope import HOST_LOAD_CEILING
from cardpicker.stage_e_load_brake import (
    DEFAULT_INTERVAL_S,
    DEFAULT_SOFT_CEILING,
    PROCEED,
    TRIP,
    WAIT,
    BrakeOutcome,
    apply_load_brake,
    brake_decision,
    run_load_brake,
)


class TestBrakeDecision:
    def test_a_load_comfortably_below_soft_proceeds(self) -> None:
        assert brake_decision(3.0, soft_ceiling=6.0, hard_ceiling=7.0) == PROCEED

    def test_the_soft_boundary_itself_waits(self) -> None:
        assert brake_decision(6.0, soft_ceiling=6.0, hard_ceiling=7.0) == WAIT

    def test_the_approach_band_waits(self) -> None:
        assert brake_decision(6.5, soft_ceiling=6.0, hard_ceiling=7.0) == WAIT

    def test_the_hard_boundary_itself_still_waits_not_trips(self) -> None:
        # Only a load STRICTLY greater than the hard ceiling trips - matches
        # `operating_envelope._bar_breach`'s own `load_avg > HOST_LOAD_CEILING` check exactly, so
        # the two can never disagree about where 7.0 itself falls.
        assert brake_decision(7.0, soft_ceiling=6.0, hard_ceiling=7.0) == WAIT

    def test_a_load_above_hard_trips(self) -> None:
        assert brake_decision(7.1, soft_ceiling=6.0, hard_ceiling=7.0) == TRIP

    def test_an_unreadable_load_proceeds_rather_than_blocking(self) -> None:
        # Matches `stage_e_dispatch._sample_envelope_signals`'s own "None means skip this bar"
        # convention - a brake that cannot see load must never withhold a dispatch on that account.
        assert brake_decision(None, soft_ceiling=6.0, hard_ceiling=7.0) == PROCEED

    def test_the_shipped_defaults_produce_a_band_that_is_actually_reachable(self) -> None:
        # Not a static "soft < hard" assertion - drives `brake_decision` itself with the real
        # module-level defaults at a load between them, so a future edit that moved the soft
        # ceiling to or past 7.0 (making the band empty) fails THIS test, not just a comparison.
        assert DEFAULT_SOFT_CEILING < HOST_LOAD_CEILING
        midpoint = (DEFAULT_SOFT_CEILING + HOST_LOAD_CEILING) / 2
        assert brake_decision(midpoint, soft_ceiling=DEFAULT_SOFT_CEILING, hard_ceiling=HOST_LOAD_CEILING) == WAIT


def _fixed_jitter(value: float = 1.0) -> Callable[[], float]:
    return lambda: value


def _sequence_sampler(values: List[Optional[float]]) -> Callable[[], Optional[float]]:
    iterator: Iterator[Optional[float]] = iter(values)

    def _sample() -> Optional[float]:
        return next(iterator)

    return _sample


def _getloadavg_sequence(one_minute_values: List[float]) -> Callable[[], "tuple[float, float, float]"]:
    """Shapes a fixed sequence into `os.getloadavg()`'s own 3-tuple return type - only the first
    element (the one-minute average) is ever read by this module."""
    iterator: Iterator[float] = iter(one_minute_values)

    def _sample() -> "tuple[float, float, float]":
        value = next(iterator)
        return (value, value, value)

    return _sample


class TestRunLoadBrake:
    def test_a_load_below_soft_produces_no_waiting_and_never_sleeps(self) -> None:
        sleeps: List[float] = []
        outcome = run_load_brake(
            sample=lambda: 3.0,
            sleep=sleeps.append,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=15.0,
            max_wait_s=240.0,
            jitter=_fixed_jitter(),
        )
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)
        assert sleeps == []

    def test_a_load_in_the_approach_band_waits_the_specific_expected_amount(self) -> None:
        # Two WAIT reads followed by a PROCEED read - the specific value asserted, not "is less
        # than": exactly 2 waits, exactly 15.0 * fixed-jitter(1.0) * 2 = 30.0 seconds slept.
        sleeps: List[float] = []
        outcome = run_load_brake(
            sample=_sequence_sampler([6.5, 6.5, 5.0]),
            sleep=sleeps.append,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=15.0,
            max_wait_s=240.0,
            jitter=_fixed_jitter(),
        )
        assert outcome == BrakeOutcome(waits=2, seconds=30.0)
        assert sleeps == [15.0, 15.0]

    def test_a_load_above_the_ceiling_stops_at_once_with_zero_wait(self) -> None:
        # The brake must never delay - and so never mask - a genuine breach: a load already past
        # the hard ceiling gets zero waits, zero seconds, and no sleep call at all.
        sleeps: List[float] = []
        outcome = run_load_brake(
            sample=lambda: 8.0,
            sleep=sleeps.append,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=15.0,
            max_wait_s=240.0,
            jitter=_fixed_jitter(),
        )
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)
        assert sleeps == []

    def test_cumulative_wait_past_the_bound_proceeds_anyway(self) -> None:
        # Load never leaves the band on its own; only max_wait_s ends the loop. Traced by hand:
        # iter 1 (total 0 < 150) sleeps 100 -> total 100; iter 2 (total 100 < 150) sleeps 100 ->
        # total 200; iter 3 (total 200 >= 150) returns without a third sleep.
        sleeps: List[float] = []
        outcome = run_load_brake(
            sample=lambda: 6.5,
            sleep=sleeps.append,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=100.0,
            max_wait_s=150.0,
            jitter=_fixed_jitter(),
        )
        assert outcome == BrakeOutcome(waits=2, seconds=200.0)
        assert sleeps == [100.0, 100.0]

    def test_it_resamples_on_every_iteration_rather_than_reusing_a_stale_reading(self) -> None:
        calls = {"count": 0}

        def _sample() -> float:
            calls["count"] += 1
            return 6.5 if calls["count"] < 3 else 5.0

        outcome = run_load_brake(
            sample=_sample,
            sleep=lambda _seconds: None,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=1.0,
            max_wait_s=240.0,
            jitter=_fixed_jitter(),
        )
        assert calls["count"] == 3
        assert outcome == BrakeOutcome(waits=2, seconds=2.0)

    def test_jitter_is_applied_to_every_sleep(self) -> None:
        sleeps: List[float] = []
        outcome = run_load_brake(
            sample=_sequence_sampler([6.5, 5.0]),
            sleep=sleeps.append,
            soft_ceiling=6.0,
            hard_ceiling=7.0,
            interval_s=10.0,
            max_wait_s=240.0,
            jitter=_fixed_jitter(0.75),
        )
        assert sleeps == [7.5]
        assert outcome == BrakeOutcome(waits=1, seconds=7.5)


class TestApplyLoadBrake:
    def test_below_soft_with_real_settings_proceeds_without_sleeping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.getloadavg", lambda: (3.0, 3.0, 3.0))
        sleeps: List[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)
        assert sleeps == []

    def test_the_shipped_defaults_actually_engage_the_brake_end_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Drives the real settings.py defaults (6.0 / 15 / 240) through the real wrapper, proving
        # the shipped configuration - not a hand-picked test value - produces an engageable band.
        monkeypatch.setattr("cardpicker.stage_e_load_brake.random.uniform", lambda a, b: 1.0)
        monkeypatch.setattr("os.getloadavg", _getloadavg_sequence([6.5, 5.0]))
        sleeps: List[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=1, seconds=DEFAULT_INTERVAL_S)
        assert sleeps == [DEFAULT_INTERVAL_S]

    def test_load_above_the_hard_ceiling_never_sleeps_even_with_real_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("os.getloadavg", lambda: (7.5, 7.5, 7.5))
        sleeps: List[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)
        assert sleeps == []

    def test_a_malformed_setting_degrades_to_unbraked_rather_than_raising(self) -> None:
        # "a typo'd env var must not be able to take the run down" - matches
        # `stage_e_batch_sizing.resolve_micro_batch_size`'s own stated posture for the same class
        # of failure.
        with override_settings(STAGE_E_HOST_LOAD_SOFT_CEILING="not-a-number"):
            outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)

    def test_an_unreadable_loadavg_degrades_to_unbraked_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> "tuple[float, float, float]":
            raise OSError("no such syscall on this platform")

        monkeypatch.setattr("os.getloadavg", _raise)
        outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=0, seconds=0.0)

    def test_max_wait_setting_is_honoured_from_real_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("cardpicker.stage_e_load_brake.random.uniform", lambda a, b: 1.0)
        with override_settings(STAGE_E_LOAD_BRAKE_INTERVAL_S=100.0, STAGE_E_LOAD_BRAKE_MAX_WAIT_S=150.0):
            monkeypatch.setattr("os.getloadavg", lambda: (6.5, 6.5, 6.5))
            sleeps: List[float] = []
            monkeypatch.setattr("time.sleep", sleeps.append)
            outcome = apply_load_brake()
        assert outcome == BrakeOutcome(waits=2, seconds=200.0)
        assert sleeps == [100.0, 100.0]
        assert outcome.seconds > 150.0  # proceeded past the bound rather than deadlocking on it
