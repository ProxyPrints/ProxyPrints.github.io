"""
Deductive printing-tag backfill: cast machine-weight `CardPrintingTag` votes for cards whose
printing is logically entailed by existing catalog data, in two confidence tiers.

PRINCIPLE: a deduction is only valid conditional on the image actually being an authentic
depiction of the named card - this catalog contains custom art, so a deduction can never be
more than a vote. `VoteSource.DEDUCTION` (weight `PRINTING_TAG_MACHINE_WEIGHT`, default 0.5) plus the
hard "at least one human-backed vote" gate in `cardpicker.vote_consensus.resolve_weighted_consensus`
means these votes can NEVER resolve consensus by themselves, regardless of volume - a human
still has to confirm. See `docs/features/printing-tags.md`'s Stage 4 section for the full
design writeup (census methodology).

D1 IS NOT CROSS-VERIFIED AGAINST SCRYFALL (corrected 2026-07-29). This docstring, the D1 tier
comment below and `docs/features/printing-tags.md` all used to say D1's uniqueness was confirmed
against "Scryfall's own printings_count". No such check exists, or ever existed. The column that
check reads - `CanonicalPrintingMetadata.catalogued_printings_count`, renamed from the misleading
`printings_count` in migration 0099 - is a COUNT of OUR OWN `CanonicalCard` rows per oracle id,
computed by `printing_metadata_import` from our own table. The check therefore restates the
name-uniqueness test that ran one line above it and excludes nothing: measured against the live
catalogue on 2026-07-29, 137 D1 candidates before the check and 137 after. See
`select_d1_candidates` for the structural proof, and issue #600 for the open question of what a
real external check would look like.

VOTES THIS MODULE CASTS TODAY CARRY WEIGHT (2026-07-29). The 2026-07-14 production run's 28,112
votes are permanently zero-weighted, but that is a ruling about THAT COHORT, held out as a
measurement control - not about this method. From the 2026-07-29 owner clarification onward, a
fresh run's votes resolve to the ordinary `PRINTING_TAG_MACHINE_WEIGHT` like any other machine
vote. The frozen cohort is identified by its stamped `run_id`, not by this module's identity, so
`run_backfill` stamps a fresh run_id per invocation and it can never be the frozen one - see
`generate_run_id` below and `vote_consensus.DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID`.
"""

import itertools
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from django.db.models import QuerySet
from django.utils import timezone

from cardpicker.local_calculate_verdicts import _get_cached_candidate_name_index
from cardpicker.local_identify_printing_tags import CandidateNameIndex
from cardpicker.models import Card, CardPrintingTag, PrintingTagStatus, VoteSource
from cardpicker.vote_consensus import DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID
from cardpicker.vote_write import purge_and_write_votes

DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"


def generate_run_id() -> str:
    """
    Fresh per-invocation `run_id` for the votes this run writes - same shape and same rationale as
    `local_identify_printing_tags.generate_run_id` (a UTC-timestamp prefix for human scannability
    plus a short random suffix so two invocations in the same second can't collide), prefixed with
    this calculator's `anonymous_id` so a run stamp says which calculator produced it on sight.

    This run was NOT stamped before 2026-07-29 - the 2026-07-14 production cohort's rows carry
    `run_id = NULL`, which is why they needed a retroactive stamp (migration
    `0097_freeze_deductive_backfill_zero_weight_cohort`) before the zero-weight override could be
    scoped to that run. Stamping every future run keeps that from ever being true again: from here
    on, every deductive-backfill vote says which invocation cast it, and `purge_machine_votes
    --run-id <id>` can retract one bad run without touching another.

    THE ASSERT IS THE ANTI-DRIFT GUARD, not a formality. The whole 2026-07-29 re-scoping rests on
    "the frozen control cohort is exactly the rows carrying one specific run_id". If this function
    could ever mint that same string, a future run's votes would silently join a ratified control
    cohort and lose their weight - re-creating, by collision, precisely the over-broad "this method
    is disqualified forever" behaviour that clarification removed. The timestamp shape makes that
    unreachable in practice; the assert makes it unreachable in fact, and fails loudly rather than
    quietly if someone changes this format to something that collides.
    """
    run_id = f"{DEDUCTIVE_BACKFILL_ANONYMOUS_ID}/{timezone.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    assert run_id != DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID, (
        "a new deductive-backfill run must never re-mint the frozen 2026-07-14 cohort's run_id: "
        "its votes would be silently swept into a ratified zero-weight measurement control."
    )
    return run_id


