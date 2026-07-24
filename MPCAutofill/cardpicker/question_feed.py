"""
Backs `GET 2/questionFeed/` - the unified single-question feed that replaces the three
printing/artist/tag tabs (see docs/features/printing-tags.md's questionFeed section and
journal/2026-07-14-queue-question-feed-design.md for the full design writeup this
implements). Deliberately a "dumb ranked union" per spec: three fixed-order tiers, first
non-empty match wins, no cross-tier scoring/ML - EXCEPT for the one deliberate ordering policy
this module now adds on top of that union (2026-07-24, see "Mix composition policy" below),
which is a served-question SELECTION change only, never a change to how any of tiers 1/2/4
individually rank their own candidates.

Tier 1 (confirm_suggestion) is large relative to the others at current volume (28,112 cards
- the full AI deductive-vote backfill, confirmed via a live query during design) - a voter
working only this feed will not reach tiers 2-3 until tier 1 is exhausted. Flagged as a known
v1 property, not silently accepted - see the design doc's "Starvation risk" section for the
concrete consequence and the planned v2 fix (interleaved/weighted union, out of scope here).

Moderator report review used to be a fourth tier here (pending_approval pairs, moderator-only,
ranked between tiers 2 and 3-formerly-4) but that made every pending report displace the
normal tagging feed entirely for any moderator, for as long as reports stayed pending -
moved out to a dedicated Moderation tab (`POST 2/moderationQueue/` in views.py, unaffected by
this module) so ordinary tagging and report review are separate, switchable views instead of
one hijacking the other. See docs/features/moderation.md.

Mix composition policy (2026-07-24, owner-ratified per the WTC vote-queue data brief - fenced
report tail, item "OWNER ADDENDUM"; full citation in docs/features/printing-tags.md's "Unified
question feed" section): serve >=`settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO` (default
0.51) of a session's questions from the LIKELY-RESOLVE pool - a printing question one more
agreeing human vote would actually resolve under the real resolver, per
`is_likely_resolve_printing` below - whenever that pool still has supply for this voter,
falling back to the pre-existing three-tier ranked union otherwise (with one refinement inside
tier 4 - see `_tier_4_fresh`'s own docstring - that prioritizes cards whose latest Stage D
scan-log origin is a "quick-negative" reason over the harder/open-ended remainder, per the same
data brief's queue-composition ranking). This is a SELECTION-LAYER policy only: it makes zero
change to `vote_consensus.resolve_weighted_consensus`'s weights, `PRINTING_TAG_MIN_VOTES`/
`MIN_SHARE` thresholds, or the D1/D4 human-backed-priority mechanisms - `is_likely_resolve_
printing` calls that same real resolver to classify a question, it never reimplements its
arithmetic. Every served item (from either the likely-resolve pool or the remainder) is
recorded in `QuestionFeedServedLog` - the bias-conditioning record the data brief's SOUNDNESS
NOTE calls for, so a future audit can correlate click behavior against a session's
easy-question exposure. See `_served_mix_ratio`/`_log_served` below.
"""

from collections import defaultdict
from typing import Hashable, Optional

from django.conf import settings
from django.db.models import (
    Case,
    Count,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)

from cardpicker.artist_consensus import get_contested_artist_card_ids
from cardpicker.attribute_tags import ATTRIBUTE_CHIP_TAG_NAMES
from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
)
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardScanLog,
    CardTagVote,
    PrintingTagStatus,
    QuestionFeedServedLog,
    QuestionFeedServedPool,
    Tag,
    TagVoteStatus,
    VoteSource,
)
from cardpicker.printing_candidates import get_ranked_printing_candidates
from cardpicker.printing_consensus import NO_MATCH, get_contested_card_ids
from cardpicker.schema_types import QuestionFeedCounts, QuestionFeedItem, TypeEnum
from cardpicker.tag_consensus import get_tag_net_polarity, get_tag_review_queue_pairs
from cardpicker.vote_consensus import (
    VoteTuple,
    is_human_backed_source,
    resolve_vote_weight,
    resolve_weighted_consensus,
)

