"""
Consensus over `CardIllustrationVote` (issue #524) - the reader that model has been missing since
it landed. `printing_consensus.py`/`artist_consensus.py`/`tag_consensus.py` each reconcile their
own vote model into a resolved outcome; until this module existed, illustration votes were
WRITTEN (by `local_illustration.run_illustration_calculator` and by the human path in
`illustration_vote.cast_illustration_vote`) and read by nothing but the admin. This module is the
missing third of that triangle, built on the same shared `vote_consensus` core as the other
three - no weighting, quorum, or human-backed gate is re-derived here.

THE OUTCOME SPACE, AND HOW `is_unknown` PARTICIPATES
----------------------------------------------------
`CardIllustrationVote` carries an `illustration_id` XOR an `is_unknown` flag
(`cardillustrationvote_illustration_xor_unknown`), so a row is always exactly one of two claims:
"this card depicts artwork <uuid>" or "this card depicts an artwork with no known illustration
identity". `is_unknown` is therefore tallied as an ORDINARY OUTCOME KEY, competing on equal
footing with every uuid - the `UNKNOWN` sentinel below, exactly as `artist_consensus.UNKNOWN`
treats `CardArtistVote.is_unknown` and as `printing_consensus.NO_MATCH` treats
`CardPrintingTag.is_no_match`.

That is a deliberate choice, and the alternative reading is the wrong one: `is_unknown` is NOT an
abstention. An abstention on this model is the ABSENCE OF A ROW - the calculator's own
`NO_CANDIDATE_MATCH`/`NO_ILLUSTRATION_INDEX_ENTRY`/`MULTIPLE_ILLUSTRATIONS` skip paths write a
`CardScanLog` row and no vote at all, and a human who does not answer leaves nothing behind. A
present `is_unknown=True` row is a positive, falsifiable assertion that someone looked and
concluded there is no identity to name, which is genuinely informative (it is the claim that a
custom/proxy/altered image has no Scryfall artwork behind it) and must be capable of both
resolving on its own and of CONTESTING a uuid claim. Treating it as a non-participant would make
it unable to do either: an `UNKNOWN`-vs-uuid disagreement would silently read as an uncontested
uuid, and a card everyone agrees is unidentifiable would sit UNRESOLVED forever, indistinguishable
from one nobody has looked at.

MD5 IDENTITY-GROUP POOLING IS BUILT IN FROM THE START, NOT RETROFITTED
----------------------------------------------------------------------
Every read path below is group-scoped: `resolve_illustration` tallies the votes of `card`'s WHOLE
md5 identity group (`printing_consensus.md5_group_card_ids` - every `Card` whose stored
`md5_checksum` equals this one's), pooled per agent by `vote_consensus.pool_group_votes`, and
`resolve_and_persist_illustration` writes the outcome to every member. The group primitives are
IMPORTED from `printing_consensus` rather than reimplemented, so there is exactly one definition
of "what is this card's md5 group", one completeness guard, and one agent-identity rule in the
codebase.

This is built in now, deliberately, rather than added once the votes exist. The printing side
acquired its pooling late, and the defect that mattered lived precisely in the seam between the
un-pooled original and the pooled retrofit (see `printing_consensus.build_group_printing_vote_
tuples`' own "Human-backed votes were NOT keyed in this function's first form" paragraph, and
`_require_full_md5_group`'s "a subset yields a DIFFERENT tally, not a weaker one"). A consensus
function that is group-scoped from its first line has no such seam: there is no un-pooled call
path to leave behind, and no caller that predates the contract.

WHY MD5 IS THE RIGHT GROUPING KEY HERE - AND STRICTLY STRONGER THAN THE ART HASH
--------------------------------------------------------------------------------
The question this model answers is "which ARTWORK is this?", and the catalogue already carries a
perceptual art hash (`Card.content_phash`) whose whole purpose is to answer artwork-identity
questions. It would be natural to group on that. Do not.

`Card.md5_checksum` is the checksum of the IMAGE FILE'S BYTES. Byte-identical files are
necessarily the same artwork - the implication holds with no threshold, no perceptual tolerance,
no distance metric, and no tuning parameter, because identical bytes decode to identical pixels
(the same fact `evidence_transfer.py`'s CONTENT-HASH ASSERTION rests on, in the same direction).
md5 identity is therefore STRICTLY STRONGER than phash proximity for this purpose: every md5
group is a subset of some art-identity class, and membership is decidable by equality rather than
by a threshold someone chose.

A phash MATCH is a different kind of claim. Two cards can share a perceptual hash and be genuinely
different artworks (a near-duplicate, a re-render, a different crop of a shared frame, a hash
collision at whatever Hamming radius the caller picked), and no radius makes that impossible. So
pooling - which DELIBERATELY suppresses evidence, collapsing an agent's agreeing votes to one
event and withholding a self-contradicting agent entirely - and propagation - which pushes one
group member's resolved outcome onto another - are only sound on byte identity. Under phash
grouping, propagation would assign one card's artwork identity to a merely similar-looking other
card, silently, with a plausible-looking uuid written to a `Card` row. Nothing in this module ever
reads `content_phash`, and that is a structural guarantee rather than a convention: group
membership has exactly one source, `printing_consensus.md5_group_card_ids`, which consults
`Card.md5_checksum` and nothing else. Pinned by
`test_illustration_consensus.TestPropagationIsMd5OnlyNeverPhash`.

PROPAGATION IS A CONSEQUENCE OF GROUP-SCOPED RESOLUTION, NOT A SEPARATE STEP
----------------------------------------------------------------------------
The gap this closes, concretely: `local_illustration`'s calculator needs BOTH image evidence AND a
successful candidate-name match. Evidence already transfers across an md5 group
(`evidence_transfer.py`, `STAGE_C_EVIDENCE_TRANSFER_ENABLED`), but the card's decorated NAME does
not - so a member whose name fails candidate resolution abstains with `no-candidate-match` (367 of
2,350 considered cards, ~15.6%, in PR #565's 30,000-card counterfactual replay) even though a byte-identical sibling
resolved cleanly.

That gap is closed HERE, by the tally being defined over the group rather than over the card:
`group_illustration_votes` reads every member's rows, so the `no-candidate-match` member's tally
is the SAME tally its sibling's is, and `resolve_and_persist_illustration` writes the resolved
uuid onto every member's own `Card` row. The abstaining member ends up with an
`inferred_illustration_id` and a RESOLVED status without any code path being aware it abstained.

The rejected alternative was an explicit propagation step that WRITES a `CardIllustrationVote` row
for the abstaining member, copying the sibling's. Three reasons it is worse, in order of weight:

  1. IT WOULD BUY NOTHING. Such a row would carry the calculator's own fixed `anonymous_id`, so it
     pools under the same `dedupe_key` as the row it was copied from and collapses to the same
     single event. Its contribution to every tally in this module is EXACTLY ZERO weight - so the
     only thing it could change is per-card display, which group-scoped persistence already
     provides. Pinned as a claim, not asserted in prose, by
     `test_illustration_consensus.TestPropagatedVoteRowsWouldBeWeightNeutral`.
  2. IT MANUFACTURES EVIDENCE. A vote row records that an agent made a claim about a card. No
     agent made this one; the pipeline's posture throughout (`pool_group_votes`' "withhold, never
     manufacture", `local_illustration`'s abstain-at-N>1 remedy for #525) is to remove claims on a
     failed cross-check, never to invent them.
  3. IT COLLIDES BY CONSTRUCTION. `CardIllustrationVote`'s unique constraint on (card,
     anonymous_id) is UNCONDITIONAL (issue #525, see the model docstring). A propagated row occupies
     the exact slot the calculator itself will want when the abstaining member later becomes
     resolvable, and `local_illustration._purge_and_write_illustration_votes` compares the stored
     `illustration_id` VALUE - so a propagated row is indistinguishable there from the calculator's
     own stale answer, and would be silently rewritten or would suppress a genuine correction.

HONEST LIMIT ON THAT PROPAGATION: nothing propagates until the group's tally actually RESOLVES,
and the human-backed gate in `resolve_weighted_consensus` means a machine-only group never does,
no matter how many members or agents it holds. So the ~15.6% figure above describes cards that
become resolvable ONCE A HUMAN WEIGHS IN ON ANY MEMBER, not cards this module resolves from
machine votes alone. That gate is a ratified invariant and this module does not weaken it.

REFERENCE DATA DEPENDENCY, STATED EXPLICITLY (owner ruling 2026-07-29)
----------------------------------------------------------------------
`CanonicalCard`/`CanonicalPrintingMetadata` are imported Scryfall reference data - informative, not
ground truth, and possibly stale, with NO import timestamp anywhere in the database to tell you
which. This module reads NEITHER. `resolve_illustration` returns the winning `uuid.UUID` verbatim
off the vote rows; `inferred_illustration_id` stores that uuid as a plain `UUIDField`, mirroring
`CardIllustrationVote.illustration_id`/`CanonicalPrintingMetadata.illustration_id`, which are both
deliberately not foreign keys (see the model docstring's "NOT A FOREIGN KEY" section). There is no
join here to be stale.

The dependency is real but it is entirely UPSTREAM and DOWNSTREAM of this file, and it is worth
being precise about what a stale snapshot would do:

  - UPSTREAM: a stale snapshot changes which uuids exist to be voted for. The calculator's index is
    built from `CanonicalPrintingMetadata`, and the human vote path's candidate grid comes from
    `printing_candidates`. If the snapshot predates a printing, no agent can name its illustration
    and this module sees no votes for it - it under-resolves, and never mis-resolves, from that
    cause alone.
  - DOWNSTREAM: a stale snapshot changes what a resolved uuid can be turned INTO. Every consumer
    that maps an illustration to its printings does that join itself
    (`local_illustration.printings_for_illustration`, `illustration_vote.
    printings_for_card_and_illustration` - the latter deliberately re-queries live, inside its
    transaction, for exactly this reason). A stale snapshot can therefore make a correctly-resolved
    illustration map to too few printings, which is a consumer-side narrowing, not a wrong
    resolution.
  - WHAT DOES NOT HAPPEN: a stale snapshot cannot change a tally, flip a winner, or alter which
    member of an md5 group a resolution propagates to, because none of those depend on reference
    data at all. If reference data is later found to have been wrong, the votes remain exactly as
    cast and re-running this module reproduces the same outcome - the correction belongs at the
    calculator, which is where the reference data was actually consulted.

THRESHOLDS (`ILLUSTRATION_MIN_VOTES`/`ILLUSTRATION_MIN_SHARE`)
--------------------------------------------------------------
Their own settings, defaulting to the printing-tuned values (`PRINTING_TAG_MIN_VOTES`=2.0,
`PRINTING_TAG_MIN_SHARE`=0.6), so this module ships changing nothing anywhere and the illustration
bar can later be tuned without moving the printing bar. Both are read at call time, so a test or
deployment override applies without reimporting.

Two thresholds and no third, deliberately: there is NO `ILLUSTRATION_MACHINE_WEIGHT`. A vote's
WEIGHT is a property of WHO cast it and BY WHAT METHOD, never of what is being voted on - see
`vote_consensus.resolve_vote_weight`'s own docstring, which makes the same argument against
letting a calculator's self-reported confidence scale its weight. A machine agent is exactly as
reliable when it names an artwork as when it names a printing; if it were not, that belongs in the
calculator's emit-or-abstain decision, upstream of a row existing. Per-vote-type weights would also
mean one agent's `CardIllustrationVote` and its derived `CardPrintingTag` (the human path in
`illustration_vote.py` writes both) counted at different strengths for the same single judgement.

Whether an illustration claim DESERVES a lower quorum than a printing claim is a genuinely open
question - it is a strictly coarser claim (artwork-to-printing is 1:N, ~2.2 printings per
illustration), so it is easier to get right, which argues for a lower bar; but it also does less
work when resolved, which argues against spending soundness on it. There is no data to settle it
with (3 illustration votes in production at the time of writing; PR #565's ~10,277 machine
rows are projected, not yet cast), so the defaults settle it by not
changing anything and the settings exist so that the answer, when it arrives, is a config change
rather than a code change.
"""