Tier = Literal["d1", "d2"]

# D1 = name matches exactly one CanonicalCard row in our catalogue. That is the whole test -
# it IS "our table happens to have one row", and nothing corroborates it externally (see the
# module docstring's correction and `select_d1_candidates`).
# D2 = name matches multiple CanonicalCard rows, but the card's own `expansion_hint`
# (parsed at upload time from a lone set-code bracket token in the source filename -
# `cardpicker/tags.py::Tags.extract()`) narrows it to exactly one.
CONFIDENCE_BY_TIER: dict[Tier, float] = {"d1": 0.95, "d2": 0.90}


@dataclass(frozen=True)
class DeductiveVote:
    card_id: int
    printing_id: int
    tier: Tier

    @property
    def confidence(self) -> float:
        return CONFIDENCE_BY_TIER[self.tier]


def _eligible_base_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """
    Shared base pool for both tiers: unresolved, no confirmed indexing match, no vote of any
    kind yet (not just no *deductive* vote - see docs/features/printing-tags.md's Stage 4
    section for why the exclusion is "any existing vote", not merely this cohort's own
    anonymous_id: a card with a pre-existing human vote is exactly the case where adding a
    machine-weight vote for the same outcome could increase an already-human-backed group's
    weight across the resolution threshold - the hard "machine-only can never resolve" gate
    protects machine-only cards, not cards where a machine vote top-tops an existing human
    vote. Excluding them outright removes the scenario rather than relying on the live
    post-write check to catch it).

    Also excludes anything that already tells us the PRINCIPLE's precondition (an authentic
    depiction of the named card) doesn't hold: a card with the "Custom" tag already resolved
    (`card.tags`, confirmed by the tag-vote consensus - this catalog deliberately allows
    custom/fan art, and a deduction from the *name* alone is meaningless once we already know
    the art isn't depicting a real printing) or a non-English card (`Card.language` - the whole
    name-matching pipeline compares against `CanonicalCard.name`, which is Scryfall's English
    oracle name; a coincidental text match against a foreign-language card's name isn't a
    trustworthy signal about which specific printing it depicts).

    BATCH SCOPING (`card_ids`, issue #722): when given, narrows the outer `Card` query itself
    (`.filter(pk__in=card_ids)`) rather than letting a caller filter the yielded `DeductiveVote`s
    afterward - the same "push into the SQL" convention
    `local_identify_printing_tags._eligible_base_queryset`'s own `card_ids` docstring establishes,
    and for the same reason: this queryset walks the full unresolved pool
    (`printing_tag_status=UNRESOLVED, canonical_card__isnull=True`, currently ~135,000+ rows), and
    a caller that already knows which cards it wants has no reason to pay a scan over the rest of
    it. `card_ids=None` (every existing caller) is byte-identical to before.
    """
    queryset = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            printing_tags__isnull=True,
            language__iexact="en",
        )
        .exclude(tags__contains=["Custom"])
        .select_related("source")
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def select_d1_candidates(
    index: "CandidateNameIndex | None" = None, card_ids: Optional[Iterable[int]] = None
) -> Iterable[DeductiveVote]:
    """
    D1: the card's name matches exactly one `CanonicalCard` row in our catalogue. That is the
    whole test - it IS "our table happens to have one row", and nothing corroborates it
    externally (see the module docstring's correction and issue #600).

    THE INDEX (2026-07-30, issue #722): resolved through
    `local_calculate_verdicts._get_cached_candidate_name_index()` - the SAME per-worker-process,
    version-stamped `CandidateNameIndex` cache `run_join_key_calculator`/`run_fallback_calculator`/
    `run_illustration_calculator`/`run_frame_mismatch_recovery`/`run_lands_identify` already use,
    not a second, module-private index rebuilt from scratch on every call (the defect this module
    used to have: `CanonicalNameIndex.__init__` scanned all 113k+ `CanonicalCard` rows, several
    queries, every single invocation).

    THE catalogued_printings_count CROSS-CHECK IS GONE, not merely stopped being read (2026-07-30).
    It used to re-verify `len(matches) == 1` against a second field, `CanonicalPrintingMetadata.
    catalogued_printings_count`, that `CandidateNameIndex`'s own scan does not carry (that index
    is shared with engines that have no use for it - see its own docstring). Losing it costs
    nothing real: `catalogued_printings_count` is the number of `CanonicalCard` rows sharing this
    row's `canonical_id` (oracle id), rows sharing an oracle id share that oracle card's name, so
    an oracle group of size N > 1 already puts N rows under the same normalised name and
    `len(matches) == 1` above has already rejected the card - the count check could only ever
    re-confirm what the name-uniqueness test already proved, never catch anything it missed
    (measured against the live catalogue 2026-07-29: 137 candidates before the removed check, 137
    after). What the removed check was never able to catch either - "Scryfall publishes more
    printings of this card than we have imported, so a unique local match is not proof of
    anything" - remains real and remains uncaught; issue #600 tracks what a genuine external check
    would look like.
    """
    index = index or _get_cached_candidate_name_index()
    for card in _eligible_base_queryset(card_ids=card_ids).only("pk", "name", "source_id").iterator(chunk_size=5000):
        matches = index.candidates_for(card.name)
        if len(matches) == 1:
            yield DeductiveVote(card_id=card.pk, printing_id=matches[0].pk, tier="d1")


