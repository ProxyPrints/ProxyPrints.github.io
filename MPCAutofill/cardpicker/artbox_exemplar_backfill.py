"""
Issue #508 phase 1: seeds `ArtboxPhashExemplar` from our own DB, never from Scryfall images (see
that model's own docstring for the full design rationale). Two seed sources, owner-ratified
2026-08-05:

- Human-backed printing resolutions (`Card.printing_tag_status == RESOLVED` - resolution always
  requires a human-backed vote, see `vote_consensus.resolve_weighted_consensus`, so no per-vote
  inspection is needed to classify one as such).
- High-confidence join-key machine votes (`local_calculate_verdicts`'s join-key calculator, at or
  above `JOIN_KEY_SEED_CONFIDENCE_FLOOR`).

Reuses the batched/resumable/idempotent shape `local_phash.run_canonical_hash_backfill` (PR #694,
branch `feat/local-backfill-canonical-hash`) established for a local, zero-network backfill: filter
on "not yet done" as the checkpoint (there, `image_hash=0`; here, no existing
`ArtboxPhashExemplar` row for the card), a `--dry-run` that reports without writing. This backfill
needs none of that branch's threaded fetch pipeline - every input here is already a local DB read
(`ImageEvidence.artbox_phash`, `CardPrintingTag.confidence`), so there is nothing to fetch and
nothing to parallelize; `Model.objects.bulk_create(..., batch_size=...)` does the insert-side
chunking on its own.
"""

import itertools
import time
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional, TypedDict
from uuid import UUID

from django.db.models import F, QuerySet

from cardpicker.evidence_transfer import md5_currency_q
from cardpicker.models import (
    ArtboxPhashExemplar,
    ArtboxPhashExemplarSeedKind,
    Card,
    CardPrintingTag,
    ImageEvidence,
    PrintingTagStatus,
)
from cardpicker.printing_consensus import md5_group_key

# Duplicated as a literal rather than imported from `local_calculate_verdicts` - matching that
# module's own "avoid a hard import-time dependency between sibling engines over one constant"
# precedent (its own comment on `DEDUCTIVE_BACKFILL_ANONYMOUS_ID`/`OCR_CONFIDENCE_BOTH`).
JOIN_KEY_ANONYMOUS_ID = "stage-d-join-key-v1"

# The floor between `local_calculate_verdicts.JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY`/
# `JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK` (0.75) and `JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT`
# (0.65). Measured 2026-08-05 against the live join-key vote population: 41,585 votes at 0.85,
# 498 at 0.75, 38 at 0.65, 16,537 at 0.6 (`JOIN_KEY_NO_MATCH_CONFIDENCE` - `is_no_match=True`
# rows, never identifications, structurally excluded below regardless of this floor).
#
# 0.85 and 0.75 are both UNCONTRADICTED matches (both signals agree, or the collector-number/
# symbol-tiebreak match stands with nothing disagreeing) - 42,083 votes admitted. 0.65 is a real
# match assertion that carries a KNOWN contradicting signal (the artist OCR read disagrees with
# the matched printing's own artist) - only 38 votes, and excluding them is the conservative
# choice per the owner's framing: a wrong exemplar propagates to every card it later matches, so
# a floor that admits a marginal, actively-contradicted identification is worse than a smaller
# index. See docs/identification-pipeline.md's "Parallel detectors" section for where this is
# documented for a reader who isn't reading this module's own source.
JOIN_KEY_SEED_CONFIDENCE_FLOOR = 0.75

DEFAULT_BACKFILL_BATCH_SIZE = 500


def human_resolution_seed_group_key(card: Card) -> str:
    """
    Stable retraction identity for a HUMAN_RESOLUTION seed - shares a value with every OTHER
    exemplar seeded from the same resolved md5 identity group (`printing_consensus.md5_group_key`
    is the same group `printing_consensus.resolve_printing` itself tallies as one unit), so
    retracting a wrong resolution retracts every exemplar it seeded, across every group member,
    in one filtered delete - not just the one card a caller happens to be looking at.
    """
    return f"human:{md5_group_key(card)}"


