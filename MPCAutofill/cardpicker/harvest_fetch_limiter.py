"""
Stage B split fetch limiter (docs/features/catalog-completion-plan.md, "Harvest-calculate
pipeline" section) - per-destination rate governance, replacing the single shared 3 req/sec
assumption `local_phash.DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC`/`_RateLimiter` were built around
for Part 2's own backfill.

Owner decision 2026-07-19 (Stage B reframe): the harvest's only fetch path -
`image_cdn_fetch.fetch_card_image`, the Worker's "full" tier - never touches R2 (confirmed
three independent ways: image-cdn/src/handler/image.ts's switch statement + its own comment,
R2Service.ts's call sites, and frontend/src/common/image.ts's `getBucketImageURL` explicitly
throwing for `size == "full"`). Google lh3/lh4 is the real, only-governed destination today.
Structured as a per-destination registry (not one flat constant) specifically so a future R2
tier - once #130 (tier-route by requested size) lands - is a new registry entry, not a rewrite;
no R2 entry exists yet, since inventing numbers for a tier with no real traffic would violate
this pilot's own "measure, don't assume" discipline.

Red-team correction (2026-07-19, docs/features/catalog-completion-plan.md's "Harvest-calculate
pipeline" section, owner-commissioned adversarial review): every fetch here goes through OUR OWN
image-cdn Worker's full tier, never "direct to Google" - the Worker's configured
IMAGE_FULL_TIER_RATE_LIMITER binding (3 req/sec, image-cdn/wrangler.toml) is empirically
confirmed leaky (local_phash.py's 2026-07-17 addendum: ~10.5/s sustained, zero 429s, during
Part 2's backfill), meaning THIS client-side limiter is the SOLE real enforcement protecting
Google's lh4 endpoint - and, since that endpoint is shared with live PDF export/bulk download,
the live site itself - at bulk volume. `GOOGLE_IMAGE` is paced per task #165's own
concurrency-raise probe (2026-07-19, see docs/features/catalog-completion-plan.md's
concurrency-probe table): rate_per_sec=8.0, max_concurrency=6, a touch under the
concurrency=6 step's measured 8.116/s ceiling for margin, superseding the earlier ~3/s Part-2-
backfill-derived pacing. That step was clean on every dimension the probe tracked, including its
independent live-site canary (p95 0.39s, BETTER than the concurrency=3 baseline's 0.81s) - not
just the remote quota signal, which alone would have missed the next step's problem: concurrency=10
(see the OWNER RATE RULING note below - the 8.0 probe number is now superseded by a ratified 7.0).
measured a higher raw throughput (9.59/s) but was REJECTED because the same canary caught a 2.43x
p95 latency regression (1.97s) on the shared Worker path despite zero Google 429/403 events across
the entire run. That gap - a clean quota signal shipping a config that would have degraded the live
site - is why concurrency=6/rate=8.0 is the chosen ceiling rather than the higher raw-throughput
number probed: it is the highest step that stayed safe on BOTH the remote-quota signal and the
live-site canary, not just the former. A 403 on a Google-bound destination is a hard stop (raises
`GoogleFetchLockoutError`), not a soft degrade-and-continue - a lockout here risks the live site's
own image serving, not just this pipeline's own throughput, and Google's lh3/lh4 endpoints are
externally documented to escalate 429->403 under sustained load. A 429 gets exponential backoff
instead - a materially milder, more common, recoverable signal.

OWNER RATE RULING (2026-07-30): "the limit needs to be on the amount we are fetching from google
api 7/s or hardware whichever comes first. and the limit needs to throttle not shut it down."

  * THE CEILING IS 7.0/s. `GOOGLE_IMAGE.rate_per_sec` drops 8.0 -> 7.0. The probe-derived 8.0 was
    the highest measured-clean step; 7.0 is the owner's own ratified number and is strictly under
    it, so nothing the probe established is contradicted - only tightened.
  * "OR HARDWARE, WHICHEVER COMES FIRST" IS ALREADY STRUCTURAL, AND DELIBERATELY NOT RE-DERIVED
    AS A SECOND NUMBER HERE. `_DestinationLimiter` is a strict MINIMUM-INTERVAL pacer: it can only
    ever DELAY a request, never issue one the caller didn't ask for. The achieved rate is therefore
    already `min(7.0, whatever this host + this network actually sustains)` by construction - the
    hardware term binds without being configured, and `current_rate()` is what reports which of the
    two is binding right now. A configured hardware-derived RATE would need a per-fetch latency
    term, and no honest one exists: `stage_e_batch_sizing.HostProfile` (#589) measures usable
    cores, a memory budget and `aggregate_fetch_threads` - counts, not a rate - and turning a
    thread count into a req/s requires a mean fetch latency this project has never measured at
    catalog scale. Inventing one would be exactly the fabricated ceiling #589 removed from
    `stage_e_batch_sizing` when it deleted its false `GOOGLE_IMAGE.max_concurrency` term. The
    honest hardware-vs-destination-budget signal is #589's `HostProfile.fetch_overcommitted`,
    which already exists and is deliberately left alone by this change.
  * "THROTTLE, DO NOT SHUT DOWN" is `DestinationThrottledError` plus decaying backoff below, and
    its consumer side in `stage_e_dispatch._run_stage_c`. Rate pressure (429/503) now DEGRADES the
    run - the pacing interval widens and the run keeps going - instead of accumulating in the
    operating envelope's fetch-failure window until it hard-stops the whole pass. A genuine
    envelope breach (host load, RSS, non-throttle fetch failures, a 403 lockout) still halts,
    unchanged. See `operating_envelope.py` and `docs/features/stage-e-operations.md`.

THE CEILING IS GLOBAL, NOT PER PROCESS (owner clarification, 2026-07-30: "to be clear: the 7
fetches per second cap is a global cap, it shouldn't be per process or per core"). Everything in
`_DestinationLimiter` below - `_next_allowed`, its `threading.Lock`, its `threading.Semaphore` -
is PER-PROCESS state, and that was the whole ceiling until now. It held for the pooled runner
(`run_image_evidence_cohort`: one process, one thread pool) and it did NOT hold for the conveyor
(`stage_e_dispatch` under django-q2, whose workers are separate OS PROCESSES): N concurrent
dispatches each paced themselves to 7/s independently, for N x 7/s at the destination, scaling with
`STAGE_E_MAX_CONCURRENT_DISPATCHES`. `acquire()` now takes its pacing decision from
`harvest_rate_coordinator` - one atomic Postgres statement over a cursor shared by every fetching
process - so the aggregate is the ceiling regardless of how many processes fetch. The per-process
arithmetic survives, divided by the process count, only as the degraded fallback when the
coordination store is unreachable. See that module's docstring for the mechanism, the rejected
alternatives, and the fail-open/fail-closed reasoning.

BACKOFF IS NO LONGER STICKY-FOREVER (same ruling). It was: "the multiplier only grows, never
resets", on the reasoning that recovering the fast rate mid-run risks re-tripping the same
undocumented ceiling. That reasoning holds for a SHORT run and fails for the one this project
actually runs: `stream_full_catalog` is a one-shot 230,753-card unattended pass, where a single
early 429 blip would otherwise pin the whole multi-hour pass at half speed (or, after four blips,
1/16th speed) with no way back. The compromise below is asymmetric on purpose - backoff DOUBLES on
one signal, and only HALVES after `_CLEAN_RESPONSES_BEFORE_DECAY` consecutive clean responses, and
never below 1.0 (the configured ceiling is a hard cap, decay can never overshoot it). Slow to
recover, fast to yield: the destination still wins every argument, it just no longer wins it
permanently on the strength of one response.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

from cardpicker import harvest_rate_coordinator

logger = logging.getLogger(__name__)


class GoogleFetchLockoutError(Exception):
    """Raised when a Google-bound destination receives a 403 - a hard stop, not a retryable
    condition. A caller catching broad Exception around a fetch call (as
    image_cdn_fetch.fetch_card_image does, to tolerate ordinary transient failures) MUST NOT
    swallow this silently - it needs an explicit carve-out, since continuing after a 403 is
    exactly the abuse pattern that risks an extended IP-level cooldown shared with the live
    site's own PDF export/bulk-download image serving. Owner notification on this condition is
    the run-orchestrator's responsibility (Stage E/F, not yet built), not this module's - a
    low-level rate limiter has no session/notification access of its own."""


class DestinationThrottledError(Exception):
    """Raised by `rate_limited_get` when a destination answered with one of its configured
    `backoff_status_codes` (429/503 for Google) - RATE PRESSURE, the mild recoverable severity, as
    distinct from `GoogleFetchLockoutError`'s hard stop. The limiter has ALREADY widened its own
    pacing interval by the time this is raised, so the correct caller response is "record that this
    one card was deferred, then keep going" - the next request through this limiter is already
    slower. It exists as a distinct exception rather than a returned response for one reason:
    without it, a 429 is indistinguishable from a 404 or a decode error by the time it reaches
    `stage_e_dispatch`'s fetch-outcome window (both arrive as `fetch_card_image_bytes() -> None`,
    via `raise_for_status()` into a broad `except`), and being counted there is what used to let
    sustained rate pressure trip `EnvelopeTrip.Bar.FETCH_FAILURE_RATE` and HARD-STOP a 230,753-card
    unattended pass with exit 3 - a human-acknowledgement stop for a condition that wanted a slower
    pace. A caller catching broad `Exception` around a fetch (as `image_cdn_fetch
    .fetch_card_image_bytes` does) MUST carve this out explicitly, exactly like the lockout above,
    or the distinction is lost again at the first `except Exception`."""


@dataclass(frozen=True)
class DestinationLimiterConfig:
    name: str
    rate_per_sec: float
    max_concurrency: int
    # Status codes that raise GoogleFetchLockoutError - a hard stop, not a pacing change. See
    # the exception's own docstring for why Google specifically treats this as fatal rather than
    # a rate to degrade into. Empty = no lockout handling for this destination.
    lockout_status_codes: frozenset[int] = frozenset()
    # Status codes that trigger exponential backoff (the pacing interval doubles each
    # occurrence, capped - see _DestinationLimiter._MAX_BACKOFF_MULTIPLIER), sticky for the
    # life of the process, same rationale as the lockout: a milder, more common, still-real
    # signal that this destination wants less traffic. Empty = no backoff for this destination.
    backoff_status_codes: frozenset[int] = frozenset()


# Google lh3/lh4 (image-cdn's "full" tier target, reached via OUR OWN Worker - see module
# docstring's red-team correction, never "direct"). The harvest's real, only-governed
# destination today (Stage B reframe - R2 is unused, see docs/features/catalog-completion-plan.md).
# Paced per task #165's concurrency-raise probe (2026-07-19, docs/features/catalog-completion-plan.md's
# concurrency-probe table): rate_per_sec=8.0/max_concurrency=6, a touch under the concurrency=6
# step's measured 8.116/s achieved throughput for margin. That step was clean on every dimension
# probed - zero lockout/backoff events AND its independent live-site canary (p95 0.39s, better
# than the concurrency=3 baseline's 0.81s) - unlike the next step up: concurrency=10 measured a
# higher raw ceiling (9.59/s) but was REJECTED, since its canary caught a 2.43x p95 latency
# regression (1.97s) on the shared Worker path despite zero Google quota (429/403) events across
# the entire step. The remote quota signal alone would have missed that regression; the canary is
# what makes concurrency=6 the actual chosen ceiling rather than concurrency=10's higher number
# (see docs/lessons.md's canary entry for the general rule this establishes). Google's own
# undocumented ceiling at 218k-image harvest scale remains unmeasured beyond what these probe
# steps exercised - hence keeping real reactive handling below rather than assuming headroom
# past the measured-clean step.
#
# 2026-07-30 OWNER RATE RULING (module docstring): `rate_per_sec` is 7.0, not the probe's 8.0.
# 7.0 is the owner's own ratified ceiling and sits strictly UNDER the concurrency=6 step's measured
# 8.116/s, so it contradicts nothing the probe established - it only tightens it. The "or hardware,
# whichever comes first" half of the ruling needs no second constant: a minimum-interval pacer can
# only ever delay, so the achieved rate is `min(7.0, what the host sustains)` by construction (see
# the module docstring for why a configured hardware RATE term would have to be fabricated).
# 503 joins 429 in `backoff_status_codes`: both are "this destination wants less traffic right
# now" - the shared image-cdn Worker path in front of Google answers 503 under its own overload,
# and treating that as an ordinary per-card failure is the same misclassification the ruling exists
# to fix. 403 stays a lockout; that severity is unchanged.
GOOGLE_IMAGE = DestinationLimiterConfig(
    name="google_image",
    rate_per_sec=7.0,
    max_concurrency=6,
    lockout_status_codes=frozenset({403}),
    backoff_status_codes=frozenset({429, 503}),
)

# Scryfall's card-image CDN (art-crop fetches, local_phash._fetch_and_hash) - a stable, publicly
# documented CDN with no observed throttling history against this project. "local caching" per
# the owner's Stage B amendment is satisfied structurally by a SEPARATE fix (2026-07-19): most
# art-crop URLs now come from CanonicalPrintingMetadata.art_crop_url, parsed from the same
# weekly bulk-data file already used for printing metadata, zero network - this limiter now only
# governs the CDN image fetch itself (still needed for every hash, cached art-crop URL or not)
# plus genuine REST fallback misses (see SCRYFALL_REST below).
SCRYFALL_CDN = DestinationLimiterConfig(
    name="scryfall_cdn",
    rate_per_sec=10.0,
    max_concurrency=5,
)

# Scryfall's REST API (api.scryfall.com/cards/<id>, local_phash._fetch_scryfall_art_crop_url) -
# a genuine-gap-only fallback as of 2026-07-19 (see SCRYFALL_CDN above): CanonicalPrintingMetadata
# .art_crop_url now serves the common case locally, zero network. This call site should only
# fire for a card whose bulk-data metadata is missing or predates this field - "true gaps" per
# the owner's own framing, not the dominant path it was before. Kept deliberately low (this
# call site should almost never fire at volume) with no reactive backoff configured - no
# observed throttling history against Scryfall, unlike Google's undocumented ceiling.
SCRYFALL_REST = DestinationLimiterConfig(
    name="scryfall_rest",
    rate_per_sec=2.0,
    max_concurrency=2,
)


class _DestinationLimiter:
    """Per-destination pacer: strict minimum-interval (mirrors local_phash._RateLimiter's "no
    burst allowance" design - the goal is holding a steady ceiling, not permitting bursts) plus
    a concurrency semaphore plus reactive handling for two distinct severities - see
    DestinationLimiterConfig's own field docs. Backoff is sticky (the multiplier only grows,
    never resets) for the same reason a lockout is a hard stop rather than a cooldown-and-retry:
    at harvest scale, a reactive signal from the destination is read as "stay cautious for the
    rest of this one-shot run," not a blip to retry past - recovering the fast rate mid-run
    risks re-tripping the same undocumented upstream ceiling repeatedly instead of settling into
    a rate the destination is actually tolerating. One instance is shared across every calling
    thread for a given destination (see the module-level registry below); `acquire()`'s context
    manager blocks the calling thread until its own turn AND holds the concurrency semaphore for
    the fetch's duration, so both ceilings hold regardless of how many threads are trying to
    fetch at once.
    """

    _MAX_BACKOFF_MULTIPLIER = 16.0  # caps exponential backoff at 1/16th speed, not unbounded
    # Decay floor: 1.0 IS the configured `rate_per_sec`. Decay walks the multiplier back TOWARD the
    # configured ceiling and can never go past it, so no amount of clean traffic can talk this
    # limiter into exceeding the number the owner ratified.
    _MIN_BACKOFF_MULTIPLIER = 1.0
    # How many CONSECUTIVE clean (non-backoff, non-lockout) responses buy one halving of the
    # multiplier. Deliberately asymmetric against the doubling on a single backoff signal - see the
    # module docstring's "BACKOFF IS NO LONGER STICKY-FOREVER" note. At 7/s a full recovery from
    # x16 back to x1 costs 400 clean responses, minutes of sustained good behaviour, not seconds.
    _CLEAN_RESPONSES_BEFORE_DECAY = 100

    def __init__(self, config: DestinationLimiterConfig) -> None:
        self._config = config
        self._interval = 1.0 / config.rate_per_sec
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._backoff_multiplier = 1.0
        self._clean_streak = 0
        self._locked_out = False
        self._semaphore = threading.Semaphore(config.max_concurrency)
        self._request_count = 0
        self._window_start = time.monotonic()
        # One Session per destination, reused for the life of the process (shared across every
        # calling thread, same as the limiter itself - Session is thread-safe for concurrent use
        # of a shared connection pool). Avoids paying a fresh TCP+TLS handshake on every fetch to
        # the same host (audit finding: 2026-07-24 IO audit, finding 2).
        self.session = requests.Session()

    @property
    def locked_out(self) -> bool:
        return self._locked_out

    @property
    def backoff_multiplier(self) -> float:
        return self._backoff_multiplier

    def current_rate(self) -> float:
        """Live achieved req/s since this limiter's construction - the observability the
        red-team review asked for ("a logged live req/s counter proving it holds"), read by
        rate_limited_get every _LOG_EVERY_N_REQUESTS requests."""
        elapsed = time.monotonic() - self._window_start
        return self._request_count / elapsed if elapsed > 0 else 0.0

    def lock_out(self) -> None:
        with self._lock:
            self._locked_out = True
        logger.error("%s destination locked out (403) - this is a hard stop, not a pacing change", self._config.name)

    def backoff(self) -> None:
        with self._lock:
            self._backoff_multiplier = min(self._backoff_multiplier * 2.0, self._MAX_BACKOFF_MULTIPLIER)
            self._clean_streak = 0
            multiplier = self._backoff_multiplier
        logger.warning("%s destination backing off (429) - pacing interval now x%.1f", self._config.name, multiplier)

    def note_clean_response(self) -> None:
        """One response that was neither a lockout nor a backoff code - the decay half of the
        adaptive throttle (module docstring's "BACKOFF IS NO LONGER STICKY-FOREVER"). Halves the
        pacing multiplier once every `_CLEAN_RESPONSES_BEFORE_DECAY` CONSECUTIVE such responses,
        floored at `_MIN_BACKOFF_MULTIPLIER` (= the configured `rate_per_sec`, never faster). Any
        backoff resets the streak to zero, so a destination that is still intermittently pushing
        back never accumulates enough clean responses to recover.

        A no-op while the multiplier is already 1.0, which is the overwhelmingly common case - a
        run that never sees a 429 never touches the streak counter at all."""
        with self._lock:
            if self._backoff_multiplier <= self._MIN_BACKOFF_MULTIPLIER:
                self._clean_streak = 0
                return
            self._clean_streak += 1
            if self._clean_streak < self._CLEAN_RESPONSES_BEFORE_DECAY:
                return
            self._clean_streak = 0
            self._backoff_multiplier = max(self._backoff_multiplier / 2.0, self._MIN_BACKOFF_MULTIPLIER)
            multiplier = self._backoff_multiplier
        logger.info(
            "%s destination recovering after %d clean responses - pacing interval now x%.1f",
            self._config.name,
            self._CLEAN_RESPONSES_BEFORE_DECAY,
            multiplier,
        )

    def _reserve_locally(self, interval: float) -> float:
        """The ORIGINAL per-process minimum-interval arithmetic, now reached only when
        cross-process coordination is unavailable (`harvest_rate_coordinator.reserve` returned
        `None`). Kept verbatim - it is a correct pacer, it was only ever wrong about its SCOPE. The
        caller widens `interval` by `degraded_divisor()` before calling this, so N processes each
        running this fallback still sum to no more than the configured ceiling."""
        with self._lock:
            now = time.monotonic()
            wait_time = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + interval
        return wait_time

    def acquire(self) -> "_LimiterSlot":
        """Blocks the calling thread until this destination's GLOBAL budget clears it to fetch, then
        returns a context manager holding the per-process concurrency semaphore for the fetch's
        duration.

        The pacing decision is made by `harvest_rate_coordinator.reserve` - a single atomic Postgres
        statement over a cursor every fetching PROCESS shares - not by this object's own
        `_next_allowed`. That is the whole point: this class's state is per-process, and django-q2's
        workers are separate OS processes, so a purely local pacer delivered N x the configured rate
        (see `harvest_rate_coordinator`'s own module docstring for the full defect writeup). The
        local pacer survives as the degraded fallback only.

        Backoff stays local and is passed INTO the reservation as an already-widened interval, so PR
        #644's throttle-not-halt behaviour is unchanged: a process under rate pressure contributes a
        larger gap to the shared cursor, which can only ever slow the aggregate, never raise it."""
        if self._locked_out:
            raise GoogleFetchLockoutError(f"{self._config.name} is locked out (403) - refusing further requests")
        self._semaphore.acquire()
        try:
            with self._lock:
                interval = self._interval * self._backoff_multiplier
                self._request_count += 1
            wait_time = harvest_rate_coordinator.reserve(self._config.name, interval)
            if wait_time is None:
                wait_time = self._reserve_locally(interval * harvest_rate_coordinator.degraded_divisor())
        except BaseException:
            # Nothing between the semaphore acquire and the sleep is expected to raise - `reserve`
            # swallows its own failures by contract. If something does anyway, the semaphore must
            # not leak, or this destination silently loses a concurrency slot for the life of the
            # process.
            self._semaphore.release()
            raise
        if wait_time > 0:
            time.sleep(wait_time)
        return _LimiterSlot(self._semaphore)


class _LimiterSlot:
    """Context manager returned by `_DestinationLimiter.acquire()` - releases the concurrency
    semaphore on exit. Pacing itself already happened by the time this is constructed (see
    `acquire()` above), so `__enter__` is a no-op; only `__exit__` does anything."""

    def __init__(self, semaphore: threading.Semaphore) -> None:
        self._semaphore = semaphore

    def __enter__(self) -> "_LimiterSlot":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._semaphore.release()


_LIMITERS: dict[str, _DestinationLimiter] = {}
_REGISTRY_LOCK = threading.Lock()
_LOG_EVERY_N_REQUESTS = 50


def get_limiter(config: DestinationLimiterConfig) -> _DestinationLimiter:
    """Process-wide singleton per destination name - one shared limiter instance governs every
    caller/thread for that destination, matching local_phash._RateLimiter's "one instance shared
    across every worker thread" contract, extended across destinations."""
    with _REGISTRY_LOCK:
        limiter = _LIMITERS.get(config.name)
        if limiter is None:
            limiter = _DestinationLimiter(config)
            _LIMITERS[config.name] = limiter
        return limiter


def reset_limiters() -> None:
    """Test-only: drops every registered limiter so each test starts with fresh pacing/trip
    state instead of leaking across tests via the module-level registry, and drops the rate
    coordinator's dedicated connection with them (the cross-process cursor itself is per
    destination NAME, so tests that want a fresh cursor must call
    `harvest_rate_coordinator.clear_cursor` for their own destination - see that module)."""
    with _REGISTRY_LOCK:
        _LIMITERS.clear()
    harvest_rate_coordinator.reset_connection()


def rate_limited_get(config: DestinationLimiterConfig, url: str, **kwargs: Any) -> "requests.Response":
    """Shared entrypoint for every destination fetch: paces + bounds concurrency via `config`'s
    limiter, then reacts to the response status - a matching lockout code raises
    GoogleFetchLockoutError immediately (caller must not swallow this, see the exception's own
    docstring); a matching backoff code escalates future pacing AND raises
    `DestinationThrottledError` (2026-07-30 owner rate ruling - it used to return the 4xx/5xx
    response and let the caller's own `raise_for_status()` flatten it into an indistinguishable
    generic failure, which is what let rate pressure hard-stop a run; see that exception's own
    docstring). Any other response decays the pacing multiplier back toward the configured ceiling
    via `note_clean_response`. Callers keep
    their own `raise_for_status()`/try-except for ordinary HTTP errors exactly as before; this
    only changes what paces the request ahead of it and adds the two severities above.

    Logs the live achieved req/s periodically (every _LOG_EVERY_N_REQUESTS requests) - the
    red-team review's "prove it holds" observability requirement."""
    limiter = get_limiter(config)
    with limiter.acquire():
        response = limiter.session.get(url, **kwargs)
    if limiter._request_count % _LOG_EVERY_N_REQUESTS == 0:
        logger.info("%s: %d requests, current rate %.2f/s", config.name, limiter._request_count, limiter.current_rate())
    if response.status_code in config.lockout_status_codes:
        limiter.lock_out()
        raise GoogleFetchLockoutError(f"{config.name} returned {response.status_code} - locking out this destination")
    if response.status_code in config.backoff_status_codes:
        limiter.backoff()
        raise DestinationThrottledError(
            f"{config.name} returned {response.status_code} - pacing interval widened to "
            f"x{limiter.backoff_multiplier:.1f}; this request is deferred, the run continues"
        )
    limiter.note_clean_response()
    return response


__all__ = [
    "DestinationLimiterConfig",
    "DestinationThrottledError",
    "GoogleFetchLockoutError",
    "GOOGLE_IMAGE",
    "SCRYFALL_CDN",
    "SCRYFALL_REST",
    "get_limiter",
    "reset_limiters",
    "rate_limited_get",
]
