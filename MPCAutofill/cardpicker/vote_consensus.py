from collections import defaultdict
from typing import Any, Hashable, Iterable, NamedTuple, TypedDict

from django.conf import settings
from django.db.models import Case, Count, IntegerField, Q, QuerySet, When

from cardpicker.models import VoteSource

# Shared across printing/artist/tag consensus - previously duplicated identically in each of
# their own modules; hoisted here so a new source (e.g. `FEDERATED`) can't be forgotten in one
# of them. `printing_consensus.py`/`artist_consensus.py`/`tag_consensus.py` import this rather
# than redefining it. DEDUCTION and OCR (the 2026-07-15 split of the old single `AI` value -
# see VoteSource's own docstring) share the same weight, matching the old AI value's - this
# was a label split, not a policy change.
_SOURCE_WEIGHTS: dict[str, float] = {
    VoteSource.USER: 1.0,
    VoteSource.ADMIN: settings.PRINTING_TAG_ADMIN_WEIGHT,
    VoteSource.DEDUCTION: settings.PRINTING_TAG_MACHINE_WEIGHT,
    VoteSource.OCR: settings.PRINTING_TAG_MACHINE_WEIGHT,
    VoteSource.FEDERATED: settings.VOTE_FEDERATED_WEIGHT,
}

# Every source NOT in this set counts as "human-backed" for resolve_weighted_consensus's
# require_privileged gate (the "an AI-only group can never resolve a card by itself, no matter
# how many AI votes pile up" invariant that every stage of this project is built around -
# verified live at scale, 0/28,112 violations in deductive_backfill's production run). A single
# shared set + helper, not scattered `!= VoteSource.AI` comparisons in each of printing_
# consensus.py/artist_consensus.py/tag_consensus.py (as it was before the AI->DEDUCTION/OCR
# split) - deliberately centralized here: a future new machine-derived source only ever needs
# to be added to this one set, not remembered at every comparison site.
_MACHINE_DERIVED_SOURCES: set[str] = {VoteSource.DEDUCTION, VoteSource.OCR}


def is_human_backed_source(source: str) -> bool:
    return source not in _MACHINE_DERIVED_SOURCES


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
    # True when the vote carries elevated moderation authority: cast by a Moderators-group
    # member (see cardpicker.moderation.is_privileged_vote) or by an admin (source==ADMIN).
    # Only consulted when `resolve_weighted_consensus` is called with `require_privileged=True`
    # (sensitive tags - see docs/features/moderation.md); defaulted so the many existing
    # call sites that predate the moderation layer construct VoteTuples unchanged.
    is_privileged: bool = False


class _PendingPrivileged:
    """
    Singleton sentinel (see PENDING_PRIVILEGED below) returned by `resolve_weighted_consensus`
    instead of the winning key when `require_privileged=True` and the crowd's consensus lacks
    a privileged co-sign. Deliberately distinct from `None`: `None` means "not enough signal
    to conclude anything", while this means "a conclusion exists and is merely awaiting
    privileged approval" - callers persist the latter as `pending_approval` (see
    cardpicker.tag_consensus.resolve_and_persist_tag_votes). Hashable, so the declared return
    type of `resolve_weighted_consensus` is unchanged. Compare with `is`.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "PENDING_PRIVILEGED"


PENDING_PRIVILEGED = _PendingPrivileged()


class _VoteGroup(TypedDict):
    weight: float
    has_human_backed: bool
    has_privileged: bool


def resolve_weighted_consensus(
    votes: Iterable[VoteTuple], min_weight: float, min_share: float, require_privileged: bool = False
) -> Hashable | None:
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

    With `require_privileged=True` (sensitive tags - see docs/features/moderation.md), a winner
    that clears all three gates above additionally needs a privileged vote *in the winning
    group* before it resolves; otherwise `PENDING_PRIVILEGED` is returned instead of the key,
    which callers persist as a pending-approval state rather than a resolution. In-group
    (mirroring `has_human_backed`'s aggregation) rather than merely present-among-the-votes,
    because a moderator voting *against* the crowd must not count as the co-sign that lets the
    crowd's outcome through - their vote argues for a different outcome entirely (and at
    privileged weight it usually flips or contests the result through the normal math anyway).
    """
    votes = list(votes)
    if not votes:
        return None

    groups: dict[Hashable, _VoteGroup] = defaultdict(
        lambda: _VoteGroup(weight=0.0, has_human_backed=False, has_privileged=False)
    )
    for vote in votes:
        group = groups[vote.outcome_key]
        group["weight"] += vote.weight
        if vote.is_human_backed:
            group["has_human_backed"] = True
        if vote.is_privileged:
            group["has_privileged"] = True

    total_weight = sum(group["weight"] for group in groups.values())
    winning_key, winner = max(groups.items(), key=lambda item: item[1]["weight"])
    share = winner["weight"] / total_weight

    if winner["weight"] >= min_weight and share >= min_share and winner["has_human_backed"]:
        if require_privileged and not winner["has_privileged"]:
            return PENDING_PRIVILEGED
        return winning_key
    return None


def contested_queryset(
    queryset: "QuerySet[Any]",
    group_by: str | list[str],
    outcome_field: str,
    sentinel_field: str | None = None,
) -> list[Any]:
    """
    Generalizes what was originally `printing_consensus.get_contested_card_ids`'s logic across
    any `AbstractWeightedVote` subclass - see that function for the original "what does
    contested mean, and why is this a cheap proxy rather than a full consensus
    recomputation" reasoning, unchanged here.

    Takes an unfiltered base `queryset` (e.g. `CardPrintingTag.objects.all()` - a queryset
    rather than the model class itself, since django-stubs can't statically resolve `.objects`
    off a bare `type[Model]`) and groups its rows by `group_by` (a field name, e.g. `"card_id"`,
    or a list of field names for a composite grouping, e.g. `["card_id", "tag_id"]`), counts
    distinct `outcome_field` values per group, and flags a group as contested if it has more
    than one distinct outcome, or - only when `sentinel_field` is given - if it has exactly one
    outcome AND at least one sentinel vote alongside it (e.g. a printing vote coexisting with
    an `is_no_match` vote). Returns a plain list of group-by values (or tuples, for a composite
    `group_by`) - materialized eagerly, same rationale as the original: the contested set is
    always a small fraction of the total.
    """
    group_fields = [group_by] if isinstance(group_by, str) else group_by
    condition = Q(distinct_outcomes__gt=1)
    annotations = {"distinct_outcomes": Count(outcome_field, distinct=True)}
    if sentinel_field is not None:
        annotations["has_sentinel"] = Count(Case(When(**{sentinel_field: True}, then=1), output_field=IntegerField()))
        condition = condition | (Q(distinct_outcomes__gte=1) & Q(has_sentinel__gt=0))

    grouped = queryset.values(*group_fields).annotate(**annotations).filter(condition)
    if len(group_fields) == 1:
        return list(grouped.values_list(group_fields[0], flat=True))
    return list(grouped.values_list(*group_fields))


__all__ = [
    "VoteTuple",
    "resolve_weighted_consensus",
    "PENDING_PRIVILEGED",
    "_SOURCE_WEIGHTS",
    "contested_queryset",
    "is_human_backed_source",
]