import uuid
from typing import Iterable, Literal, Sequence, TypedDict

from django.conf import settings

from cardpicker.models import Card, CardIllustrationVote, IllustrationVoteStatus
from cardpicker.printing_consensus import (
    _require_full_md5_group,
    agent_dedupe_key,
    md5_group_card_ids,
    md5_group_cards,
)
from cardpicker.vote_consensus import (
    VoteTuple,
    contested_queryset,
    is_human_backed_source,
    pool_group_votes,
    resolve_vote_weight,
    resolve_weighted_consensus,
)

UNKNOWN: Literal["UNKNOWN"] = "UNKNOWN"

# The resolved outcome of illustration consensus: a Scryfall artwork uuid, the UNKNOWN sentinel
# (consensus is that this image has no known illustration identity), or None (not enough signal).
IllustrationOutcome = uuid.UUID | Literal["UNKNOWN"] | None


def illustration_min_votes() -> float:
    """
    `settings.ILLUSTRATION_MIN_VOTES`, read at CALL time rather than captured at import - so a
    `django_settings` override in a test, or a deployment-time env change, applies without this
    module being reimported. Falls back to `PRINTING_TAG_MIN_VOTES` if the setting is absent,
    which keeps this module importable and behaviour-identical on a checkout (or a rebase onto a
    branch) where `settings.py` hasn't yet gained the new name.
    """
    return getattr(settings, "ILLUSTRATION_MIN_VOTES", settings.PRINTING_TAG_MIN_VOTES)


