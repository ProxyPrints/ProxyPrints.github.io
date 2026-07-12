from collections import defaultdict
from typing import Hashable, Iterable, NamedTuple, TypedDict

from django.conf import settings

from cardpicker.models import VoteSource

# Shared across printing/artist/tag consensus - previously duplicated identically in each of
# their own modules; hoisted here so a new source (e.g. `FEDERATED`) can't be forgotten in one
# of them. `printing_consensus.py`/`artist_consensus.py`/`tag_consensus.py` import this rather
# than redefining it.
_SOURCE_WEIGHTS: dict[str, float] = {
    VoteSource.USER: 1.0,
    VoteSource.ADMIN: settings.PRINTING_TAG_ADMIN_WEIGHT,
    VoteSource.AI: settings.PRINTING_TAG_AI_WEIGHT,
    VoteSource.FEDERATED: settings.VOTE_FEDERATED_WEIGHT,
}


class VoteTuple(NamedTuple):
    """
    A single vote reduced to just what `resolve_weighted_consensus` needs to reconcile it: the
    outcome it argues for (grouping key - e.g. a printing's pk, an artist's pk, or a tag's
    polarity), its weight (already resolved from the vote's `source` by the caller), and
    whether it should count towards the human-backed gate below. This is deliberately not
    derived automatically from `source == AI` inside this module - the caller decides, since a
    future federated vote's human-backed-ness depends on what the exporting peer reported, not
    on the local `source` value alone (see docs/federation-v1.md). Every wrapper today
    (`USER`/`ADMIN`/`AI`) still computes this as `source != AI`, so behaviour is unchanged.
    """

    outcome_key: Hashable
    weight: float
    is_human_backed: bool


class _VoteGroup(TypedDict):
    weight: float
    has_human_backed: bool


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
      - it contains at least one human-backed vote (a hard gate, independent of the weight math
        above, so that no volume of non-human-backed votes - e.g. AI-only - can ever resolve
        consensus on their own).
    """
    votes = list(votes)
    if not votes:
        return None

    groups: dict[Hashable, _VoteGroup] = defaultdict(lambda: _VoteGroup(weight=0.0, has_human_backed=False))
    for vote in votes:
        group = groups[vote.outcome_key]
        group["weight"] += vote.weight
        if vote.is_human_backed:
            group["has_human_backed"] = True

    total_weight = sum(group["weight"] for group in groups.values())
    winning_key, winner = max(groups.items(), key=lambda item: item[1]["weight"])
    share = winner["weight"] / total_weight

    if winner["weight"] >= min_weight and share >= min_share and winner["has_human_backed"]:
        return winning_key
    return None


__all__ = ["VoteTuple", "resolve_weighted_consensus", "_SOURCE_WEIGHTS"]
