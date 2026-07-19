"""
L2 engine for the local printing-identification pilot (cardpicker.local_identify_printing_tags,
docs/features/printing-tags.md's Stage 8): perceptual-hash art matching.

`CanonicalCard.image_hash` already exists (added alongside `import_canonical_card_data` - see
"CanonicalCard population fix" in the docs) but is unpopulated in production
(`--skip-image-hash` was used for the real import; confirmed live, 113,224/113,224 rows still
at the placeholder 0) - this module is what actually computes it, lazily, only for candidates a
selected card's name actually produced, never a bulk backfill of the full 113k-row table.
"""

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Optional

import imagehash
from PIL import Image

from cardpicker.harvest_fetch_limiter import (
    SCRYFALL_CDN,
    SCRYFALL_REST,
    rate_limited_get,
)
from cardpicker.image_cdn_fetch import fetch_card_image
from cardpicker.local_fallback import classify_bleed_edge, normalize_crop_box
from cardpicker.models import CanonicalCard, CanonicalPrintingMetadata, Card
from cardpicker.utils import twos_complement

if TYPE_CHECKING:
    from cardpicker.local_identify_printing_tags import CandidatePrinting

logger = logging.getLogger(__name__)

SCRYFALL_HEADERS = {"User-Agent": "mpc-autofill/1.0", "Accept": "application/json"}
_HASH_BITS = 64
_HASH_HEX_DIGITS = _HASH_BITS // 4

# Tuned against real production distances (2026-07-15), not the commonly-quoted "under 10"
# imagehash convention - that assumes well-aligned crops, and ART_CROP_BOX's fixed fractions
# are deliberately crude (see its own comment). Sampled ~26 real multi-candidate cards: best
# (minimum) distance across all of them ranged 14-22, never below 14 - a threshold of 10 would
# reject every single real candidate, pass or fail, before the margin check even runs. 20/5
# still rejects the common case where multiple printings share identical official art (reprints
# routinely do) - those cluster within a few points of each other and correctly fail the margin
# check - while accepting cases with real separation.
DEFAULT_DISTANCE_THRESHOLD = 20
DEFAULT_MARGIN = 5

# MTG modern (2015+) frame art window as a fraction of the full card image - deliberately
# crude for a pilot: a fixed box, not a real frame-aware detector. Modern frame reserves
# roughly the top ~8% for the title bar and the bottom ~42% for the type line/rules text/
# bottom border, leaving the art in between; left/right margins trim the frame's own border.
# Older frames (1993/1997/2003) have measurably different proportions - this box is a
# reasonable average, not tuned per-frame-era, which is exactly the kind of imprecision a
# margin-gated match (not just a threshold) is meant to tolerate.
ART_CROP_BOX: tuple[float, float, float, float] = (0.07, 0.10, 0.93, 0.58)

# Hash-at-ingest/backfill fetch size (2026-07-16, docs/features/printing-tags.md's "Phash
# accuracy at small CDN sizes"): deliberately small, NOT DEFAULT_FETCH_DPI (250) - phash's own
# internal downsample to 32x32 grayscale before its DCT means 148px is already ~5x the
# resolution the algorithm actually uses, and measured on 150 real cards/11,175 pairs, zero
# false merges occurred at this size (min distance among confirmed-different pairs: 16-18,
# nowhere near 0). MUST be a multiple of 10 - see image_cdn_fetch.get_worker_image_url's
# docstring for why (Google's lh4 endpoint 400s on a non-integer height param). 40 (148px) over
# 50 (185px): the false-merge/false-split evidence didn't distinguish between them at the
# sample size measured, and the smaller size is ~15-20% faster to fetch on top of the ~2-2.5x
# win either one already gets over full resolution.
INGEST_HASH_FETCH_DPI = 40


def _hash_to_int(image_hash: "imagehash.ImageHash") -> int:
    return twos_complement(str(image_hash), _HASH_BITS)