# Origin reasons `local_calculate_verdicts.py`'s Stage D join-key/fallback calculators write to
# `CardScanLog.skip_reason` that the 2026-07-24 data brief's queue-composition item classifies
# as "answerable-as-quick-negative" - a quick, low-ambiguity classification click (custom-art/
# no-match/visual-contradiction), not an open-ended one. Two of these have named constants in
# `local_calculate_verdicts.py` already (imported above); "eliminated"/"border-mismatch"/
# "frame-mismatch" are that module's own inline skip-reason vocabulary (no named constant exists
# for these three there today) taken verbatim - see that module's own skip_reason call sites.
# Deliberately EXCLUDES "ambiguous" despite the brief calling it "YES - answerable" in principle:
# the same brief's prioritization item ranks it as BLOCKED on a build dependency
# (`CardScanLog.survivor_pks` is unpopulated for every to-review card - see that field's own
# docstring), not free supply today, so it falls into this module's default/hard-open-ended
# bucket alongside "no-sub-check-evidence"/"no-text" rather than the quick-negative one.
QUICK_NEGATIVE_SKIP_REASONS = frozenset(
    {JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON, "eliminated", "border-mismatch", "frame-mismatch"}
)

# anonymous_id placeholder for the hypothetical vote `is_likely_resolve_printing` adds - never
# persisted, never compared against a real anonymous_id; passed through `resolve_vote_weight`
# (rather than reading `vote_consensus._SOURCE_WEIGHTS[VoteSource.USER]` directly) purely so this
# stays routed through the one sanctioned weight-resolution entry point, matching every other
# caller's convention, even though `resolve_vote_weight`'s only override (the deductive-backfill
# zero-weight cohort) can never match `source=VoteSource.USER` regardless of anonymous_id.
_HYPOTHETICAL_VOTE_ANONYMOUS_ID = "question-feed-hypothetical-vote"


def _tag_confidence(card: Card) -> dict[str, float]:
    """netPolarity for every attribute-chip tag against `card`, for the chip fill overlay -
    always the full fixed set (not just tags with votes), so an unvoted chip predictably reads
    as 0.0 (neutral) rather than being absent from the payload."""
    tags_by_name = {tag.name: tag for tag in Tag.objects.filter(name__in=ATTRIBUTE_CHIP_TAG_NAMES)}
    return {name: get_tag_net_polarity(card, tag) for name, tag in tags_by_name.items()}


def _confirm_suggestion_item(card: Card) -> Optional[QuestionFeedItem]:
    ai_vote = (
        card.printing_tags.filter(source__in=[VoteSource.DEDUCTION, VoteSource.OCR], is_no_match=False)
        .select_related("printing__expansion", "printing__printing_metadata", "printing__artist")
        .first()
    )
    if ai_vote is None or ai_vote.printing is None:
        return None
    candidates = get_ranked_printing_candidates(card, card.name)
    return QuestionFeedItem(
        type=TypeEnum.confirmsuggestion,
        card=card.serialise(),
        suggestedPrinting=ai_vote.printing.serialise_as_printing_candidate(),
        candidates=[candidate.serialise_as_printing_candidate() for candidate in candidates],
        tagConfidence=_tag_confidence(card),
    )


def _identify_printing_item(card: Card) -> QuestionFeedItem:
    candidates = get_ranked_printing_candidates(card, card.name)
    return QuestionFeedItem(
        type=TypeEnum.identifyprinting,
        card=card.serialise(),
        candidates=[candidate.serialise_as_printing_candidate() for candidate in candidates],
        tagConfidence=_tag_confidence(card),
    )


def _artist_item(card: Card) -> QuestionFeedItem:
    serialised = card.serialise()
    confidently_known_artist_name = (
        serialised.canonicalArtist.name
        if serialised.canonicalArtist is not None and not serialised.canonicalArtistIsFromVoteOnly
        else None
    )
    return QuestionFeedItem(
        type=TypeEnum.artist, card=serialised, confidentlyKnownArtistName=confidently_known_artist_name
    )


def _tag_item(card: Card, tag_name: str) -> QuestionFeedItem:
    return QuestionFeedItem(type=TypeEnum.tag, card=card.serialise(), tagName=tag_name)


def _printing_vote_tuples(card: Card) -> list[VoteTuple]:
    """
    Builds `VoteTuple`s for `card`'s current `CardPrintingTag` rows - the exact same per-vote
    weight/human-backed resolution `printing_consensus.resolve_printing` uses
    (`resolve_vote_weight`/`is_human_backed_source`, both imported from `vote_consensus` rather
    than reimplemented), just without that function's private printing-lookup bookkeeping this
    caller doesn't need (only the outcome KEY, an int pk or the `NO_MATCH` sentinel, matters
    for the likely-resolve check below).
    """
    return [
        VoteTuple(
            outcome_key=NO_MATCH if vote.is_no_match else vote.printing_id,
            weight=resolve_vote_weight(vote.source, vote.anonymous_id),
            is_human_backed=is_human_backed_source(vote.source),
        )
        for vote in card.printing_tags.all()
    ]


