"""
Stage E host-load soft brake ("throttle on approach to 7.0") — added 2026-08-05, after
`operating_envelope.HOST_LOAD_CEILING = 7.0` tripped on a 1.1% overshoot
(load_avg 7.0796) and again 2026-08-05 on a 2.5% overshoot (7.17236328125), each costing a stopped
pass and a fresh human `resolve_envelope_trip` action (no self-resume — see that module's own
docstring). The ceiling is a binary cliff: `_bar_breach` trips the instant `load_avg > 7.0`, and
until this module existed there was no feedback from a live load reading anywhere in the dispatch
path except that trip — `stage_e_batch_sizing._duration_limit` derives its own contention term from
the CEILING, not a live sample, on purpose (reproducibility, see that function's own docstring), so
it cannot fill this gap.

WHAT THIS IS NOT: this brake does not soften the 7.0 bar, does not touch `operating_envelope.py`,
and does not suppress a trip. A load that actually crosses 7.0 still reaches
`stage_e_dispatch._sample_envelope_signals`/`check_envelope` and trips exactly as before this
module existed — this module's only power is to DELAY a dispatch decision by re-sampling load in a
band BELOW the ceiling and sleeping while it stays there, so a pass under momentary contention slows
down instead of arriving at the ceiling at all. Called from `stage_e_dispatch.dispatch_micro_batch`,
between the no-self-resume gate and the fresh envelope sample — see that function's own docstring
for why that is the only correct insertion point (a braking process must hold no concurrency-cap
slot, and the brake's own sample must never be reused as the envelope's fresh sample).

MECHANISM — three bands, `STAGE_E_HOST_LOAD_SOFT_CEILING` (default 6.0, ~85% of the hard 7.0) below
`operating_envelope.HOST_LOAD_CEILING` (7.0):

  * `load < soft` — proceed immediately. The common case; zero added cost.
  * `soft <= load <= hard` — sleep, re-sample, repeat.
  * `load > hard` — stop braking at once and let the caller's own fresh envelope sample trip
    honestly. This module never itself decides "trip" — `brake_decision` reports the band, and the
    caller (`dispatch_micro_batch`) is the one that acts on the caller's OWN sample moments later.
  * cumulative wait > `STAGE_E_LOAD_BRAKE_MAX_WAIT_S` (default 240s) — proceed anyway. Best-effort,
    and must never deadlock an unattended multi-hour run.

WHY THIS ACTUALLY REDUCES LOAD: the load a pass generates is its own concurrency
(`settings.STAGE_E_MAX_CONCURRENT_DISPATCHES`). When every resident dispatcher is in the band, each
one pauses independently at its own next batch boundary — the resident process count falls, load
decays, and they resume. The pass self-throttles down to whatever concurrency fits under the
ceiling, continuously, instead of running at full concurrency until it hits the wall and halts.

JITTER IS MANDATORY. Every dispatcher reads the same global `os.getloadavg()`. Without jitter they
would all back off and resume in lockstep — a sawtooth, and a thundering herd on every resume. Each
sleep is `interval_s * uniform(0.75, 1.5)`.

`os.getloadavg()`'s 1-minute figure is an EWMA with a ~60s time constant — it shows only ~63% of a
step change after 60s. A single 15s sleep barely moves it; this is why the default max wait (240s,
~4 time constants, ~98% decay) is what it is, and why this module is written to expect a slow
response rather than tuned as though load reacted instantly to a paused process.

TESTABILITY follows `EnvelopeSignals`' own precedent (`operating_envelope.py`): `brake_decision` is
plain data in, one of three strings out, no I/O. `run_load_brake` is a thin loop with the sampler,
the sleep function and the jitter function all INJECTED, so no test ever monkeypatches
`os.getloadavg` globally or actually sleeps. `apply_load_brake` is the only function that touches
`os`/`time.sleep`/Django settings, and it is a thin, deliberately untested-in-detail wrapper around
`run_load_brake` — see that function's own docstring for why it also can never raise.
"""

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from django.conf import settings

from cardpicker.operating_envelope import HOST_LOAD_CEILING

logger = logging.getLogger(__name__)

# Defaults, active out of the box - an
# instance maintainer running their own catalogue for the first time gets the brake without having
# to know it exists or opt in, matching this project's standing "a knob that has to be set to do
# anything is the wrong polarity" posture (see settings.py's STAGE_E_MAX_CONCURRENT_DISPATCHES/
# STAGE_E_STREAMING_ENABLED comments for the same convention applied elsewhere in this subsystem).
DEFAULT_SOFT_CEILING = 6.0
DEFAULT_INTERVAL_S = 15.0
DEFAULT_MAX_WAIT_S = 240.0

# `brake_decision`'s three possible answers - plain strings rather than an enum, matching
# `operating_envelope.EnvelopeTrip.Bar`'s own "match the caller's existing string convention"
# precedent for a small, stable, cross-module vocabulary.
WAIT = "wait"
PROCEED = "proceed"
TRIP = "trip"