def illustration_min_share() -> float:
    """`settings.ILLUSTRATION_MIN_SHARE` - see `illustration_min_votes` for both the call-time
    read and the fallback."""
    return getattr(settings, "ILLUSTRATION_MIN_SHARE", settings.PRINTING_TAG_MIN_SHARE)


def group_illustration_votes(
    card: Card, group_card_ids: Sequence[int] | None = None
) -> tuple[list[CardIllustrationVote], bool]:
    """
    Every `CardIllustrationVote` row cast against any member of `card`'s md5 identity group, plus
    whether that group actually has more than one member. The illustration analogue of
    `printing_consensus.group_printing_votes`, with the identical contract - read that function's
    docstring; only the model differs.

    `group_card_ids`, when given, MUST be `card`'s COMPLETE md5 identity group. That is CHECKED
    here, at the one place in this module where a caller-supplied group is CONSUMED (via the
    shared `printing_consensus._require_full_md5_group`), for the same reason and with the same
    force as on the printing side: a partial group does not yield a weaker tally, it yields a
    DIFFERENT one. Pooling withholds an agent that contradicts itself ACROSS THE GROUP, so an
    agent that looks consistent on the members you kept - and contradicted itself on one you
    dropped - is counted here where the full group withholds it, and the resulting resolution is
    a plausible-looking WRONG uuid written onto every member. If you are threading a batch's
    `card_ids` through the pipeline (#533/#541): scope the batch's TARGETS by it, never a target's
    md5 neighbourhood lookup.

    A group of ONE reads `card.illustration_votes.all()` - deliberately that exact expression, not
    a `filter(card_id__in=[card.pk])` returning the same rows, so a caller's own
    `prefetch_related("illustration_votes")` is honoured and the singleton case is a byte-for-byte
    no-op in query shape as well as in outcome. The multi-member branch orders by `(card_id, pk)`
    so the pooled tally is deterministic across runs.
    """
    if group_card_ids is None:
        group_card_ids = md5_group_card_ids(card)
    else:
        _require_full_md5_group(card, group_card_ids, "group_card_ids")
    if len(group_card_ids) <= 1:
        return list(card.illustration_votes.all()), False
    votes = list(CardIllustrationVote.objects.filter(card_id__in=group_card_ids).order_by("card_id", "pk"))
    return votes, True


