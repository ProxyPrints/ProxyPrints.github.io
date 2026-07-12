from collections import defaultdict
from typing import Hashable, Iterable, NamedTuple, TypedDict


class VoteTuple(NamedTuple):
    """
    A single vote reduced to just what `resolve_weighted_consensus` needs to reconcile it: the
    outcome it argues for (grouping key - e.g. a printing's pk, an artist's pk, or a tag's
    polarity), its weight (already resolved from the vote's `source` by the caller), and
    whether it came from an AI (which can never single-handedly clear consensus, regardless of
    weight - see the non-AI gate below).
    """

    outcome_key: Hashable
    weight: float
    is_ai: bool


class _VoteGroup(TypedDict):
    weight: float
    has_non_ai: bool


def resolve_weighted_consensus(votes: Iterable[VoteTuple], min_weight: float, min_share: float) -> Hashable | None:
    """
    Reconciles a set of weighted votes into a single resolved outcome key, or `None` if there
    isn't yet enough signal to conclude anything (no votes, a tie, or a genuinely contested
    set of votes). This is the shared core behind `cardpicker.printing_consensus.resolve_printing`,
    `cardpicker.artist_consensus.resolve_artist`, and `cardpicker.tag_consensus.resolve_tag` - each
    of those is a thin wrapper that builds `VoteTuple`s from its own vote model and calls this.

    Votes are grouped by `outcome_key`, and the highest-weighted group wins if, and only if,
    ALL of the following hold:
      - its summed weight is >= `min_weight` (compared against summed weight, not a raw row
        count - a single admin vote, at a typical admin weight of 5, already clears a default
        threshold of 2 on its own, which is what produces "admin override" behaviour from this
        one unified formula, with no special-cased branch for admin votes);
      - its share of the total weight across all groups is >= `min_share`;
      - it contains at least one non-AI vote (a hard gate, independent of the weight math
        above, so that no volume of AI-only votes can ever resolve consensus on their own).
    """
    votes = list(votes)
    if not votes:
        return None

    groups: dict[Hashable, _VoteGroup] = defaultdict(lambda: _VoteGroup(weight=0.0, has_non_ai=False))
    for vote in votes:
        group = groups[vote.outcome_key]
        group["weight"] += vote.weight
        if not vote.is_ai:
            group["has_non_ai"] = True

    total_weight = sum(group["weight"] for group in groups.values())
    winning_key, winner = max(groups.items(), key=lambda item: item[1]["weight"])
    share = winner["weight"] / total_weight

    if winner["weight"] >= min_weight and share >= min_share and winner["has_non_ai"]:
        return winning_key
    return None


__all__ = ["VoteTuple", "resolve_weighted_consensus"]
