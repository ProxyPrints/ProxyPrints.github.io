from collections import defaultdict
from typing import Literal, TypedDict

from django.conf import settings

from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTagSource,
    PrintingTagStatus,
)

NO_MATCH: Literal["NO_MATCH"] = "NO_MATCH"

_SOURCE_WEIGHTS: dict[str, float] = {
    CardPrintingTagSource.USER: 1.0,
    CardPrintingTagSource.ADMIN: settings.PRINTING_TAG_ADMIN_WEIGHT,
    CardPrintingTagSource.AI: settings.PRINTING_TAG_AI_WEIGHT,
}


class _VoteGroup(TypedDict):
    weight: float
    has_non_ai: bool
    printing: CanonicalCard | None


def resolve_printing(card: Card) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Reconciles all `CardPrintingTag` votes cast against `card` into a single resolved
    outcome: a specific `CanonicalCard` printing, the `NO_MATCH` sentinel (consensus is
    that no printing matches), or `None` if there isn't yet enough signal to conclude
    anything (no votes, a tie, or a genuinely contested set of votes).

    Votes are weighted by their `source` (`PRINTING_TAG_ADMIN_WEIGHT`/`PRINTING_TAG_AI_WEIGHT`
    settings; user votes always weigh 1). Votes are grouped by outcome, and the
    highest-weighted group wins if, and only if, ALL of the following hold:
      - its summed weight is >= `PRINTING_TAG_MIN_VOTES` (this is compared against the
        summed weight, not a raw row count — a single admin vote, at the default weight
        of 5, already clears the default threshold of 2 on its own, which is what
        produces "admin override" behaviour from this one unified formula, with no
        special-cased branch for admin votes);
      - its share of the total weight across all groups is >= `PRINTING_TAG_MIN_SHARE`;
      - it contains at least one non-AI vote (a hard gate, independent of the weight
        math above, so that no volume of AI-only votes can ever resolve consensus on
        their own).
    """
    votes = list(card.printing_tags.all())
    if not votes:
        return None

    groups: dict[int | Literal["NO_MATCH"] | None, _VoteGroup] = defaultdict(
        lambda: _VoteGroup(weight=0.0, has_non_ai=False, printing=None)
    )
    for vote in votes:
        key: int | Literal["NO_MATCH"] | None = NO_MATCH if vote.is_no_match else vote.printing_id
        group = groups[key]
        group["weight"] += _SOURCE_WEIGHTS[vote.source]
        if vote.source != CardPrintingTagSource.AI:
            group["has_non_ai"] = True
        if not vote.is_no_match:
            group["printing"] = vote.printing

    total_weight = sum(group["weight"] for group in groups.values())
    winning_key, winner = max(groups.items(), key=lambda item: item[1]["weight"])
    share = winner["weight"] / total_weight

    if (
        winner["weight"] >= settings.PRINTING_TAG_MIN_VOTES
        and share >= settings.PRINTING_TAG_MIN_SHARE
        and winner["has_non_ai"]
    ):
        return NO_MATCH if winning_key == NO_MATCH else winner["printing"]
    return None


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