def build_group_illustration_vote_tuples(votes: Iterable[CardIllustrationVote], pool: bool) -> list[VoteTuple]:
    """
    Translates `CardIllustrationVote` rows into the `VoteTuple`s `resolve_weighted_consensus`
    reads, pooling them across an md5 identity group when `pool` is True. The illustration
    analogue of `printing_consensus.build_group_illustration_vote_tuples`'s printing twin; the
    substantive decisions are all inherited from it and restated here only where this model
    differs.

    OUTCOME KEY: the `illustration_id` uuid, or the `UNKNOWN` sentinel for an `is_unknown` row -
    the two arms of `cardillustrationvote_illustration_xor_unknown`. See the module docstring for
    why `is_unknown` is a full participant in the tally rather than an abstention. `uuid.UUID` is
    hashable and compares by value, so two agents naming the same artwork land in one group
    whether their rows arrived as `UUID` objects or were coerced from strings by the ORM.

    AGENT IDENTITY: `agent_dedupe_key(vote.anonymous_id)` - the versionless calculator FAMILY for
    a machine id, the raw id for a human's client-generated UUID. NOT the raw `anonymous_id`: a
    calculator's version lives inside its identity string, so keying on the raw value would make
    `stage-d-illustration-v1` and `-v2` look like two independent agents across an ordinary
    redeploy and let one calculator supply a whole quorum by itself. That is not hypothetical for
    THIS calculator specifically - PR #565 (merged) bumped it from v1 to v2, and a version bump re-votes
    incrementally, so an md5 group whose members straddle the migration holds rows under both
    strings simultaneously. Read `agent_dedupe_key`'s own docstring before touching this line.

    EVERY vote is keyed when pooling, human-backed included. `anonymous_id` identifies the VOTER,
    so leaving human votes unkeyed would let ONE person reach quorum by answering the same image
    twice under two of its catalogue identifiers - a resolution neither card could reach alone,
    out of one human judgement. This model's unconditional (card, anonymous_id) unique constraint
    stops one identity holding two opinions about ONE card; it says nothing about one identity
    holding opinions about two byte-identical cards, which is exactly what pooling is for.

    With `pool=False` (a group of one) no vote is keyed and `pool_group_votes` is never called, so
    the returned list is the plain per-card tally.

    `votes` AND `pool` MUST COME FROM ONE `group_illustration_votes` CALL, unsplit - this function
    takes no `Card` and so cannot check its own completeness (same limitation, same reason, as the
    printing twin). Do not filter `votes` in between, and do not compute `pool` yourself.

    Weight resolves through `vote_consensus.resolve_vote_weight`, not a bare `_SOURCE_WEIGHTS`
    lookup. The 2026-07-23 deductive-backfill zero-weight ruling it enforces has never matched an
    illustration row (that backfill only ever wrote `CardPrintingTag`), so this is convention
    rather than live behaviour - which is the point: the ruling has exactly one enforcement site,
    and a future zero-weighted cohort is honoured here without this file being touched.
    """
    vote_tuples: list[VoteTuple] = []
    for vote in votes:
        key: uuid.UUID | Literal["UNKNOWN"]
        if vote.is_unknown:
            key = UNKNOWN
        else:
            # guaranteed non-null here by the model's illustration_xor_unknown CheckConstraint
            assert vote.illustration_id is not None
            key = vote.illustration_id
        vote_tuples.append(
            VoteTuple(
                outcome_key=key,
                # `run_id` is the third conjunct of the zeroed-cohort predicate (#570 re-scoped the
                # override from the calculator FAMILY to one 2026-07-14 RUN, which made the stamp
                # part of the signature). Passed straight off the row, exactly as the sibling call
                # in `printing_consensus.py` does - this file states above that the ruling has one
                # enforcement site and is honoured here without this file being touched, and
                # withholding the discriminator would quietly break that.
                weight=resolve_vote_weight(vote.source, vote.anonymous_id, vote.run_id),
                is_human_backed=is_human_backed_source(vote.source),
                dedupe_key=agent_dedupe_key(vote.anonymous_id) if pool else None,
            )
        )
    return pool_group_votes(vote_tuples) if pool else vote_tuples


