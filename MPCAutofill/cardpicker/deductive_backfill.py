"""
Deductive printing-tag backfill: cast AI-weight `CardPrintingTag` votes for cards whose
printing is logically entailed by existing catalog data, in two confidence tiers.

PRINCIPLE: a deduction is only valid conditional on the image actually being an authentic
depiction of the named card - this catalog contains custom art, so a deduction can never be
more than a vote. `VoteSource.AI` (weight `PRINTING_TAG_AI_WEIGHT`, default 0.5) plus the
hard "at least one human-backed vote" gate in `cardpicker.vote_consensus.resolve_weighted_consensus`
means these votes can NEVER resolve consensus by themselves, regardless of volume - a human
still has to confirm. See `docs/features/printing-tags.md`'s Stage 4 section for the full
design writeup (census methodology, Scryfall `printings_count` cross-verification).
"""

import collections
import itertools
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from django.db.models import QuerySet

from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.search.sanitisation import to_searchable

DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"

Tier = Literal["d1", "d2"]

# D1 = name matches exactly one CanonicalCard, cross-verified against Scryfall's own
# `printings_count` (not just "our table happens to have one row" - see module docstring).
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


class CanonicalNameIndex:
    """
    In-memory index over every `CanonicalCard`, built once and reused across the whole scan -
    `to_searchable` isn't a SQL function, so per-card exact-name and (name, expansion) lookups
    have to happen in Python against a prebuilt structure rather than as a query per card
    (which would be 113k+ queries per backfill run).
    """

    def __init__(self) -> None:
        by_name: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
        by_name_expansion: dict[tuple[str, str], list[tuple[int, int]]] = collections.defaultdict(list)
        rows = CanonicalCard.objects.select_related("expansion", "printing_metadata").values_list(
            "pk", "name", "expansion__code", "printing_metadata__printings_count"
        )
        for pk, name, expansion_code, printings_count in rows:
            normalised = to_searchable(name)
            # printings_count can be null if a CanonicalCard predates the metadata import
            # (`printing_metadata` is a nullable reverse OneToOne) - treat as "unverifiable",
            # never as 1, so it can't slip through the D1 Scryfall cross-check by accident.
            count = printings_count if printings_count is not None else -1
            by_name[normalised].append((pk, count))
            by_name_expansion[(normalised, expansion_code.lower())].append((pk, count))
        self._by_name = dict(by_name)
        self._by_name_expansion = dict(by_name_expansion)

    def exact_matches(self, name: str) -> list[tuple[int, int]]:
        return self._by_name.get(to_searchable(name), [])

    def exact_matches_in_expansion(self, name: str, expansion_code_lower: str) -> list[tuple[int, int]]:
        return self._by_name_expansion.get((to_searchable(name), expansion_code_lower), [])


def _eligible_base_queryset() -> "QuerySet[Card]":
    """
    Shared base pool for both tiers: unresolved, no confirmed indexing match, no vote of any
    kind yet (not just no *deductive* vote - see docs/features/printing-tags.md's Stage 4
    section for why the exclusion is "any existing vote", not merely this cohort's own
    anonymous_id: a card with a pre-existing human vote is exactly the case where adding an
    AI-weight vote for the same outcome could increase an already-human-backed group's weight
    across the resolution threshold - the hard "AI-only can never resolve" gate protects
    AI-only cards, not cards where AI top-tops an existing human vote. Excluding them outright
    removes the scenario rather than relying on the live post-write check to catch it).

    Also excludes anything that already tells us the PRINCIPLE's precondition (an authentic
    depiction of the named card) doesn't hold: a card with the "Custom" tag already resolved
    (`card.tags`, confirmed by the tag-vote consensus - this catalog deliberately allows
    custom/fan art, and a deduction from the *name* alone is meaningless once we already know
    the art isn't depicting a real printing) or a non-English card (`Card.language` - the whole
    name-matching pipeline compares against `CanonicalCard.name`, which is Scryfall's English
    oracle name; a coincidental text match against a foreign-language card's name isn't a
    trustworthy signal about which specific printing it depicts).
    """
    return (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            printing_tags__isnull=True,
            language__iexact="en",
        )
        .exclude(tags__contains=["Custom"])
        .select_related("source")
    )


def select_d1_candidates(index: "CanonicalNameIndex | None" = None) -> Iterable[DeductiveVote]:
    index = index or CanonicalNameIndex()
    for card in _eligible_base_queryset().only("pk", "name", "source_id").iterator(chunk_size=5000):
        matches = index.exact_matches(card.name)
        if len(matches) == 1:
            printing_pk, printings_count = matches[0]
            if printings_count == 1:
                yield DeductiveVote(card_id=card.pk, printing_id=printing_pk, tier="d1")


def select_d2_candidates(index: "CanonicalNameIndex | None" = None) -> Iterable[DeductiveVote]:
    index = index or CanonicalNameIndex()
    for card in _eligible_base_queryset().only("pk", "name", "expansion_hint", "source_id").iterator(chunk_size=5000):
        if not card.expansion_hint:
            continue
        matches = index.exact_matches(card.name)
        if len(matches) <= 1:
            continue  # D1's territory, or no match at all - not D2
        narrowed = index.exact_matches_in_expansion(card.name, card.expansion_hint)
        if len(narrowed) == 1:
            printing_pk, _printings_count = narrowed[0]
            yield DeductiveVote(card_id=card.pk, printing_id=printing_pk, tier="d2")


def select_candidates(tier: Literal["d1", "d2", "all"]) -> Iterable[DeductiveVote]:
    index = CanonicalNameIndex()
    if tier in ("d1", "all"):
        yield from select_d1_candidates(index)
    if tier in ("d2", "all"):
        yield from select_d2_candidates(index)


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
    catch) to confirm the new AI-only vote didn't tip any card into a resolved outcome. Returns
    the card pks that violated the gate - empty on success. Structurally this should always be
    empty (see module docstring: AI-only groups can never satisfy `resolve_weighted_consensus`'s
    human-backed gate, and `_eligible_base_queryset` excludes every card with a pre-existing
    vote of any kind), but "should structurally never happen" is exactly what an operational
    gate exists to verify against the real data rather than trust.
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
) -> BackfillResult:
    """
    Selects candidates for `tier`, writes them in `batch_size` chunks (so an interrupted run
    keeps whatever it already committed rather than losing all progress - `_eligible_base_queryset`
    excludes any card with an existing vote, so simply re-running the command later picks up
    exactly where it left off with no separate checkpoint file needed), then - unless `dry_run`
    - runs the live gate check over every card just written to.
    """
    votes: Iterable[DeductiveVote] = select_candidates(tier)
    if limit is not None:
        votes = itertools.islice(votes, limit)

    result = BackfillResult(dry_run=dry_run)
    written_card_ids: list[int] = []
    batch: list[DeductiveVote] = []
    seen = 0

    def flush(pending: list[DeductiveVote]) -> None:
        if not pending:
            return
        if not dry_run:
            CardPrintingTag.objects.bulk_create(
                [
                    CardPrintingTag(
                        card_id=vote.card_id,
                        printing_id=vote.printing_id,
                        is_no_match=False,
                        anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
                        source=VoteSource.AI,
                        confidence=vote.confidence,
                    )
                    for vote in pending
                ]
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
    "CONFIDENCE_BY_TIER",
    "DeductiveVote",
    "CanonicalNameIndex",
    "BackfillResult",
    "select_d1_candidates",
    "select_d2_candidates",
    "select_candidates",
    "verify_zero_resolutions",
    "run_backfill",
]