def join_key_seed_group_key(vote_id: int) -> str:
    """
    Stable retraction identity for a JOIN_KEY_MACHINE seed - one vote seeds exactly one exemplar,
    so this is a 1:1 key, kept in the same `f"{kind}:{value}"` shape as
    `human_resolution_seed_group_key` rather than reusing the vote's own pk as a bare int, so a
    caller retracting "by seed" never needs to know which of the two seed kinds it's holding.
    """
    return f"machine:vote:{vote_id}"


def _current_artbox_evidence_queryset() -> "QuerySet[ImageEvidence]":
    """
    Bulk form of `image_evidence.current_evidence_queryset` (that function is single-card;
    `evidence_transfer.md5_currency_q` is its own bulk F-expression half, reused here directly) -
    every `ImageEvidence` row that is CURRENT for its own card (live `content_phash` match, and
    the md5-currency rule `md5_currency_q` expresses) AND carries a populated `artbox_phash`. A
    stale row (an evidence row from a since-replaced image) can never reach here, and neither can
    a card with no `artbox_phash` yet (79,207 of 230,378 rows, per issue #508's brief) - both
    excluded by construction, never by a downstream filter a future caller could forget.
    """
    return ImageEvidence.objects.filter(
        content_hash=F("card__content_phash"),
        card__content_phash__isnull=False,
        artbox_phash__isnull=False,
    ).filter(md5_currency_q())


class _ExemplarFields(TypedDict):
    illustration_id: UUID
    artbox_phash: int
    card_id: int
    printing_id: int
    seed_kind: str
    is_human_backed: bool
    source_vote_id: Optional[int]
    confidence: Optional[float]
    seed_group_key: str
    content_hash: int


def _chunked(iterable: Iterable[Any], size: int) -> Iterator[list[Any]]:
    """Groups `iterable` into lists of at most `size` - used only for the join-key pass's bulk
    evidence lookup (one query per chunk instead of one per vote), never for the insert side
    (`bulk_create`'s own `batch_size` argument already chunks that)."""
    iterator = iter(iterable)
    while True:
        chunk = list(itertools.islice(iterator, size))
        if not chunk:
            return
        yield chunk


def _human_resolution_candidates() -> Iterator[_ExemplarFields]:
    """
    Every current-evidence card whose `printing_tag_status` is RESOLVED and whose resolved
    printing carries an `illustration_id` - resolution is human-backed by construction (see this
    module's own docstring), so no per-vote inspection is needed.
    `.exclude(card__artbox_phash_exemplar__isnull=False)` is the checkpoint: a card that already
    has an exemplar row is never re-visited, the same NULL/absence-filter resumability discipline
    `local_phash.run_canonical_hash_backfill` uses for `image_hash=0`.
    """
    queryset = (
        _current_artbox_evidence_queryset()
        .filter(
            card__printing_tag_status=PrintingTagStatus.RESOLVED,
            card__inferred_canonical_card__isnull=False,
            card__inferred_canonical_card__printing_metadata__illustration_id__isnull=False,
        )
        .exclude(card__artbox_phash_exemplar__isnull=False)
        .select_related("card", "card__inferred_canonical_card__printing_metadata")
        .order_by("card_id")
    )
    for evidence in queryset.iterator(chunk_size=DEFAULT_BACKFILL_BATCH_SIZE):
        card = evidence.card
        printing = card.inferred_canonical_card
        # Both asserts state what the queryset's own filters above already guarantee at runtime
        # (inferred_canonical_card__isnull=False, printing_metadata__illustration_id__isnull=
        # False, artbox_phash__isnull=False) - mypy cannot see through a QuerySet filter, so
        # these are for the type checker, not a real runtime possibility.
        assert printing is not None
        assert printing.printing_metadata.illustration_id is not None
        assert evidence.artbox_phash is not None
        yield _ExemplarFields(
            illustration_id=printing.printing_metadata.illustration_id,
            artbox_phash=evidence.artbox_phash,
            card_id=card.pk,
            printing_id=printing.pk,
            seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION,
            is_human_backed=True,
            source_vote_id=None,
            confidence=None,
            seed_group_key=human_resolution_seed_group_key(card),
            content_hash=evidence.content_hash,
        )


