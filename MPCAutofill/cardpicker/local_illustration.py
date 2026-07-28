"""
Stage D illustration deduction calculator (public issue #507, ``stage-d-illustration-v1``) — a
new calculator in the Stage D framework that uses the ``illustration_id`` field imported from
Scryfall (issue #506) to deduce printing identity. When an artist-OCR hit identifies the artist,
and that artist has printings associated with exactly one ``illustration_id`` for this card name,
we vote for all printings carrying that illustration.

Anonymous ID: ``stage-d-illustration-v1``
Source: ``VoteSource.DEDUCTION``
Base confidence: ``BASE_CONFIDENCE = 0.85``

Logic:
  1. Build an in-memory index ``(artist_pk, searchable_card_name) → {illustration_id → [printing_pk]}``
     from ``CanonicalCard``/``CanonicalPrintingMetadata`` pairs where ``illustration_id`` is
     non-null, using ``to_searchable`` normalization.
  2. For each eligible card, use ``match_artist`` to fuzzy-match the OCR-extracted artist name
     against the card's candidate artists.
  3. For each surviving artist, look up the illustration index by ``(artist_pk, searchable_name)``.
  4. Collect unique ``illustration_id`` values:
     - 0 → abstain (no vote, skip logged)
     - 1 → vote every printing of that illustration at ``BASE_CONFIDENCE``
     - N>1 → union of printings across the N illustrations (plain set union), one vote each at
       ``BASE_CONFIDENCE / N``

NO vote pooling across illustration siblings — each printing gets its own independent vote.
Confidence is currently informational-only (``resolve_vote_weight`` weights by source, never
confidence — see ``vote_consensus.py``); the base/N division must NOT be "fixed" into weight
math.

Wired into ``local_calculate_verdicts.py`` (management command) after the fallback calculator,
before slow-path routing. Reuses ``_eligible_cards_queryset`` from that module for the base
eligibility query, with additional single-faced and artist-ocr filters. Gate: ``verify_zero_resolutions``
after writes (human-backed consensus prevents machine-only resolution).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from django.db.models import Count, Max, Q, QuerySet

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_fallback import match_artist
from cardpicker.local_identify_printing_tags import CandidateNameIndex, generate_run_id
from cardpicker.models import (
    CanonicalCard,
    CanonicalPrintingMetadata,
    Card,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    ImageEvidence,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.search.sanitisation import to_searchable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Own anonymous_id — distinct from every other Stage D engine's identity for
# independent purge/re-run via ``purge_machine_votes --run-id``.
ILLUSTRATION_ANONYMOUS_ID = "stage-d-illustration-v1"

# Owner-ratified base confidence (issue #507 spec). Informational-only — does
# NOT flow into ``resolve_vote_weight``; the human-backed consensus gate
# prevents machine-only resolution regardless of confidence value.
BASE_CONFIDENCE = 0.85

# The two remaining knowledge-inventory constants, duplicated as literals from
# ``local_calculate_verdicts.py`` — same "avoid a hard import-time dependency
# between sibling engines over one constant" precedent.
RESOLUTION_FLOOR_DPI = 200
EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]

# Skip reasons
NO_EVIDENCE_SKIP_REASON = "no-evidence"
NO_ARTIST_OCR_SKIP_REASON = "no-artist-ocr"
SINGLE_FACED_ONLY_SKIP_REASON = "multi-faced-v1"
NO_CANDIDATE_MATCH_SKIP_REASON = "no-candidate-match"
NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON = "no-illustration-index-entry"
MULTIPLE_ILLUSTRATIONS_SKIP_REASON = "multiple-illustrations"

# Cards the join-key calculator already concluded have no confident hit —
# this calculator only considers those. Carried verbatim from
# ``local_calculate_verdicts.JOIN_KEY_NO_HIT_SKIP_REASONS``.
_JOIN_KEY_NO_HIT_SKIP_REASONS = frozenset(
    {
        "ambiguous",
        "no-text",
        "proxy-marker-veto",
        "border-mismatch",
        "frame-mismatch",
        "truncated-image",
        "copyright-year-mismatch",
        "unknown-set-code",
    }
)

# Rescannable skip reasons for this calculator — "no-evidence" is transient
# (a future extraction may land it).
RESCANNABLE_SKIP_REASONS = frozenset({NO_EVIDENCE_SKIP_REASON})


# ---------------------------------------------------------------------------
# In-memory illustration index
# ---------------------------------------------------------------------------


class IllustrationIndex:
    """
    In-memory index mapping ``(artist_pk, searchable_card_name) → {illustration_id_str → [printing_pk]}``.

    Built from ``CanonicalCard`` rows that have ``CanonicalPrintingMetadata.illustration_id``
    non-null. Also exposes:
      - ``artist_by_pk``: ``{card_pk → artist_name}`` for ``match_artist``
      - ``card_pk_to_artist_pk``: ``{canonical_card_pk → artist_pk}`` for post-match lookups

    CATALOG-WIDE, NOT BATCH-SCOPED — two full ``CanonicalCard`` scans (113,224 rows live). Never
    construct this directly from a Stage E hot path; go through
    ``_get_cached_illustration_index()`` below, which memoizes one instance per worker process
    behind a cheap version stamp (see that function and the section comment above it).
    """

    def __init__(self) -> None:
        # (artist_pk, searchable_name) → {illustration_id_str → [printing_pk]}
        self._index: dict[tuple[int, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        # artist_pk → artist_name (for match_artist's artist_by_pk parameter)
        self.artist_by_pk: dict[int, str] = {}
        # canonical_card_pk → artist_pk (for post-match lookup)
        self.card_pk_to_artist_pk: dict[int, int] = {}

        # No `.select_related(...)` here: chained BEFORE a `.values_list()` that already names
        # its own traversals (`artist__name`, `printing_metadata__illustration_id`), it is a
        # documented no-op - `values_list` builds its own JOINs from the traversal arguments and
        # discards the select_related plan entirely, so the call added zero rows to the SELECT and
        # zero saved queries. Removed rather than "made effective" (i.e. rather than dropping the
        # traversals and hydrating model instances instead): hydrating 113,224 CanonicalCard +
        # CanonicalArtist + CanonicalPrintingMetadata objects to read four columns off each is the
        # expensive direction, and `values_list` is exactly what `CandidateNameIndex` itself uses
        # for the same catalog-wide-index-build job.
        rows = CanonicalCard.objects.filter(printing_metadata__illustration_id__isnull=False).values_list(
            "pk",
            "name",
            "artist__pk",
            "artist__name",
            "printing_metadata__pk",
            "printing_metadata__illustration_id",
        )

        for card_pk, card_name, artist_pk, artist_name, printing_pk, illustration_id in rows:
            if artist_pk is None:
                continue  # type: ignore[unreachable]
            searchable_name = to_searchable(card_name)
            key = (artist_pk, searchable_name)
            illustration_str = str(illustration_id)
            self._index[key][illustration_str].append(printing_pk)

        # Populate artist_by_pk and card_pk_to_artist_pk from ALL canonical cards (not just
        # those with illustration metadata) so match_artist can identify artists even when
        # they have no illustration data yet. The illustration lookup (illustration_printings)
        # will still return empty for cards whose artists have no metadata, correctly producing
        # NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON.
        all_cards = CanonicalCard.objects.filter(artist__isnull=False).values_list("pk", "artist__pk", "artist__name")
        for card_pk, artist_pk, artist_name in all_cards:
            self.artist_by_pk[card_pk] = artist_name
            self.card_pk_to_artist_pk[card_pk] = artist_pk

    def illustration_printings(self, artist_pk: int, searchable_card_name: str) -> dict[str, list[int]]:
        """Return ``{illustration_id_str → [printing_pk]}`` for the given (artist, card_name) key."""
        return dict(self._index.get((artist_pk, searchable_card_name), {}))


# ---------------------------------------------------------------------------------------------
# LAZY, PER-WORKER-PROCESS ``IllustrationIndex`` CACHE — the same shape (and the same reason)
# ``local_calculate_verdicts._get_cached_candidate_name_index()`` already implements for
# ``CandidateNameIndex`` under issue #469, applied here because this calculator is invoked from
# ``stage_e_dispatch._run_stage_d`` ONCE PER 25-CARD MICRO-BATCH. ``IllustrationIndex.__init__``
# issues two catalog-wide ``CanonicalCard`` queries (113,224 rows live) — one filtered on
# ``printing_metadata__illustration_id``, one unfiltered over every card with an artist — and
# builds full-catalog dicts from both. Rebuilding that per micro-batch is O(catalog) work inside
# a conveyor whose whole contract (issues #458/#460) is O(batch), and it dominates the cost of a
# micro-batch that ends up with one eligible card, or none.
#
# Invalidation is a cheap version-stamp CHECK per call, not a write-time hook — the same
# "no soundness implication" trade ``_candidate_name_index_version_stamp`` documents. The stamp
# is ``(CanonicalCard max pk, CanonicalCard count, CanonicalPrintingMetadata max pk,
# CanonicalPrintingMetadata count, count of NON-NULL illustration_id)``. The first four catch any
# INSERT (a fresh max pk) or DELETE (count moves even when max pk doesn't) in either table; the
# fifth exists because this index's whole input is a column that is BACKFILLED IN PLACE —
# ``import_scryfall_printing_metadata`` populates ``illustration_id`` on rows that already exist,
# an UPDATE that moves neither max pk nor row count. Without that fifth term a worker process
# that built the index before an illustration backfill would serve a stale, under-populated index
# for its whole lifetime. ``illustration_id`` is ``db_index=True``, so the extra term is an
# index-only count, not a table scan.
#
# STILL NOT DETECTED (accepted, same reasoning as the CandidateNameIndex cache's own comment): an
# in-place rename of a ``CanonicalCard.name`` or ``CanonicalArtist.name``, or an in-place change
# of an ALREADY-NON-NULL ``illustration_id`` to a different value. Those are catalog-data edits,
# not routine, and a stale index in that narrow case re-derives the same deduction a fresh one
# would for every card whose row did not change. No vote-soundness exposure: this is a pure
# performance change.
# ---------------------------------------------------------------------------------------------

IllustrationIndexVersionStamp = tuple[int, int, int, int, int]

_illustration_index_cache: Optional[tuple[IllustrationIndexVersionStamp, "IllustrationIndex"]] = None


def _illustration_index_version_stamp() -> IllustrationIndexVersionStamp:
    """
    Cheap (index-only aggregates, not table scans) stamp used to detect a
    ``CanonicalCard``/``CanonicalPrintingMetadata`` write since the cached ``IllustrationIndex``
    was built — see this section's own comment above for the full invalidation-shape rationale,
    including why the non-null ``illustration_id`` count is a term and what is deliberately not
    detected.
    """
    canonical_card_agg = CanonicalCard.objects.aggregate(max_pk=Max("pk"), count=Count("pk"))
    printing_metadata_agg = CanonicalPrintingMetadata.objects.aggregate(max_pk=Max("pk"), count=Count("pk"))
    illustration_id_count = CanonicalPrintingMetadata.objects.filter(illustration_id__isnull=False).count()
    return (
        canonical_card_agg["max_pk"] or 0,
        canonical_card_agg["count"] or 0,
        printing_metadata_agg["max_pk"] or 0,
        printing_metadata_agg["count"] or 0,
        illustration_id_count,
    )


def _get_cached_illustration_index() -> "IllustrationIndex":
    """
    Returns the current worker process's cached ``IllustrationIndex``, building (or rebuilding, on
    a version-stamp mismatch) it exactly once per distinct stamp. Call this LAZILY — only once
    there is a card that actually needs an illustration lookup, never unconditionally at the top
    of a dispatch — so a micro-batch whose ``card_ids``-scoped eligible set is empty pays neither
    the index build nor even this function's own version-stamp query.
    """
    global _illustration_index_cache
    stamp = _illustration_index_version_stamp()
    if _illustration_index_cache is not None and _illustration_index_cache[0] == stamp:
        return _illustration_index_cache[1]
    index = IllustrationIndex()
    _illustration_index_cache = (stamp, index)
    return index


def reset_illustration_index_cache_for_tests() -> None:
    """
    TEST-ONLY hook, never called from any production code path — clears the module-level
    ``IllustrationIndex`` cache above, so a test asserting an exact construction COUNT starts from
    a known-empty cache instead of depending on Postgres's own incidental
    sequence-advance-across-rollback behaviour. Mirrors
    ``local_calculate_verdicts.reset_candidate_name_index_cache_for_tests``.
    """
    global _illustration_index_cache
    _illustration_index_cache = None


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IllustrationVerdict:
    """Pure result of one card's illustration deduction — no DB write yet."""

    card_id: int
    printing_pks: tuple[int, ...] = ()
    confidence: float = 0.0
    skip_reason: str = ""
    illustration_count: int = 0


