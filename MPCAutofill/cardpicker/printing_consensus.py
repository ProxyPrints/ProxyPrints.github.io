from dataclasses import dataclass
from typing import Hashable, Iterable, Literal, Sequence, TypedDict

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist

from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    PrintingTagStatus,
    calculator_family,
)
from cardpicker.vote_consensus import (
    VoteTuple,
    contested_queryset,
    is_human_backed_source,
    pool_group_votes,
    resolve_vote_weight,
    resolve_weighted_consensus,
)

NO_MATCH: Literal["NO_MATCH"] = "NO_MATCH"

# `Card.md5_checksum` (the Drive-API-reported checksum of the image file this catalogue row
# indexes), referenced by NAME rather than as an attribute so this module is importable and
# correct both before and after that field exists: it is added by issue #473's PR-1
# (`md5-checksum-substrate`), which this branch is cut BEFORE and merges AFTER. Every read of it
# funnels through `_card_md5_checksum`/`_md5_checksums_for_card_ids`/`_card_ids_with_md5_checksums`
# below - the only three places in this module that touch the column - so on a checkout without
# the field every card is a group of one and every group-aware path below degenerates, provably,
# to its pre-#473 behavior.
MD5_CHECKSUM_FIELD = "md5_checksum"


def _card_md5_checksum(card: Card) -> str | None:
    """
    `card`'s file checksum, or `None` when it has none (`LOCAL_FILE` and other checksum-less
    sources, per issue #473 ruling 3) - and, until PR-1 lands, for every card, since the field
    doesn't exist yet and `getattr` reports the default. Empty string is normalized to `None`:
    "" is not an identity, and grouping every checksum-less card into one giant group would be a
    catastrophic misreading of exactly this degenerate case.
    """
    return getattr(card, MD5_CHECKSUM_FIELD, None) or None


