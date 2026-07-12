from typing import Literal, TypedDict

from django.conf import settings
from django.db.models import Case, Count, IntegerField, Q, When

from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.vote_consensus import VoteTuple, resolve_weighted_consensus

NO_MATCH: Literal["NO_MATCH"] = "NO_MATCH"

_SOURCE_WEIGHTS: dict[str, float] = {
    VoteSource.USER: 1.0,
    VoteSource.ADMIN: settings.PRINTING_TAG_ADMIN_WEIGHT,
    VoteSource.AI: settings.PRINTING_TAG_AI_WEIGHT,
}


def resolve_printing(card: Card) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Reconciles all `CardPrintingTag` votes cast against `card` into a single resolved
    outcome: a specific `CanonicalCard` printing, the `NO_MATCH` sentinel (consensus is
    that no printing matches), or `None` if there isn't yet enough signal to conclude
    anything. See `cardpicker.vote_consensus.resolve_weighted_consensus` for the shared
    weighting/threshold rules (votes weighted by `source`, `PRINTING_TAG_MIN_VOTES`/
    `MIN_SHARE` gates, non-AI gate) - this is a thin wrapper translating `CardPrintingTag`
    rows into `VoteTuple`s and the winning outcome key back into a `CanonicalCard`.
    """
    votes = list(card.printing_tags.all())
    if not votes:
        return None

    printings_by_id: dict[int, CanonicalCard] = {}
    vote_tuples: list[VoteTuple] = []
    for vote in votes:
        key: int | Literal["NO_MATCH"]
        if vote.is_no_match:
            key = NO_MATCH
        else:
            # guaranteed non-null here by the model's printing_xor_no_match CheckConstraint
            assert vote.printing_id is not None
            assert vote.printing is not None
            key = vote.printing_id
            printings_by_id[vote.printing_id] = vote.printing
        vote_tuples.append(
            VoteTuple(outcome_key=key, weight=_SOURCE_WEIGHTS[vote.source], is_ai=vote.source == VoteSource.AI)
        )

    winning_key = resolve_weighted_consensus(
        vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
    )
    if winning_key is None:
        return None
    if winning_key == NO_MATCH:
        return NO_MATCH
    assert isinstance(winning_key, int)
    return printings_by_id[winning_key]


def resolve_and_persist_printing(card: Card) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Runs `resolve_printing(card)` and writes the outcome onto `card.inferred_canonical_card`
    and `card.printing_tag_status` together, so that `Card.serialise()` (which already reads
    `inferred_canonical_card`) and the printing-tag review queue (which filters on the
    indexed `printing_tag_status`, rather than recomputing consensus for every card) both
    stay in sync with the latest votes. Intended to be called synchronously right after a
    vote is submitted for `card` - cheap, since it only touches this one card's own votes.
    Returns the same outcome `resolve_printing` returned, so callers don't need to
    recompute it again immediately afterwards.
    """
    result = resolve_printing(card)
    if result is None:
        card.inferred_canonical_card = None
        card.printing_tag_status = PrintingTagStatus.UNRESOLVED
    elif result == NO_MATCH:
        card.inferred_canonical_card = None
        card.printing_tag_status = PrintingTagStatus.NO_MATCH
    else:
        card.inferred_canonical_card = result
        card.printing_tag_status = PrintingTagStatus.RESOLVED
    card.save(update_fields=["inferred_canonical_card", "printing_tag_status"])
    return result


class VoteTallyEntry(TypedDict):
    printing: CanonicalCard | None
    is_no_match: bool
    count: int


def get_contested_card_ids() -> list[int]:
    """
    IDs of cards with conflicting printing-tag votes on record: more than one distinct
    printing voted for, or both a printing vote and a no-match vote. Coarser than
    `resolve_printing` (a card can show as contested here yet still resolve if one side
    dominates on weight), but avoids running the full consensus calculation per card for
    a queue/triage ordering. Shared between the admin's contested-card filter and the
    "Who's That Planeswalker?" queue, which defaults to surfacing contested cards first.
    Materialized to a plain list (rather than returning the lazy QuerySet) since the set of
    actually-contested cards is always a small fraction of the total - cheap to evaluate
    eagerly, and sidesteps django-stubs' QuerySet generic entirely for callers.
    """
    return list(
        CardPrintingTag.objects.values("card_id")
        .annotate(
            distinct_printings=Count("printing_id", distinct=True),
            has_no_match=Count(Case(When(is_no_match=True, then=1), output_field=IntegerField())),
        )
        .filter(Q(distinct_printings__gt=1) | (Q(distinct_printings__gte=1) & Q(has_no_match__gt=0)))
        .values_list("card_id", flat=True)
    )


def get_vote_tally(card: Card) -> list[VoteTallyEntry]:
    """
    Returns a plain, unweighted per-outcome vote count for `card` - e.g. "3 votes for
    Ravnica Allegiance #45, 1 for no match" - for showing a voter what's been said so far
    before they confirm or dispute it. Deliberately doesn't weight by source the way
    `resolve_printing` does: this is for display, not for deciding the outcome.
    """
    tally: dict[int | Literal["NO_MATCH"] | None, VoteTallyEntry] = {}
    for vote in card.printing_tags.all():
        key: int | Literal["NO_MATCH"] | None = NO_MATCH if vote.is_no_match else vote.printing_id
        if key not in tally:
            tally[key] = VoteTallyEntry(printing=vote.printing, is_no_match=vote.is_no_match, count=0)
        tally[key]["count"] += 1
    return sorted(tally.values(), key=lambda entry: entry["count"], reverse=True)