def brake_decision(load_avg: Optional[float], soft_ceiling: float, hard_ceiling: float) -> str:
    """
    The pure primitive - one load reading in, one band out, no I/O, no sleep, no settings read.
    `load_avg=None` (a platform without a readable `os.getloadavg`, matching
    `stage_e_dispatch._sample_envelope_signals`'s own documented convention) always returns
    `PROCEED` - a brake that cannot see load must never block a dispatch on that account.

    Boundaries are both closed on the WAIT side, per the brief's own table: `load == soft_ceiling`
    and `load == hard_ceiling` both wait, matching "soft <= load <= hard -> sleep, re-sample,
    repeat" verbatim. Only `load > hard_ceiling` (strictly greater, matching
    `operating_envelope._bar_breach`'s own `load_avg > HOST_LOAD_CEILING` check byte-for-byte) is
    TRIP - this function must classify a genuine breach identically to the envelope primitive it
    sits in front of, or the two could disagree about where 7.0 itself falls.
    """
    if load_avg is None:
        return PROCEED
    if load_avg > hard_ceiling:
        return TRIP
    if load_avg >= soft_ceiling:
        return WAIT
    return PROCEED


@dataclass(frozen=True)
class BrakeOutcome:
    """What one `run_load_brake` call did - zero waits/zero seconds is indistinguishable from
    "the brake never engaged" and from "the brake was never reached", both of which are the
    correct reading for a caller that only wants to know whether THIS call was delayed."""

    waits: int = 0
    seconds: float = 0.0


def run_load_brake(
    sample: Callable[[], Optional[float]],
    sleep: Callable[[float], None],
    soft_ceiling: float,
    hard_ceiling: float,
    interval_s: float,
    max_wait_s: float,
    jitter: Callable[[], float] = lambda: random.uniform(0.75, 1.5),
) -> BrakeOutcome:
    """
    The thin loop (module docstring's TESTABILITY section) - `sample`, `sleep` and `jitter` are all
    injected so a test drives this deterministically without touching `os.getloadavg` or actually
    sleeping. Re-samples via `sample()` on every iteration (never reuses a reading), matching the
    brief's "must re-sample rather than reuse a stale sample" requirement.

    Stops WAITing the moment `brake_decision` reports anything other than `WAIT` (a `TRIP` reading
    stops braking AT ONCE and returns immediately, letting the caller's own fresh envelope sample
    trip honestly a moment later - this function never itself trips anything), or the moment
    cumulative wait already spent would meet or exceed `max_wait_s` before another sleep - checked
    BEFORE sleeping, not after, so the returned `seconds` can never itself exceed `max_wait_s`.
    """
    waits = 0
    total_wait = 0.0
    while True:
        decision = brake_decision(sample(), soft_ceiling, hard_ceiling)
        if decision != WAIT:
            return BrakeOutcome(waits=waits, seconds=round(total_wait, 3))
        if total_wait >= max_wait_s:
            return BrakeOutcome(waits=waits, seconds=round(total_wait, 3))
        wait_for = interval_s * jitter()
        sleep(wait_for)
        waits += 1
        total_wait += wait_for


def _sample_load_avg() -> Optional[float]:
    """Matches `stage_e_dispatch._sample_envelope_signals`'s own `os.getloadavg` try/except
    convention byte-for-byte - `None` on a platform without it, never an exception."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def apply_load_brake() -> BrakeOutcome:
    """
    THE entry point `dispatch_micro_batch` calls - reads the three settings, samples real load via
    `os.getloadavg`, sleeps via real `time.sleep`, and drives `run_load_brake`.

    Wrapped in a bare `try/except Exception` that returns an unbraked `BrakeOutcome()` on ANY
    error - matching `stage_e_batch_sizing.resolve_micro_batch_size`'s own stated posture ("a
    typo'd env var must not be able to take the run down"). A malformed setting, a transient
    `os.getloadavg` failure mid-loop, or anything else this function did not anticipate must
    degrade to "dispatch proceeds as if unbraked", never to a broken pass - the brake is a
    convenience the envelope's own hard ceiling does not depend on.
    """
    try:
        soft_ceiling = float(getattr(settings, "STAGE_E_HOST_LOAD_SOFT_CEILING", DEFAULT_SOFT_CEILING))
        interval_s = float(getattr(settings, "STAGE_E_LOAD_BRAKE_INTERVAL_S", DEFAULT_INTERVAL_S))
        max_wait_s = float(getattr(settings, "STAGE_E_LOAD_BRAKE_MAX_WAIT_S", DEFAULT_MAX_WAIT_S))
        outcome = run_load_brake(
            sample=_sample_load_avg,
            sleep=time.sleep,
            soft_ceiling=soft_ceiling,
            hard_ceiling=HOST_LOAD_CEILING,
            interval_s=interval_s,
            max_wait_s=max_wait_s,
        )
        if outcome.waits:
            logger.info(
                "Stage E load brake engaged - %s wait(s), %.1fs total, before this dispatch",
                outcome.waits,
                outcome.seconds,
            )
        return outcome
    except Exception:
        logger.exception("Stage E load brake failed - proceeding unbraked")
        return BrakeOutcome()