# ---------------------------------------------------------------------------
# Calculator result
# ---------------------------------------------------------------------------


@dataclass
class IllustrationCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    multi_faced_skipped: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    already_voted: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Eligible-cards query
# ---------------------------------------------------------------------------


def _eligible_illustration_cards_queryset(
    join_key_voted_card_ids: Iterable[int],
    join_key_scanned_card_ids: Iterable[int],
    chunk_size: int = 500,
    card_ids: Optional[Iterable[int]] = None,
) -> "QuerySet[Card]":
    """
    Cards the join-key calculator already concluded have no confident hit, plus the same base
    eligibility filters as every other Stage D calculator (via a fresh queryset matching
    ``_eligible_cards_queryset``'s exact shape).

    Additional v1 constraints:
      - Current ``ImageEvidence`` with non-null ``artist_ocr_name`` (checked per-card in the
        loop, not in the queryset, since ImageEvidence is keyed by content_phash).
      - Single-faced layouts only (``layout_class`` empty or not set — single-faced cards have
        no DFC layout_class reading; multi-faced cards have ``layout_class`` in
        {"split", "transform", "meld", "double_faced"}).  Multi-faced cards are counted and
        skipped (logged), not errored — v1 scope limitation.

    ``card_ids`` (Stage E micro-batch scoping) mirrors
    ``local_calculate_verdicts._eligible_cards_queryset``'s own parameter exactly — a pure scope
    narrowing, applied to BOTH the outer ``Card`` queryset and the ``CardScanLog`` subquery below.
    ``None`` (BULK mode) leaves both unscoped, byte-identical to this function's pre-``card_ids``
    behaviour.
    """
    # Start with the same base query every Stage D calculator uses: unresolved, no
    # confirmed match, card_type=CARD, no own-vote, no non-rescannable scan-log,
    # resolution floor, excluded tags.
    non_rescannable_scanned = CardScanLog.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).exclude(
        skip_reason__in=RESCANNABLE_SKIP_REASONS
    )
    if card_ids is not None:
        # Issue #469 (Tron §8 gate finding, 2026-07-25), carried over to this calculator: CardScanLog
        # is 2,093,147 rows live and append-only, growing — when the caller has already narrowed the
        # outer Card queryset to `card_ids` (as `stage_e_dispatch._run_stage_d` does, 25 cards at a
        # time), this subquery must be scoped the same way rather than scanning the whole table.
        # Purely a cost narrowing, not a behaviour change: the resulting excluded-pk set is
        # equivalent for THIS caller either way, since a row this subquery would find outside
        # `card_ids` could never survive the outer queryset's own `.filter(pk__in=card_ids)`
        # (applied below) regardless. `card_ids is None` (BULK mode) leaves this exactly as it was
        # before this fix — unscoped over the whole table.
        non_rescannable_scanned = non_rescannable_scanned.filter(card_id__in=card_ids)

    queryset = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .exclude(printing_tags__anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned.values_list("card_id", flat=True))
        .exclude(Q(dpi__lt=RESOLUTION_FLOOR_DPI) & Q(dpi__isnull=False))
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
        # Join-key no-hit population — cards the join-key calculator found no
        # confident hit for (is_no_match vote OR a non-rescannable skip).
        .filter(Q(pk__in=join_key_voted_card_ids) | Q(pk__in=join_key_scanned_card_ids))
        .distinct()
        .select_related("source")
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