def select_d2_candidates(
    index: "CandidateNameIndex | None" = None, card_ids: Optional[Iterable[int]] = None
) -> Iterable[DeductiveVote]:
    """D2: the card's name matches more than one `CanonicalCard` row (D1's territory otherwise),
    but the card's own `expansion_hint` (already lowercased at parse time - see `tags.py::Tags.
    extract()`) narrows `index.candidates_for(card.name)` to exactly one `expansion_code` match.
    Same shared, process-cached `CandidateNameIndex` as `select_d1_candidates` - see that
    function's own docstring."""
    index = index or _get_cached_candidate_name_index()
    for card in (
        _eligible_base_queryset(card_ids=card_ids)
        .only("pk", "name", "expansion_hint", "source_id")
        .iterator(chunk_size=5000)
    ):
        if not card.expansion_hint:
            continue
        matches = index.candidates_for(card.name)
        if len(matches) <= 1:
            continue  # D1's territory, or no match at all - not D2
        narrowed = [candidate for candidate in matches if candidate.expansion_code == card.expansion_hint]
        if len(narrowed) == 1:
            yield DeductiveVote(card_id=card.pk, printing_id=narrowed[0].pk, tier="d2")


def select_candidates(
    tier: Literal["d1", "d2", "all"], card_ids: Optional[Iterable[int]] = None
) -> Iterable[DeductiveVote]:
    index = _get_cached_candidate_name_index()
    if tier in ("d1", "all"):
        yield from select_d1_candidates(index, card_ids=card_ids)
    if tier in ("d2", "all"):
        yield from select_d2_candidates(index, card_ids=card_ids)


@dataclass
class BackfillResult:
    d1_written: int = 0
    d2_written: int = 0
    dry_run: bool = False
    gate_violations: list[int] = field(default_factory=list)

    @property
    def total_written(self) -> int:
        return self.d1_written + self.d2_written


def verify_zero_resolutions(card_ids: list[int], batch_size: int = 5000) -> list[int]:
    """
    The live gate check: re-fetches each just-voted card fresh from the DB (picking up the
    vote(s) just written) and runs the *pure* `resolve_printing` (never `resolve_and_persist_printing`
    - this must never itself cause a write, including under the failure case this exists to
    catch) to confirm the new machine-only vote didn't tip any card into a resolved outcome. Returns
    the card pks that violated the gate - empty on success. Structurally this should always be
    empty (see module docstring: machine-only groups can never satisfy `resolve_weighted_consensus`'s
    human-backed gate, and `_eligible_base_queryset` excludes every card with a pre-existing
    vote of any kind), but "should structurally never happen" is exactly what an operational
    gate exists to verify against the real data rather than trust.

    LEFT FAMILY-AGNOSTIC ON PURPOSE (2026-07-29 review of every consumer of the old family-scoped
    zero-weight rule): this gate keys on nothing about this calculator's identity - it just re-runs
    the real `resolve_printing` against fresh DB state. That is what makes it still meaningful now
    that this run's votes carry weight again. Before the re-scoping it was trivially satisfied for
    a second reason (every vote written weighed 0); now it is satisfied only by the reason that
    actually matters - `_eligible_base_queryset` admits only cards with ZERO pre-existing votes,
    so a just-voted card holds one machine-only vote, and `resolve_weighted_consensus`' hard
    human-backed gate makes a machine-only group unresolvable at any weight. Do not "optimise"
    this by skipping the check on the grounds that these votes are zero-weight. They are not.
    """
    from cardpicker.printing_consensus import resolve_printing

    violations: list[int] = []
    for i in range(0, len(card_ids), batch_size):
        chunk = card_ids[i : i + batch_size]
        for card in Card.objects.filter(pk__in=chunk).iterator(chunk_size=batch_size):
            if resolve_printing(card) is not None:
                violations.append(card.pk)
    return violations


