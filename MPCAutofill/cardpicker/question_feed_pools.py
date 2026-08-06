"""
Materialised, shared, per-lane candidate pools for `question_feed.py`'s ranked union (issue
#727). Backs the "fast path" `get_next_question_feed_item` now tries before each live tier
function: issue #726 measured every tier query doing a Parallel Seq Scan over `cardpicker_card`
(the `printing_tag_status='unresolved'` predicate matches 99.9% of rows, so the existing index is
correctly ignored) feeding a DISK sort on unindexed `date_created`, 2.4-4.7s for a fresh voter and
up to 47.8s in one pathological run - on a single-gunicorn-worker deployment (#544), that blocks
the whole site for every concurrent visitor on every page view. The pools move that cost out of
the request path and onto a periodic warm.

FOUR LANES, mirroring the four tier functions this module never redesigns (issue #727's own
explicit caution - a pool must reproduce its tier's lane semantics, i.e. the same filter/exclude/
order clauses, never a different candidate SET):
  - `LANE_RESOLUTION_IMMINENT` mirrors `question_feed._likely_resolve_printing_card`.
  - `LANE_CONFIRM` mirrors `question_feed._tier_1_confirm_suggestion`.
  - `LANE_CONTESTED` mirrors `question_feed._tier_2_contested` (printing, artist, AND tag halves).
  - `LANE_COLD` mirrors `question_feed._tier_4_fresh` (printing, artist, AND tag halves).
Kept as four separate lanes rather than collapsed - lanes 1 and 2 are both "easy" but their yield
differs completely (see `question_feed.py`'s own module docstring), and collapsing any of them
would hide that.

SHARED, NOT PER-VOTER. A pool holds the CANDIDATE SET only - voter-independent by construction,
same as every tier function's own queryset. The voter's exclusion (`answered_card_ids` and
friends, already computed once per request in `get_next_question_feed_item`) is applied entirely
at READ time, in the `draw_*` functions below, never baked into the cached pool itself. A
per-voter pool would reproduce the exact symptom this fixes (a first-time visitor has no pool, so
their first request is a cold miss and they wait) and would scale warm cost with voter count
instead of catalogue size - see issue #727's own "Pools are shared, not per-voter" section.

SERVING DOES NOT CONSUME. Nothing here ever pops or mutates a pool entry - consensus requires the
SAME card being shown to several voters (`PRINTING_TAG_MIN_VOTES`/`MIN_SHARE`,
`vote_consensus.resolve_weighted_consensus`); what removes a card from a pool is reaching
resolution, which happens at consensus time and is picked up at the next warm (or, for a card that
resolved mid-warm-cycle, filtered out by the read-time staleness check below).

SERVE FROM A RANDOM OFFSET, NOT THE HEAD (`_iter_from_random_offset`) - a fixed ordered pool read
from the front on every request just relocates the same "every voter sees the same card" problem
the live `date_created` ordering already has.

PER-LANE REFRESH CADENCE, NOT ONE GLOBAL INTERVAL. Lane 1 churns with every vote cast and wants
minutes; lane 4 changes only as the pipeline extracts new evidence and tolerates hours. Each
lane's warm cadence is its own settings-driven knob
(`settings.QUESTION_FEED_POOL_WARM_MINUTES_*`), scheduled as its own django-q2 `Schedule` row
(`cardpicker/migrations/0105_question_feed_pools_schedule.py`) executed in the separate
`mpcautofill_worker` container - same infrastructure `catalog_stats.warm_catalog_stats_cache`/
`warm_catalog_stats.py` already uses, no new service.

STALENESS: a card can resolve while its pool is warm. Every `draw_*` function below re-checks the
ONE row it is about to serve (`printing_tag_status`/`artist_vote_status`/
`tag_vote_statuses[tag_name]` still in the state the lane expects) immediately before returning
it - cheap (one indexed query), and exactly the guard issue #727 calls for ("a single-row
validation before serving is cheap"). This is deliberately NOT a full re-derivation of the lane's
classification logic (e.g. re-running `is_likely_resolve_printing`) - that IS the expensive part
pooling exists to avoid paying per-request.

NOT DISJOINT, BY DESIGN - NO EXTRA DEDUPE STRUCTURE NEEDED. A card can be both contested and one
vote from resolving; nothing here prevents it appearing in more than one lane's pool, same as the
live tier functions never prevented it either (get_contested_card_ids() and
_likely_resolve_printing_card's own filter were never mutually exclusive - see question_feed.py's
docstring). What has always prevented DOUBLE-SERVING (and still does, unchanged, in
get_next_question_feed_item) is that both the pool draws AND their live-fallback tiers are
consulted as a strict, first-hit-wins WATERFALL in the same fixed order the original code already
used (likely-resolve -> tier 1 -> tier 2 -> tier 4): whichever lane is tried FIRST that has a
valid (unexcluded, unstale) entry for THIS voter wins the request, and every lane after it is
never even reached. A card sitting in two lanes' pools is drawable from whichever one the
waterfall reaches first for a given voter/request - identical precedence to the pre-pool code,
just resolved via a bounded pool scan instead of a live query.

FAST PATH, NOT A CORRECTNESS BOUNDARY. Every `draw_*` function returns `None` on a cache miss
(pool never warmed, or the configured `"shared"` cache backend is unavailable) OR when this
voter's exclusion exhausts every entry in the pool (a full lap with nothing servable) - the caller
(`question_feed.get_next_question_feed_item`) always falls through to the corresponding live tier
function in that case, so a heavy voter, a cold cache, or a not-yet-scheduled environment degrades
to exactly today's behaviour rather than under-serving.
"""