def _join_key_machine_candidates(
    batch_size: int, already_seeded_card_ids: set[int]
) -> Iterator[tuple[list[_ExemplarFields], int]]:
    """
    Yields `(batch, skipped_in_batch)` for every `CardPrintingTag` vote cast by the join-key
    calculator at or above `JOIN_KEY_SEED_CONFIDENCE_FLOOR`. `already_seeded_card_ids` is the set
    of cards the human-resolution pass just seeded (or would have, under `--dry-run`) - a card
    resolved AND join-key-voted is seeded once, from the higher-trust human resolution, never
    both; this in-memory exclusion is what keeps that true even inside a single `--dry-run`
    invocation, where the DB-level `.exclude(card__artbox_phash_exemplar__isnull=False)` checkpoint
    (correct across separate invocations) hasn't actually written anything yet to exclude against.
    A vote whose card has no CURRENT `artbox_phash` (stale evidence, or evidence that was never
    computed) is counted in `skipped_in_batch`, never silently dropped.
    """
    votes_queryset = (
        CardPrintingTag.objects.filter(
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            is_no_match=False,
            confidence__gte=JOIN_KEY_SEED_CONFIDENCE_FLOOR,
            printing__printing_metadata__illustration_id__isnull=False,
        )
        .exclude(card__artbox_phash_exemplar__isnull=False)
        .select_related("printing__printing_metadata")
        .order_by("pk")
    )
    for vote_chunk in _chunked(votes_queryset.iterator(chunk_size=batch_size), batch_size):
        vote_chunk = [vote for vote in vote_chunk if vote.card_id not in already_seeded_card_ids]
        if not vote_chunk:
            continue
        card_ids = [vote.card_id for vote in vote_chunk]
        evidence_by_card_id = {
            card_id: (artbox_phash, content_hash)
            for card_id, artbox_phash, content_hash in _current_artbox_evidence_queryset()
            .filter(card_id__in=card_ids)
            .values_list("card_id", "artbox_phash", "content_hash")
        }
        batch: list[_ExemplarFields] = []
        skipped = 0
        for vote in vote_chunk:
            evidence = evidence_by_card_id.get(vote.card_id)
            if evidence is None:
                skipped += 1
                continue
            artbox_phash, content_hash = evidence
            # Same rationale as _human_resolution_candidates' own asserts above - the queryset
            # filters already guarantee these are non-null; mypy just can't see through them.
            assert artbox_phash is not None
            assert vote.printing is not None
            assert vote.printing.printing_metadata.illustration_id is not None
            batch.append(
                _ExemplarFields(
                    illustration_id=vote.printing.printing_metadata.illustration_id,
                    artbox_phash=artbox_phash,
                    card_id=vote.card_id,
                    printing_id=vote.printing_id,
                    seed_kind=ArtboxPhashExemplarSeedKind.JOIN_KEY_MACHINE,
                    is_human_backed=False,
                    source_vote_id=vote.pk,
                    confidence=vote.confidence,
                    seed_group_key=join_key_seed_group_key(vote.pk),
                    content_hash=content_hash,
                )
            )
        yield batch, skipped


def _bulk_create_exemplars(fields_list: list[_ExemplarFields], run_id: Optional[str], batch_size: int) -> None:
    ArtboxPhashExemplar.objects.bulk_create(
        [
            ArtboxPhashExemplar(
                illustration_id=fields["illustration_id"],
                artbox_phash=fields["artbox_phash"],
                card_id=fields["card_id"],
                printing_id=fields["printing_id"],
                seed_kind=fields["seed_kind"],
                is_human_backed=fields["is_human_backed"],
                source_vote_id=fields["source_vote_id"],
                confidence=fields["confidence"],
                seed_group_key=fields["seed_group_key"],
                content_hash=fields["content_hash"],
                run_id=run_id,
            )
            for fields in fields_list
        ],
        batch_size=batch_size,
    )