def resolve_illustration(card: Card, group_card_ids: Sequence[int] | None = None) -> IllustrationOutcome:
    """
    Reconciles all `CardIllustrationVote` votes cast against `card`'s md5 identity group into a
    single resolved outcome: a specific Scryfall artwork `uuid.UUID`, the `UNKNOWN` sentinel
    (consensus is that this image has no known illustration identity), or `None` if there isn't
    yet enough signal to conclude anything. A thin wrapper over the shared
    `vote_consensus.resolve_weighted_consensus` - every weighting rule, the quorum/share gates,
    and the human-backed gate live there and are not re-derived here.

    THE HUMAN-BACKED GATE APPLIES UNCHANGED, and is worth stating plainly for this vote type
    because illustration votes are overwhelmingly machine-authored (PR #565's counterfactual replay projects
    ~10,277 machine rows catalogue-wide, against 3 human ones on record today): a winning outcome group must contain at least one
    human-backed vote, so no volume of machine votes - across any number of agents, any number of
    md5 siblings, at any confidence - ever resolves an illustration by itself. Pinned by
    `test_illustration_consensus.TestHumanBackedGate`.

    The identity group (issue #473) is every card indexing a byte-identical image file: ONE
    identification target, so its votes are tallied once, together, and the outcome applies to all
    of it. A card with no checksum, or the only card with its checksum, is a group of one (ruling
    3): no pooling keys are set, `pool_group_votes` is not called, and the result is the plain
    per-card tally.

    `group_card_ids` is an optional convenience for a caller that already derived the group; when
    given it MUST be exactly `md5_group_card_ids(card)` (ordering normalised, duplicates rejected)
    and anything else raises `ValueError`. Omitting it is always correct and costs one indexed
    query. See `group_illustration_votes`, where the check runs, for the full contract.
    """
    votes, is_group = group_illustration_votes(card, group_card_ids)
    if not votes:
        return None

    vote_tuples = build_group_illustration_vote_tuples(votes, pool=is_group)
    winning_key = resolve_weighted_consensus(
        vote_tuples, min_weight=illustration_min_votes(), min_share=illustration_min_share()
    )
    if winning_key is None:
        return None
    if winning_key == UNKNOWN:
        return UNKNOWN
    assert isinstance(winning_key, uuid.UUID)
    return winning_key


