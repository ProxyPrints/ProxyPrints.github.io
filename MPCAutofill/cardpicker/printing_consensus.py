from collections import defaultdict
from typing import Literal, TypedDict

from django.conf import settings

from cardpicker.models import CanonicalCard, Card, CardPrintingTagSource

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