@dataclass(frozen=True)
class ArtboxExemplarBackfillResult:
    dry_run: bool = False
    human_backed_seeded: int = 0
    machine_seeded: int = 0
    machine_skipped_stale_or_missing_evidence: int = 0
    distinct_illustration_ids: int = 0
    elapsed_seconds: float = 0.0


def run_artbox_exemplar_backfill(
    dry_run: bool = False,
    batch_size: int = DEFAULT_BACKFILL_BATCH_SIZE,
    limit: Optional[int] = None,
    run_id: Optional[str] = None,
) -> ArtboxExemplarBackfillResult:
    """
    Human-backed resolutions are seeded FIRST, in full, before the join-key machine pass even
    queries - the priority order the owner's design implies ("seed from high-confidence join-key
    hits AS WELL AS human-backed resolutions"): a card that qualifies for both is seeded once,
    from the higher-trust human resolution.

    `limit` bounds the TOTAL number of exemplar rows created across both passes combined (for
    testing/sampling - mirrors `local_phash.run_canonical_hash_backfill`'s own `--limit`), not a
    per-pass limit. Human-backed resolutions currently number 12 catalogue-wide (2026-08-05), so
    materializing that pass's candidates as one list, rather than streaming it in batches the way
    the (much larger) machine pass below does, is a deliberate, safe simplification - not an
    oversight that stops scaling once that population is no longer small; growth in resolved
    printings is governed by real human review throughput, which will not silently jump this
    module's own memory footprint.
    """
    start_time = time.monotonic()
    illustration_ids: set[UUID] = set()

    human_fields = list(_human_resolution_candidates())
    if limit is not None:
        human_fields = human_fields[:limit]
    human_backed_seeded = len(human_fields)
    illustration_ids.update(fields["illustration_id"] for fields in human_fields)
    if not dry_run and human_fields:
        _bulk_create_exemplars(human_fields, run_id, batch_size)

    already_seeded_card_ids = {fields["card_id"] for fields in human_fields}
    remaining = None if limit is None else max(limit - human_backed_seeded, 0)

    machine_seeded = 0
    machine_skipped = 0
    if remaining is None or remaining > 0:
        for batch, skipped_in_batch in _join_key_machine_candidates(batch_size, already_seeded_card_ids):
            machine_skipped += skipped_in_batch
            if remaining is not None:
                batch = batch[:remaining]
            if not batch:
                if remaining is not None and remaining <= 0:
                    break
                continue
            if not dry_run:
                _bulk_create_exemplars(batch, run_id, batch_size)
            machine_seeded += len(batch)
            illustration_ids.update(fields["illustration_id"] for fields in batch)
            if remaining is not None:
                remaining -= len(batch)
                if remaining <= 0:
                    break

    return ArtboxExemplarBackfillResult(
        dry_run=dry_run,
        human_backed_seeded=human_backed_seeded,
        machine_seeded=machine_seeded,
        machine_skipped_stale_or_missing_evidence=machine_skipped,
        distinct_illustration_ids=len(illustration_ids),
        elapsed_seconds=time.monotonic() - start_time,
    )


def dry_run_candidate_exemplar_hashes(batch_size: int = DEFAULT_BACKFILL_BATCH_SIZE) -> list[int]:
    """
    Every `artbox_phash` value `run_artbox_exemplar_backfill(dry_run=True, ...)` would have
    seeded, re-derived from the live tables rather than read back from a persisted table (nothing
    was written) - for a dry run's own coverage measurement (`measure_unresolved_coverage`),
    which needs the candidate hash set regardless of whether this invocation is allowed to write
    it anywhere.
    """
    human_fields = list(_human_resolution_candidates())
    already_seeded_card_ids = {fields["card_id"] for fields in human_fields}
    hashes = [fields["artbox_phash"] for fields in human_fields]
    for batch, _skipped in _join_key_machine_candidates(batch_size, already_seeded_card_ids):
        hashes.extend(fields["artbox_phash"] for fields in batch)
    return hashes