# ---------------------------------------------------------------------------
# Verdict calculation
# ---------------------------------------------------------------------------


def calculate_illustration_verdict(
    card_id: int,
    evidence: ImageEvidence,
    illustration_index: IllustrationIndex,
    candidates: list[Any],
    searchable_card_name: str,
) -> IllustrationVerdict:
    """
    Pure function — computes one card's illustration verdict from evidence and index state.

    Flow:
      1. ``match_artist(evidence.artist_ocr_name, candidates, illustration_index.artist_by_pk)``
         → surviving candidate pks.
      2. For each surviving candidate pk, get its artist_pk via
         ``illustration_index.card_pk_to_artist_pk``.
      3. Look up ``(artist_pk, searchable_card_name)`` in the illustration index → illustration_ids.
      4. 0 → abstain; 1 → full confidence; N>1 → spread.

    ``candidates`` is a list of objects with a ``.pk`` attribute (CanonicalCard pks) — either
    real ``CandidatePrinting`` objects from ``CandidateNameIndex.candidates_for()`` or lightweight
    adapter objects (see ``_CandidateAdapter`` below).
    """
    surviving_card_pks = match_artist(evidence.artist_ocr_name, candidates, illustration_index.artist_by_pk)

    if surviving_card_pks is None:
        return IllustrationVerdict(card_id=card_id, skip_reason=NO_CANDIDATE_MATCH_SKIP_REASON)

    # Collect unique illustration_ids across all surviving candidates' artists.
    illustration_printing_map: dict[str, list[int]] = {}
    for card_pk in surviving_card_pks:
        artist_pk = illustration_index.card_pk_to_artist_pk.get(card_pk)
        if artist_pk is None:
            continue
        illustrations = illustration_index.illustration_printings(artist_pk, searchable_card_name)
        for illustration_id_str, printing_pks in illustrations.items():
            if illustration_id_str not in illustration_printing_map:
                illustration_printing_map[illustration_id_str] = []
            illustration_printing_map[illustration_id_str].extend(printing_pks)

    if not illustration_printing_map:
        return IllustrationVerdict(card_id=card_id, skip_reason=NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON)

    n_illustrations = len(illustration_printing_map)

    if n_illustrations > 1:
        # N>1 illustrations: union of printings across all illustrations, each at BASE_CONFIDENCE/N.
        all_printing_pks: list[int] = []
        seen_pks: set[int] = set()
        for printing_pks in illustration_printing_map.values():
            for pk in printing_pks:
                if pk not in seen_pks:
                    seen_pks.add(pk)
                    all_printing_pks.append(pk)
        confidence = BASE_CONFIDENCE / n_illustrations
        return IllustrationVerdict(
            card_id=card_id,
            printing_pks=tuple(all_printing_pks),
            confidence=confidence,
            illustration_count=n_illustrations,
        )

    # Exactly 1 illustration: vote every printing at full BASE_CONFIDENCE.
    single_illustration_pks = next(iter(illustration_printing_map.values()))
    return IllustrationVerdict(
        card_id=card_id,
        printing_pks=tuple(single_illustration_pks),
        confidence=BASE_CONFIDENCE,
        illustration_count=1,
    )