def _distinct_illustration_outcomes(votes: Iterable[CardIllustrationVote]) -> set[uuid.UUID | Literal["UNKNOWN"]]:
    """
    The distinct outcomes argued for by `votes` - what separates CONTESTED from plain UNRESOLVED
    below. Deliberately UNWEIGHTED and UNPOOLED, matching `vote_consensus.contested_queryset`'s
    own "cheap proxy, not a consensus recomputation" stance: "people disagree about this card" is
    a triage/display notion, and a disagreement that pooling would collapse (one agent
    contradicting itself across siblings) is still a disagreement worth surfacing to a human -
    arguably more so, since it means the same agent said two things about identical bytes.

    GROUP-scoped, not card-scoped: it is fed the whole group's rows, so two internally-consistent
    members that disagree WITH EACH OTHER read as contested. That is the case
    `get_contested_illustration_card_ids` (a per-card SQL proxy shared with the other vote types)
    structurally cannot see, and it is exactly the case md5 grouping creates.
    """
    outcomes: set[uuid.UUID | Literal["UNKNOWN"]] = set()
    for vote in votes:
        if vote.is_unknown:
            outcomes.add(UNKNOWN)
        else:
            # guaranteed non-null by the model's illustration_xor_unknown CheckConstraint
            assert vote.illustration_id is not None
            outcomes.add(vote.illustration_id)
    return outcomes


def resolve_and_persist_illustration(card: Card, members: Sequence[Card] | None = None) -> IllustrationOutcome:
    """
    Runs `resolve_illustration(card)` and writes the outcome onto `inferred_illustration_id` and
    `illustration_vote_status` together - for EVERY member of `card`'s md5 identity group, not just
    `card`. Mirrors `printing_consensus.resolve_and_persist_printing`'s group-write contract; see
    that function for the `members` identity/completeness argument, which is enforced identically
    here.

    THIS FUNCTION IS THE PROPAGATION MECHANISM described in the module docstring. A member that
    never received an illustration vote of its own - the `no-candidate-match` abstainer whose
    byte-identical sibling resolved cleanly - is written here from the GROUP's resolution, because
    the group's tally is its tally. Nothing in this function is aware that such a member abstained,
    and nothing needs to be: it is a member of the identity group, so the group's answer is its
    answer. Soundness rests entirely on group membership being md5-derived, which
    `md5_group_cards`/`md5_group_card_ids` guarantee (`Card.md5_checksum` and nothing else - never
    `content_phash`).

    When unresolved, distinguishes CONTESTED (more than one distinct outcome has votes anywhere in
    the group) from plain UNRESOLVED (not enough votes yet to conclude anything) - the same
    distinction `artist_consensus.resolve_and_persist_artist` draws, and, like it, at the cost of
    one extra read taken ONLY on that branch, so the common resolved case pays nothing for it.
    Unlike it, the read is group-scoped, so a group whose members disagree with each other is
    contested even though no single member is.

    Members are WRITTEN in pk order (not the caller-first order they arrive in), so two concurrent
    votes landing on two different members of one group take that group's row locks in the same
    order and queue behind each other instead of deadlocking - identical rationale to
    `resolve_and_persist_printing`'s own ordering.

    No Elasticsearch push: `inferred_illustration_id`/`illustration_vote_status` are not indexed
    fields (`documents.py` indexes neither, and no search path reads them), so unlike the printing
    twin there is no index to keep in step. If an illustration ever becomes a search-visible
    attribute, this is where the `_effective_indexed_*`-style gate belongs.
    """
    group_cards = list(members) if members is not None else md5_group_cards(card)
    if members is not None and not any(member is card for member in group_cards):
        # identity, not pk membership: an equal-pk COPY is precisely what this rejects. This
        # function would write the resolution through the copy, leaving the caller's own `card`
        # object on a stale status with nothing to indicate it. Completeness is left to
        # `resolve_illustration`'s own guard on the next line rather than re-derived here.
        raise ValueError(
            f"`members` must contain the caller's own `card` instance (pk {card.pk}) itself, "
            "unreplaced - see `printing_consensus.md5_group_cards`, whose output this expects."
        )
    group_card_ids = [member.pk for member in group_cards]
    result = resolve_illustration(card, group_card_ids=group_card_ids)

    illustration_id: uuid.UUID | None = None
    if result is None:
        votes, _ = group_illustration_votes(card, group_card_ids)
        contested = len(_distinct_illustration_outcomes(votes)) > 1
        status = IllustrationVoteStatus.CONTESTED if contested else IllustrationVoteStatus.UNRESOLVED
    elif isinstance(result, uuid.UUID):
        status = IllustrationVoteStatus.RESOLVED
        illustration_id = result
    else:
        # the UNKNOWN sentinel: consensus says there IS no artwork identity, which is a resolved
        # finding and not a withheld one - hence its own status, with a null id.
        status = IllustrationVoteStatus.UNKNOWN

    for member in sorted(group_cards, key=lambda group_card: group_card.pk):
        member.inferred_illustration_id = illustration_id
        member.illustration_vote_status = status
        member.save(update_fields=["inferred_illustration_id", "illustration_vote_status"])

    return result