def _hamming_radius_le_2_variants(value: int, bits: int = 64) -> Iterator[int]:
    """Every 64-bit integer within Hamming distance <=2 of `value` (2,081 total: itself, each
    single-bit flip, and each pair of bit flips) - a generator, not a materialized list, so a
    caller checking membership against a small target set (`set.isdisjoint` short-circuits on
    the first hit) never pays for the full 2,081 unless no match exists."""
    yield value
    for i in range(bits):
        yield value ^ (1 << i)
    for i in range(bits):
        for j in range(i + 1, bits):
            yield value ^ (1 << i) ^ (1 << j)


@dataclass(frozen=True)
class UnresolvedCoverageResult:
    unresolved_candidates_considered: int = 0
    matches_at_d0: int = 0
    matches_at_d_le_2: int = 0


def measure_unresolved_coverage(exemplar_hashes: Iterable[int]) -> UnresolvedCoverageResult:
    """
    The honest phase-2 estimate #508 asks for: of every currently-UNRESOLVED card carrying a
    CURRENT `artbox_phash`, how many would match the exemplar index at perceptual identity (d=0)
    and how many within the established narrowing radius (d<=2 - see `ArtboxPhashExemplar`'s own
    docstring on why this radius, not `local_phash.find_best_match`'s unrelated 20/5 cross-source
    cutoffs). `exemplar_hashes` is every seeded (or about-to-be-seeded, under `--dry-run`)
    `artbox_phash` value - deduplicated into a plain Python `set` once, then checked per-candidate
    rather than materializing every exemplar's own 2,081-hash expansion into one giant set: with
    tens of thousands of exemplars, expanding the exemplar side once would already cost tens of
    millions of entries; expanding each CANDIDATE on demand instead, with an early-exiting
    `isdisjoint` check against the small exemplar set, costs at most 2,081 checks per candidate
    and typically far fewer once a match is found (Hamming distance is symmetric, so "some
    exemplar is within 2 of this candidate" and "this candidate is within 2 of some exemplar" are
    the same question).
    """
    exemplar_hash_set = set(exemplar_hashes)
    # `values_list("artbox_phash", flat=True)` is typed `int | None` at the field level (mypy
    # can't see that `_current_artbox_evidence_queryset` already filters artbox_phash__isnull=
    # False) - the `if value is not None` filter is what narrows this list back to `list[int]`.
    candidate_hashes: list[int] = [
        value
        for value in _current_artbox_evidence_queryset()
        .filter(card__printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .values_list("artbox_phash", flat=True)
        if value is not None
    ]
    matches_at_d0 = sum(1 for candidate_hash in candidate_hashes if candidate_hash in exemplar_hash_set)
    matches_at_d_le_2 = sum(
        1
        for candidate_hash in candidate_hashes
        if not exemplar_hash_set.isdisjoint(_hamming_radius_le_2_variants(candidate_hash))
    )
    return UnresolvedCoverageResult(
        unresolved_candidates_considered=len(candidate_hashes),
        matches_at_d0=matches_at_d0,
        matches_at_d_le_2=matches_at_d_le_2,
    )


__all__ = [
    "JOIN_KEY_ANONYMOUS_ID",
    "JOIN_KEY_SEED_CONFIDENCE_FLOOR",
    "DEFAULT_BACKFILL_BATCH_SIZE",
    "human_resolution_seed_group_key",
    "join_key_seed_group_key",
    "ArtboxExemplarBackfillResult",
    "run_artbox_exemplar_backfill",
    "dry_run_candidate_exemplar_hashes",
    "UnresolvedCoverageResult",
    "measure_unresolved_coverage",
]
