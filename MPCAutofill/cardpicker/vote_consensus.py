from collections import defaultdict
from typing import Any, Hashable, Iterable, NamedTuple, TypedDict

from django.conf import settings
from django.db.models import Case, Count, IntegerField, Q, QuerySet, When

from cardpicker.models import VoteSource, calculator_family

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
    # Per-vote weight of an implicit vote (docs/features/printing-tags.md's implicit-vote
    # section) - deliberately tiny (default 0.25, well below a single USER vote) since this is a
    # passive by-product of a card *selection* under active filter chips, not a deliberate "yes
    # this tag applies" click. `resolve_weighted_consensus` additionally hard-caps the SUM of
    # implicit weight per (outcome, i.e. per polarity side) group at
    # `PRINTING_TAG_IMPLICIT_CAP` - see that function's own docstring for why a per-vote weight
    # alone isn't a strong enough guarantee.
    VoteSource.IMPLICIT: settings.PRINTING_TAG_IMPLICIT_WEIGHT,
}

# Every source NOT in this set counts as "human-backed" for resolve_weighted_consensus's
# require_privileged gate (the "an AI-only group can never resolve a card by itself, no matter
# how many AI votes pile up" invariant that every stage of this project is built around -
# verified live at scale, 0/28,112 violations in deductive_backfill's production run). A single
# shared set + helper, not scattered `!= VoteSource.AI` comparisons in each of printing_
# consensus.py/artist_consensus.py/tag_consensus.py (as it was before the AI->DEDUCTION/OCR
# split) - deliberately centralized here: a future new machine-derived source only ever needs
# to be added to this one set, not remembered at every comparison site.
#
# FEDERATED is included here as a defensive default, not (yet) the real mechanism:
# docs/federation-v1.md's "FEDERATED_VOTE_GATE_MODE" section designs a settings-driven,
# per-peer-promotable gate treatment for federated verdicts (default "suggestion" - contributes
# weight, never clears the human-backed gate alone) for when an importer actually exists. No
# importer exists yet, so this line makes the safe behavior the default now, before one can be
# built, rather than a thing that importer's author must remember to add.
#
# IMPLICIT is here for the same reason DEDUCTION/OCR are: a passive filter-chip-driven signal
# must never itself satisfy the human-backed gate, no matter how many implicit votes pile up -
# the per-(outcome)-group cap in `resolve_weighted_consensus` additionally stops it from ever
# supplying the *quorum* weight alone, but this set is what stops it from ever supplying the
# human-backed bit, which the cap alone would not.
_MACHINE_DERIVED_SOURCES: set[str] = {VoteSource.DEDUCTION, VoteSource.OCR, VoteSource.FEDERATED, VoteSource.IMPLICIT}


def is_human_backed_source(source: str) -> bool:
    return source not in _MACHINE_DERIVED_SOURCES


# `cardpicker.deductive_backfill.DEDUCTIVE_BACKFILL_ANONYMOUS_ID`, duplicated as a literal here
# (same convention `local_identify_printing_tags.py` already uses for its own copy) rather than
# importing that module - keeps this shared consensus core free of a dependency on one specific
# backfill script.
#
# Owner ruling 2026-07-23: the 28,112 `CardPrintingTag` votes this backfill run wrote (source=
# DEDUCTION, anonymous_id=this constant - pure name-matching inference, zero image inspection,
# see `deductive_backfill.py`'s own module docstring) carry ZERO weight in every consensus
# computation, forever - the rows themselves are KEPT as history (raw tallies/display paths,
# e.g. `get_vote_tally`/`_suggested_canonical_card`/the questionFeed tier-1 surface, are
# unaffected - this only zeroes WEIGHT). Basis, verified live against the production run at
# ratification time: 60% of the 28,112 were already redundant with an agreeing image-channel
# (DEDUCTION/OCR) vote, 17% were opposed by an explicit human no-match vote, 66 were directly
# contradicted by a later human vote for a different printing, and only 459 were unopposed yet
# unverifiable against any independent evidence. Soundness is strictly tightening: this removes
# name-derived weight from resolution, leaving only image-derived machine evidence (OCR/phash/
# fallback - see `local_phash.py`/`local_fallback.py`) plus human votes - see docs/theory.md's
# soundness section for the full writeup. This is scoped to (source, calculator FAMILY) together
# - see `DEDUCTIVE_BACKFILL_FAMILY` and `resolve_vote_weight` below - not to
# `VoteSource.DEDUCTION` alone, so a future, differently-sourced DEDUCTION-labelled cohort
# (should one ever be ratified) isn't silently swept in by this same override without its own
# separate review.
DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"

