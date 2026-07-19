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
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DestinationLimiterConfig:
    name: str
    rate_per_sec: float
    max_concurrency: int
    # Status codes that trip the degraded rate below, ONE-WAY for the life of the process (see
    # _DestinationLimiter's docstring on why this is sticky, not a cooldown-and-recover backoff).
    # Empty = no reactive degradation for this destination.
    trip_status_codes: frozenset[int] = frozenset()
    degraded_rate_per_sec: Optional[float] = None


# Google lh3/lh4 (image-cdn's "full" tier target) - the harvest's real, only-governed
# destination today (Stage B reframe). Deliberately conservative relative to the Worker's own
# configured IMAGE_FULL_TIER_RATE_LIMITER (3 req/sec, image-cdn/wrangler.toml) despite that
# binding being empirically confirmed leaky at smaller volume (local_phash.py's 2026-07-17
# addendum measured ~10.5/s sustained with zero 429s during Part 2's backfill) - the real
# unknown is Google's own undocumented ceiling on lh3/lh4 at 218k-image harvest scale, not our
# Worker's binding, hence the reactive 403 trip below rather than trusting the
# smaller-scale-observed headroom to hold at ~40x the volume.
GOOGLE_IMAGE = DestinationLimiterConfig(
    name="google_image",
    rate_per_sec=5.0,
    max_concurrency=3,
    trip_status_codes=frozenset({403}),
    degraded_rate_per_sec=1.0,
)

# Scryfall's card-image CDN (art-crop fetches, local_phash._fetch_and_hash) - a stable, publicly
# documented CDN with no observed throttling history against this project. "local caching" per
# the owner's Stage B amendment is already satisfied structurally, not by anything new here:
# CanonicalCard.image_hash is a permanent, forever cache
# (local_phash.get_or_compute_canonical_hash never refetches a nonzero hash) - this limiter only
# ever governs genuine first-time misses.
SCRYFALL_CDN = DestinationLimiterConfig(
    name="scryfall_cdn",
    rate_per_sec=10.0,
    max_concurrency=5,
)

# Scryfall's REST API (api.scryfall.com/cards/<id>, local_phash._fetch_scryfall_art_crop_url) -
# near-zero ceiling: this pilot's own volume is meant to mostly come from data already captured
# at catalog-import time, so REST traffic here should stay small. Not yet true in practice (every
# not-yet-hashed canonical still makes one REST call today) - narrowing that gap is Stage C/D
# scope, not this limiter's job; the low ceiling here is deliberately a guard against volume this
# call site shouldn't have at harvest scale, not a tuned-for-comfort throughput target.
SCRYFALL_REST = DestinationLimiterConfig(
    name="scryfall_rest",
    rate_per_sec=2.0,
    max_concurrency=2,
)


class _DestinationLimiter:
    """Per-destination pacer: strict minimum-interval (mirrors local_phash._RateLimiter's "no
    burst allowance" design - the goal is holding a steady ceiling, not permitting bursts) plus
    a concurrency semaphore plus one-way sticky degradation on a trip status code.

    Sticky, not a cooldown-and-recover backoff: a trip status at harvest scale is a signal to
    stay cautious for the rest of a one-shot run, not a transient blip to retry past - recovering
    the fast rate mid-run risks re-tripping the same undocumented upstream ceiling repeatedly
    instead of settling into a rate the destination is actually tolerating. One instance is
    shared across every calling thread for a given destination (see the module-level registry
    below); `acquire()`'s context manager blocks the calling thread until its own turn AND holds
    the concurrency semaphore for the fetch's duration, so both ceilings hold regardless of how
    many threads are trying to fetch at once.
    """

    def __init__(self, config: DestinationLimiterConfig) -> None:
        self._config = config
        self._interval = 1.0 / config.rate_per_sec
        self._degraded_interval = 1.0 / config.degraded_rate_per_sec if config.degraded_rate_per_sec else None
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._tripped = False
        self._semaphore = threading.Semaphore(config.max_concurrency)

    @property
    def tripped(self) -> bool:
        return self._tripped

    def trip(self) -> None:
        with self._lock:
            already_tripped = self._tripped
            self._tripped = True
        if not already_tripped:
            logger.warning(
                "%s rate limiter tripped - degrading to %.2f/s for the rest of this process",
                self._config.name,
                self._config.degraded_rate_per_sec or 0.0,
            )

    def acquire(self) -> "_LimiterSlot":
        self._semaphore.acquire()
        with self._lock:
            now = time.monotonic()
            interval = (
                self._degraded_interval if (self._tripped and self._degraded_interval is not None) else self._interval
            )
            wait_time = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + interval
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
    limiter, then trips it to the degraded rate on a matching status code (see
    DestinationLimiterConfig.trip_status_codes) BEFORE returning - tripping is a side effect
    observed here, not a new error path callers must handle. Callers keep their own
    `raise_for_status()`/try-except exactly as before; this only changes what paces the request
    ahead of it."""
    limiter = get_limiter(config)
    with limiter.acquire():
        response = requests.get(url, **kwargs)
    if response.status_code in config.trip_status_codes:
        limiter.trip()
    return response


__all__ = [
    "DestinationLimiterConfig",
    "GOOGLE_IMAGE",
    "SCRYFALL_CDN",
    "SCRYFALL_REST",
    "get_limiter",
    "reset_limiters",
    "rate_limited_get",
]