class IllustrationVoteTallyEntry(TypedDict):
    illustration_id: uuid.UUID | None
    is_unknown: bool
    count: int


def get_illustration_vote_tally(card: Card) -> list[IllustrationVoteTallyEntry]:
    """
    Plain, unweighted per-outcome vote count for `card` ALONE - mirrors
    `printing_consensus.get_vote_tally`/`artist_consensus.get_artist_vote_tally`, for showing a
    voter what has already been said before they confirm or dispute it.

    DELIBERATELY NOT GROUP-SCOPED, unlike everything else in this module. This is a display of what
    was said ABOUT THIS CARD; folding in siblings' rows would show a voter counts they cannot
    reconcile with the card in front of them, and would double-count exactly the repetition
    pooling exists to suppress (it is unweighted, so it has no pooling to apply). The group is the
    unit of RESOLUTION; the card is the unit of DISPLAY.
    """
    tally: dict[uuid.UUID | Literal["UNKNOWN"], IllustrationVoteTallyEntry] = {}
    for vote in card.illustration_votes.all():
        key: uuid.UUID | Literal["UNKNOWN"]
        if vote.is_unknown:
            key = UNKNOWN
        else:
            # guaranteed non-null by the model's illustration_xor_unknown CheckConstraint
            assert vote.illustration_id is not None
            key = vote.illustration_id
        if key not in tally:
            tally[key] = IllustrationVoteTallyEntry(
                illustration_id=vote.illustration_id, is_unknown=vote.is_unknown, count=0
            )
        tally[key]["count"] += 1
    return sorted(tally.values(), key=lambda entry: entry["count"], reverse=True)


def get_contested_illustration_card_ids() -> list[int]:
    """
    IDs of cards with conflicting illustration votes on record - more than one distinct
    `illustration_id`, or an `illustration_id` coexisting with an `is_unknown` vote. Generalized
    via `vote_consensus.contested_queryset`; see that function for what "contested" means here and
    why it is a cheap proxy rather than a full consensus recomputation.

    Per-CARD, not per-group, for the same reason `get_illustration_vote_tally` is: this feeds
    triage surfaces that show a human one card. A group whose disagreement is spread across two
    members - each internally consistent - is invisible to this query and visible to
    `resolve_and_persist_illustration`'s CONTESTED status, which is the group-scoped statement of
    the same idea.
    """
    return contested_queryset(
        CardIllustrationVote.objects.all(),
        group_by="card_id",
        outcome_field="illustration_id",
        sentinel_field="is_unknown",
    )


__all__ = [
    "UNKNOWN",
    "IllustrationOutcome",
    "illustration_min_votes",
    "illustration_min_share",
    "group_illustration_votes",
    "build_group_illustration_vote_tuples",
    "resolve_illustration",
    "resolve_and_persist_illustration",
    "get_illustration_vote_tally",
    "get_contested_illustration_card_ids",
    "IllustrationVoteTallyEntry",
]