from __future__ import annotations

import random
from typing import Any, Iterator, NamedTuple, Optional

from django.conf import settings
from django.core.cache import InvalidCacheBackendError, caches
from django.db.models import Case, Count, IntegerField, Value, When

from cardpicker.artist_consensus import get_contested_artist_card_ids
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardArtistVote,
    CardTagVote,
    PrintingTagStatus,
    TagVoteStatus,
    VoteSource,
)
from cardpicker.printing_consensus import get_contested_card_ids
from cardpicker.tag_consensus import get_tag_review_queue_pairs

# The named cache alias this feature reads/writes - deliberately NOT `default` (per-process
# LocMemCache, see `MPCAutofill/settings.py`'s own "WHICH CACHE DO I USE?" section). The warm
# command runs in the `mpcautofill_worker` container, a different process from the gunicorn
# worker(s) answering `GET 2/questionFeed/` - a `default`-cached pool would be invisible to them.
SHARED_CACHE_ALIAS = "shared"

LANE_RESOLUTION_IMMINENT = "resolution_imminent"
LANE_CONFIRM = "confirm"
LANE_CONTESTED = "contested"
LANE_COLD = "cold"
LANES = (LANE_RESOLUTION_IMMINENT, LANE_CONFIRM, LANE_CONTESTED, LANE_COLD)

KIND_PRINTING = "printing"
KIND_ARTIST = "artist"
KIND_TAG = "tag"

CACHE_KEY_PREFIX = "question-feed-pool-v1"
# `None` (persist until the next warm overwrites it) - same convention as
# `catalog_stats.CACHE_TIMEOUT`: a cache-only reader must never see this entry silently expire
# and fall back to a "zeroed" state mid-cycle; the next scheduled warm is what refreshes it.
CACHE_TIMEOUT = None


class PoolEntry(NamedTuple):
    """One candidate in a materialised pool. `tag_name` is only set for `KIND_TAG` entries.
    `reason` is an optional PRE-COMPUTED override for `QuestionFeedServedLog.origin_reason` -
    used only by the cold-lane printing sub-list, where the quick-negative/fresh distinction is
    cheaper to resolve once at warm time than to recompute per read; every other entry leaves it
    `None` and the caller in `question_feed.py` falls back to its own lane-default reason
    string."""

    kind: str
    card_id: int
    tag_name: Optional[str] = None
    reason: Optional[str] = None


def _cache_key(lane: str) -> str:
    return f"{CACHE_KEY_PREFIX}-{lane}"


def _shared_cache_for_read() -> Optional[Any]:
    """Same split as `catalog_stats._shared_cache_for_read` - swallows a missing `"shared"`
    alias as an ordinary miss, so a pre-#538/#543 environment (or a lane that was never warmed)
    degrades to the live tier functions rather than 500ing."""
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError:
        return None


def _shared_cache_for_write() -> Any:
    """Same split as `catalog_stats._shared_cache_for_write` - raises loudly rather than
    silently writing nowhere, since a warm run that appears to succeed while writing nowhere is
    exactly the bug issue #538 exists to prevent."""
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError as e:
        raise RuntimeError(
            f"The {SHARED_CACHE_ALIAS!r} cache backend is not configured in CACHES "
            "(MPCAutofill/settings.py) - question-feed pools cannot write anywhere without it, "
            "so refusing to run rather than silently succeeding while writing nowhere."
        ) from e