def _md5_checksum_column_exists() -> bool:
    """
    Whether `Card.md5_checksum` exists on this checkout - False until issue #473's PR-1 merges
    into this branch, True forever after. Only the BULK reader below needs to ask: it filters on
    the column by name (`.values_list`), which raises rather than degrading if the field is
    absent, unlike `_card_md5_checksum`'s per-instance `getattr`. A `_meta` lookup, so this is a
    dict access, not a query - safe to call per request.
    """
    try:
        Card._meta.get_field(MD5_CHECKSUM_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def _md5_checksums_for_card_ids(card_ids: Iterable[int]) -> set[str]:
    """
    The distinct non-null checksums held by `card_ids` - ONE column read, not a fetch of whole
    `Card` rows (2026-07-25 gate on PR #482, condition f1: the row-fetch form regressed the
    question feed's per-request cost even before PR-1, since it hydrated a model instance per
    card the voter had ever voted on purely to read one string off it). Returns an empty set,
    without querying at all, while the column doesn't exist.
    """
    if not _md5_checksum_column_exists():
        return set()
    return {
        checksum
        for checksum in Card.objects.filter(pk__in=card_ids).values_list(MD5_CHECKSUM_FIELD, flat=True)
        if checksum
    }


def _card_ids_with_md5_checksums(checksums: set[str]) -> list[int]:
    """
    Every `Card.pk` whose checksum is in `checksums` - the one query in this module that filters
    ON the column (see `MD5_CHECKSUM_FIELD`). Unreachable while the field doesn't exist, because
    its only callers below skip it when they hold no non-null checksum, and `_card_md5_checksum`
    can only report non-null once PR-1 has added the column.
    """
    return list(Card.objects.filter(**{f"{MD5_CHECKSUM_FIELD}__in": checksums}).values_list("pk", flat=True))


def md5_group_key(card: Card) -> Hashable:
    """
    Stable identity of `card`'s md5 group, for callers that need to visit each group ONCE across
    a large iteration (`consensus_recompute`) rather than re-resolving the same group per member.
    A checksum-less card keys on its own pk, so it is always a group of one and never collides
    with another card's key.
    """
    checksum = _card_md5_checksum(card)
    return ("md5", checksum) if checksum is not None else ("card", card.pk)


def md5_group_card_ids(card: Card) -> list[int]:
    """
    The pks of `card`'s md5 identity group - every card indexing a byte-identical image file,
    `card` included - sorted, so the tally built from it is deterministic. `[card.pk]` for a
    checksum-less or unique-checksum card (issue #473 ruling 3's group of one), which is also
    the shape every card has before PR-1 adds the checksum column.
    """
    checksum = _card_md5_checksum(card)
    if checksum is None:
        return [card.pk]
    return sorted(set(_card_ids_with_md5_checksums({checksum})) | {card.pk})


def md5_group_cards(card: Card) -> list[Card]:
    """
    `card`'s md5 group as `Card` INSTANCES, with the caller's own `card` object first and
    unreplaced - `resolve_and_persist_printing` writes through these instances, and its callers
    (e.g. `consensus_recompute`, the vote-submission views) read `card.printing_tag_status` off
    their own object afterwards, so substituting a freshly-fetched copy of the same row would
    silently strand them on a stale status. A group of one performs no query at all.
    """
    group_card_ids = md5_group_card_ids(card)
    other_ids = [card_id for card_id in group_card_ids if card_id != card.pk]
    if not other_ids:
        return [card]
    return [card, *Card.objects.filter(pk__in=other_ids)]


def md5_group_expanded_card_ids(card_ids: Iterable[int]) -> set[int]:
    """
    `card_ids` widened to include every md5 sibling of every card in it - "the cards this voter
    has already answered" widened to "the identity groups this voter has already answered", for
    `question_feed`'s serve-one-member-per-group exclusion. Returns `card_ids` unchanged when
    none of them carry a checksum (which, before PR-1, is always - at a cost of zero queries,
    see `_md5_checksums_for_card_ids`). At most two queries otherwise, neither of which
    materializes a `Card` instance.
    """
    ids = set(card_ids)
    if not ids:
        return ids
    checksums = _md5_checksums_for_card_ids(ids)
    if not checksums:
        return ids
    return ids | set(_card_ids_with_md5_checksums(checksums))


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


def group_printing_votes(card: Card, group_card_ids: Sequence[int] | None = None) -> tuple[list[CardPrintingTag], bool]:
    """
    Every `CardPrintingTag` row cast against any member of `card`'s md5 identity group, plus
    whether that group actually has more than one member. Pass `group_card_ids` when the caller
    already knows the group (e.g. it is about to persist to those same members) to avoid
    re-deriving it.

    A group of ONE reads `card.printing_tags.all()` - deliberately the identical expression
    this module used before issue #473, not a `filter(card_id__in=[card.pk])` that happens to
    return the same rows: that expression is what honours a caller's own
    `prefetch_related("printing_tags")` (`consensus_recompute` batches on exactly that, one
    query per batch instead of one per card), and keeping it is what makes the singleton case a
    byte-for-byte no-op in query shape as well as in outcome. The multi-member branch orders by
    `(card_id, pk)` so the pooled tally `pool_group_votes` builds is deterministic across runs.
    """
    if group_card_ids is None:
        group_card_ids = md5_group_card_ids(card)
    if len(group_card_ids) <= 1:
        return list(card.printing_tags.all()), False
    votes = list(
        CardPrintingTag.objects.filter(card_id__in=group_card_ids).select_related("printing").order_by("card_id", "pk")
    )
    return votes, True


def agent_dedupe_key(anonymous_id: str) -> str:
    """
    The identity of the AGENT behind `anonymous_id`, for `pool_group_votes`' `dedupe_key`: the
    versionless CALCULATOR FAMILY (`models.calculator_family` - "stage-d-join-key" for
    "stage-d-join-key-v1") when the id follows the machine naming convention, and otherwise the
    `anonymous_id` verbatim.

    WHY THE FAMILY IS THE AGENT, and why this must not be "simplified" back to the raw id
    ------------------------------------------------------------------------------------
    A machine calculator carries its version INSIDE its identity string rather than beside it as
    metadata, so bumping a calculator (`-v1` -> `-v2`) changes the string every one of its votes
    is stamped with. Keying pooling on that raw string makes ONE calculator look like TWO
    INDEPENDENT AGENTS the moment its version is bumped, because `pool_group_votes` compares
    keys for equality and "x-v1" != "x-v2".

    That is reachable in ordinary operation, not a hypothetical: a version bump re-votes cards
    INCREMENTALLY, so an md5 identity group whose members straddle the migration holds some
    members' votes under the old version and some under the new one. Under a raw-id key those
    two rows sum, and one calculator on its own supplies the whole of `PRINTING_TAG_MIN_VOTES`
    - exactly the "summed weight means distinct agents" invariant `pool_group_votes` exists to
    enforce (see its docstring's soundness paragraph), defeated by a routine redeploy.

    v1 and v2 of one calculator are the SAME agent holding an updated opinion, not two
    independent observers: they run the same algorithm over the same evidence channel on the
    same bytes, so their agreement is correlated by construction and carries no more information
    than either alone. Keying on the family makes that structural fact mechanical - agreement
    across a version bump collapses to one event, and a calculator that CONTRADICTS ITSELF
    across a version bump (v1 said printing A, v2 says printing B - the normal shape of a
    corrective re-vote) is withheld from the group's tally entirely, which is the correct
    reading: it changed its mind about byte-identical bytes, so it is not evidence for either
    outcome until the group is re-voted consistently.

    HUMAN VOTERS ARE UNTOUCHED, structurally rather than by convention: human `anonymous_id`s
    are client-generated UUIDs (`frontend/src/common/anonymousId.ts`), which can never match
    `models.CALCULATOR_VERSION_RE`, so `calculator_family` returns None for every one of them
    and they fall through to the raw-id branch and dedupe on their own UUID exactly as before
    this function existed. The 2026-07-25 gate on PR #482 (condition 1) requires humans to be
    keyed at all - that is unchanged here; only the KEY a machine id maps to changes. Pinned by
    `test_md5_group_pooling.TestVersionedCalculatorIdentity`.

    Do NOT collapse this back to `vote.anonymous_id`. It reads like an identity function with
    extra steps only because the failure it prevents is invisible until a calculator is
    versioned up, at which point it silently lowers the quorum bar for that calculator's whole
    cohort with no error and no log line.
    """
    return calculator_family(anonymous_id) or anonymous_id


def build_group_printing_vote_tuples(
    votes: Iterable[CardPrintingTag], pool: bool, printings_by_id: dict[int, CanonicalCard] | None = None
) -> list[VoteTuple]:
    """
    Translates `CardPrintingTag` rows into the `VoteTuple`s `resolve_weighted_consensus` reads,
    pooling them across an md5 identity group when `pool` is True (issue #473 ruling 1, applied
    by `vote_consensus.pool_group_votes`): EVERY vote is keyed on the identity of the agent that
    cast it - human-backed votes included - so one agent's agreeing votes about a set of
    byte-identical images are ONE event no matter how many members carry a copy, and one agent
    that contradicts itself across members is withheld from the tally entirely. Distinct agents
    still sum: two different people voting on two members are two votes, which is the point of
    tallying a group as one target.

    That agent identity is `agent_dedupe_key(vote.anonymous_id)`, NOT `vote.anonymous_id` itself
    - read that function's docstring before touching this line. In short: a machine calculator's
    version lives inside its `anonymous_id`, so keying on the raw string counts one calculator
    as two independent agents across a version bump; the versionless family is the stable agent
    identity. Human voters' UUIDs have no family and key on themselves, unchanged.

    Human-backed votes were NOT keyed in this function's first form, on the reading that separate
    people are separate events regardless. That was wrong for the case that matters and was
    rejected at review (2026-07-25 gate on PR #482, condition 1): `anonymous_id` identifies the
    VOTER, so leaving human votes unkeyed let ONE person reach a 2.0 quorum by answering the same
    image twice under two of its identifiers - a resolution neither card could reach alone, from
    one human judgement. Keying humans too is what makes `PRINTING_TAG_MIN_VOTES` a count of
    distinct agents rather than of rows.

    With `pool=False` (a group of one) no vote is keyed, `pool_group_votes` is never called, and
    the returned list is exactly what this module built before #473.

    Passing a `printings_by_id` dict populates it with each voted `CanonicalCard` (needed to map
    a winning outcome key back to a printing). Callers that only need the outcome KEY - e.g.
    `question_feed.is_likely_resolve_printing`, which runs this in a scan loop - pass `None` and
    this never touches `vote.printing`, so it costs no per-vote related lookup for them.

    Per-vote weight is resolved via `vote_consensus.resolve_vote_weight` (not a bare
    `_SOURCE_WEIGHTS[vote.source]` lookup) so the 2026-07-23 owner ruling zeroing the
    deductive-backfill cohort's weight (see that function's own docstring) is honoured here -
    the one call site every printing consensus computation (winner selection, the gate checks
    and share math inside `resolve_weighted_consensus`, and every caller of `resolve_printing`,
    including `consensus_impact_report`/`consensus_recompute`) ultimately funnels through.
    """
    vote_tuples: list[VoteTuple] = []
    for vote in votes:
        key: int | Literal["NO_MATCH"]
        if vote.is_no_match:
            key = NO_MATCH
        else:
            # guaranteed non-null here by the model's printing_xor_no_match CheckConstraint
            assert vote.printing_id is not None
            key = vote.printing_id
            if printings_by_id is not None:
                assert vote.printing is not None
                printings_by_id[vote.printing_id] = vote.printing
        vote_tuples.append(
            VoteTuple(
                outcome_key=key,
                weight=resolve_vote_weight(vote.source, vote.anonymous_id),
                is_human_backed=is_human_backed_source(vote.source),
                # agent identity, not the raw id - see `agent_dedupe_key`'s docstring for why a
                # version bump must not turn one calculator into two agents.
                dedupe_key=agent_dedupe_key(vote.anonymous_id) if pool else None,
            )
        )
    return pool_group_votes(vote_tuples) if pool else vote_tuples


def resolve_printing(
    card: Card, group_card_ids: Sequence[int] | None = None
) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Reconciles all `CardPrintingTag` votes cast against `card`'s md5 identity group into a
    single resolved outcome: a specific `CanonicalCard` printing, the `NO_MATCH` sentinel
    (consensus is that no printing matches), or `None` if there isn't yet enough signal to
    conclude anything. See `cardpicker.vote_consensus.resolve_weighted_consensus` for the shared
    weighting/threshold rules (votes weighted by `source`, `PRINTING_TAG_MIN_VOTES`/
    `MIN_SHARE` gates, non-AI gate) - this is a thin wrapper translating `CardPrintingTag`
    rows into `VoteTuple`s and the winning outcome key back into a `CanonicalCard`.

    The identity group (issue #473) is every card indexing a byte-identical image file: ONE
    identification target, so its votes are tallied once, together, and the outcome applies to
    all of it. A card with no checksum, or the only card with its checksum, is a group of one
    (ruling 3) and takes the pre-#473 path unchanged - same rows, same query, same tuples, same
    result. `group_card_ids` may be passed by a caller that already derived the group.
    """
    votes, is_group = group_printing_votes(card, group_card_ids)
    if not votes:
        return None

    printings_by_id: dict[int, CanonicalCard] = {}
    vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group, printings_by_id=printings_by_id)

    winning_key = resolve_weighted_consensus(
        vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
    )
    if winning_key is None:
        return None
    if winning_key == NO_MATCH:
        return NO_MATCH
    assert isinstance(winning_key, int)
    return printings_by_id[winning_key]


def _effective_indexed_printing_id(status: str, printing_id: int | None) -> int | None:
    """
    The printing id that actually reaches Elasticsearch for a card in `status`: `Card.
    get_expansion_code`/`get_collector_number` (the fields `documents.py` indexes) only fall
    back to `inferred_canonical_card` while `printing_tag_status == RESOLVED` - a card that's
    UNRESOLVED or NO_MATCH is indexed as if `inferred_canonical_card` were `None`, regardless
    of what's actually stored there. Comparing this derived value (not the raw fields) before
    and after a consensus run is what lets a status flip with no printing change, or a
    printing change with no status flip, both correctly count as "the index needs updating."
    """
    return printing_id if status == PrintingTagStatus.RESOLVED else None


def resolve_and_persist_printing(
    card: Card, members: Sequence[Card] | None = None
) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Runs `resolve_printing(card)` and writes the outcome onto `inferred_canonical_card` and
    `printing_tag_status` together - for EVERY member of `card`'s md5 identity group, not just
    `card` (issue #473 ruling 1: byte-identical images are one identification target, so a
    resolution reached on one of them is a resolution for all of them, and cannot be allowed to
    disagree with itself across the group by construction). `Card.serialise()` (which already
    reads `inferred_canonical_card`) and the printing-tag review queue (which filters on the
    indexed `printing_tag_status`, rather than recomputing consensus for every card) therefore
    stay in sync with the latest votes for every member at once. Intended to be called
    synchronously right after a vote is submitted for `card` - cheap, since it only touches this
    one group's own votes. Returns the same outcome `resolve_printing` returned, so callers
    don't need to recompute it again immediately afterwards.

    A group of one (a checksum-less or unique-checksum card - ruling 3) writes exactly the one
    row it always did, through the caller's own `card` instance, with no additional query.
    `members` may be passed by a caller that already materialized the group (see
    `md5_group_cards`, whose contract this expects: `card` itself, first, unreplaced).

    Also pushes each written card into Elasticsearch, but only when the outcome actually changes
    what's indexed for THAT card (see `_effective_indexed_printing_id`) - entering RESOLVED,
    leaving RESOLVED (contested/unresolved again after new votes), or the resolved printing
    itself changing while remaining RESOLVED. A re-resolve that lands on the same outcome as
    before (the common case whenever this runs against a card that already has a settled
    consensus) does not touch the index; the per-member gate means propagating an unchanged
    outcome across a group reindexes only the members that were actually out of step. The push
    itself is failure-isolated (`reindex_card_safely`) - an ES hiccup is logged, never raised;
    this function's own DB write has already committed by that point regardless.

    Members are WRITTEN in pk order (not in the caller-first order they arrive in), so two
    concurrent votes landing on two different members of the same group take that group's row
    locks in the same order and queue behind each other instead of deadlocking. For a group of
    one this is the same single write, in the same place, it always was.
    """
    group_cards = list(members) if members is not None else md5_group_cards(card)
    result = resolve_printing(card, group_card_ids=[member.pk for member in group_cards])

    for member in sorted(group_cards, key=lambda group_card: group_card.pk):
        prior_status = member.printing_tag_status
        prior_printing_id = member.inferred_canonical_card_id
        prior_effective = _effective_indexed_printing_id(prior_status, prior_printing_id)

        if result is None:
            member.inferred_canonical_card = None
            member.printing_tag_status = PrintingTagStatus.UNRESOLVED
        elif result == NO_MATCH:
            member.inferred_canonical_card = None
            member.printing_tag_status = PrintingTagStatus.NO_MATCH
        else:
            member.inferred_canonical_card = result
            member.printing_tag_status = PrintingTagStatus.RESOLVED
        member.save(update_fields=["inferred_canonical_card", "printing_tag_status"])

        new_effective = _effective_indexed_printing_id(member.printing_tag_status, member.inferred_canonical_card_id)
        if new_effective != prior_effective:
            from cardpicker.documents import (
                reindex_card_safely,  # local import - avoids a top-level ES dependency in this module
            )

            reindex_card_safely(member)

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
