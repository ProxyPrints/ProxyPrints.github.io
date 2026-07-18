"""
Backs `GET 2/questionFeed/` - the unified single-question feed that replaces the three
printing/artist/tag tabs (see docs/features/printing-tags.md's questionFeed section and
journal/2026-07-14-queue-question-feed-design.md for the full design writeup this
implements). Deliberately a "dumb ranked union" per spec: three fixed-order tiers, first
non-empty match wins, no cross-tier scoring/ML.

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
"""

from typing import Optional

from django.db.models import Count, Q

from cardpicker.artist_consensus import get_contested_artist_card_ids
from cardpicker.attribute_tags import ATTRIBUTE_CHIP_TAG_NAMES
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardTagVote,
    PrintingTagStatus,
    Tag,
    TagVoteStatus,
    VoteSource,
)
from cardpicker.printing_candidates import get_ranked_printing_candidates
from cardpicker.printing_consensus import get_contested_card_ids
from cardpicker.schema_types import QuestionFeedCounts, QuestionFeedItem, TypeEnum
from cardpicker.tag_consensus import get_tag_net_polarity, get_tag_review_queue_pairs


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


def _tier_2_contested(anonymous_id: str) -> Optional[QuestionFeedItem]:
    printing_card = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, pk__in=get_contested_card_ids())
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if printing_card is not None:
        return _identify_printing_item(printing_card)

    artist_card = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.CONTESTED, pk__in=get_contested_artist_card_ids())
        .exclude(artist_votes__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if artist_card is not None:
        return _artist_item(artist_card)

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
            return _tag_item(card, tag_name)
    return None


def _tier_4_fresh(anonymous_id: str) -> Optional[QuestionFeedItem]:
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
    printing_card = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .exclude(pk__in=get_contested_card_ids())
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .annotate(vote_count=Count("printing_tags", distinct=True))
        .order_by("-vote_count", "-date_created")
        .first()
    )
    if printing_card is not None:
        return _identify_printing_item(printing_card)

    artist_card = (
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        .exclude(artist_votes__anonymous_id=anonymous_id)
        .order_by("-date_created")
        .first()
    )
    if artist_card is not None:
        return _artist_item(artist_card)

    for card_id, tag_name in get_tag_review_queue_pairs():
        # see tier 2's identical comment above - scoped to (card, tag, anonymous_id)
        if CardTagVote.objects.filter(card_id=card_id, tag__name=tag_name, anonymous_id=anonymous_id).exists():
            continue
        card = Card.objects.get(pk=card_id)
        status = card.tag_vote_statuses.get(tag_name)
        if status == TagVoteStatus.UNRESOLVED:
            return _tag_item(card, tag_name)
    return None


def get_next_question_feed_item(anonymous_id: str) -> Optional[QuestionFeedItem]:
    """The dumb ranked union itself - first non-None tier wins, in priority order."""
    return _tier_1_confirm_suggestion(anonymous_id) or _tier_2_contested(anonymous_id) or _tier_4_fresh(anonymous_id)


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


__all__ = ["get_next_question_feed_item", "get_remaining_estimate"]