def _get_cached_pool(lane: str) -> Optional[list[PoolEntry]]:
    """Cache-only read for `lane`'s pool - `None` on a missing `"shared"` backend, a cache miss,
    or an explicitly empty pool (a warm run that found zero candidates), all three of which the
    caller treats identically: fall through to the live tier function."""
    shared_cache = _shared_cache_for_read()
    if shared_cache is None:
        return None
    return shared_cache.get(_cache_key(lane)) or None


def _iter_from_random_offset(entries: list[PoolEntry]) -> Iterator[PoolEntry]:
    """Yields every entry in `entries` exactly once, starting from a uniformly random position
    and wrapping around - "serve from a random offset, not the head" (issue #727), so voters
    reading the same warm pool don't converge on the handful of cards nearest the front, the same
    problem the live tier functions' deterministic `date_created` ordering already has."""
    if not entries:
        return
    offset = random.randrange(len(entries))
    for i in range(len(entries)):
        yield entries[(offset + i) % len(entries)]


# ---------------------------------------------------------------------------------------------
# Pool builders (warm-time only). Each mirrors its live tier function's own filter/exclude/order
# clauses from `question_feed.py` - collecting up to `settings.QUESTION_FEED_POOL_SIZE` matches
# per sub-kind instead of stopping at the first one, since this now runs once per warm cycle
# instead of once per page view. Never applies per-voter exclusion (`answered_card_ids` and
# friends) - pools are shared, that's a read-time-only concern (see module docstring).
# ---------------------------------------------------------------------------------------------


def _build_pool_resolution_imminent() -> list[PoolEntry]:
    # Local import: `question_feed.py` imports this module at its own top level, so importing
    # back from it here at module scope would be a circular import at load time. Deferred to
    # call time (warm-time only, never on the request path), this is the standard way to break
    # that cycle without duplicating `is_likely_resolve_printing`'s consensus-facing arithmetic.
    from cardpicker.question_feed import is_likely_resolve_printing

    limit = settings.QUESTION_FEED_POOL_SIZE
    entries: list[PoolEntry] = []
    candidates = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, printing_tags__isnull=False)
        .distinct()
        .order_by("date_created")
    )
    for card in candidates.iterator():
        if is_likely_resolve_printing(card):
            entries.append(PoolEntry(kind=KIND_PRINTING, card_id=card.pk))
            if len(entries) >= limit:
                break
    return entries


def _build_pool_confirm() -> list[PoolEntry]:
    from cardpicker.question_feed import _confirm_suggestion_item

    limit = settings.QUESTION_FEED_POOL_SIZE
    entries: list[PoolEntry] = []
    candidates = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .distinct()
        .order_by("date_created")
    )
    for card in candidates.iterator():
        if _confirm_suggestion_item(card) is not None:
            entries.append(PoolEntry(kind=KIND_PRINTING, card_id=card.pk))
            if len(entries) >= limit:
                break
    return entries


def _build_pool_contested() -> list[PoolEntry]:
    limit = settings.QUESTION_FEED_POOL_SIZE
    contested_card_ids = get_contested_card_ids()
    contested_artist_card_ids = get_contested_artist_card_ids()

    printing_ids = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, pk__in=contested_card_ids)
        .order_by("-date_created")
        .values_list("pk", flat=True)[:limit]
    )
    entries: list[PoolEntry] = [PoolEntry(kind=KIND_PRINTING, card_id=card_id) for card_id in printing_ids]

    artist_ids = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.CONTESTED, pk__in=contested_artist_card_ids)
        .order_by("-date_created")
        .values_list("pk", flat=True)[:limit]
    )
    entries.extend(PoolEntry(kind=KIND_ARTIST, card_id=card_id) for card_id in artist_ids)

    tag_count = 0
    for card_id, tag_name in get_tag_review_queue_pairs():
        if tag_count >= limit:
            break
        card = Card.objects.get(pk=card_id)
        if card.tag_vote_statuses.get(tag_name) == TagVoteStatus.CONTESTED:
            entries.append(PoolEntry(kind=KIND_TAG, card_id=card_id, tag_name=tag_name))
            tag_count += 1

    return entries