# ---------------------------------------------------------------------------
# Candidate adapter for match_artist compatibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CandidateAdapter:
    """Lightweight adapter with just a ``.pk`` attribute — satisfies ``match_artist``'s interface."""

    pk: int


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_illustration_calculator(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> IllustrationCalculatorResult:
    """
    Batch runner for the illustration deduction calculator (issue #507).

    Mirrors ``run_fallback_calculator``'s shape: iterates eligible cards, computes verdicts,
    batches ``CardPrintingTag`` writes, calls ``resolve_and_persist_printing`` per touched card.
    ``dry_run=True`` (default) computes and counts everything without writing.
    ``card_ids`` is forwarded to the eligibility queryset for Stage E micro-batch scoping.
    """
    run_id = run_id or generate_run_id()
    result = IllustrationCalculatorResult(dry_run=dry_run, run_id=run_id)

    # Lazy, CACHED indexes — both are catalog-wide builds, resolved on first actual need below and
    # never unconditionally here, so a micro-batch whose eligible set turns out empty pays for
    # neither. See ``_get_cached_illustration_index`` above and
    # ``local_calculate_verdicts._get_cached_candidate_name_index`` (issue #469) for the shared
    # per-worker-process, version-stamped caching these local variables sit in front of; the local
    # variables themselves exist only so the version-stamp CHECK is paid once per invocation
    # rather than once per card, exactly as ``run_join_key_calculator``/``run_fallback_calculator``
    # do with their own ``index`` locals.
    illustration_index: Optional[IllustrationIndex] = None
    candidate_name_index: Optional[CandidateNameIndex] = None

    votes_batch: list[CardPrintingTag] = []
    scan_log_batch: list[CardScanLog] = []
    touched_card_ids: list[int] = []

    # Pre-compute join-key no-hit populations for eligibility filtering.
    from cardpicker.local_calculate_verdicts import (
        JOIN_KEY_ANONYMOUS_ID,
        JOIN_KEY_NO_HIT_SKIP_REASONS,
        _get_cached_candidate_name_index,
    )

    # Deliberately NOT wrapped in `list(...)`: these stay lazy querysets so Django compiles them
    # into SQL subqueries of the `Q(pk__in=...) | Q(pk__in=...)` filter below, evaluated inside the
    # one eligibility query and narrowed by its own `card_ids` scope. Materializing them instead
    # pulled every join-key no-match vote and every join-key no-hit CardScanLog row (2,093,147 rows
    # live, append-only) into this process's memory on EVERY micro-batch, before any card_ids
    # scoping applied. Matches `local_calculate_verdicts._fallback_eligible_cards_queryset`, which
    # has always kept the identical pair lazy.
    join_key_no_match_card_ids = CardPrintingTag.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
    ).values_list("card_id", flat=True)
    join_key_no_hit_scanned_card_ids = CardScanLog.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS
    ).values_list("card_id", flat=True)

    queryset = _eligible_illustration_cards_queryset(
        join_key_voted_card_ids=join_key_no_match_card_ids,
        join_key_scanned_card_ids=join_key_no_hit_scanned_card_ids,
        card_ids=card_ids,
    )

    multi_faced_skipped = 0

    for card in queryset.iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash to key ImageEvidence lookup

        # Lazy illustration index — resolved once we know there are eligible cards, from the
        # per-worker-process cache (NOT a fresh catalog-wide build per micro-batch).
        if illustration_index is None:
            illustration_index = _get_cached_illustration_index()

        evidence = (
            current_evidence_queryset(card)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )

        if evidence is None:
            result.skip_counts[NO_EVIDENCE_SKIP_REASON] = result.skip_counts.get(NO_EVIDENCE_SKIP_REASON, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=NO_EVIDENCE_SKIP_REASON,
                    )
                )
            continue

        # v1 constraint: single-faced only. A multi-faced card has a non-empty
        # layout_class from OCR; single-faced cards leave it empty.
        if evidence.layout_class and evidence.layout_class.strip():
            multi_faced_skipped += 1
            result.skip_counts[SINGLE_FACED_ONLY_SKIP_REASON] = (
                result.skip_counts.get(SINGLE_FACED_ONLY_SKIP_REASON, 0) + 1
            )
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=SINGLE_FACED_ONLY_SKIP_REASON,
                    )
                )
            continue

        if not evidence.artist_ocr_name or not evidence.artist_ocr_name.strip():
            result.skip_counts[NO_ARTIST_OCR_SKIP_REASON] = result.skip_counts.get(NO_ARTIST_OCR_SKIP_REASON, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=NO_ARTIST_OCR_SKIP_REASON,
                    )
                )
            continue

        result.cards_considered += 1

        # Lazy CandidateNameIndex — resolved through `local_calculate_verdicts`' own
        # per-worker-process cache (issue #469), the same call `run_join_key_calculator`/
        # `run_fallback_calculator` make. This used to call `CandidateNameIndex()` directly while
        # claiming in a comment to use "the same cached pattern" — it did not: it bypassed the
        # cache entirely and paid a fresh 113,224-row, 1.48s catalog scan on every micro-batch
        # that had at least one card with artist OCR.
        if candidate_name_index is None:
            candidate_name_index = _get_cached_candidate_name_index()

        # Build candidate list for match_artist — adapter objects with .pk.
        raw_candidates = candidate_name_index.candidates_for(card.name)
        candidates = [_CandidateAdapter(pk=c.pk) for c in raw_candidates]

        searchable_card_name = to_searchable(card.name)

        verdict = calculate_illustration_verdict(
            card_id=card.pk,
            evidence=evidence,
            illustration_index=illustration_index,
            candidates=candidates,
            searchable_card_name=searchable_card_name,
        )

        if verdict.skip_reason:
            result.skip_counts[verdict.skip_reason] = result.skip_counts.get(verdict.skip_reason, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=verdict.skip_reason,
                    )
                )
            continue

        # Vote to cast: one CardPrintingTag per printing in the verdict.
        n_printings = len(verdict.printing_pks)
        result.votes_would_cast += n_printings

        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "card_id": card.pk,
                    "illustration_count": verdict.illustration_count,
                    "confidence": verdict.confidence,
                    "printing_pks": list(verdict.printing_pks),
                }
            )

        if not dry_run:
            for printing_pk in verdict.printing_pks:
                votes_batch.append(
                    CardPrintingTag(
                        card_id=card.pk,
                        printing_id=printing_pk,
                        is_no_match=False,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        source=VoteSource.DEDUCTION,
                        confidence=verdict.confidence,
                        run_id=run_id,
                    )
                )
            touched_card_ids.append(card.pk)

    result.multi_faced_skipped = multi_faced_skipped

    if not dry_run:
        from cardpicker.local_calculate_verdicts import (
            _purge_and_write_printing_tag_votes,
            _split_new_printing_tag_votes,
        )

        # ORDER MATTERS — split/count FIRST, purge SECOND, purge+insert inside ONE transaction.
        # See `_purge_and_write_printing_tag_votes`' own docstring for both halves: running the
        # purge first deleted exactly the rows `_split_new_printing_tag_votes` looks for (so
        # `already_voted` was structurally 0 forever — the "zero forever would suggest the guard
        # itself is dead code" case
        # `stage_e_dispatch.DispatchOutcome.stage_d_illustration_already_voted` documents), and an
        # untransacted DELETE-then-INSERT loses votes outright if the process is killed between
        # the two, which this project's operator does deliberately, mid-flight.
        new_votes, result.already_voted = _split_new_printing_tag_votes(votes_batch)
        _purge_and_write_printing_tag_votes(ILLUSTRATION_ANONYMOUS_ID, new_votes)
        if scan_log_batch:
            CardScanLog.objects.bulk_create(scan_log_batch)
        for touched_card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_printing(touched_card)

        result.votes_written = len(new_votes)

    return result
