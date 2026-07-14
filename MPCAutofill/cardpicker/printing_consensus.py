from dataclasses import dataclass
from typing import Iterable, Literal, TypedDict

from django.conf import settings

from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
    contested_queryset,
    resolve_weighted_consensus,
)

NO_MATCH: Literal["NO_MATCH"] = "NO_MATCH"


@dataclass(frozen=True)
class ResolvedPrinting:
    expansion_code: str
    collector_number: str
    full_art: bool
    border_color: str


def get_resolved_printings(identifiers: Iterable[str]) -> dict[str, ResolvedPrinting]:
    """
    Batch lookup of community-vote-RESOLVED printing data for a set of `Card.identifier`s.
    This is the hard-gate helper: cards absent from the returned dict are UNRESOLVED or
    NO_MATCH and MUST be treated as unaffected by any printing-tag-driven consumption
    behavior (search re-ranking, attribute filtering) - callers should never fall back to
    `canonical_card` or otherwise infer a printing for an identifier this function omits.
    Shared by both the search re-rank and the attribute-filter logic in
    `cardpicker.search.search_functions.retrieve_card_identifiers`, so the two features can't
    drift out of sync on what counts as "resolved."
    """
    cards = Card.objects.filter(
        identifier__in=identifiers,
        printing_tag_status=PrintingTagStatus.RESOLVED,
    ).select_related("inferred_canonical_card__expansion", "inferred_canonical_card__printing_metadata")
    result: dict[str, ResolvedPrinting] = {}
    for card in cards:
        printing = card.inferred_canonical_card
        if printing is None:
            # shouldn't happen given resolve_and_persist_printing's invariant (RESOLVED always
            # pairs with a non-null inferred_canonical_card), but a card in an inconsistent
            # state should be treated as unresolved rather than crash the search path.
            continue
        metadata = getattr(printing, "printing_metadata", None)
        result[card.identifier] = ResolvedPrinting(
            expansion_code=printing.expansion.code.upper(),
            collector_number=printing.collector_number,
            full_art=metadata.full_art if metadata is not None else False,
            border_color=metadata.border_color if metadata is not None else "",
        )
    return result


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
            VoteTuple(
                outcome_key=key,
                weight=_SOURCE_WEIGHTS[vote.source],
                is_human_backed=vote.source != VoteSource.AI,
            )
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
    "What's That Card?" queue, which defaults to surfacing contested cards first.
    Materialized to a plain list (rather than returning the lazy QuerySet) since the set of
    actually-contested cards is always a small fraction of the total - cheap to evaluate
    eagerly, and sidesteps django-stubs' QuerySet generic entirely for callers.

    Delegates to the shared `vote_consensus.contested_queryset` - this function's name,
    signature, and behavior are unchanged; it's the reference point that function's own
    docstring calls "behavior-preserving".
    """
    return contested_queryset(
        CardPrintingTag.objects.all(), group_by="card_id", outcome_field="printing_id", sentinel_field="is_no_match"
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