def _build_pool_cold() -> list[PoolEntry]:
    # See `_build_pool_resolution_imminent`'s comment for why these are local imports.
    from cardpicker.question_feed import (
        QUICK_NEGATIVE_SKIP_REASONS,
        _latest_stage_d_origin_reason_subquery,
    )

    limit = settings.QUESTION_FEED_POOL_SIZE
    contested_card_ids = get_contested_card_ids()

    printing_rows = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .exclude(pk__in=contested_card_ids)
        .annotate(vote_count=Count("printing_tags", distinct=True))
        .annotate(origin_reason=_latest_stage_d_origin_reason_subquery())
        .annotate(
            is_quick_negative=Case(
                When(origin_reason__in=QUICK_NEGATIVE_SKIP_REASONS, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-vote_count", "is_quick_negative", "-date_created")
        .values_list("pk", "origin_reason")[:limit]
    )
    entries: list[PoolEntry] = [
        PoolEntry(
            kind=KIND_PRINTING,
            card_id=card_id,
            reason=(
                "tier_4_quick_negative_to_review"
                if origin_reason in QUICK_NEGATIVE_SKIP_REASONS
                else "tier_4_fresh_printing"
            ),
        )
        for card_id, origin_reason in printing_rows
    ]

    artist_ids = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        .order_by("-date_created")
        .values_list("pk", flat=True)[:limit]
    )
    entries.extend(PoolEntry(kind=KIND_ARTIST, card_id=card_id) for card_id in artist_ids)

    tag_count = 0
    for card_id, tag_name in get_tag_review_queue_pairs():
        if tag_count >= limit:
            break
        card = Card.objects.get(pk=card_id)
        if card.tag_vote_statuses.get(tag_name) == TagVoteStatus.UNRESOLVED:
            entries.append(PoolEntry(kind=KIND_TAG, card_id=card_id, tag_name=tag_name))
            tag_count += 1

    return entries


_POOL_BUILDERS = {
    LANE_RESOLUTION_IMMINENT: _build_pool_resolution_imminent,
    LANE_CONFIRM: _build_pool_confirm,
    LANE_CONTESTED: _build_pool_contested,
    LANE_COLD: _build_pool_cold,
}


def warm_pool_cache(lane: str) -> int:
    """Builds `lane`'s candidate pool fresh from the live database and overwrites its cache
    entry - the body of the `warm_question_feed_pools <lane>` management command. Idempotent:
    two back-to-back runs for the same lane leave the cache in exactly the state a single run
    would, same convention as `catalog_stats.warm_catalog_stats_cache`. Resolves the `"shared"`
    cache backend BEFORE building anything, so a misconfigured environment never pays for the
    build it couldn't have written down anyway. Returns the number of entries written."""
    if lane not in _POOL_BUILDERS:
        raise ValueError(f"Unknown question-feed pool lane: {lane!r} (expected one of {LANES})")
    shared_cache = _shared_cache_for_write()
    entries = _POOL_BUILDERS[lane]()
    shared_cache.set(_cache_key(lane), entries, timeout=CACHE_TIMEOUT)
    return len(entries)


# ---------------------------------------------------------------------------------------------
# Pool draws (read-time, per request). Each returns `None` on a cache miss or once this voter's
# exclusion/staleness filtering has walked every entry with nothing servable - the caller always
# falls back to the corresponding live tier function in that case (see module docstring's "FAST
# PATH, NOT A CORRECTNESS BOUNDARY").
# ---------------------------------------------------------------------------------------------


def _fetch_unresolved_printing_card(card_id: int) -> Optional[Card]:
    """The read-time staleness check for a printing entry: still `UNRESOLVED` right now, not
    just as of the last warm. One indexed query per candidate scanned, same cost shape the live
    tier functions already pay per row via `.iterator()`."""
    return Card.objects.filter(pk=card_id, printing_tag_status=PrintingTagStatus.UNRESOLVED).first()


def draw_resolution_imminent_card(answered_card_ids: set[int]) -> Optional[Card]:
    entries = _get_cached_pool(LANE_RESOLUTION_IMMINENT)
    if not entries:
        return None
    for entry in _iter_from_random_offset(entries):
        if entry.card_id in answered_card_ids:
            continue
        card = _fetch_unresolved_printing_card(entry.card_id)
        if card is not None:
            return card
    return None


def draw_confirm_card(answered_card_ids: set[int]) -> Optional[Card]:
    entries = _get_cached_pool(LANE_CONFIRM)
    if not entries:
        return None
    for entry in _iter_from_random_offset(entries):
        if entry.card_id in answered_card_ids:
            continue
        card = _fetch_unresolved_printing_card(entry.card_id)
        if card is not None:
            return card
    return None


def draw_contested_entry(
    answered_card_ids: set[int],
    answered_artist_card_ids: set[int],
    answered_tag_card_ids_by_tag: dict[str, set[int]],
    not_official_art_card_ids: set[int],
) -> Optional[tuple[str, Card, Optional[str], Optional[str]]]:
    """Returns `(kind, card, tag_name, reason)` for the first unexcluded, unstale entry found
    from a random offset, or `None`. Exclusion sets match `_tier_2_contested`'s own exactly - all
    three (`answered_card_ids`/`answered_artist_card_ids`/`answered_tag_card_ids_by_tag`) are
    already the md5-widened, per-request-memoised sets `get_next_question_feed_item` computes
    once and threads through, same as the live tier."""
    entries = _get_cached_pool(LANE_CONTESTED)
    if not entries:
        return None
    for entry in _iter_from_random_offset(entries):
        if entry.kind == KIND_PRINTING:
            if entry.card_id in answered_card_ids:
                continue
            card = _fetch_unresolved_printing_card(entry.card_id)
            if card is None:
                continue
            return KIND_PRINTING, card, None, entry.reason
        if entry.kind == KIND_ARTIST:
            if entry.card_id in answered_artist_card_ids or entry.card_id in not_official_art_card_ids:
                continue
            card = Card.objects.filter(pk=entry.card_id, artist_vote_status=ArtistVoteStatus.CONTESTED).first()
            if card is None:
                continue
            return KIND_ARTIST, card, None, entry.reason
        assert entry.tag_name is not None  # guaranteed for KIND_TAG entries by every builder above
        if entry.card_id in answered_tag_card_ids_by_tag.get(entry.tag_name, set()):
            continue
        card = Card.objects.filter(pk=entry.card_id).first()
        if card is None or card.tag_vote_statuses.get(entry.tag_name) != TagVoteStatus.CONTESTED:
            continue
        return KIND_TAG, card, entry.tag_name, entry.reason
    return None


def draw_cold_entry(
    anonymous_id: str,
    answered_card_ids: set[int],
    not_official_art_card_ids: set[int],
    contested_card_ids: list[int],
) -> Optional[tuple[str, Card, Optional[str], Optional[str]]]:
    """The cold-lane analogue of `draw_contested_entry`. `contested_card_ids` is re-checked
    in-memory (a card can have gone from fresh to contested since this pool's last warm) -
    mirrors `_tier_4_fresh`'s own `.exclude(pk__in=contested_card_ids)`. The artist/tag halves
    deliberately use an UNWIDENED, per-candidate `anonymous_id` existence check rather than the
    md5-widened `answered_artist_card_ids`/`answered_tag_card_ids_by_tag` sets - `_tier_4_fresh`
    itself keeps its own pre-existing unwidened form for both (see that function's own docstring
    for why: the widened convention is scoped to `_tier_2_contested` only), so reproducing it
    here means one extra indexed query per artist/tag candidate scanned rather than a second,
    possibly-diverging exclusion rule."""
    entries = _get_cached_pool(LANE_COLD)
    if not entries:
        return None
    contested_card_id_set = set(contested_card_ids)
    for entry in _iter_from_random_offset(entries):
        if entry.kind == KIND_PRINTING:
            if entry.card_id in answered_card_ids or entry.card_id in contested_card_id_set:
                continue
            card = _fetch_unresolved_printing_card(entry.card_id)
            if card is None:
                continue
            return KIND_PRINTING, card, None, entry.reason
        if entry.kind == KIND_ARTIST:
            if entry.card_id in not_official_art_card_ids:
                continue
            if CardArtistVote.objects.filter(card_id=entry.card_id, anonymous_id=anonymous_id).exists():
                continue
            card = Card.objects.filter(pk=entry.card_id, artist_vote_status=ArtistVoteStatus.UNRESOLVED).first()
            if card is None:
                continue
            return KIND_ARTIST, card, None, entry.reason
        if CardTagVote.objects.filter(
            card_id=entry.card_id, tag__name=entry.tag_name, anonymous_id=anonymous_id
        ).exists():
            continue
        card = Card.objects.filter(pk=entry.card_id).first()
        if card is None or card.tag_vote_statuses.get(entry.tag_name) != TagVoteStatus.UNRESOLVED:
            continue
        return KIND_TAG, card, entry.tag_name, entry.reason
    return None


__all__ = [
    "LANES",
    "LANE_RESOLUTION_IMMINENT",
    "LANE_CONFIRM",
    "LANE_CONTESTED",
    "LANE_COLD",
    "KIND_PRINTING",
    "KIND_ARTIST",
    "KIND_TAG",
    "PoolEntry",
    "warm_pool_cache",
    "draw_resolution_imminent_card",
    "draw_confirm_card",
    "draw_contested_entry",
    "draw_cold_entry",
]
