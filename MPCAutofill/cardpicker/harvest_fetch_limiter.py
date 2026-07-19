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
the live site itself - at bulk volume. `GOOGLE_IMAGE` is paced at the documented,
empirically-safe rate Part 2's backfill actually sustained (~3/s), not a higher number the
Worker binding's leaky config might otherwise suggest is safe. A 403 on a Google-bound
destination is a hard stop (raises `GoogleFetchLockoutError`), not a soft degrade-and-continue -
a lockout here risks the live site's own image serving, not just this pipeline's own
throughput, and Google's lh3/lh4 endpoints are externally documented to escalate 429->403 under
sustained load. A 429 gets exponential backoff instead - a materially milder, more common,
recoverable signal.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

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
# Paced at the rate Part 2's own backfill empirically sustained safely (~3/s) - not a higher
# number the Worker binding's observed leakiness (~10.5/s with zero 429s at smaller volume)
# might otherwise suggest is safe. The real unknown is Google's own undocumented ceiling at
# 218k-image harvest scale (~40x Part 2's volume), which this pipeline has no data point for
# yet - hence pacing at the one rate that's actually been proven safe, plus real reactive
# handling below rather than an optimistic higher guess.
GOOGLE_IMAGE = DestinationLimiterConfig(
    name="google_image",
    rate_per_sec=3.0,
    max_concurrency=3,
    lockout_status_codes=frozenset({403}),
    backoff_status_codes=frozenset({429}),
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

    def __init__(self, config: DestinationLimiterConfig) -> None:
        self._config = config
        self._interval = 1.0 / config.rate_per_sec
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._backoff_multiplier = 1.0
        self._locked_out = False
        self._semaphore = threading.Semaphore(config.max_concurrency)
        self._request_count = 0
        self._window_start = time.monotonic()

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
            multiplier = self._backoff_multiplier
        logger.warning("%s destination backing off (429) - pacing interval now x%.1f", self._config.name, multiplier)

    def acquire(self) -> "_LimiterSlot":
        if self._locked_out:
            raise GoogleFetchLockoutError(f"{self._config.name} is locked out (403) - refusing further requests")
        self._semaphore.acquire()
        with self._lock:
            now = time.monotonic()
            interval = self._interval * self._backoff_multiplier
            wait_time = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + interval
            self._request_count += 1
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
    state instead of leaking across tests via the module-level registry."""
    with _REGISTRY_LOCK:
        _LIMITERS.clear()


def rate_limited_get(config: DestinationLimiterConfig, url: str, **kwargs: Any) -> "requests.Response":
    """Shared entrypoint for every destination fetch: paces + bounds concurrency via `config`'s
    limiter, then reacts to the response status - a matching lockout code raises
    GoogleFetchLockoutError immediately (caller must not swallow this, see the exception's own
    docstring); a matching backoff code escalates future pacing but does not raise. Callers keep
    their own `raise_for_status()`/try-except for ordinary HTTP errors exactly as before; this
    only changes what paces the request ahead of it and adds the two severities above.

    Logs the live achieved req/s periodically (every _LOG_EVERY_N_REQUESTS requests) - the
    red-team review's "prove it holds" observability requirement."""
    limiter = get_limiter(config)
    with limiter.acquire():
        response = requests.get(url, **kwargs)
    if limiter._request_count % _LOG_EVERY_N_REQUESTS == 0:
        logger.info("%s: %d requests, current rate %.2f/s", config.name, limiter._request_count, limiter.current_rate())
    if response.status_code in config.lockout_status_codes:
        limiter.lock_out()
        raise GoogleFetchLockoutError(f"{config.name} returned {response.status_code} - locking out this destination")
    if response.status_code in config.backoff_status_codes:
        limiter.backoff()
    return response


__all__ = [
    "DestinationLimiterConfig",
    "GoogleFetchLockoutError",
    "GOOGLE_IMAGE",
    "SCRYFALL_CDN",
    "SCRYFALL_REST",
    "get_limiter",
    "reset_limiters",
    "rate_limited_get",
]
