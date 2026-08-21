"""
Stage E host-load AIMD governor — replaces the three-band soft brake (2026-08-05) after a 2026-08-13
incident it could not prevent: a 9-hour Stage D backfill launched at 02:10:21Z on a host also running
several developer agent sessions, and 23 seconds later `envtrip-20260813T021044-b5d7524a` opened with
reason `host_load` and halted the pass permanently (no self-resume — see `operating_envelope.py`'s own
docstring). Load had settled to 6.27 when sampled externally moments later — a spike, not sustained
overload. The old brake's TRIP band did not distinguish the two: any single reading above
`operating_envelope.HOST_LOAD_CEILING` (7.0) stopped braking at once and let the caller's own fresh
envelope sample trip honestly, regardless of whether the load-generating burst had already passed.

WHAT THIS IS: additive-increase, multiplicative-decrease — the control law TCP uses for congestion —
with host load as the congestion signal and this pass's own dispatch concurrency as the throttle
position. This is TCP's problem: independent OS processes (one per django-q2 worker, plus the shakedown/
pipeline drivers — see `stage_e_concurrency.py`'s own module docstring for why they are always separate
processes, never threads) competing for a shared resource (this host's CPU/Postgres capacity) with no
central coordinator, needing to converge on a fair share nobody tells them. Called from
`stage_e_dispatch.dispatch_micro_batch`, in the exact same slot the old brake occupied — between the
no-self-resume gate and the fresh envelope sample (see that function's own docstring for why that is the
only correct insertion point: a governing process must hold no concurrency-cap slot while it decides, and
its own sample must never be reused as the envelope's fresh sample).

THE CONTROL LAW — one classification per call (`classify_load`), one response per band:

  * `load < STAGE_E_HOST_LOAD_SOFT_CEILING` (default 4.5, moved down from the old brake's 6.0 — see
    below) — ADDITIVE INCREASE. Concurrency +1, bounded by the concurrency cap (below). No sleep: a quiet
    box should be used properly, not delayed on the way to using it.
  * `soft <= load <= HOST_LOAD_CEILING` (7.0, unmoved) — HOLD. This is the intended equilibrium:
    concurrency is left unchanged. Sleeps and re-samples (`interval_s * uniform(0.75, 1.5)`, matching the
    old brake's own jitter requirement — see "JITTER IS MANDATORY" below), bounded by
    `STAGE_E_LOAD_BRAKE_MAX_WAIT_S` (default 240s, unchanged), then proceeds anyway. Identical in shape
    to the old brake's WAIT band; only the label changed, because concurrency no longer moves here.
  * `load > HOST_LOAD_CEILING` — MULTIPLICATIVE DECREASE. If concurrency is above its floor of 1, it is
    halved (`max(1, concurrency // 2)`) and this call sleeps for `interval_s * (load_avg -
    HOST_LOAD_CEILING)` (jittered) — proportional to how far over the ceiling load is, not a flat
    interval, so a narrow overshoot barely delays anything and a real spike backs off hard. It then
    re-samples: if load has fallen out of this band, the call returns (at the new, lower concurrency)
    without ever reaching the envelope's own fresh sample while load was still high — this is what makes
    a transient spike NOT trip. "Back off fast, recover slowly" (the additive step above is +1, not
    +half) is the asymmetry that makes AIMD converge instead of oscillate.
  * Concurrency is ALREADY at its floor of 1 and load is STILL above the hard ceiling — the new trip
    condition. The pass has throttled as far as it can and the box is still overloaded; that overload is
    not this pass's own concurrency to shed, so continuing to back off would just add wait time with
    nothing left to reduce. Rather than deciding "trip" itself (this module still touches no
    `operating_envelope.py`, no `EnvelopeTrip`, no DB row of its own — the module docstring's old
    "WHAT THIS IS NOT" boundary survives unchanged), this state's response is to STOP GOVERNING at once,
    exactly as the old brake's TRIP band did, once a SUSTAINED window (below) at the floor has elapsed —
    so the caller's own fresh `check_envelope` sample, moments later, sees the still-elevated load and
    trips it honestly. `operating_envelope._bar_breach`'s own `load_avg > HOST_LOAD_CEILING` check is
    untouched, so the two can never disagree about where 7.0 itself falls (`classify_load` uses the
    identical strict `>` comparison — see its own docstring).

WHY THE SOFT CEILING MOVED 6.0 -> 4.5 (HARD CEILING UNCHANGED AT 7.0). The old value was read off two
narrow-overshoot incidents (7.0796, 7.17236328125) as "the top of a band with room to notice an approach"
— sized only for HOLD's re-sample-and-wait behaviour. This governor also climbs concurrency in that same
sub-soft space, and needs room to do so *before* nearing the ceiling, not just room to notice the
ceiling coming: 4.5 is roughly two additive-increase steps' worth of headroom below the old 6.0, so a
quiet box is found and used well before load risks entering the equilibrium band at all.
`HOST_LOAD_CEILING` (7.0) is untouched — this host has 8 cores and also serves live traffic
(`api.proxyprints.ca`); that reserve is the live site's own latency margin, not this governor's to spend.

CONCURRENCY IS BOUNDED ABOVE BY `STAGE_E_GOVERNOR_CONCURRENCY_CAP` (default `os.cpu_count() - 1`, floored
at 1), NOT by `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` — that setting is now only this governor's
SEED value (its concurrency the first time a process calls `apply_load_governor`), because a static
config for "how many dispatches may run at once" and a dynamic one both trying to be the enforced ceiling
would fight each other. Climbing past the old static default (2) is exactly the point of ADDITIVE
INCREASE on a quiet box; climbing without any explicit bound is not, because more concurrent dispatches
means more concurrent Postgres work, and Postgres also serves the live site — `cores - 1` is a real
resource backstop for that, made explicit and configurable rather than left implicit in a per-run
concurrency count nobody set on purpose. Load is the real, live constraint (the whole point of this
governor); the cap is only the ceiling load's own reading can never be trusted to catch fast enough on
its own — see the EWMA note below.

WHY THE SUSTAINED WINDOW EXISTS, AND WHY IT IS 120s. `os.getloadavg()`'s 1-minute figure is an EWMA with
a ~60s time constant (it shows only ~63% of a step change after 60s, ~87% after two constants) — a window
shorter than ~2 minutes would be measuring noise in that same signal, not a genuine sustained condition.
`DEFAULT_SUSTAINED_TRIP_WINDOW_S` is 120s: two time constants, long enough that a reading which is still
above the hard ceiling throughout it reflects real, persistent load rather than the sensor's own lag. The
same slowness is why this governor's ADDITIVE INCREASE step is +1, not some larger jump, and why it does
not attempt to "out-run" the sensor with aggressive climbs — `os.getloadavg()` will not confirm new
headroom quickly regardless of how eagerly this governor asks for it.

WHERE CONCURRENCY STATE LIVES, AND WHY THAT IS SAFE WITH MULTIPLE RESIDENT DISPATCHERS. `apply_load_governor`
keeps its `GovernorState` (current concurrency, and — only while at the floor and over the hard ceiling —
the wall-clock moment that condition started) in a module-level global, `_state`, seeded once per OS
process on that process's first call. This is deliberately NOT shared across processes (no cache, no DB
row, no IPC) — and that is the correct design, not a gap, for the same reason a cache-based concurrency
counter was already rejected in `stage_e_concurrency.py`'s own module docstring: django-q2's workers are
separate OS PROCESSES, so any single shared counter would need new coordination infrastructure this
governor has no more mandate to introduce than that module did. AIMD does not need one: every resident
process independently classifies the SAME externally-shared signal (`os.getloadavg()`, which already
reflects every process's combined contribution to load) and independently adjusts its own idea of how
much concurrency it should be using, exactly as independent TCP flows sharing one bottleneck link
converge on a fair split without ever talking to each other directly — the shared signal IS the
coordination. Within one process, calls are never concurrent with each other either: each django-q2
worker executes one task at a time, and every other caller (`stream_full_catalog`, `stage_e_shakedown`,
`run_pipeline`) drives `dispatch_micro_batch` synchronously in its own loop — so the module global needs
no lock. This governor's concurrency choice is fed forward to `stage_e_concurrency.try_acquire_dispatch_slot`
as `max_slots` (see that module's own docstring for the advisory-lock mechanism this bounds) — the
governor decides the throttle position, that module still enforces it.

WHAT THIS IS NOT (survives from the old brake, unchanged): this module does not move the 7.0 cliff, does
not touch `operating_envelope.py`, and does not persist a trip itself. A load that genuinely crosses 7.0
while this governor is already at its floor and has been for the sustained window still reaches
`stage_e_dispatch._sample_envelope_signals`/`check_envelope` and trips exactly as before this governor
existed — this module's only power is to delay a dispatch decision (by re-sampling below the ceiling, or
backing off while above it) so that a pass under momentary contention slows down and recovers instead of
arriving at the ceiling at all.

JITTER IS MANDATORY, unchanged from the old brake. Every dispatcher reads the same global
`os.getloadavg()`. Without jitter they would all back off and resume in lockstep — a sawtooth, and a
thundering herd on every resume. Every sleep in this module, in both the HOLD band and the
MULTIPLICATIVE DECREASE band, is `base * uniform(0.75, 1.5)`.

TESTABILITY follows the old brake's own precedent, extended by one more injected primitive: `now`.
`classify_load` and `run_governor` never touch `os.getloadavg`/`time.sleep`/`time.monotonic` — `sample`,
`sleep`, `now` and `jitter` are all injected, so no test monkeypatches any of them globally or actually
sleeps or waits on a real clock. `apply_load_governor` is the only function that touches `os`/`time`/
Django settings/this module's own process-global state, and it is a thin, deliberately untested-in-detail
wrapper around `run_governor` that can never raise (see that function's own docstring for why).
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

# Defaults, active out of the box - matching this project's standing "a knob that has to be set to do
# anything is the wrong polarity" posture (see settings.py's STAGE_E_MAX_CONCURRENT_DISPATCHES/
# STAGE_E_STREAMING_ENABLED comments for the same convention applied elsewhere in this subsystem).
#
# DEFAULT_SOFT_CEILING moved 6.0 -> 4.5 (module docstring's own "WHY THE SOFT CEILING MOVED" section).
DEFAULT_SOFT_CEILING = 4.5
DEFAULT_INTERVAL_S = 15.0
DEFAULT_MAX_WAIT_S = 240.0
# Two EWMA time constants of os.getloadavg()'s 1-minute figure (module docstring's own "WHY THE
# SUSTAINED WINDOW EXISTS" section) - the floor below which a "sustained" reading is really sensor lag.
DEFAULT_SUSTAINED_TRIP_WINDOW_S = 120.0
# cores - 1, floored at 1 - module docstring's "CONCURRENCY IS BOUNDED ABOVE" section. Computed here so
# a test importing this module sees the same formula settings.py's own
# STAGE_E_GOVERNOR_CONCURRENCY_CAP default uses, without duplicating a literal number between the two.
DEFAULT_CONCURRENCY_CAP = max(1, (os.cpu_count() or 2) - 1)

# `classify_load`'s four possible bands - plain strings rather than an enum, matching
# `operating_envelope.EnvelopeTrip.Bar`'s own "match the caller's existing string convention" precedent.
PROCEED = "proceed"
ADDITIVE_INCREASE = "additive_increase"
HOLD = "hold"
MULTIPLICATIVE_DECREASE = "multiplicative_decrease"
TRIP = "trip"


def classify_load(load_avg: Optional[float], soft_ceiling: float, hard_ceiling: float) -> str:
    """
    The pure per-sample primitive - one load reading in, one band out, no I/O, no sleep, no settings
    read, no concurrency logic (that lives in `run_governor`, since it depends on state this function
    deliberately does not see). `load_avg=None` (a platform without a readable `os.getloadavg`, matching
    `stage_e_dispatch._sample_envelope_signals`'s own documented convention) always returns `PROCEED` - a
    governor that cannot see load must never block or reshape a dispatch on that account.

    Boundaries: `load == soft_ceiling` and `load == hard_ceiling` both classify as `HOLD` - only
    `load > hard_ceiling` (strictly greater, matching `operating_envelope._bar_breach`'s own
    `load_avg > HOST_LOAD_CEILING` check byte-for-byte) is `MULTIPLICATIVE_DECREASE`. This function must
    classify a genuine breach identically to the envelope primitive it sits in front of, or the two could
    disagree about where 7.0 itself falls.
    """
    if load_avg is None:
        return PROCEED
    if load_avg > hard_ceiling:
        return MULTIPLICATIVE_DECREASE
    if load_avg >= soft_ceiling:
        return HOLD
    return ADDITIVE_INCREASE


@dataclass(frozen=True)
class GovernorState:
    """
    The AIMD state one `run_governor` call reads and returns an updated copy of - the module docstring's
    "WHERE CONCURRENCY STATE LIVES" section covers where this is kept between calls and why that is safe.

    `above_ceiling_since` is `None` whenever concurrency is above its floor of 1, OR concurrency is at
    the floor but load has not (yet, or currently) been read above the hard ceiling - it is only ever a
    real wall-clock reading while concurrency is AT the floor AND the most recent classification was
    `MULTIPLICATIVE_DECREASE`. Threading it back out to the caller (rather than resetting it to `None` on
    every call) is what lets the sustained-trip window span MULTIPLE `run_governor` calls - a single
    micro-batch dispatch is far shorter than the 120s default window, so the window can only ever be
    observed across several consecutive dispatches, exactly as intended (module docstring's own
    "WHY THE SUSTAINED WINDOW EXISTS" section).
    """

    concurrency: int
    above_ceiling_since: Optional[float] = None


@dataclass(frozen=True)
class GovernorOutcome:
    """
    What one `run_governor`/`apply_load_governor` call did. `state` is the new `GovernorState` the caller
    must persist for the next call (`apply_load_governor` does this itself via its own module-global -
    see that function's docstring). `trip=True` means this call observed the new trip condition
    (concurrency already at floor, load sustained above the hard ceiling for the full window) and
    returned WITHOUT sleeping further, precisely so the caller's own fresh `check_envelope` sample -
    reached moments later - sees the still-elevated load and trips it honestly; `trip` here is an
    observability signal for the caller, never itself a persisted `EnvelopeTrip` row (module docstring's
    own "WHAT THIS IS NOT" section - this module still touches no `operating_envelope.py` state).
    """

    state: GovernorState
    action: str
    waits: int = 0
    seconds: float = 0.0
    trip: bool = False


def run_governor(
    sample: Callable[[], Optional[float]],
    sleep: Callable[[float], None],
    now: Callable[[], float],
    state: GovernorState,
    soft_ceiling: float,
    hard_ceiling: float,
    concurrency_cap: int,
    interval_s: float,
    max_wait_s: float,
    sustained_trip_window_s: float,
    jitter: Callable[[], float] = lambda: random.uniform(0.75, 1.5),
) -> GovernorOutcome:
    """
    The thin loop (module docstring's TESTABILITY section) - `sample`, `sleep`, `now` and `jitter` are
    all injected so a test drives this deterministically without touching `os.getloadavg`,
    `time.sleep`/`time.monotonic`, or actually waiting. Re-samples via `sample()` on every iteration
    (never reuses a reading), matching the old brake's own "must re-sample rather than reuse a stale
    sample" requirement.

    Four exits, one per band `classify_load` can report for the CURRENT sample:
      - `PROCEED` (unreadable load) / `ADDITIVE_INCREASE` (below soft) - return immediately, no sleep.
        `ADDITIVE_INCREASE` bumps concurrency by exactly one, bounded by `concurrency_cap`.
      - `HOLD` (in the soft..hard band) - sleeps `interval_s * jitter()` and re-samples, exactly like the
        old brake's own WAIT band, bounded by `max_wait_s` (checked BEFORE sleeping, so the returned
        `seconds` can never itself exceed it) - "the in-band path proceeds after its cap rather than
        deadlocking" survives unchanged from the old brake.
      - `MULTIPLICATIVE_DECREASE` (above hard) with concurrency still above its floor - halves
        concurrency (floor 1), clears `above_ceiling_since` (this call did not spend any time AT the
        floor while overloaded - the earliest it could is the NEXT iteration), sleeps
        `interval_s * (load_avg - hard_ceiling) * jitter()` (proportional to the overshoot, not a flat
        interval), and re-samples - never returns from this branch without sleeping first, so a transient
        spike is given the chance to have decayed by the time this call ever returns control to the
        caller's own fresh envelope sample.
      - `MULTIPLICATIVE_DECREASE` with concurrency ALREADY at its floor of 1 - starts (or continues) the
        sustained-overload clock. Once `now() - above_ceiling_since >= sustained_trip_window_s`, returns
        immediately (`trip=True`, no further sleep) rather than continuing to back off with nothing left
        to reduce - the new trip condition (module docstring). Otherwise sleeps proportionally to the
        overshoot exactly as the concurrency>1 case does, and loops.

    This function itself never trips anything and never touches `operating_envelope.py` - `trip=True` is
    purely "stop governing, let the caller's own next check decide" (see `GovernorOutcome`'s own
    docstring).
    """
    concurrency = state.concurrency
    above_ceiling_since = state.above_ceiling_since
    waits = 0
    total_wait = 0.0

    while True:
        load_avg = sample()
        band = classify_load(load_avg, soft_ceiling, hard_ceiling)

        if band in (PROCEED, ADDITIVE_INCREASE):
            if band == ADDITIVE_INCREASE:
                concurrency = min(concurrency + 1, concurrency_cap)
            return GovernorOutcome(
                state=GovernorState(concurrency=concurrency, above_ceiling_since=None),
                action=band,
                waits=waits,
                seconds=round(total_wait, 3),
            )

        if band == HOLD:
            if total_wait >= max_wait_s:
                return GovernorOutcome(
                    state=GovernorState(concurrency=concurrency, above_ceiling_since=None),
                    action=HOLD,
                    waits=waits,
                    seconds=round(total_wait, 3),
                )
            wait_for = interval_s * jitter()
            sleep(wait_for)
            waits += 1
            total_wait += wait_for
            continue

        # band == MULTIPLICATIVE_DECREASE (load_avg > hard_ceiling, load_avg is not None here)
        assert load_avg is not None
        if concurrency > 1:
            concurrency = max(1, concurrency // 2)
            above_ceiling_since = None
        else:
            current_time = now()
            if above_ceiling_since is None:
                above_ceiling_since = current_time
            elif current_time - above_ceiling_since >= sustained_trip_window_s:
                return GovernorOutcome(
                    state=GovernorState(concurrency=concurrency, above_ceiling_since=above_ceiling_since),
                    action=TRIP,
                    waits=waits,
                    seconds=round(total_wait, 3),
                    trip=True,
                )

        overage = load_avg - hard_ceiling
        wait_for = interval_s * overage * jitter()
        sleep(wait_for)
        waits += 1
        total_wait += wait_for
        continue


def _sample_load_avg() -> Optional[float]:
    """Matches `stage_e_dispatch._sample_envelope_signals`'s own `os.getloadavg` try/except convention
    byte-for-byte - `None` on a platform without it, never an exception."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def _concurrency_cap() -> int:
    """`STAGE_E_GOVERNOR_CONCURRENCY_CAP` (module docstring's "CONCURRENCY IS BOUNDED ABOVE" section),
    floored at 1 - the same "an ops typo must not silently disable dispatch forever" posture
    `stage_e_concurrency._slot_count` already applies to `STAGE_E_MAX_CONCURRENT_DISPATCHES`."""
    return max(1, int(getattr(settings, "STAGE_E_GOVERNOR_CONCURRENCY_CAP", DEFAULT_CONCURRENCY_CAP)))


def _seed_concurrency() -> int:
    """This governor's STARTING concurrency, the first time a process calls `apply_load_governor` -
    `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` (the pre-governor static cap) read as a seed only, not
    as an ongoing ceiling (module docstring's "CONCURRENCY IS BOUNDED ABOVE" section covers why the two
    roles are deliberately different settings now), clamped into `[1, cap]`."""
    cap = _concurrency_cap()
    configured = int(getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2))
    return min(max(1, configured), cap)


# The AIMD state this OS process's dispatches converge on - a module-level global, deliberately not
# shared across processes. See the module docstring's own "WHERE CONCURRENCY STATE LIVES" section for
# why that is the safe, intended design rather than a coordination gap. Seeded lazily (`None` until the
# first `apply_load_governor` call) so `_seed_concurrency`'s settings read happens with Django's settings
# fully configured, never at import time.
_state: Optional[GovernorState] = None


def apply_load_governor() -> GovernorOutcome:
    """
    THE entry point `dispatch_micro_batch` calls - reads the settings, samples real load via
    `os.getloadavg`, sleeps via real `time.sleep`, times via real `time.monotonic`, and drives
    `run_governor` against (and updates) this process's own module-global `_state`.

    Wrapped in a bare `try/except Exception` that proceeds unbraked at the LAST KNOWN GOOD concurrency
    (or this process's seed value, if the failure happened before `_state` was ever set) on ANY error -
    matching `stage_e_batch_sizing.resolve_micro_batch_size`'s own stated posture ("a typo'd env var must
    not be able to take the run down"). A malformed setting, a transient `os.getloadavg` failure mid-loop,
    or anything else this function did not anticipate must degrade to "dispatch proceeds, at whatever
    concurrency was already established", never to a broken pass - this governor is a convenience the
    envelope's own hard ceiling does not depend on, exactly as the old brake was.
    """
    global _state
    try:
        if _state is None:
            _state = GovernorState(concurrency=_seed_concurrency(), above_ceiling_since=None)

        soft_ceiling = float(getattr(settings, "STAGE_E_HOST_LOAD_SOFT_CEILING", DEFAULT_SOFT_CEILING))
        interval_s = float(getattr(settings, "STAGE_E_LOAD_BRAKE_INTERVAL_S", DEFAULT_INTERVAL_S))
        max_wait_s = float(getattr(settings, "STAGE_E_LOAD_BRAKE_MAX_WAIT_S", DEFAULT_MAX_WAIT_S))
        sustained_trip_window_s = float(
            getattr(
                settings,
                "STAGE_E_LOAD_GOVERNOR_SUSTAINED_TRIP_WINDOW_S",
                DEFAULT_SUSTAINED_TRIP_WINDOW_S,
            )
        )

        outcome = run_governor(
            sample=_sample_load_avg,
            sleep=time.sleep,
            now=time.monotonic,
            state=_state,
            soft_ceiling=soft_ceiling,
            hard_ceiling=HOST_LOAD_CEILING,
            concurrency_cap=_concurrency_cap(),
            interval_s=interval_s,
            max_wait_s=max_wait_s,
            sustained_trip_window_s=sustained_trip_window_s,
        )
        _state = outcome.state
        if outcome.waits:
            logger.info(
                "Stage E load governor: %s (%s wait(s), %.1fs total) - concurrency now %s",
                outcome.action,
                outcome.waits,
                outcome.seconds,
                outcome.state.concurrency,
            )
        return outcome
    except Exception:
        logger.exception("Stage E load governor failed - proceeding unbraked at last known concurrency")
        fallback_concurrency = _state.concurrency if _state is not None else _seed_concurrency_safe()
        return GovernorOutcome(
            state=GovernorState(concurrency=fallback_concurrency, above_ceiling_since=None),
            action=PROCEED,
        )


def _seed_concurrency_safe() -> int:
    """`_seed_concurrency`, but never itself able to raise inside `apply_load_governor`'s own except
    block - a malformed `STAGE_E_MAX_CONCURRENT_DISPATCHES`/`STAGE_E_GOVERNOR_CONCURRENCY_CAP` (the exact
    class of error this whole wrapper exists to survive) must not turn "proceed unbraked" into an
    unhandled exception of its own."""
    try:
        return _seed_concurrency()
    except Exception:
        return 2