# The versionless FAMILY of the id above ("deductive-backfill"), which is what the zero-weight
# override actually matches on. DERIVED, not written out as a second literal, so the two can
# never drift: `models.calculator_family` is the single definition of how a version suffix is
# stripped. The assert makes a rename that took this constant outside the machine naming
# convention fail loudly at import time rather than silently disabling a ratified ruling.
DEDUCTIVE_BACKFILL_FAMILY = calculator_family(DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
assert DEDUCTIVE_BACKFILL_FAMILY is not None, (
    "DEDUCTIVE_BACKFILL_ANONYMOUS_ID must follow the machine calculator naming convention "
    "(<family>-v<N>): the 2026-07-23 zero-weight ruling is enforced by family, not by literal."
)


def resolve_vote_weight(source: str, anonymous_id: str) -> float:
    """
    Resolves a single vote's consensus weight from its `source` (via `_SOURCE_WEIGHTS`), with
    one override: a vote carrying `source=VoteSource.DEDUCTION` AND an `anonymous_id` in the
    DEDUCTIVE-BACKFILL CALCULATOR FAMILY resolves to 0.0 regardless of
    `_SOURCE_WEIGHTS[DEDUCTION]`. See `DEDUCTIVE_BACKFILL_ANONYMOUS_ID`'s own comment above for
    the 2026-07-23 owner ruling that zeroed that cohort's 28,112 votes and the evidence behind
    it.

    WHY THE MATCH IS SCOPED TO THE FAMILY, NOT TO THE EXACT ID
    ---------------------------------------------------------
    This was an exact string comparison against "deductive-backfill-v1" until it was noticed
    that a machine calculator's version lives INSIDE its `anonymous_id` rather than beside it as
    metadata (see `models.calculator_family`). Under an exact match, bumping this calculator to
    "deductive-backfill-v2" - an ordinary, unremarkable redeploy - would silently restore the
    whole cohort to full DEDUCTION weight: no error, no log line, no failing test, a ratified
    owner ruling reversed by a version string. Matching on the family is what makes "forever" in
    that ruling mean forever. The ruling was about the METHOD (pure name-matching inference,
    zero image inspection), and a re-versioned run of the same method is the same method.

    It is scoped to that ONE family and NO WIDER, deliberately: the ruling zeroed one cohort,
    not `VoteSource.DEDUCTION` as a class. Every call site that builds a `VoteTuple`'s (or an
    inline weighted-sum's) `weight` from a vote row's `source` should route through this rather
    than indexing `_SOURCE_WEIGHTS` directly, so a future zero-weight cohort (should one ever be
    ratified) has exactly ONE place to be added - preserve that property when adding one, and
    give the new cohort its own family check rather than broadening this one.

    CONFIDENCE IS NOT A PARAMETER OF THIS FUNCTION and must not become one. A vote's weight is a
    function of WHO cast it and by what method - not of how sure that agent reports being.
    Letting a calculator's self-reported confidence scale its own consensus weight would let a
    miscalibrated or merely optimistic calculator buy quorum, which is exactly what the
    distinct-agent quorum rule (see `pool_group_votes`) exists to prevent. Confidence belongs in
    a calculator's own emit-or-skip decision, upstream of any vote row existing at all.

    `CardArtistVote`/`CardTagVote` rows are unaffected in practice (`deductive_backfill.py` only
    ever writes `CardPrintingTag` rows) but are safe to route through this too - the override
    simply never matches for them.
    """
    if source == VoteSource.DEDUCTION and calculator_family(anonymous_id) == DEDUCTIVE_BACKFILL_FAMILY:
        return 0.0
    return _SOURCE_WEIGHTS[source]


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
    # True for a `VoteSource.IMPLICIT` vote (docs/features/printing-tags.md's implicit-vote
    # section) - always paired with `is_human_backed=False` by every caller that sets it.
    # Deliberately its own flag rather than reusing `source == IMPLICIT` inside this module (same
    # rationale as `is_human_backed` above: the caller decides, so a future federated import of
    # an implicit-shaped verdict isn't silently mis-tallied by a source-string comparison here).
    # Defaulted so every existing call site is unaffected. See `resolve_weighted_consensus`'s
    # docstring for how this is used: capped per-outcome-group, and excluded entirely (alongside
    # every other non-human-backed vote) whenever that function's D1/D4 mechanisms engage.
    is_implicit: bool = False
    # Identity of the AGENT this vote came from, for `pool_group_votes` (md5 identity groups,
    # issue #473 ruling 1) - an `anonymous_id` in practice. Votes sharing a non-None `dedupe_key`
    # are one agent speaking about one identification target across several of its byte-identical
    # members: agreeing ones collapse to a single vote, disagreeing ones withhold that agent
    # entirely (see `pool_group_votes`). `None` (the default, and the value every pre-existing
    # call site constructs) means "never collapse this with anything" - which is what makes a
    # group of one a byte-for-byte no-op: nothing to collapse against. Set by
    # `printing_consensus.build_group_printing_vote_tuples` for EVERY vote (human-backed
    # included - one person is one agent) inside a multi-member group, and for none outside one.
    dedupe_key: Hashable | None = None


def pool_group_votes(votes: Iterable[VoteTuple]) -> list[VoteTuple]:
    """
    Collapses the votes of an md5 IDENTITY GROUP (issue #473: a set of `Card`s whose stored
    file checksums are equal, i.e. byte-identical images - ONE identification target, not N)
    into the tally `resolve_weighted_consensus` should actually see, per the owner's 2026-07-25
    ruling 1: an evidence EVENT that was merely observed on several members of the group counts
    ONCE, never summed. What makes summed weight mean anything is that the summands are
    DISTINCT AGENTS, so that is exactly what this enforces.

    Mechanically, two rules over votes carrying a non-None `dedupe_key` (see
    `VoteTuple.dedupe_key` - the casting agent's `anonymous_id`, set by
    `printing_consensus.build_group_printing_vote_tuples` for every vote, human-backed or not,
    when and only when the group has more than one member):

      1. **Agreement collapses.** All of one agent's votes for the SAME outcome across the group
         become one vote, at that agent's highest weight for it. One person answering the same
         question twice under two identifiers of the same image file is one answer, not two -
         and one machine agent's verdict about identical bytes is one verdict, however many
         members carry a copy of it.
      2. **Self-contradiction withholds.** An agent whose votes across the group argue for
         DIFFERENT outcomes (possible: `CardPrintingTag`'s uniqueness constraints allow one
         `anonymous_id` several printing votes per card, e.g. a rescan that matched differently)
         contributes NOTHING to this group's tally - not its maximum, not either side. It has
         contradicted itself about byte-identical bytes, so it is not evidence for either
         outcome. This mirrors `g₄`'s withhold-never-manufacture philosophy (docs/theory.md
         §7a): a cross-check that fails removes a claim rather than picking a winner for it.
         The earlier keep-the-max form of this rule was rejected at review (2026-07-25 gate on
         PR #482): with equal weights it resolved the contradiction by INPUT ORDER, i.e. by
         `card_id`, which silently manufactured correlated agreement between an arbitrary
         sibling and whatever else agreed with it.

    `dedupe_key=None` votes pass through untouched, in input order - which is EVERY vote of a
    group of one, so a singleton pools to itself and grouping is a no-op for it. The result is
    fed to `resolve_weighted_consensus` unchanged: none of the matrix logic (the implicit cap,
    D1/D4 non-human exclusion, the human-backed gate, the deductive-backfill zero-weight
    override) is aware that pooling happened, and none of it needed to change.

    Soundness, stated narrowly (docs/theory.md §4 item 3 carries the full statement): this
    function only ever REMOVES weight from the tally it is given - it never adds, upgrades, or
    re-labels one. What it therefore preserves EXACTLY is the machine-alone bound: no volume of
    non-human-backed weight can resolve a group, because the human-backed gate is untouched and
    pooling cannot manufacture a human-backed vote. What it makes true, rather than assumes, is
    the independence the quorum threshold rests on: after pooling, `min_weight` is a sum over
    distinct agents rather than over rows, so neither one person answering n siblings nor one
    machine agent's evidence transferred to n siblings (issue #473 PR-2) can reach quorum by
    repetition. Note the direction of that claim carefully: pooling REPLACES a per-card tally
    with a group tally, and a group tally can resolve things no single card's tally could (two
    different people, one vote each, on two members) - that is the intended multiplier, not an
    accident.

    Ordering: the retained set is a function of the votes, not of the order they arrive in
    (agreement is order-insensitive, and a contradicting agent is dropped wholesale), so a
    caller's row ordering cannot influence any outcome.

    COMPLETENESS IS THE CALLER'S TO GUARANTEE, and it is not optional. `votes` must be the WHOLE
    group's votes: rule 2 is a statement about an agent's behaviour ACROSS THE GROUP, so an agent
    that contradicts itself on a member the caller left out looks perfectly consistent here and
    is counted, where the complete set withholds it. A subset therefore yields a DIFFERENT tally
    rather than a weaker one, and can select a different winner - silently, since nothing in a
    list of `VoteTuple`s says which group it came from or whether any of it is missing. This
    function has no `Card` and no group identity, so it cannot check that itself; the guarantee
    is established at the point the group is read (`printing_consensus.group_printing_votes`,
    whose `_require_full_md5_group` check rejects a caller-supplied partial group) and must be
    preserved by every caller in between - in particular, do not narrow the vote set by a batch's
    `card_ids` on the way here (#533/#541).
    """
    votes = list(votes)
    outcomes_by_dedupe_key: dict[Hashable, set[Hashable]] = defaultdict(set)
    for vote in votes:
        if vote.dedupe_key is not None:
            outcomes_by_dedupe_key[vote.dedupe_key].add(vote.outcome_key)
    withheld_dedupe_keys = {key for key, outcomes in outcomes_by_dedupe_key.items() if len(outcomes) > 1}

    pooled: list[VoteTuple] = []
    index_by_dedupe_key: dict[Hashable, int] = {}
    for vote in votes:
        if vote.dedupe_key is None:
            pooled.append(vote)
            continue
        if vote.dedupe_key in withheld_dedupe_keys:
            continue
        index = index_by_dedupe_key.get(vote.dedupe_key)
        if index is None:
            index_by_dedupe_key[vote.dedupe_key] = len(pooled)
            pooled.append(vote)
        elif vote.weight > pooled[index].weight:
            pooled[index] = vote
    return pooled


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
    # weight contributed by human-backed votes (VoteTuple.is_human_backed=True) - USER/ADMIN
    # today, plus any future FEDERATED vote a peer explicitly asserts as human-backed.
    human_weight: float
    # weight contributed by non-human-backed, non-implicit votes (DEDUCTION/OCR/FEDERATED-as-
    # imported-today) - "machine-derived" per docs/theory.md's terminology.
    machine_weight: float
    # RAW (uncapped) weight contributed by is_implicit=True votes - the cap is applied later,
    # once per group, not accumulated here, so the raw total remains inspectable if ever needed.
    implicit_weight_raw: float
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

    IMPLICIT weight (docs/features/printing-tags.md) is capped per-outcome-group at
    `settings.PRINTING_TAG_IMPLICIT_CAP` before it contributes anywhere in the math below - a
    hard ceiling, strictly below `min_weight` by policy, so no volume of implicit votes on one
    side can ever supply a whole group's quorum weight by itself (mirrors the human-backed gate's
    own "volume never wins" invariant, for a different failure mode).

    Two further mechanisms - both owner-ratified 2026-07-22 (see the vote-weight scenario matrix,
    `docs/upstreaming/license-provenance.md` §3's "reimplement from a written description, never
    from source" convention applies here too: this is an original design against that ratified
    spec, not adapted from anywhere) - stop non-human-backed weight (DEDUCTION/OCR/FEDERATED-as-
    imported-today/IMPLICIT alike) from ever being the thing that actually decides a contest
    between humans. Both collapse into ONE shared trigger, `exclude_non_human`, computed BEFORE
    winner selection (2026-07-22 hardening: an earlier version of this function computed D4's
    condition from the *already-selected* winner, which let a large enough machine/implicit pile
    win the selection outright on raw weight, then fail the human-backed gate and return `None`
    instead of correctly resolving the actual human-backed group - see the matrix's own B4 note
    and this fix's own test suite for the N=4/5/100-machine-dissent regression cases this closes):

    `exclude_non_human` is true when EITHER:
      - **D1** - a live human-vs-human contest: two or more outcome groups each carry SOME
        human-backed weight (a genuine human-vs-human disagreement, not one human side vs. a
        purely machine-derived one); OR
      - **D4** - ANY single group's human_weight ALONE already clears `min_weight` (that group
        doesn't need machine/implicit help to reach quorum, so no other group's machine/implicit
        pile should be able to out-weigh it in the selection, no matter how large).

    When `exclude_non_human` is true, EVERY group's non-human-backed weight (machine + implicit)
    is dropped entirely for BOTH winner-selection and the share/quorum gate checks below - only
    `human_weight` counts, for every group, not just the winner. A machine/implicit pile can
    still make an already-agreeing human group's total look bigger when `exclude_non_human` is
    false (see D2 below), but it can never be the deciding weight that lets a machine-only group
    outrank, flip, or de-resolve a human-backed group's own outcome. This does NOT touch the
    quorum (`min_weight`) check's *threshold* itself, and does NOT trigger when no group's
    human-backed weight alone clears `min_weight` and there's no live human contest either - a
    lone human vote plus agreeing machine weight can still be promoted to a resolution the same
    way it always could (D2: `exclude_non_human` is false in that shape, since there's only one
    human-backed group and its own human weight doesn't clear `min_weight` by itself).

    This function is unaware of md5 identity groups (issue #473) and deliberately stays that
    way: a group-aware caller pools its members' votes through `pool_group_votes` FIRST and
    hands the result here, so every mechanism above runs on the pooled tally with no branch of
    its own. A group of one pools to itself, which is what makes grouping a no-op for it.
    """
    votes = list(votes)
    if not votes:
        return None

    groups: dict[Hashable, _VoteGroup] = defaultdict(
        lambda: _VoteGroup(
            human_weight=0.0, machine_weight=0.0, implicit_weight_raw=0.0, has_human_backed=False, has_privileged=False
        )
    )
    for vote in votes:
        group = groups[vote.outcome_key]
        if vote.is_implicit:
            group["implicit_weight_raw"] += vote.weight
        elif vote.is_human_backed:
            group["human_weight"] += vote.weight
        else:
            group["machine_weight"] += vote.weight
        if vote.is_human_backed:
            group["has_human_backed"] = True
        if vote.is_privileged:
            group["has_privileged"] = True

    implicit_cap = settings.PRINTING_TAG_IMPLICIT_CAP

    def full_weight(group: _VoteGroup) -> float:
        return group["human_weight"] + group["machine_weight"] + min(group["implicit_weight_raw"], implicit_cap)

    # D1: a live human-vs-human contest is >=2 groups each carrying human-backed weight - not
    # merely >=2 groups existing (a human group vs. a purely-machine/implicit one is NOT this).
    live_human_contest = sum(1 for group in groups.values() if group["has_human_backed"]) >= 2
    # D4: ANY group's human weight alone already clears quorum - checked BEFORE winner selection
    # (not against the already-selected winner - see this function's own docstring for why that
    # ordering was the bug), so a machine/implicit-only group can never out-select a human-quorum
    # -valid group in the first place, regardless of how large that machine/implicit pile is.
    human_quorum_group_exists = any(group["human_weight"] >= min_weight for group in groups.values())
    exclude_non_human = live_human_contest or human_quorum_group_exists

    def decision_weight(group: _VoteGroup) -> float:
        return group["human_weight"] if exclude_non_human else full_weight(group)

    winning_key, winner = max(groups.items(), key=lambda item: decision_weight(item[1]))
    winner_weight = decision_weight(winner)

    if exclude_non_human:
        total_weight = sum(group["human_weight"] for group in groups.values())
        winner_share_weight = winner["human_weight"]
    else:
        total_weight = sum(full_weight(group) for group in groups.values())
        winner_share_weight = full_weight(winner)

    share = winner_share_weight / total_weight if total_weight else 0.0

    if winner_weight >= min_weight and share >= min_share and winner["has_human_backed"]:
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
    "pool_group_votes",
    "resolve_weighted_consensus",
    "PENDING_PRIVILEGED",
    "_SOURCE_WEIGHTS",
    "contested_queryset",
    "is_human_backed_source",
    "DEDUCTIVE_BACKFILL_ANONYMOUS_ID",
    "resolve_vote_weight",
]
