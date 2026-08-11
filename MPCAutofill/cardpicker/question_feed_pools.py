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

SERVE FROM A RANDOM OFFSET, NOT THE HEAD (`_iter_windowed_from_random_offset`) - a fixed ordered
pool read from the front on every request just relocates the same "every voter sees the same
card" problem the live `date_created` ordering already has. The information-gain re-ranking
(issue #716) that reorders each serve's window by expected information gain is layered ON TOP of
that random start, not instead of it: only a BOUNDED window taken from the random offset
(`question_feed._CANDIDATE_SCORING_WINDOW` - the same bound the live tiers' own bounded
re-ranking already uses, not a second one invented here) is scored, since each scored candidate
costs several vote queries and a pool holds hundreds to thousands of entries
(`settings.QUESTION_FEED_POOL_SIZE`). See `_iter_windowed_from_random_offset`'s own docstring.

SAMPLE THE POPULATION, NOT THE HEAD (`_sample_across_pk_strata`) - the build side's own half of
the same anti-convergence property the random-offset serve above exists for. A builder whose
underlying query is `.order_by(<field>)[:limit]` (or an unbounded walk stopped at `limit`
matches) reads the query's own HEAD - and cards imported in one batch share close pk values and
`date_created` timestamps, so the head of any such ordering is one import batch, not a sample of
the catalogue. Every builder below instead visits the WHOLE `Card` table's pk range in a handful
of randomly-shuffled windows (`_shuffled_pk_strata`) and pulls a bounded chunk from each
(`_sample_across_pk_strata`), so a warm draws from across every batch the lane's filter/exclude
clauses admit, not just whichever batch happens to sort first. BOUNDED, not full-scan: cost is
`_POOL_SAMPLE_STRATA * chunk_size` (a fixed, small multiple of `limit`) regardless of how many
rows qualify - the review queue is 137k+ rows and growing, and a warm that scaled with it would
reintroduce the exact request-path cost this module's own opening paragraph exists to avoid,
just moved to a background job instead of a page view. The SQL ordering each builder cared about
before (`-date_created` for the contested/cold lanes' tie-break, `-vote_count`/quick-negative for
the cold lane's own printing ranking) is now applied to the SAMPLED rows only, after collection -
the tie-break structure `_iter_windowed_from_random_offset` depends on still holds, only WHICH
rows land in the pool changed, never their relative order once there.

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
get_next_question_feed_item) is that the four lane draws are consulted as a strict, first-hit-wins
WATERFALL (likely-resolve first, then the three remainder lanes in `question_feed.
_REMAINDER_LANE_ORDER`'s fixed confirm/contested/cold order - see question_feed.py's own
"Evidence-gated printing-confirmation policy" docstring section for why tier 1 is gated rather
than ranked, so a fixed order needs no per-session rebalancing): whichever lane is tried FIRST
that has a valid (unexcluded,
unstale) entry for THIS voter wins the request, and every lane after it is never even reached. A
card sitting in two lanes' pools is drawable from whichever one the waterfall reaches first for a
given voter/request.

POOLS ARE THE SOLE SERVING MECHANISM ON THE REQUEST PATH - NOT A FAST PATH WITH A LIVE FALLBACK
(issue #762 correction; an earlier version of this module built a lane's pool INLINE, in
`_get_cached_pool`, on a cache miss - the exact Parallel Seq Scan this module's own opening
paragraph exists to move off the request path, reintroduced on every cold start, eviction, or
worker restart). Every `draw_*` function returns `None` on a cache miss (pool never warmed,
evicted, or the configured `"shared"` cache backend is unavailable) OR when this voter's exclusion
exhausts every entry in the pool (a full lap with nothing servable) - in EITHER case that lane
simply has no supply for this request, and the caller
(`question_feed.get_next_question_feed_item`) moves on to the next lane in its waterfall, honestly
returning `None` overall if none of the four has supply. This never blocks or loops: warmers
(`warm_pool_cache`, scheduled per-lane - see the cadence section above) are the only path that
ever builds a pool; a heavy voter, a cold cache, or a not-yet-scheduled environment degrades to
"caught up" rather than paying for a live build.
"""

from __future__ import annotations

import random
from typing import Any, Iterator, NamedTuple, Optional

from django.conf import settings
from django.core.cache import InvalidCacheBackendError, caches
from django.db.models import Case, Count, IntegerField, Max, Min, Value, When

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
    """Reads `lane`'s candidate pool from cache. `None` on a cache miss (never warmed, evicted,
    or the `"shared"` backend isn't configured) - callers treat that as "no supply for this
    request", never a signal to build the pool inline: an inline build is precisely the
    unindexed Parallel Seq Scan (2.4-4.7s typical, up to 47.8s observed - issue #726/#727) this
    module exists to move off the request path. `warm_pool_cache` (via `_POOL_BUILDERS`,
    scheduled per-lane) is the ONLY path that ever builds a pool - see this module's own
    "POOLS ARE THE SOLE SERVING MECHANISM" docstring section."""
    shared_cache = _shared_cache_for_read()
    if shared_cache is None:
        return None
    return shared_cache.get(_cache_key(lane))


def _iter_windowed_from_random_offset(entries: list[PoolEntry]) -> Iterator[PoolEntry]:
    """Yields every entry in `entries`, ranked candidates first: a BOUNDED window of
    `question_feed._CANDIDATE_SCORING_WINDOW` entries taken from a RANDOM offset into the pool is
    scored by expected information gain (issue #716) and yielded best-first, then every
    remaining entry (the rest of the pool, continuing from where the window left off) is yielded
    unscored, in that same rotated order - so a draw that exhausts the ranked window (every
    candidate in it excluded or stale for this voter) still walks the rest of the pool exactly as
    before, never truncating a voter's effective supply to just the window.

    BOUNDED, not full-pool: scoring costs several vote queries per candidate
    (`_question_information_gain_score`'s own dispatch), and a pool holds hundreds to thousands
    of entries (`settings.QUESTION_FEED_POOL_SIZE`) - scoring every entry on every serve
    reintroduces per-request cost this module's pooling exists to avoid paying (see its own module
    docstring). The window size is `question_feed._CANDIDATE_SCORING_WINDOW` - the SAME bound the
    live tiers' own bounded re-ranking already uses (`question_feed._max_scored_candidate`), one
    shared knob rather than a second one invented here.

    RANDOM OFFSET, restored: a fixed head-to-tail scan (scored or not) means every voter reading
    the same warm pool converges on the same handful of cards nearest the front - the exact
    problem this module's own "SERVE FROM A RANDOM OFFSET" section exists to prevent. Drawing the
    scored window from a randomised start (rather than always the head) keeps that anti-
    convergence property even though the window itself is now reordered by score.

    TIE-BREAK ANCHORED TO THE POOL'S OWN ORIGINAL ORDER, NOT THE RANDOMISED ONE: two candidates
    that score equally (the common case for the cold lane's `-vote_count`/quick-negative/
    `-date_created`-ordered printing sub-list, where most candidates carry `vote_count=0` and tie
    on score) fall back to whichever came first in `entries` as WARMED - the SQL ordering
    `_build_pool_cold`/`_build_pool_contested` already applied - never to wherever the random
    rotation happened to place them for THIS particular draw. Sorting the window by `(-score,
    original_index)` rather than relying on a plain stable sort over the rotated list is what
    keeps that guarantee - a plain stable sort over the rotated list would let the same tie
    resolve differently request to request, silently breaking the tier's own tiebreak chain
    (see `_tier_4_fresh`'s own docstring, and this module's own "NOT DISJOINT" section)."""
    if not entries:
        return
    from cardpicker.question_feed import (
        _CANDIDATE_SCORING_WINDOW,
        _question_information_gain_score,
    )

    offset = random.randrange(len(entries))
    rotated_indices = [(offset + step) % len(entries) for step in range(len(entries))]
    window_indices, rest_indices = (
        rotated_indices[:_CANDIDATE_SCORING_WINDOW],
        rotated_indices[_CANDIDATE_SCORING_WINDOW:],
    )

    scored = []
    for index in window_indices:
        entry = entries[index]
        card = Card.objects.filter(pk=entry.card_id).first()
        score = _question_information_gain_score(entry.kind, card, entry.tag_name) if card is not None else 0.0
        scored.append((score, index, entry))
    scored.sort(key=lambda triple: (-triple[0], triple[1]))

    for _, _, entry in scored:
        yield entry
    for index in rest_indices:
        yield entries[index]


def _iter_by_kind_precedence(entries: list[PoolEntry]) -> Iterator[PoolEntry]:
    """Yields every entry in `entries`, KIND-GROUPED first (printing, then artist, then tag - the
    same structural precedence `_tier_2_contested`/`_tier_4_fresh` encode by trying their printing
    candidates entirely before their artist candidates, and those entirely before their tag
    candidates - an unconditional order, never a tiebreak), with
    `_iter_windowed_from_random_offset`'s own bounded/randomised/scored ordering applied WITHIN
    each kind group. A single mixed-kind random-offset scan would let a tied score (e.g. two
    zero-vote, zero-signal candidates of different kinds) resolve to whichever kind the random
    rotation happened to place first, silently breaking that precedence on some requests and not
    others - grouping by kind before windowing keeps it structural instead, matching the
    contested/cold lanes' own live-tier counterparts exactly."""
    for kind in (KIND_PRINTING, KIND_ARTIST, KIND_TAG):
        yield from _iter_windowed_from_random_offset([entry for entry in entries if entry.kind == kind])


# Number of contiguous windows the WHOLE `Card` table's pk range is partitioned into when a
# pool builder needs to sample its qualifying population instead of taking its own head - see
# "SAMPLE THE POPULATION, NOT THE HEAD" in the module docstring above. A fixed, small constant:
# cost stays `_POOL_SAMPLE_STRATA * chunk_size` regardless of how many rows exist in the
# catalogue.
_POOL_SAMPLE_STRATA = 10


def _pk_bounds() -> Optional[tuple[int, int]]:
    """The whole `Card` table's pk range - two index-scan aggregates, O(1) regardless of
    catalogue size. Used only to choose random windows to sample WITHIN below; each lane's own
    filter/exclude clauses still apply inside every window, so a window with few or no
    qualifying rows just yields fewer entries, never a wrong one. `None` when the table is
    empty."""
    bounds = Card.objects.aggregate(lo=Min("pk"), hi=Max("pk"))
    if bounds["lo"] is None:
        return None
    return bounds["lo"], bounds["hi"]


def _shuffled_pk_strata(pk_min: int, pk_max: int, strata: int = _POOL_SAMPLE_STRATA) -> list[tuple[int, int]]:
    """`strata` contiguous, non-overlapping `[lo, hi)` windows spanning the whole `[pk_min,
    pk_max]` range, freshly shuffled into random order on every call - so successive warms (and
    the different builders within one warm) draw from a different sequence of windows rather
    than the same fixed partition every time. Clamped to at most one window per pk when the
    range is smaller than `strata`, so a tiny catalogue (as in tests) still gets full coverage
    rather than empty windows."""
    total = pk_max - pk_min + 1
    strata = max(1, min(strata, total))
    base_width, remainder = divmod(total, strata)
    windows: list[tuple[int, int]] = []
    lo = pk_min
    for i in range(strata):
        # First `remainder` windows absorb the one extra pk each, rather than a single
        # oversized/undersized final window - so window count is exactly `strata`, never fewer
        # from a plain ceil-division width silently under-covering the range (e.g. a width of
        # `ceil(15 / 10) = 2` only spans 8 windows over a 15-pk range, not the target 10).
        width = base_width + (1 if i < remainder else 0)
        hi = lo + width
        windows.append((lo, hi))
        lo = hi
    random.shuffle(windows)
    return windows


def _pool_sample_chunk_size(limit: int, strata: int = _POOL_SAMPLE_STRATA) -> int:
    """Per-window row budget for `_sample_across_pk_strata`, sized to roughly double the even
    split of `limit` across `strata` windows - so no single randomly-chosen window can satisfy a
    whole pool on its own. Without this cap, one oversized import batch confined to a single
    window could fill the entire pool before any other window is even visited, silently
    defeating the "sample across batches" property this module exists to restore. At least
    `strata // 2` distinct windows must contribute before `limit` is reached, even in that
    adversarial case."""
    return max(1, -(-limit // strata) * 2)


def _sample_across_pk_strata(queryset: Any, chunk_size: int, strata: int = _POOL_SAMPLE_STRATA) -> Iterator[Any]:
    """Bounded-cost replacement for consuming `queryset`'s own head (`.order_by(<field>)[:limit]`
    or an unbounded walk stopped at the first `limit` matches) - both cluster on whichever import
    batch happens to sort first, which is the defect this function exists to fix (see "SAMPLE THE
    POPULATION, NOT THE HEAD" in the module docstring). Visits the whole `Card` table's pk range
    in `strata` windows, shuffled into random order by `_shuffled_pk_strata`, and yields up to
    `chunk_size` of `queryset`'s own rows (whatever `.values_list()`/model shape `queryset` was
    already built with) from each window in turn, ordered by pk within the window.

    Total rows touched is bounded by `strata * chunk_size` - proportional to the caller's own
    chunk budget, never to the size of `queryset`'s underlying qualifying population; a caller
    that stops consuming early (e.g. once it has collected its pool's `limit`) pays even less,
    since unvisited windows are simply never queried. `queryset`'s own filter/exclude clauses are
    untouched - only its windowing changes, never which rows qualify."""
    bounds = _pk_bounds()
    if bounds is None:
        return
    pk_min, pk_max = bounds
    for lo, hi in _shuffled_pk_strata(pk_min, pk_max, strata):
        yield from queryset.filter(pk__gte=lo, pk__lt=hi).order_by("pk")[:chunk_size]


# ---------------------------------------------------------------------------------------------
# Pool builders (warm-time only). Each mirrors its live tier function's own filter/exclude
# clauses from `question_feed.py` - collecting up to `settings.QUESTION_FEED_POOL_SIZE` matches
# per sub-kind, sampled across the qualifying population via `_sample_across_pk_strata` rather
# than taken from the query's own head (see module docstring), since this now runs once per warm
# cycle instead of once per page view. Never applies per-voter exclusion (`answered_card_ids` and
# friends) - pools are shared, that's a read-time-only concern (see module docstring).
# ---------------------------------------------------------------------------------------------


def _build_pool_resolution_imminent() -> list[PoolEntry]:
    # Local import: `question_feed.py` imports this module at its own top level, so importing
    # back from it here at module scope would be a circular import at load time. Deferred to
    # call time (warm-time only, never on the request path), this is the standard way to break
    # that cycle without duplicating `is_likely_resolve_printing`'s consensus-facing arithmetic.
    from cardpicker.question_feed import is_likely_resolve_printing

    limit = settings.QUESTION_FEED_POOL_SIZE
    candidates = Card.objects.filter(
        printing_tag_status=PrintingTagStatus.UNRESOLVED, printing_tags__isnull=False
    ).distinct()
    matches: list[Card] = []
    for card in _sample_across_pk_strata(candidates, chunk_size=_pool_sample_chunk_size(limit)):
        if is_likely_resolve_printing(card):
            matches.append(card)
            if len(matches) >= limit:
                break
    matches.sort(key=lambda card: card.date_created)
    return [PoolEntry(kind=KIND_PRINTING, card_id=card.pk) for card in matches]


def _build_pool_confirm() -> list[PoolEntry]:
    # `_confirm_suggestion_item` (issue #766) now returns `None` for a card whose recorded
    # evidence is incomplete, not just for a card with no machine suggestion at all - so this
    # builder can legitimately come back empty even though `candidates` below is non-empty,
    # rather than that meaning a bug in the sampling. See question_feed.py's own "Evidence-gated
    # printing-confirmation policy" docstring section for the measured scale of that today.
    from cardpicker.question_feed import _confirm_suggestion_item

    limit = settings.QUESTION_FEED_POOL_SIZE
    candidates = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .distinct()
    )
    matches: list[Card] = []
    for card in _sample_across_pk_strata(candidates, chunk_size=_pool_sample_chunk_size(limit)):
        if _confirm_suggestion_item(card) is not None:
            matches.append(card)
            if len(matches) >= limit:
                break
    matches.sort(key=lambda card: card.date_created)
    return [PoolEntry(kind=KIND_PRINTING, card_id=card.pk) for card in matches]


def _build_pool_contested() -> list[PoolEntry]:
    limit = settings.QUESTION_FEED_POOL_SIZE
    contested_card_ids = get_contested_card_ids()
    contested_artist_card_ids = get_contested_artist_card_ids()

    printing_candidates = Card.objects.filter(
        printing_tag_status=PrintingTagStatus.UNRESOLVED, pk__in=contested_card_ids
    ).values_list("pk", "date_created")
    printing_rows: list[tuple[int, Any]] = []
    for pk, date_created in _sample_across_pk_strata(printing_candidates, chunk_size=_pool_sample_chunk_size(limit)):
        printing_rows.append((pk, date_created))
        if len(printing_rows) >= limit:
            break
    printing_rows.sort(key=lambda row: row[1], reverse=True)
    entries: list[PoolEntry] = [PoolEntry(kind=KIND_PRINTING, card_id=pk) for pk, _ in printing_rows]

    artist_candidates = Card.objects.filter(
        artist_vote_status=ArtistVoteStatus.CONTESTED, pk__in=contested_artist_card_ids
    ).values_list("pk", "date_created")
    artist_rows: list[tuple[int, Any]] = []
    for pk, date_created in _sample_across_pk_strata(artist_candidates, chunk_size=_pool_sample_chunk_size(limit)):
        artist_rows.append((pk, date_created))
        if len(artist_rows) >= limit:
            break
    artist_rows.sort(key=lambda row: row[1], reverse=True)
    entries.extend(PoolEntry(kind=KIND_ARTIST, card_id=pk) for pk, _ in artist_rows)

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

    printing_candidates = (
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
        .values_list("pk", "origin_reason", "vote_count", "is_quick_negative", "date_created")
    )
    printing_rows: list[tuple[int, Any, int, int, Any]] = []
    for row in _sample_across_pk_strata(printing_candidates, chunk_size=_pool_sample_chunk_size(limit)):
        printing_rows.append(row)
        if len(printing_rows) >= limit:
            break
    # Stable multi-pass sort reproduces `order_by("-vote_count", "is_quick_negative",
    # "-date_created")` on the sampled rows: least significant key sorted first, most
    # significant sorted last, relying on Python's sort stability to compose them.
    printing_rows.sort(key=lambda row: row[4], reverse=True)
    printing_rows.sort(key=lambda row: row[3])
    printing_rows.sort(key=lambda row: row[2], reverse=True)
    entries: list[PoolEntry] = [
        PoolEntry(
            kind=KIND_PRINTING,
            card_id=pk,
            reason=(
                "tier_4_quick_negative_to_review"
                if origin_reason in QUICK_NEGATIVE_SKIP_REASONS
                else "tier_4_fresh_printing"
            ),
        )
        for pk, origin_reason, _vote_count, _is_quick_negative, _date_created in printing_rows
    ]

    artist_candidates = Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED).values_list(
        "pk", "date_created"
    )
    artist_rows: list[tuple[int, Any]] = []
    for pk, date_created in _sample_across_pk_strata(artist_candidates, chunk_size=_pool_sample_chunk_size(limit)):
        artist_rows.append((pk, date_created))
        if len(artist_rows) >= limit:
            break
    artist_rows.sort(key=lambda row: row[1], reverse=True)
    entries.extend(PoolEntry(kind=KIND_ARTIST, card_id=pk) for pk, _ in artist_rows)

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


def draw_resolution_imminent_card(
    answered_card_ids: set[int], hidden_card_ids: Optional[set[int]] = None
) -> Optional[Card]:
    entries = _get_cached_pool(LANE_RESOLUTION_IMMINENT)
    if not entries:
        return None
    hidden_card_ids = hidden_card_ids or set()
    for entry in _iter_windowed_from_random_offset(entries):
        if entry.card_id in answered_card_ids:
            continue
        if entry.card_id in hidden_card_ids:
            continue
        card = _fetch_unresolved_printing_card(entry.card_id)
        if card is not None:
            return card
    return None


def draw_confirm_card(answered_card_ids: set[int], hidden_card_ids: Optional[set[int]] = None) -> Optional[Card]:
    entries = _get_cached_pool(LANE_CONFIRM)
    if not entries:
        return None
    hidden_card_ids = hidden_card_ids or set()
    for entry in _iter_windowed_from_random_offset(entries):
        if entry.card_id in answered_card_ids:
            continue
        if entry.card_id in hidden_card_ids:
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
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[str, Card, Optional[str], Optional[str]]]:
    """Returns `(kind, card, tag_name, reason)` for the first unexcluded, unstale entry found via
    `_iter_by_kind_precedence` (printing entries entirely before artist, before tag - see that
    function's own docstring), or `None`. Exclusion sets match `_tier_2_contested`'s own exactly - all
    three (`answered_card_ids`/`answered_artist_card_ids`/`answered_tag_card_ids_by_tag`) are
    already the md5-widened, per-request-memoised sets `get_next_question_feed_item` computes
    once and threads through, same as the live tier. `hidden_card_ids` (this voter's
    `question_feed._voter_hidden_card_ids` set, `None` for a direct caller meaning no hidden
    exclusion) applies to all three kinds at once - the live tier excludes a hidden card from
    its printing AND artist querysets and its tag loop, and this reproduces that card-level
    exclusion here rather than per-kind."""
    entries = _get_cached_pool(LANE_CONTESTED)
    if not entries:
        return None
    hidden_card_ids = hidden_card_ids or set()
    for entry in _iter_by_kind_precedence(entries):
        if entry.card_id in hidden_card_ids:
            continue
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
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[str, Card, Optional[str], Optional[str]]]:
    """The cold-lane analogue of `draw_contested_entry`. `contested_card_ids` is re-checked
    in-memory (a card can have gone from fresh to contested since this pool's last warm) -
    mirrors `_tier_4_fresh`'s own `.exclude(pk__in=contested_card_ids)`. The artist/tag halves
    deliberately use an UNWIDENED, per-candidate `anonymous_id` existence check rather than the
    md5-widened `answered_artist_card_ids`/`answered_tag_card_ids_by_tag` sets - `_tier_4_fresh`
    itself keeps its own pre-existing unwidened form for both (see that function's own docstring
    for why: the widened convention is scoped to `_tier_2_contested` only), so reproducing it
    here means one extra indexed query per artist/tag candidate scanned rather than a second,
    possibly-diverging exclusion rule. `hidden_card_ids` (`question_feed._voter_hidden_card_ids`,
    `None` for a direct caller meaning no hidden exclusion) is applied card-level, same as the
    contested lane above."""
    entries = _get_cached_pool(LANE_COLD)
    if not entries:
        return None
    hidden_card_ids = hidden_card_ids or set()
    contested_card_id_set = set(contested_card_ids)
    for entry in _iter_by_kind_precedence(entries):
        if entry.card_id in hidden_card_ids:
            continue
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