def is_likely_resolve_printing(card: Card) -> bool:
    """
    True when ONE hypothetical additional agreeing human vote (`VoteSource.USER` weight) added
    to `card`'s current highest-weighted printing outcome group would resolve it under the REAL
    resolver (`vote_consensus.resolve_weighted_consensus` - the same function
    `printing_consensus.resolve_printing` calls; this never reimplements its weight/threshold
    arithmetic). This is the serve-time LIKELY-RESOLVE classification the 2026-07-24 data
    brief's exact-code simulation approach specifies (the same method that produced its
    46,310-card LIKELY-RESOLVE SUPPLY figure): find the currently-leading outcome group by
    summed weight, add one hypothetical `VoteSource.USER` vote to THAT group, re-run the real
    resolver, and check whether it wins with that group's own key.

    False for a card with no printing-tag votes at all (there is no "leading" group to add to -
    this is exactly the cold-start population the brief's item 1 table calls out as having
    "ZERO non-zero-weight signal", never likely-resolve by this definition) and false for an
    already-RESOLVED card (a caller should never ask, since `_likely_resolve_printing_card`
    only scans `PrintingTagStatus.UNRESOLVED` cards, but this stays a plain `False` rather than
    raising either way - the resolver would simply report the same key already won, which this
    function would then also (correctly, if uninterestingly) report as "likely resolve").
    """
    vote_tuples = _printing_vote_tuples(card)
    if not vote_tuples:
        return False

    current_weight_by_key: dict[Hashable, float] = defaultdict(float)
    for vote in vote_tuples:
        current_weight_by_key[vote.outcome_key] += vote.weight
    leading_key = max(current_weight_by_key.items(), key=lambda pair: pair[1])[0]

    hypothetical_vote = VoteTuple(
        outcome_key=leading_key,
        weight=resolve_vote_weight(VoteSource.USER, _HYPOTHETICAL_VOTE_ANONYMOUS_ID),
        is_human_backed=True,
    )
    winning_key = resolve_weighted_consensus(
        vote_tuples + [hypothetical_vote],
        min_weight=settings.PRINTING_TAG_MIN_VOTES,
        min_share=settings.PRINTING_TAG_MIN_SHARE,
    )
    return winning_key == leading_key


def _likely_resolve_printing_card(anonymous_id: str) -> Optional[Card]:
    """
    First UNRESOLVED printing card (in `date_created` order, same scan convention tier 1 uses)
    that both carries at least one existing `CardPrintingTag` row and passes
    `is_likely_resolve_printing` - the >=51% mix-composition policy's own supply pool (see this
    module's docstring for the ratio policy this feeds, and `get_next_question_feed_item` for
    where it's consulted).

    Cost/approach (compute-per-serve, no caching layer - stated per this change's own spec):
    pre-filters to `printing_tags__isnull=False` (97,212 of 218,345 cards at the 2026-07-24 data
    brief's snapshot - cards carrying ANY printing-tag signal, not the full unresolved
    population, though this still includes the ~8k zero-weight-only deductive-backfill rows
    that `is_likely_resolve_printing` will correctly reject) before doing a per-card Python-side
    `is_likely_resolve_printing` check via `.iterator()` - the same "scan in priority order,
    stop at the first match" shape `_tier_1_confirm_suggestion` already uses, not a new
    performance-risk pattern this change introduces. Worst case (this voter has already
    excluded most of the pool, or the pool is nearly exhausted) is a bounded scan of the
    pre-filtered ~97k rows, not the full 218k-card catalog and not unbounded - accepted as a v1
    cost matching this module's own "known v1 property, not a bug" convention (see the module
    docstring), not solved with a materialized/cached index here.
    """
    candidates = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, printing_tags__isnull=False)
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .distinct()
        .order_by("date_created")
    )
    for card in candidates.iterator():
        if is_likely_resolve_printing(card):
            return card
    return None


def _likely_resolve_item(card: Card) -> QuestionFeedItem:
    """Serves `card` as a `confirm_suggestion` (it has a live AI-sourced suggestion to confirm -
    the common shape within this pool, the data brief's 45,154-of-46,310 single-candidate split)
    or a bare `identify_printing` question (the multi-candidate remainder) - the same two item
    shapes tiers 1/2 already produce; the likely-resolve pool changes WHICH card gets served
    first, never what an individual served item looks like."""
    item = _confirm_suggestion_item(card)
    if item is not None:
        return item
    return _identify_printing_item(card)