def _int_to_hash(value: int) -> "imagehash.ImageHash":
    unsigned = value & ((1 << _HASH_BITS) - 1)
    return imagehash.hex_to_hash(f"{unsigned:0{_HASH_HEX_DIGITS}x}")


def _fetch_scryfall_art_crop_url(scryfall_id: str) -> Optional[str]:
    try:
        response = rate_limited_get(
            SCRYFALL_REST, f"https://api.scryfall.com/cards/{scryfall_id}", headers=SCRYFALL_HEADERS, timeout=10
        )
        response.raise_for_status()
        return response.json().get("image_uris", {}).get("art_crop")
    except Exception:
        logger.exception("Failed to fetch Scryfall card data for %s", scryfall_id)
        return None


def _fetch_and_hash(url: str) -> Optional[int]:
    try:
        response = rate_limited_get(SCRYFALL_CDN, url, headers=SCRYFALL_HEADERS, stream=True, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        return _hash_to_int(imagehash.phash(image))
    except Exception:
        logger.exception("Failed to fetch/hash image at %s", url)
        return None


def _local_art_crop_url(canonical: CanonicalCard) -> Optional[str]:
    """The art-crop URL already sitting in CanonicalPrintingMetadata (Stage B, 2026-07-19,
    docs/features/catalog-completion-plan.md) - parsed from the same weekly bulk-data file
    import_scryfall_printing_metadata already reads, zero network. Returns None (not "") for
    "genuinely not available locally", covering both a missing sidecar row (a card that predates
    this field, or whose metadata import hasn't run yet) and a present-but-empty URL (a real gap
    in Scryfall's own data for this printing) - both fall through to the live REST call below,
    which is exactly SCRYFALL_REST's own "guard for true gaps only" contract."""
    try:
        url = canonical.printing_metadata.art_crop_url
    except CanonicalPrintingMetadata.DoesNotExist:
        return None
    return url or None


def get_or_compute_canonical_hash(canonical: CanonicalCard) -> Optional[int]:
    """
    Returns canonical.image_hash, computing and persisting it first if it's still the unset
    placeholder (0 - see module docstring). Cached forever once computed: a printing's art crop
    never changes, so a 0 read back here always means "never computed", not "computed as zero"
    (an all-white or otherwise-degenerate phash of 0 is possible in principle but vanishingly
    unlikely for real card art - not specially handled, matching upstream's own use of the same
    sentinel in import_canonical_card_data).

    Art-crop URL source, local-first (Stage B, 2026-07-19): CanonicalPrintingMetadata.art_crop_url
    if present (zero network - the same bulk-data file the weekly metadata import already reads),
    else one live Scryfall REST call as a genuine-gap fallback - see _local_art_crop_url and
    SCRYFALL_REST's own docstring in harvest_fetch_limiter.py. Previously always took the REST
    path; measured as the dominant cost (93.6% of a 30-card Stage B wall-clock probe) before this
    change.
    """
    if canonical.image_hash != 0:
        return canonical.image_hash

    art_crop_url = _local_art_crop_url(canonical) or _fetch_scryfall_art_crop_url(str(canonical.identifier))
    if art_crop_url is None:
        return None
    computed = _fetch_and_hash(art_crop_url)
    if computed is None:
        return None
    canonical.image_hash = computed
    canonical.save(update_fields=["image_hash"])
    return computed


def compute_card_art_hash(card_image: "Image.Image", bleed_class: Optional[str] = None) -> int:
    """`bleed_class` (from local_fallback.classify_bleed_edge, run once per card ahead of
    everything else - see run_pilot) remaps ART_CROP_BOX via local_fallback.normalize_crop_box
    for a trimmed image; a no-op otherwise."""
    width, height = card_image.size
    left, top, right, bottom = normalize_crop_box(ART_CROP_BOX, bleed_class)
    art_region = card_image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
    return _hash_to_int(imagehash.phash(art_region))


def compute_content_phash_for_card(card: "Card", dpi: int = INGEST_HASH_FETCH_DPI) -> Optional[int]:
    """
    Hash-at-ingest/backfill primitive (docs/features/printing-tags.md, 2026-07-16): fetches
    `card`'s own image at a small CDN size and computes its content phash - the same
    `compute_card_art_hash` the pilot's phash engine and cluster dedup both already use, just at
    a much smaller fetch size (see INGEST_HASH_FETCH_DPI) since this is meant to run
    unconditionally at ingest time, not only for a run's selected pool.

    Best-effort: returns None on any fetch/hash failure (a transient CDN hiccup should never
    block a card from being created/updated - it just stays unset for a later backfill pass or
    the next ingest to retry, same NULL-means-not-yet-computed contract as
    Card.content_phash itself).
    """
    image = fetch_card_image(card, dpi)
    if image is None:
        return None
    bleed_class = classify_bleed_edge(image)
    return compute_card_art_hash(image, bleed_class)


DEFAULT_BACKFILL_BATCH_SIZE = 500
DEFAULT_BACKFILL_WORKERS = 5  # matches cardpicker.sources.update_database's own MAX_WORKERS


@dataclass(frozen=True)
class BackfillResult:
    dry_run: bool = False
    total_candidates: int = 0
    hashed: int = 0
    failed: int = 0


# Part 2 (docs/features/catalog-completion-plan.md): the CDN Worker's shared full-tier rate
# limiter (image-cdn/wrangler.toml's IMAGE_FULL_TIER_RATE_LIMITER, 3 req/sec) is the real
# throughput ceiling, shared with live PDF export/bulk download - "N fetch threads sized to
# saturate the allowance" means N~3-5, not a large pool, since throughput beyond ~3/sec is
# rate-limited regardless of local thread count.
DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES = 2

# 2026-07-17 addendum: the Worker's IMAGE_FULL_TIER_RATE_LIMITER binding above was confirmed -
# via direct read of cardpicker.image_cdn_fetch.get_worker_image_url (hardcodes the "full" tier
# URL regardless of dpi, so this backfill's small-dpi fetches take the identical uncached path
# as the pilot's own) and image-cdn/src/handler/image.ts's "full" case (unconditional
# fetchWithRateLimit call, no cache short-circuit) - to NOT be enforcing its configured 3 req/sec
# ceiling at this backfill's real bulk-fetch volume (observed ~10.5/s sustained, zero 429s in the
# log). See docs/troubleshooting.md. The ceiling's original purpose (protecting the shared lh4
# endpoint live PDF export/bulk download also depend on) is unchanged, so client-side pacing is
# now the only layer actually holding it.
#
# Stage B addendum (2026-07-19, docs/features/catalog-completion-plan.md): this backfill's own
# `_RateLimiter` below now composes with `cardpicker.harvest_fetch_limiter.GOOGLE_IMAGE`, which
# `image_cdn_fetch.fetch_card_image` (this backfill's actual fetch call, via
# `compute_content_phash_for_card`) paces internally as of Stage B. Two gates in series, not a
# conflict: the effective rate is whichever is stricter. At this constant's default (3.0/s) that
# stays this value, unchanged from before Stage B existed - GOOGLE_IMAGE's 8.0/s ceiling (task
# #165's concurrency-raise probe, 2026-07-19) only becomes the binding one if a caller explicitly
# raises `--rate-limit-per-sec` above it.
DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC = 3.0


class _RateLimiter:
    """Strict minimum-interval pacer - not a token bucket, no burst allowance, since the goal is
    holding a steady <= rate ceiling (see DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC above), not
    permitting bursts. One instance is shared across every worker thread; acquire() blocks the
    calling thread until its own turn, so the ceiling holds regardless of how many threads are
    trying to fetch at once."""

    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / rate_per_sec
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_time = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if wait_time > 0:
            time.sleep(wait_time)


def run_content_phash_backfill(
    dry_run: bool = False,
    batch_size: int = DEFAULT_BACKFILL_BATCH_SIZE,
    workers: int = DEFAULT_BACKFILL_WORKERS,
    limit: Optional[int] = None,
    nice: bool = True,
    progress_every: int = 1000,
    queue_depth_batches: int = DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES,
    rate_limit_per_sec: Optional[float] = None,
) -> BackfillResult:
    """
    One-time backfill (docs/features/printing-tags.md, 2026-07-16): hashes every existing Card
    row whose content_phash is still NULL - the correction path for rows that predate
    hash-at-ingest (cardpicker.sources.update_database.hash_newly_created_cards runs only for
    CREATED cards going forward - see its own docstring), or that hashing failed for at ingest
    time (a transient CDN fetch error - see compute_content_phash_for_card's best-effort
    contract).

    Idempotent and resumable by construction: filters on content_phash__isnull=True, so a plain
    re-invocation after a kill picks up exactly where it left off with no separate checkpoint
    file or --resume flag needed - same NULL-filter-as-checkpoint discipline
    local_identify_printing_tags.run_pilot uses via its own anonymous_id exclusion.

    Pipelined, not per-batch-blocking (Part 2): ONE long-lived `workers`-thread pool for the
    whole run (not recreated per batch - the original implementation's actual inefficiency
    wasn't the per-batch bulk_update, which is cheap, but the strict alternation between "wait
    for this batch's fetches" and "wait for this batch's persist" with no overlap between the
    two). A sliding submission window of `batch_size * queue_depth_batches` futures is kept full
    at all times via `concurrent.futures.wait(..., return_when=FIRST_COMPLETED)` - as soon as
    any fetch completes, its slot is immediately refilled with the next card, so a batch's
    persist (fast, DB-only) happens in the main thread while the worker pool keeps fetching
    ahead, uninterrupted. `queue_depth_batches` bounds how many fetched-but-not-yet-persisted
    Card objects can be in flight at once (memory bound), independent of `workers` (the CDN rate
    limit bounds real fetch throughput regardless of pool size - see DEFAULT_BACKFILL_WORKERS).

    Completion order is NOT submission order once more than one worker thread is fetching
    concurrently - a later-submitted card can finish before an earlier one (a slow/large image,
    a transient retry, network jitter). This is safe here specifically because each card's
    persist is independent (no ordering dependency, no shared cross-card state, unlike e.g. a
    running index or a "first N" cutoff) - see TestPipelinedBackfillOutOfOrder in
    test_local_identify_printing_tags.py for the explicit proof. A kill/crash loses at most the
    in-flight window (`batch_size * queue_depth_batches` cards, already-persisted batches are
    safe) - the same NULL-filter checkpoint discipline covers it on the next invocation.

    `rate_limit_per_sec` (2026-07-17 addendum, see DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC and
    _RateLimiter above): None (the default here) disables pacing entirely - every test in this
    module relies on that to stay fast. The management command passes the real ceiling
    explicitly. Gated at the fetch call itself (inside the per-card worker function), not at
    submission, so it holds regardless of `workers`/`batch_size` tuning.
    """
    if nice:
        try:
            os.nice(15)
        except (AttributeError, PermissionError, OSError):
            logger.warning("os.nice unavailable in this environment - --nice throttling is CPU-yield-only")

    queryset = (
        Card.objects.filter(content_phash__isnull=True)
        .select_related("source")
        .only("pk", "identifier", "source_id", "source__source_type")
        .order_by("pk")
    )
    if limit is not None:
        queryset = queryset[:limit]
    all_cards = list(queryset)
    total = len(all_cards)
    print(f"{total} card/s with no content_phash yet.")

    hashed = 0
    failed = 0
    processed = 0
    to_persist: list[Card] = []
    window_size = max(batch_size * queue_depth_batches, workers)
    limiter = _RateLimiter(rate_limit_per_sec) if rate_limit_per_sec else None

    def _fetch_one(card: Card) -> Optional[int]:
        if limiter is not None:
            limiter.acquire()
        return compute_content_phash_for_card(card)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending: dict["Future[Optional[int]]", Card] = {}
        card_iter = iter(all_cards)

        def submit_next() -> None:
            card = next(card_iter, None)
            if card is not None:
                pending[executor.submit(_fetch_one, card)] = card

        for _ in range(window_size):
            submit_next()

        while pending:
            done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
            for done_future in done:
                card = pending.pop(done_future)
                content_hash = done_future.result()
                processed += 1
                submit_next()  # keep the window full - fetch stays ahead of persist

                if content_hash is not None:
                    card.content_phash = content_hash
                    to_persist.append(card)
                    hashed += 1
                else:
                    failed += 1

                if len(to_persist) >= batch_size:
                    if not dry_run:
                        Card.objects.bulk_update(to_persist, ["content_phash"], batch_size=batch_size)
                    to_persist = []

                if progress_every and processed % progress_every < len(done):
                    print(f"  ... {processed}/{total} cards hashed")

        if to_persist and not dry_run:
            Card.objects.bulk_update(to_persist, ["content_phash"], batch_size=batch_size)

    return BackfillResult(dry_run=dry_run, total_candidates=total, hashed=hashed, failed=failed)


@dataclass(frozen=True)
class PhashMatch:
    candidate: "CandidatePrinting"
    distance: int
    runner_up_distance: Optional[int]


def find_best_match(
    card_hash: int,
    candidates_with_hashes: list[tuple["CandidatePrinting", int]],
    distance_threshold: int = DEFAULT_DISTANCE_THRESHOLD,
    margin: int = DEFAULT_MARGIN,
) -> tuple[Optional[PhashMatch], str]:
    """
    Returns (match, skip_reason). skip_reason is "no-hashable-candidates" (every candidate
    failed to fetch/hash), "no-clear-winner" (best distance is over threshold, or the runner-up
    is too close behind it), or "" (matched). Requires at least 2 hashed candidates to compute a
    margin at all when there's more than one name-candidate in the first place; a genuinely
    single-candidate name (already excluded by the orchestrator's selection - phash only runs on
    multi-candidate names in practice) would just need the threshold.
    """
    if not candidates_with_hashes:
        return None, "no-hashable-candidates"

    # card_hash and each candidate hash are both plain ints (the DB storage representation) -
    # ImageHash's `-` operator (Hamming distance) needs two ImageHash objects, not raw ints.
    card_image_hash = _int_to_hash(card_hash)
    scored = sorted(
        (
            (candidate, card_image_hash - _int_to_hash(candidate_hash))
            for candidate, candidate_hash in candidates_with_hashes
        ),
        key=lambda pair: pair[1],
    )
    best_candidate, best_distance = scored[0]
    runner_up_distance = scored[1][1] if len(scored) > 1 else None

    if best_distance > distance_threshold:
        return None, "no-clear-winner"
    if runner_up_distance is not None and (runner_up_distance - best_distance) <= margin:
        return None, "no-clear-winner"

    return PhashMatch(candidate=best_candidate, distance=best_distance, runner_up_distance=runner_up_distance), ""


__all__ = [
    "DEFAULT_DISTANCE_THRESHOLD",
    "DEFAULT_MARGIN",
    "ART_CROP_BOX",
    "INGEST_HASH_FETCH_DPI",
    "DEFAULT_BACKFILL_BATCH_SIZE",
    "DEFAULT_BACKFILL_WORKERS",
    "DEFAULT_PIPELINE_QUEUE_DEPTH_BATCHES",
    "DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC",
    "PhashMatch",
    "BackfillResult",
    "get_or_compute_canonical_hash",
    "compute_card_art_hash",
    "compute_content_phash_for_card",
    "run_content_phash_backfill",
    "find_best_match",
]