def run_backfill(
    tier: Literal["d1", "d2", "all"],
    limit: Optional[int] = None,
    dry_run: bool = False,
    batch_size: int = 2000,
    progress_every: int = 20000,
    card_ids: Optional[Iterable[int]] = None,
) -> BackfillResult:
    """
    Selects candidates for `tier`, writes them in `batch_size` chunks (so an interrupted run
    keeps whatever it already committed rather than losing all progress - `_eligible_base_queryset`
    excludes any card with an existing vote, so simply re-running the command later picks up
    exactly where it left off with no separate checkpoint file needed), then - unless `dry_run`
    - runs the live gate check over every card just written to.

    Every vote this invocation writes is stamped with ONE `run_id`, generated once here and
    threaded through the whole run (`generate_run_id`'s own docstring covers why, and why it can
    never collide with the frozen 2026-07-14 cohort's stamp). Votes written by this run carry
    ordinary machine weight - see the module docstring.

    `card_ids` (issue #722) is threaded straight through to `select_candidates` ->
    `_eligible_base_queryset`, where it is pushed into the SQL rather than filtered here in
    Python - see that function's own docstring. `card_ids=None` (the management command's only
    calling shape) is byte-identical to before. NOT wired into any Stage E dispatch path yet -
    that is a deliberate, separate decision pending a measured per-card cost at micro-batch
    granularity, not an oversight; see issue #722's own acceptance criteria.
    """
    votes: Iterable[DeductiveVote] = select_candidates(tier, card_ids=card_ids)
    if limit is not None:
        votes = itertools.islice(votes, limit)

    run_id = generate_run_id()
    result = BackfillResult(dry_run=dry_run)
    written_card_ids: list[int] = []
    batch: list[DeductiveVote] = []
    seen = 0

    def flush(pending: list[DeductiveVote]) -> None:
        if not pending:
            return
        if not dry_run:
            # CANCEL-SAFETY (2026-07-28): the chunked flush already means an interrupted run keeps
            # whatever it committed (see this function's own docstring), but the purge and the
            # insert within a chunk were two untransacted statements - a kill between them deleted
            # the chunk's cards' previous same-family votes and wrote no replacement, which is
            # worse than simply losing the chunk. `vote_write.purge_and_write_votes` makes the
            # pair atomic and scopes the purge to exactly the rows it inserts; `ignore_conflicts`
            # stays off, as before.
            purge_and_write_votes(
                CardPrintingTag,
                [
                    CardPrintingTag(
                        card_id=vote.card_id,
                        printing_id=vote.printing_id,
                        is_no_match=False,
                        anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
                        source=VoteSource.DEDUCTION,
                        confidence=vote.confidence,
                        run_id=run_id,
                    )
                    for vote in pending
                ],
                anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
                target_field="card_id",
            )
        for vote in pending:
            if vote.tier == "d1":
                result.d1_written += 1
            else:
                result.d2_written += 1
            written_card_ids.append(vote.card_id)

    for vote in votes:
        batch.append(vote)
        seen += 1
        if len(batch) >= batch_size:
            flush(batch)
            batch = []
        if seen % progress_every == 0:
            print(f"  ... {seen} candidates processed")
    flush(batch)

    if not dry_run and written_card_ids:
        result.gate_violations = verify_zero_resolutions(written_card_ids)

    return result


__all__ = [
    "DEDUCTIVE_BACKFILL_ANONYMOUS_ID",
    "generate_run_id",
    "CONFIDENCE_BY_TIER",
    "DeductiveVote",
    "BackfillResult",
    "select_d1_candidates",
    "select_d2_candidates",
    "select_candidates",
    "verify_zero_resolutions",
    "run_backfill",
]