def _tier_1_confirm_suggestion(anonymous_id: str) -> Optional[QuestionFeedItem]:
    cards = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .distinct()
        .order_by("date_created")
    )
    for card in cards.iterator():
        item = _confirm_suggestion_item(card)
        if item is not None:
            return item
    return None


def _tier_2_contested(anonymous_id: str) -> Optional[tuple[QuestionFeedItem, str]]:
    printing_card = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, pk__in=get_contested_card_ids())
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if printing_card is not None:
        return _identify_printing_item(printing_card), "tier_2_contested_printing"

    artist_card = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.CONTESTED, pk__in=get_contested_artist_card_ids())
        .exclude(artist_votes__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if artist_card is not None:
        return _artist_item(artist_card), "tier_2_contested_artist"

    for card_id, tag_name in get_tag_review_queue_pairs():
        # scoped to (card, tag, anonymous_id), not just (card, anonymous_id) - a voter who
        # already answered a *different* tag on this card (there are ~11 attribute-chip tags
        # per card) must still see this tag if they haven't answered it yet. A card-level
        # exclude here would silently hide every other still-open tag on a card the moment
        # this voter touches any one tag on it.
        if CardTagVote.objects.filter(card_id=card_id, tag__name=tag_name, anonymous_id=anonymous_id).exists():
            continue
        card = Card.objects.get(pk=card_id)
        status = card.tag_vote_statuses.get(tag_name)
        if status == TagVoteStatus.CONTESTED:
            return _tag_item(card, tag_name), "tier_2_contested_tag"
    return None


def _latest_stage_d_origin_reason_subquery() -> Subquery:
    """Correlated subquery: `card`'s most recent Stage D join-key/fallback `CardScanLog.
    skip_reason` (the ORIGIN reason - the specific sub-check outcome that first routed this card
    toward review), or `None` if no such row exists. Feeds `_tier_4_fresh`'s quick-negative
    reordering below - see that function's own docstring for why."""
    return Subquery(
        CardScanLog.objects.filter(
            card_id=OuterRef("pk"), anonymous_id__in=[JOIN_KEY_ANONYMOUS_ID, STAGE_D_FALLBACK_ANONYMOUS_ID]
        )
        .order_by("-scanned_at")
        .values("skip_reason")[:1]
    )


def _tier_4_fresh(anonymous_id: str) -> Optional[tuple[QuestionFeedItem, str]]:
    # named "tier 4" (not renumbered to 3) even though moderation's former tier 3 was removed
    # (see module docstring) - keeps this name stable against every docstring/test/comment
    # that already refers to "tier 4" rather than triggering a pure-renumbering diff.
    # A card with one AI-sourced vote plus one *agreeing* human vote (weight 1.5 at default
    # settings - still short of PRINTING_TAG_MIN_VOTES=2) is exactly as close to resolving as
    # a card can get without being resolved outright, yet it's excluded from tier 1 (any human
    # vote moves a card out of tier 1's "AI-only" pool) and isn't contested (agreeing votes,
    # not conflicting, so tier 2's contested check doesn't catch it either) - it lands here,
    # in tier 4, with zero votes and 28,112 genuinely-untouched cards. `-vote_count` surfaces
    # these "one vote from resolving" cards first within this tier, a small, concrete answer
    # to "prioritize whichever question is closest to actually resolving" without building a
    # full scoring system (out of scope - see this module's docstring).
    #
    # 2026-07-24 addition: `is_quick_negative` is a SECONDARY tiebreak (after `-vote_count`,
    # never ahead of it - a real "closer to resolving" card still wins first, exactly as
    # before) that prioritizes a card whose latest Stage D scan-log origin is a quick-negative
    # reason (`QUICK_NEGATIVE_SKIP_REASONS`) over one that's hard/open-ended or has no scan-log
    # row at all - the data brief's queue-composition ranking's second-from-last remainder
    # slice, ahead of the smallest "hard/open-ended" slice. Most tier-4 candidates share
    # `vote_count=0` (the "totally fresh" case), so in practice this origin-reason tiebreak is
    # what actually decides ordering among them, not a rarely-reached fallback.
    printing_card = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .exclude(pk__in=get_contested_card_ids())
        .exclude(printing_tags__anonymous_id=anonymous_id)
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
        .first()
    )
    if printing_card is not None:
        origin_reason = (
            "tier_4_quick_negative_to_review"
            if printing_card.origin_reason in QUICK_NEGATIVE_SKIP_REASONS
            else "tier_4_fresh_printing"
        )
        return _identify_printing_item(printing_card), origin_reason

    artist_card = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        .exclude(artist_votes__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if artist_card is not None:
        return _artist_item(artist_card), "tier_4_fresh_artist"

    for card_id, tag_name in get_tag_review_queue_pairs():
        # see tier 2's identical comment above - scoped to (card, tag, anonymous_id)
        if CardTagVote.objects.filter(card_id=card_id, tag__name=tag_name, anonymous_id=anonymous_id).exists():
            continue
        card = Card.objects.get(pk=card_id)
        status = card.tag_vote_statuses.get(tag_name)
        if status == TagVoteStatus.UNRESOLVED:
            return _tag_item(card, tag_name), "tier_4_fresh_tag"
    return None


def _served_mix_ratio(anonymous_id: str) -> float:
    """
    `likely_resolve` share of this `anonymous_id`'s own served-question history so far
    (`QuestionFeedServedLog`) - consulted by `get_next_question_feed_item` to decide whether the
    NEXT served item should try the likely-resolve pool first. Two cheap `COUNT` queries,
    indexed on `(anonymous_id, served_at)` - no per-row scan, no caching needed at this cost.

    Returns 0.0 (below every plausible target ratio) for a session with no served-log rows yet,
    so a fresh session's very first question still tries the likely-resolve pool, rather than
    treating "no data" as "ratio already satisfied."
    """
    total = QuestionFeedServedLog.objects.filter(anonymous_id=anonymous_id).count()
    if total == 0:
        return 0.0
    likely_resolve_count = QuestionFeedServedLog.objects.filter(
        anonymous_id=anonymous_id, pool=QuestionFeedServedPool.LIKELY_RESOLVE
    ).count()
    return likely_resolve_count / total


def _log_served(anonymous_id: str, item: QuestionFeedItem, pool: str, origin_reason: str) -> QuestionFeedItem:
    """Records one served-question row (see `QuestionFeedServedLog`'s own docstring for why -
    the data brief's SOUNDNESS NOTE bias-conditioning record) and returns `item` unchanged, so
    every `get_next_question_feed_item` return path can stay a simple one-liner."""
    QuestionFeedServedLog.objects.create(
        anonymous_id=anonymous_id, pool=pool, question_type=item.type.value, origin_reason=origin_reason
    )
    return item


def get_next_question_feed_item(anonymous_id: str) -> Optional[QuestionFeedItem]:
    """
    The ranked union itself. When this session's served-mix ratio (`_served_mix_ratio`) is
    below `settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO` AND the likely-resolve pool still
    has supply for this voter, that pool is served first - otherwise (ratio already at/above
    target, or the pool has no supply for this voter right now) this falls through to the
    pre-existing three-tier ranked union unchanged (tier 1 -> tier 2 -> tier 4, first non-empty
    tier wins), with tier 4's own quick-negative reordering (see its docstring). This never
    infinite-loops or blocks on a starved pool - each branch is a single bounded query/scan, and
    an exhausted likely-resolve pool simply falls through to the remainder every time, letting
    the session's ratio drop honestly rather than stalling to protect it.
    """
    if _served_mix_ratio(anonymous_id) < settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO:
        likely_resolve_card = _likely_resolve_printing_card(anonymous_id)
        if likely_resolve_card is not None:
            item = _likely_resolve_item(likely_resolve_card)
            return _log_served(
                anonymous_id, item, QuestionFeedServedPool.LIKELY_RESOLVE, "printing_one_vote_from_resolving"
            )

    tier_1_item = _tier_1_confirm_suggestion(anonymous_id)
    if tier_1_item is not None:
        return _log_served(anonymous_id, tier_1_item, QuestionFeedServedPool.REMAINDER, "tier_1_confirm_suggestion")

    tier_2_result = _tier_2_contested(anonymous_id)
    if tier_2_result is not None:
        tier_2_item, tier_2_reason = tier_2_result
        return _log_served(anonymous_id, tier_2_item, QuestionFeedServedPool.REMAINDER, tier_2_reason)

    tier_4_result = _tier_4_fresh(anonymous_id)
    if tier_4_result is not None:
        tier_4_item, tier_4_reason = tier_4_result
        return _log_served(anonymous_id, tier_4_item, QuestionFeedServedPool.REMAINDER, tier_4_reason)

    return None


def _tag_review_card_ids_by_status() -> tuple[set[int], set[int]]:
    """
    (contested_card_ids, unresolved_card_ids) - distinct cards with >=1 persisted
    `tag_vote_statuses` entry of that status. Same source query as
    `tag_consensus.get_tag_review_queue_pairs` (one pass over `Card.tag_vote_statuses` - a
    JSONField has no native per-key/per-value DB filter, see that function's docstring), but
    skips its second query (vote weights, for pair ordering) and the interleaving, since a
    distinct-card count doesn't need per-pair identity or ordering.
    """
    contested_ids: set[int] = set()
    unresolved_ids: set[int] = set()
    for card_id, statuses in Card.objects.exclude(tag_vote_statuses={}).values_list("id", "tag_vote_statuses"):
        values = statuses.values()
        if TagVoteStatus.CONTESTED in values:
            contested_ids.add(card_id)
        if TagVoteStatus.UNRESOLVED in values:
            unresolved_ids.add(card_id)
    return contested_ids, unresolved_ids


def get_remaining_estimate() -> QuestionFeedCounts:
    """
    "Still need help with" counts for the feed header - NOT per-voter (doesn't account for
    own-vote exclusion, which is comparatively cheap to skip here since this is advisory copy,
    not a candidate set). Pending-moderation-report count is deliberately not folded in here -
    it has its own badge on the dedicated Moderation tab (see this module's docstring),
    separate from ordinary tagging's "remaining" counts.

    Returns four numbers instead of one flat sum:
    - `total`: DISTINCT cards needing review in any category (printing, artist, or tag) - a
      single `.distinct().count()` query, bounded by catalogue size. This replaces the old
      implementation's `printing.count() + artist.count() + len(tag_pairs)`, which summed three
      overlapping per-category counts and could count the same untouched card 2-3+ times (every
      fresh card defaults to UNRESOLVED on *both* printing and artist simultaneously) - see
      docs/features/printing-tags.md's questionFeed section for the diagnosis that motivated
      this fix.
    - `confirmable`/`contested`/`fresh`: aggregate counts mirroring the feed's own three tiers
      (`_tier_1_confirm_suggestion`/`_tier_2_contested`/`_tier_4_fresh`), for a more informative
      header than one opaque number - e.g. "N quick confirmations" up front. These are
      independent per-tier metrics, not a partition of `total`: a single card can count toward
      more than one bucket (e.g. an AI-suggested-but-unconfirmed printing plus a still-fresh
      artist question), same as it can appear in more than one tier across separate voter
      sessions in the real feed.

    Query shape: `get_contested_card_ids()` (contested-printing ids) and
    `_tag_review_card_ids_by_status()` (contested/unresolved-tag ids) each run once and get
    reused across every bucket below - 2 queries total for those, plus one indexed `.count()`
    per bucket (4 buckets), for 6 queries overall. No per-card sub-queries in a loop - the only
    Python-side materialization is the tag-status scan, which was already the established
    pattern for this JSONField (see `_tag_review_card_ids_by_status`'s docstring).
    """
    contested_printing_ids = get_contested_card_ids()
    tag_contested_ids, tag_unresolved_ids = _tag_review_card_ids_by_status()

    confirmable = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .distinct()
        .count()
    )

    contested = (
        Card.objects.filter(
            (Q(pk__in=contested_printing_ids) & Q(printing_tag_status=PrintingTagStatus.UNRESOLVED))
            | Q(artist_vote_status=ArtistVoteStatus.CONTESTED)
            | Q(pk__in=tag_contested_ids)
        )
        .distinct()
        .count()
    )

    fresh = (
        Card.objects.filter(
            (Q(printing_tag_status=PrintingTagStatus.UNRESOLVED) & ~Q(pk__in=contested_printing_ids))
            | Q(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
            | Q(pk__in=tag_unresolved_ids)
        )
        .distinct()
        .count()
    )

    total = (
        Card.objects.filter(
            Q(printing_tag_status=PrintingTagStatus.UNRESOLVED)
            | Q(artist_vote_status__in=[ArtistVoteStatus.UNRESOLVED, ArtistVoteStatus.CONTESTED])
            | Q(pk__in=tag_contested_ids | tag_unresolved_ids)
        )
        .distinct()
        .count()
    )

    return QuestionFeedCounts(total=total, confirmable=confirmable, contested=contested, fresh=fresh)


__all__ = [
    "get_next_question_feed_item",
    "get_remaining_estimate",
    "is_likely_resolve_printing",
    "QUICK_NEGATIVE_SKIP_REASONS",
]
