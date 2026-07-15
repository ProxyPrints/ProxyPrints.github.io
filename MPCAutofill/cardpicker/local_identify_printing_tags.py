"""
Local (zero-API-cost) printing-identification backfill pilot: two independent engines that
vote on a card's printing by actually looking at its image, rather than deducing it from
pre-existing structured data (see cardpicker.deductive_backfill, the sibling this extends).
Same non-negotiable principle: a vote here is always just a vote (VoteSource.OCR), never a
direct resolve - the human-backed gate in vote_consensus.resolve_weighted_consensus still
applies, at any volume. See docs/features/printing-tags.md's Stage 8 section for the full
design writeup (environment, engine details, pilot discipline).

Targets the residual pool deductive backfill's D1/D2 tiers can't reach: names that match MORE
THAN ONE CanonicalCard row (deductive backfill only resolves the exactly-one-match case
directly, or the expansion_hint-narrows-to-one case) - visual disambiguation (a legible
collector line, or a matching art crop) is exactly the signal that's missing there. Selection
also revisits single-candidate names deductive backfill's own Scryfall printings_count
cross-check rejected, since those are still unresolved despite one local match.
"""

import collections
import functools
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable, Literal, Optional

import requests
from PIL import Image

from django.conf import settings
from django.db.models import QuerySet

from cardpicker import local_fallback, local_ocr, local_phash
from cardpicker.local_fallback import (
    FALLBACK_ANONYMOUS_ID,
    FALLBACK_CONFIDENCE_MULTI_EVIDENCE,
    FALLBACK_CONFIDENCE_SINGLE_EVIDENCE,
)
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    CardTagVote,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.search.sanitisation import to_searchable
from cardpicker.sources.source_types import SourceTypeChoices

logger = logging.getLogger(__name__)

OCR_ANONYMOUS_ID = "local-ocr-v1"
PHASH_ANONYMOUS_ID = "local-phash-v1"
# cardpicker.deductive_backfill.DEDUCTIVE_BACKFILL_ANONYMOUS_ID, duplicated as a literal
# rather than imported to avoid a hard import-time dependency between the two backfill
# modules over one constant string.
DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"

OCR_CONFIDENCE_BOTH = 0.85  # set code + collector number both parsed and matched
OCR_CONFIDENCE_COLLECTOR_ONLY = 0.75  # pre-M15 cards: no set code printed on the collector line
PHASH_CONFIDENCE = 0.8
# Basic lands and staple commons can carry hundreds of printings (Forest alone: 944 in the
# live pilot's own eligible pool, confirmed live 2026-07-15) - and "multi-candidate names
# first" ordering puts exactly those names first, meaning an uncapped pilot run would try to
# fetch+hash hundreds of Scryfall art crops for the very first cards it processes. 25% of the
# eligible pool (43,094/171,878, confirmed live) exceeds this cap - capped, not tuned; a name
# this common needs a different strategy entirely (a name-level index, not per-run fetching),
# out of scope for this pilot.
PHASH_MAX_CANDIDATES = 12

# Checkpointing (Stage 8 pre-scale program item 2, see run_pilot): flush every this many cards
# processed. Deliberately much smaller than deductive_backfill's batch_size=2000 - that pipeline
# is pure DB writes with no per-card network fetch/OCR/phash cost, so losing an un-flushed batch
# to a crash is cheap there; here each card costs a real image fetch plus OCR/phash CPU work, so
# a smaller batch bounds how much re-fetchable-but-not-yet-durable work a kill can waste.
DEFAULT_BATCH_SIZE = 25

# cardpicker.reason_tags.NO_MATCH_REASON_TAGS - a resolved custom-art/non-english tag already
# tells us the PRINCIPLE's precondition (an authentic depiction of a real printing) is false,
# same exclusion rationale as cardpicker.deductive_backfill's "Custom" tag check, just against
# this taxonomy's tag names instead of the filename-inferred one.
EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]

Engine = Literal["ocr", "phash"]

_NICE_SLEEP_SECONDS = 0.05


@dataclass(frozen=True)
class CandidatePrinting:
    pk: int
    expansion_code: str  # lowercase
    collector_number: str


class CandidateNameIndex:
    """
    Like cardpicker.deductive_backfill.CanonicalNameIndex, but keyed on the same to_searchable
    name normalisation and carrying (expansion_code, collector_number) per candidate instead of
    just a printings_count - both engines here need to check a parsed/matched value against a
    candidate's actual identity, not just count how many candidates exist. Built once, reused
    across the whole scan (one query over CanonicalCard's 113k+ rows, not one per card).
    """

    def __init__(self) -> None:
        by_name: dict[str, list[CandidatePrinting]] = collections.defaultdict(list)
        rows = CanonicalCard.objects.select_related("expansion").values_list(
            "pk", "name", "expansion__code", "collector_number"
        )
        for pk, name, expansion_code, collector_number in rows:
            by_name[to_searchable(name)].append(
                CandidatePrinting(pk=pk, expansion_code=expansion_code.lower(), collector_number=collector_number)
            )
        self._by_name = dict(by_name)

    def candidates_for(self, name: str) -> list[CandidatePrinting]:
        return self._by_name.get(to_searchable(name), [])


@dataclass(frozen=True)
class SelectedCard:
    card: Card
    candidates: list[CandidatePrinting]


def _eligible_base_queryset(anonymous_id: str, exclude_source_pks: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """
    unresolved, no confirmed indexing match, no existing vote from this engine's own
    anonymous_id (the idempotence/checkpoint mechanism - see module docstring and
    cardpicker.deductive_backfill's identical pattern), not already covered by the deductive
    backfill (which is provably exact by construction where it applies - this pilot's engines
    are weaker, lower-confidence signal and shouldn't pile onto a card that already has a
    stronger deduction), and no resolved custom-art/non-english tag.

    exclude_source_pks is a purely mechanical, caller-supplied deprioritization knob (no source
    pk is ever hardcoded here) - see select_candidates and the management command's
    --exclude-sources-ocr/--exclude-sources-phash flags.
    """
    queryset = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, canonical_card__isnull=True)
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .exclude(printing_tags__anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
        .distinct()
        .select_related("source")
    )
    if exclude_source_pks:
        queryset = queryset.exclude(source_id__in=exclude_source_pks)
    return queryset


def select_candidates(
    engine: Engine, index: Optional[CandidateNameIndex] = None, exclude_source_pks: Optional[Iterable[int]] = None
) -> list[SelectedCard]:
    """Multi-candidate names first (the cases deductive backfill's D1/D2 tiers can't reach
    without an expansion_hint), then single-candidate names, in `Card.pk` order within each
    group for determinism."""
    index = index or CandidateNameIndex()
    anonymous_id = OCR_ANONYMOUS_ID if engine == "ocr" else PHASH_ANONYMOUS_ID
    multi: list[SelectedCard] = []
    single: list[SelectedCard] = []
    for card in (
        _eligible_base_queryset(anonymous_id, exclude_source_pks)
        .only("pk", "name", "identifier", "source_id")
        .order_by("pk")
        .iterator(chunk_size=5000)
    ):
        candidates = index.candidates_for(card.name)
        if not candidates:
            continue
        (multi if len(candidates) > 1 else single).append(SelectedCard(card=card, candidates=candidates))
    return multi + single


# The empirically-validated OCR resolution floor (pre-scale program item 6/3c, 2026-07-15):
# a real 6-way dpi sweep (100/150/200/250/300/native) against the same 30-card sample used to
# validate the tightened crop box (see local_ocr.DEFAULT_CROP_BOX's comment) showed dpi<=150
# genuinely degrades OCR yield (3/30, 7/30 vs. an 8/30 native-resolution baseline), while
# dpi>=200 matches or EXCEEDS the native baseline (12/30, 10/30, 9/30) despite a 2-4x smaller
# payload - smaller re-encoded JPEGs plausibly render small text more cleanly than a full-res
# original in some cases, though 30 cards is too small a sample to fully explain that. 250 is a
# safety margin above the empirically-best 200, not the raw optimum - hedges against small-
# sample noise while still keeping most of the bandwidth win (mean 728KB vs. 1.84MB native, a
# 2.5x reduction). PILOT-ONLY: this constant is local_identify_printing_tags' own default, not
# shared with frontend/src/features/pdf/ or .../download/, which need full print resolution by
# design and are untouched by this change.
DEFAULT_FETCH_DPI: Optional[int] = 250


def get_worker_image_url(card: Card, dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional[str]:
    """
    The card's image via the image CDN Worker's "full" tier (image-cdn/, docs/features/image-cdn.md)
    - the same route the PDF export path uses, but at a resolution capped via `dpi` (see
    DEFAULT_FETCH_DPI) rather than the print-quality original PDF export needs. Google Drive
    sources only, matching that Worker's current scope (frontend/src/common/image.ts's
    getWorkerImageURL has the identical restriction) - any other source type returns None,
    counted by the caller as an "unsupported-source-type" skip.
    """
    if card.get_source_type_choices() != SourceTypeChoices.GOOGLE_DRIVE:
        return None
    dpi_param = f"&dpi={dpi}" if dpi is not None else ""
    return f"{settings.IMAGE_WORKER_URL}/images/google_drive/full/{card.identifier}.jpg?jpgQuality=100{dpi_param}"


def fetch_card_image(card: Card, dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional["Image.Image"]:
    url = get_worker_image_url(card, dpi)
    if url is None:
        return None
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception:
        logger.exception("Failed to fetch image for card %s", card.identifier)
        return None


@dataclass(frozen=True)
class EngineVote:
    engine: Engine
    printing_pk: int
    confidence: float
    detail: str  # raw OCR text, or a phash distance/margin summary - for the audit checkpoint


@dataclass
class CardOutcome:
    card_id: int
    ocr_vote: Optional[EngineVote] = None
    ocr_skip_reason: str = ""
    phash_vote: Optional[EngineVote] = None
    phash_skip_reason: str = ""
    disagreement: bool = False
    fallback_vote: Optional[EngineVote] = None
    fallback_skip_reason: str = ""
    fallback_evidence_types: list[str] = field(default_factory=list)
    border_color: Optional[str] = None
    frame_reading_attempted: bool = False
    frame_class: Optional[str] = None
    frame_mismatch: bool = False  # printing vote withheld: frame reading contradicts the match
    image_fetched: bool = False  # distinguishes "no image at all" from "image present but a
    # reading came back ambiguous/None" for the abstain counters below (bleed_class is None in
    # both cases - this field is what lets the caller tell them apart, same convention as
    # frame_reading_attempted's identical purpose for the frame abstain counter).
    # bleed classification (addendum item 7) - now computed FIRST, ahead of everything else in
    # _compute_card, per the owner-directed reordering (2026-07-15): every other fixed-fraction
    # crop box in this card's pipeline (OCR collector line, phash art crop, illus-anchor crop,
    # symbol strip, border-sample bands) gets normalized against this reading via
    # local_fallback.normalize_crop_box, so it has to be known before any of them run, not after.
    bleed_class: Optional[str] = None


@dataclass(frozen=True)
class CardComputeResult:
    """The output of _compute_card - everything about a card that can be computed independent of
    every OTHER card's state (no DB writes, no shared counters) - see _compute_card's own
    docstring for why this split exists (pre-scale program item 3d, pipeline concurrency)."""

    card_id: int
    fetch_attempted: bool  # counts against --fetch-budget - see run_pilot's chunked loop
    outcome: CardOutcome


@dataclass
class OcrCardResult:
    vote: Optional[EngineVote] = None
    skip_reason: str = ""
    raw_texts: list[str] = field(default_factory=list)
    # frame-style signal (docs/features/printing-tags.md's Stage 8 "frame votes" addition): did
    # ANY preprocessing variant successfully extract a collector number, independent of whether
    # it went on to validate against a real candidate? A legible collector-line format is
    # itself evidence of a post-2003 frame, whether or not the specific number matched.
    parsed_a_collector_number: bool = False


def run_ocr_for_card(
    selected: SelectedCard,
    image: Optional["Image.Image"],
    crop_box: tuple[float, float, float, float] = local_ocr.DEFAULT_CROP_BOX,
    bleed_class: Optional[str] = None,
) -> OcrCardResult:
    """`bleed_class` (from local_fallback.classify_bleed_edge, run once per card ahead of
    everything else - see run_pilot) remaps `crop_box` via local_fallback.normalize_crop_box for
    a trimmed image; a no-op otherwise."""
    if image is None:
        return OcrCardResult(skip_reason="unfetchable-image")

    cropped = local_ocr.crop_collector_line(image, local_fallback.normalize_crop_box(crop_box, bleed_class))
    variants = local_ocr.preprocess_variants(cropped)

    result = OcrCardResult()
    for variant in variants:
        raw_text = local_ocr.run_tesseract(variant)
        result.raw_texts.append(raw_text)
        parsed = local_ocr.parse_collector_line(raw_text)
        if parsed.collector_number is not None:
            result.parsed_a_collector_number = True
        matched, reason = local_ocr.validate_against_candidates(parsed, selected.candidates)
        if matched is not None:
            confidence = OCR_CONFIDENCE_BOTH if parsed.set_code is not None else OCR_CONFIDENCE_COLLECTOR_ONLY
            result.vote = EngineVote(
                engine="ocr", printing_pk=matched.pk, confidence=confidence, detail=raw_text.strip()
            )
            return result
    result.skip_reason = "parsed-but-no-match" if result.parsed_a_collector_number else "no-text"
    return result


def run_phash_for_card(
    selected: SelectedCard,
    image: Optional["Image.Image"],
    distance_threshold: int = local_phash.DEFAULT_DISTANCE_THRESHOLD,
    margin: int = local_phash.DEFAULT_MARGIN,
    max_candidates: int = PHASH_MAX_CANDIDATES,
    bleed_class: Optional[str] = None,
) -> tuple[Optional[EngineVote], str]:
    """`bleed_class` (from local_fallback.classify_bleed_edge, run once per card ahead of
    everything else - see run_pilot) remaps local_phash.ART_CROP_BOX via
    local_fallback.normalize_crop_box for a trimmed image; a no-op otherwise."""
    # checked first, before any candidate-hash fetch - see PHASH_MAX_CANDIDATES' comment for
    # why this matters (basic lands/staple commons can have hundreds of candidates)
    if len(selected.candidates) > max_candidates:
        return None, "too-many-candidates"

    if image is None:
        return None, "unfetchable-image"

    card_hash = local_phash.compute_card_art_hash(image, bleed_class)

    canonicals_by_pk = {c.pk: c for c in CanonicalCard.objects.filter(pk__in=[c.pk for c in selected.candidates])}
    candidates_with_hashes: list[tuple[CandidatePrinting, int]] = []
    for candidate in selected.candidates:
        canonical = canonicals_by_pk.get(candidate.pk)
        if canonical is None:
            continue
        candidate_hash = local_phash.get_or_compute_canonical_hash(canonical)
        if candidate_hash is not None:
            candidates_with_hashes.append((candidate, candidate_hash))

    match, reason = local_phash.find_best_match(card_hash, candidates_with_hashes, distance_threshold, margin)
    if match is None:
        return None, reason
    detail = f"distance={match.distance} runner_up={match.runner_up_distance}"
    return EngineVote(engine="phash", printing_pk=match.candidate.pk, confidence=PHASH_CONFIDENCE, detail=detail), ""


# Default concurrent worker count (pre-scale program item 3d, 2026-07-15): measured, not
# assumed, against this box's real constraint - 2 CPU cores total, shared with 5 live production
# containers (Django/nginx/Postgres/Elasticsearch/worker). A live-contention test (10 real
# candidate cards, dry, fetch+OCR+phash only) compared this box's live API latency under three
# conditions: idle (79.8ms mean/94.7ms p95), the CURRENT single-threaded pilot running (88.7ms/
# 126.1ms), and a 2-worker concurrent pool running (93.9ms/135.7ms) - only ~5ms extra mean
# latency for 2 workers over the ALREADY-EXISTING single-threaded impact, while wall clock for
# the same 10 cards dropped from 13.42s to 6.34s (near-ideal ~2.1x speedup matching the 2-core
# count - tesseract's subprocess-based OCR genuinely parallelizes here, the GIL is released
# during the subprocess wait). 2 matches the core count exactly; more workers would only add
# contention without real additional parallelism on this box.
DEFAULT_WORKERS = 2


def _compute_card(
    selected: SelectedCard,
    ocr_selected_ids: set[int],
    phash_selected_ids: set[int],
    already_fallback_covered: set[int],
    ocr_crop_box: tuple[float, float, float, float],
    phash_distance_threshold: int,
    phash_margin: int,
    phash_max_candidates: int,
    fetch_dpi: Optional[int],
) -> CardComputeResult:
    """The parallelizable half of a card's work (pre-scale program item 3d): fetch + every
    read-only heuristic reading (OCR, phash, border/frame/bleed classification, pass-2
    fallback) - no DB writes, no shared/nonlocal state, safe to run concurrently across cards
    via ThreadPoolExecutor.map() (see run_pilot's chunked loop). Deliberately does NOT include
    the ground-truth-preferred attribute override or the frame-mismatch consistency check -
    both of those are tightly coupled to the write/consensus decision (which candidate_vote
    ultimately gets accepted) and stay in run_pilot's own sequential loop, same as before this
    split.

    Bleed classification runs FIRST, ahead of everything else (owner-directed reordering,
    2026-07-15) - it's the one reading every other fixed-fraction crop box in this function
    needs (via local_fallback.normalize_crop_box) to know whether to correct itself for a
    trimmed image, so it has to be available before OCR/phash/illus-anchor/border/symbol crop.
    """
    card_id = selected.card.pk
    outcome = CardOutcome(card_id=card_id)
    fetch_attempted = get_worker_image_url(selected.card, fetch_dpi) is not None
    image = fetch_card_image(selected.card, fetch_dpi)
    ocr_raw_texts: list[str] = []

    outcome.image_fetched = image is not None
    bleed_class = local_fallback.classify_bleed_edge(image) if image is not None else None
    outcome.bleed_class = bleed_class

    if card_id in ocr_selected_ids:
        ocr_result = run_ocr_for_card(selected, image, ocr_crop_box, bleed_class)
        outcome.ocr_vote, outcome.ocr_skip_reason = ocr_result.vote, ocr_result.skip_reason
        ocr_raw_texts = ocr_result.raw_texts
    if card_id in phash_selected_ids:
        outcome.phash_vote, outcome.phash_skip_reason = run_phash_for_card(
            selected, image, phash_distance_threshold, phash_margin, phash_max_candidates, bleed_class
        )

    if outcome.ocr_vote is not None and outcome.phash_vote is not None:
        if outcome.ocr_vote.printing_pk != outcome.phash_vote.printing_pk:
            outcome.disagreement = True

    if image is not None:
        outcome.border_color = local_fallback.classify_border_color(image, bleed_class)
        illus_anchor_fired, _artist_name = local_fallback.detect_illus_anchor(image, ocr_raw_texts, bleed_class)
        parsed_a_collector_number = card_id in ocr_selected_ids and bool(
            outcome.ocr_vote is not None or outcome.ocr_skip_reason == "parsed-but-no-match"
        )
        outcome.frame_reading_attempted = True
        outcome.frame_class = local_fallback.classify_frame_style(parsed_a_collector_number, illus_anchor_fired)

    pass_1_accepted = (outcome.ocr_vote is not None or outcome.phash_vote is not None) and not outcome.disagreement
    if not pass_1_accepted and card_id not in already_fallback_covered and image is not None:
        fallback_outcome = local_fallback.run_fallback_for_card(selected, image, ocr_raw_texts, bleed_class)
        outcome.fallback_skip_reason = fallback_outcome.skip_reason
        outcome.fallback_evidence_types = fallback_outcome.evidence_types_used
        if fallback_outcome.printing_pk is not None:
            confidence = (
                FALLBACK_CONFIDENCE_MULTI_EVIDENCE
                if len(fallback_outcome.evidence_types_used) >= 2
                else FALLBACK_CONFIDENCE_SINGLE_EVIDENCE
            )
            outcome.fallback_vote = EngineVote(
                engine="phash",  # placeholder Engine literal - fallback isn't a selectable --engine
                printing_pk=fallback_outcome.printing_pk,
                confidence=confidence,
                detail=",".join(fallback_outcome.evidence_types_used),
            )

    return CardComputeResult(card_id=card_id, fetch_attempted=fetch_attempted, outcome=outcome)


@dataclass
class PilotResult:
    engine: str
    dry_run: bool = False
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    disagreements: list[dict[str, object]] = field(default_factory=list)
    audit: list[dict[str, object]] = field(default_factory=list)  # per-card checkpoint detail
    gate_violations: list[int] = field(default_factory=list)
    fetch_budget_exhausted: bool = False
    cards_not_attempted_this_invocation: int = 0


@dataclass
class AttributeReport:
    """Side-effect votes cast alongside printing identification, and census-only findings that
    never write anything (docs/features/printing-tags.md's Stage 8 "border evidence does
    double duty" and "frame votes" additions)."""

    border_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    frame_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    frame_abstain_count: int = 0
    frame_mismatches: list[dict[str, object]] = field(default_factory=list)  # up to 10, for the report
    # of the totals above, how many came from the matched printing's own CanonicalPrintingMetadata
    # (ground truth) rather than this module's pixel/OCR heuristic - see run_pilot's
    # ground-truth-preferred wiring.
    border_ground_truth_count: int = 0
    frame_ground_truth_count: int = 0
    # addendum item 7 (2026-07-15): bleed-edge classification, votes on the pre-existing
    # `appropriate-bleed` SENSITIVE tag (local_fallback.classify_bleed_edge/cast_bleed_edge_vote).
    # No ground-truth counterpart - unlike border/frame, there's no Scryfall field encoding this.
    bleed_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    bleed_abstain_count: int = 0


def run_pilot(
    engine: Literal["ocr", "phash", "both"] = "both",
    limit: int = 300,
    dry_run: bool = False,
    nice: bool = True,
    ocr_crop_box: tuple[float, float, float, float] = local_ocr.DEFAULT_CROP_BOX,
    phash_distance_threshold: int = local_phash.DEFAULT_DISTANCE_THRESHOLD,
    phash_margin: int = local_phash.DEFAULT_MARGIN,
    phash_max_candidates: int = PHASH_MAX_CANDIDATES,
    exclude_source_pks_by_engine: Optional[dict[Engine, list[int]]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_every: int = 50,
    fetch_budget: Optional[int] = None,
    fetch_dpi: Optional[int] = DEFAULT_FETCH_DPI,
    workers: int = DEFAULT_WORKERS,
) -> tuple[dict[str, PilotResult], AttributeReport]:
    if nice:
        try:
            os.nice(15)
        except (AttributeError, PermissionError, OSError):
            logger.warning("os.nice unavailable in this environment - --nice throttling is CPU-yield-only")

    index = CandidateNameIndex()
    engines_to_run: list[Engine] = ["ocr", "phash"] if engine == "both" else [engine]
    results: dict[str, PilotResult] = {e: PilotResult(engine=e, dry_run=dry_run) for e in engines_to_run}
    results["fallback"] = PilotResult(engine="fallback", dry_run=dry_run)
    attributes = AttributeReport()
    exclude_source_pks_by_engine = exclude_source_pks_by_engine or {}
    selected_by_engine = {
        e: select_candidates(e, index, exclude_source_pks_by_engine.get(e))[:limit] for e in engines_to_run
    }

    # when both engines run, process the union of cards either engine selected so agreement/
    # disagreement can be evaluated per card - each engine still only ever votes on a card it
    # itself selected (its own eligibility/exclusion rules still apply independently).
    all_selected_by_card_id: dict[int, SelectedCard] = {}
    for e in engines_to_run:
        for s in selected_by_engine[e]:
            all_selected_by_card_id.setdefault(s.card.pk, s)

    # fallback's own idempotence check - it has no selection query/anonymous_id exclusion of
    # its own (it rides on whichever cards ocr/phash already selected), so a card already
    # covered by a prior fallback run is excluded here instead.
    already_fallback_covered = set(
        CardPrintingTag.objects.filter(
            card_id__in=all_selected_by_card_id.keys(), anonymous_id=FALLBACK_ANONYMOUS_ID
        ).values_list("card_id", flat=True)
    )

    ocr_selected_ids = {s.card.pk for s in selected_by_engine.get("ocr", [])}
    phash_selected_ids = {s.card.pk for s in selected_by_engine.get("phash", [])}

    # Checkpointing (Stage 8 pre-scale program item 2): a multi-day unattended run must survive
    # a kill without losing everything accumulated since the last flush. Matches
    # cardpicker.deductive_backfill.run_backfill's periodic-flush pattern (a plain re-invocation
    # resumes cleanly with no separate checkpoint file, since select_candidates already excludes
    # any card with an existing vote from this engine's own anonymous_id), but deliberately
    # DIVERGES from that precedent on ONE point: the gate check runs after every flush here, not
    # once at the very end. deductive_backfill's votes are provably exact by construction (a gate
    # violation there is structurally impossible), so a single end-of-run check is just belt-and-
    # suspenders; this pilot's OCR/phash/fallback votes are explicitly weaker, lower-confidence
    # signal (module docstring) where a real violation is more plausible, and a kill is an
    # EXPECTED event for a multi-day run (the whole reason this checkpointing exists) - a
    # violation in an already-flushed batch must not sit undetected in the DB indefinitely just
    # because the process died before reaching the final check.
    written_card_ids: list[int] = []
    all_gate_violations: list[int] = []
    votes_batch: list[CardPrintingTag] = []
    tag_votes_batch: list[CardTagVote] = []
    batch_written_card_ids: list[int] = []

    def flush() -> None:
        nonlocal votes_batch, tag_votes_batch, batch_written_card_ids
        if dry_run:
            votes_batch, tag_votes_batch, batch_written_card_ids = [], [], []
            return
        if tag_votes_batch:
            CardTagVote.objects.bulk_create(tag_votes_batch, ignore_conflicts=True)
        if votes_batch:
            CardPrintingTag.objects.bulk_create(votes_batch)
        if batch_written_card_ids:
            all_gate_violations.extend(verify_zero_resolutions(batch_written_card_ids))
        votes_batch, tag_votes_batch, batch_written_card_ids = [], [], []

    # Fetch budget (pre-scale program item 3b): every image fetch is one request against the
    # image CDN Worker, which shares its daily request quota with live site traffic
    # (docs/features/image-cdn.md) - an unattended multi-hour pilot slice must not be able to
    # consume an unbounded share of that shared budget. Counts only requests actually sent
    # (get_worker_image_url returning None - an unsupported source type - never reaches the
    # network at all, so it doesn't count). On exhaustion, the run stops cleanly: whatever's
    # already been flushed stays committed, and every card not yet reached is left completely
    # untouched (no vote, no outcome recorded) so the next invocation's selection query picks
    # them up fresh with no special resume handling needed.
    fetches_made = 0
    budget_exhausted = False
    cards_attempted = 0

    # Pipeline concurrency (pre-scale program item 3d, 2026-07-15): the per-card COMPUTE work
    # (fetch, OCR, phash, border/frame/bleed classification, pass-2 fallback - everything
    # _compute_card does) is independent per card and safe to run concurrently; the per-card
    # WRITE work below (votes_batch/tag_votes_batch staging, disagreement bookkeeping,
    # ground-truth-preferred attribute overrides, the frame-mismatch consistency check) stays
    # single-threaded and in selection order, completely UNCHANGED from before this split - only
    # where its input comes from is different (a CardComputeResult instead of being computed
    # inline). Chunked at `batch_size` granularity, reusing the SAME boundary as checkpointing's
    # flush/gate-check (Stage 8 pre-scale program item 2) rather than introducing a second
    # batching concept - each chunk's compute pool completes before that chunk's writes are
    # staged and flushed, so write order and gate-check timing are identical to running with
    # workers=1, just with the compute portion overlapped.
    all_items = list(all_selected_by_card_id.items())
    total_cards = len(all_items)
    workers = max(1, workers)
    if workers > 1:
        # tesseract's LSTM engine can use OpenMP internally - without this, N concurrent
        # tesseract subprocesses (one per in-flight OCR call) could each ALSO try to
        # multi-thread themselves, oversubscribing this box's 2 real cores well beyond
        # `workers`. setdefault, not direct assignment - respects an operator's own override.
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    compute = functools.partial(
        _compute_card,
        ocr_selected_ids=ocr_selected_ids,
        phash_selected_ids=phash_selected_ids,
        already_fallback_covered=already_fallback_covered,
        ocr_crop_box=ocr_crop_box,
        phash_distance_threshold=phash_distance_threshold,
        phash_margin=phash_margin,
        phash_max_candidates=phash_max_candidates,
        fetch_dpi=fetch_dpi,
    )

    chunk_start = 0
    while chunk_start < total_cards:
        # Fetch budget (pre-scale program item 3b, belt-and-suspenders alongside the image CDN
        # Worker's own IMAGE_FULL_TIER_RATE_LIMITER - see the CLI command's --fetch-budget help):
        # checked between chunks, not per-card - a chunk already in flight always runs to
        # completion once started, so the real bound on an overshoot is one chunk's worth of
        # fetches (<= batch_size), not zero. Acceptable given this is explicitly the secondary
        # safeguard, not the primary one.
        if fetch_budget is not None and fetches_made >= fetch_budget:
            budget_exhausted = True
            break
        chunk = all_items[chunk_start : chunk_start + batch_size]
        chunk_start += len(chunk)
        selected_in_chunk = [selected for _card_id, selected in chunk]

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # .map() preserves submission order in its results regardless of completion
                # order - the write loop below sees cards in the exact same order it would with
                # workers=1, so nothing downstream needs to know concurrency happened at all.
                chunk_results = list(pool.map(compute, selected_in_chunk))
        else:
            chunk_results = [compute(s) for s in selected_in_chunk]

        for compute_result in chunk_results:
            card_id = compute_result.card_id
            outcome = compute_result.outcome
            cards_attempted += 1
            if compute_result.fetch_attempted:
                fetches_made += 1

            # Finalize + queue for write - a card's full cost (image fetch, OCR, phash,
            # fallback) was already paid once in _compute_card above; nothing here depends on
            # any OTHER card's outcome, only this card's own DB state (the frame-mismatch
            # consistency check below re-queries the matched printing's own metadata,
            # independent of processing order).
            result_ocr = results.get("ocr")
            result_phash = results.get("phash")
            result_fallback = results["fallback"]

            printing_vote_withheld_for_frame_mismatch = False
            # consistency check: only meaningful once a printing vote (from either pass) exists
            # to compare against the observed frame reading.
            candidate_vote = outcome.ocr_vote or outcome.phash_vote or outcome.fallback_vote
            if outcome.frame_class is not None and candidate_vote is not None and not outcome.disagreement:
                canonical = (
                    CanonicalCard.objects.filter(pk=candidate_vote.printing_pk)
                    .select_related("printing_metadata")
                    .first()
                )
                printing_frame_value = (
                    canonical.printing_metadata.frame
                    if canonical is not None and getattr(canonical, "printing_metadata", None) is not None
                    else None
                )
                if not local_fallback.frame_style_is_consistent(outcome.frame_class, printing_frame_value):
                    outcome.frame_mismatch = True
                    printing_vote_withheld_for_frame_mismatch = True
                    attributes.frame_mismatches.append(
                        {
                            "card_id": card_id,
                            "observed_frame_class": outcome.frame_class,
                            "matched_printing_pk": candidate_vote.printing_pk,
                            "matched_printing_frame_value": printing_frame_value,
                        }
                    )

            if outcome.disagreement:
                assert (
                    result_ocr is not None and result_phash is not None
                )  # both engines ran, or there's no disagreement to detect
                result_ocr.disagreements.append(
                    {"card_id": card_id, "ocr": outcome.ocr_vote, "phash": outcome.phash_vote}
                )
                result_ocr.skip_counts["disagreement-with-other-engine"] += 1
                result_phash.skip_counts["disagreement-with-other-engine"] += 1
            else:
                if outcome.ocr_vote is not None and result_ocr is not None:
                    if printing_vote_withheld_for_frame_mismatch:
                        result_ocr.skip_counts["frame-mismatch"] += 1
                    else:
                        votes_batch.append(
                            CardPrintingTag(
                                card_id=card_id,
                                printing_id=outcome.ocr_vote.printing_pk,
                                is_no_match=False,
                                anonymous_id=OCR_ANONYMOUS_ID,
                                source=VoteSource.OCR,
                                confidence=outcome.ocr_vote.confidence,
                            )
                        )
                        result_ocr.votes_written += 1
                        result_ocr.audit.append({"card_id": card_id, "raw_text": outcome.ocr_vote.detail})
                        written_card_ids.append(card_id)
                        batch_written_card_ids.append(card_id)
                elif outcome.ocr_skip_reason and result_ocr is not None:
                    result_ocr.skip_counts[outcome.ocr_skip_reason] += 1

                if outcome.phash_vote is not None and result_phash is not None:
                    if printing_vote_withheld_for_frame_mismatch:
                        result_phash.skip_counts["frame-mismatch"] += 1
                    else:
                        votes_batch.append(
                            CardPrintingTag(
                                card_id=card_id,
                                printing_id=outcome.phash_vote.printing_pk,
                                is_no_match=False,
                                anonymous_id=PHASH_ANONYMOUS_ID,
                                source=VoteSource.OCR,
                                confidence=outcome.phash_vote.confidence,
                            )
                        )
                        result_phash.votes_written += 1
                        result_phash.audit.append({"card_id": card_id, "detail": outcome.phash_vote.detail})
                        if card_id not in written_card_ids:
                            written_card_ids.append(card_id)
                            batch_written_card_ids.append(card_id)
                elif outcome.phash_skip_reason and result_phash is not None:
                    result_phash.skip_counts[outcome.phash_skip_reason] += 1

                if outcome.fallback_vote is not None:
                    if printing_vote_withheld_for_frame_mismatch:
                        result_fallback.skip_counts["frame-mismatch"] += 1
                    else:
                        votes_batch.append(
                            CardPrintingTag(
                                card_id=card_id,
                                printing_id=outcome.fallback_vote.printing_pk,
                                is_no_match=False,
                                anonymous_id=FALLBACK_ANONYMOUS_ID,
                                source=VoteSource.OCR,
                                confidence=outcome.fallback_vote.confidence,
                            )
                        )
                        result_fallback.votes_written += 1
                        result_fallback.audit.append({"card_id": card_id, "evidence": outcome.fallback_vote.detail})
                        if card_id not in written_card_ids:
                            written_card_ids.append(card_id)
                            batch_written_card_ids.append(card_id)
                elif outcome.fallback_skip_reason:
                    result_fallback.skip_counts[outcome.fallback_skip_reason] += 1

            # border/frame attribute votes are independent of printing-vote success or the
            # consistency-check outcome above - they fire for any card a border/frame reading
            # was taken on, per the module docstring's "double duty" note. BUT when a printing
            # was actually confirmed for this card this run, ground truth from that printing's
            # own CanonicalPrintingMetadata (Scryfall border_color/frame) is preferred over the
            # pixel/OCR heuristic estimate - the heuristic's whole purpose was to independently
            # validate an uncertain match (the consistency check above needs an independent
            # signal to compare against), not to guess an answer we now actually know. Falls
            # back to the heuristic reading whenever no printing was confirmed this run, or the
            # confirmed printing has no usable ground truth for that particular attribute.
            card = all_selected_by_card_id[card_id].card
            confirmed_printing_pk = (
                candidate_vote.printing_pk
                if candidate_vote is not None
                and not outcome.disagreement
                and not printing_vote_withheld_for_frame_mismatch
                else None
            )
            ground_truth_metadata = None
            if confirmed_printing_pk is not None:
                confirmed_canonical = (
                    CanonicalCard.objects.filter(pk=confirmed_printing_pk).select_related("printing_metadata").first()
                )
                if (
                    confirmed_canonical is not None
                    and getattr(confirmed_canonical, "printing_metadata", None) is not None
                ):
                    ground_truth_metadata = confirmed_canonical.printing_metadata

            border_class = outcome.border_color
            border_confidence = local_fallback.BORDER_ATTRIBUTE_VOTE_CONFIDENCE
            if ground_truth_metadata is not None and ground_truth_metadata.border_color:
                # gate on a known tag mapping before overriding - Scryfall's border_color can be
                # "gold", outside this v1 taxonomy (see local_fallback.BORDER_COLOR_TO_TAG's
                # docstring); an unmapped ground truth value must not discard a valid heuristic
                # reading in favour of a vote that will silently resolve to nothing.
                ground_truth_border_class = ground_truth_metadata.border_color
                if ground_truth_border_class in local_fallback.BORDER_COLOR_TO_TAG:
                    border_class = ground_truth_border_class
                    border_confidence = local_fallback.GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE
                    attributes.border_ground_truth_count += 1

            if border_class is not None:
                attributes.border_votes_by_class[border_class] += 1
                border_vote = local_fallback.cast_border_attribute_vote(
                    card, border_class, confidence=border_confidence
                )
                if border_vote is not None and not dry_run:
                    tag_votes_batch.append(border_vote)

            frame_class = outcome.frame_class
            frame_confidence = local_fallback.FRAME_VOTE_CONFIDENCE
            if ground_truth_metadata is not None and ground_truth_metadata.frame:
                ground_truth_frame_class = local_fallback.FRAME_VALUE_TO_CLASS.get(ground_truth_metadata.frame)
                if ground_truth_frame_class is not None:
                    frame_class = ground_truth_frame_class
                    frame_confidence = local_fallback.GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE
                    attributes.frame_ground_truth_count += 1

            if outcome.frame_reading_attempted:
                if frame_class is not None:
                    attributes.frame_votes_by_class[frame_class] += 1
                    frame_vote = local_fallback.cast_frame_style_vote(card, frame_class, confidence=frame_confidence)
                    if frame_vote is not None and not dry_run:
                        tag_votes_batch.append(frame_vote)
                else:
                    attributes.frame_abstain_count += 1

            # addendum item 7: bleed-edge classification - independent of printing-vote success,
            # same "fires for any card with a fetched image" convention as border/frame above,
            # and (unlike those two) has no ground-truth counterpart to prefer, since Scryfall
            # doesn't encode this at all. Already computed once in _compute_card - FIRST, ahead
            # of everything else (see that function's docstring) - so this reads outcome.bleed_
            # class/outcome.image_fetched rather than recomputing against `image` (which is no
            # longer available here now that fetch+compute moved into _compute_card).
            if outcome.bleed_class is not None:
                attributes.bleed_votes_by_class[outcome.bleed_class] += 1
                bleed_vote = local_fallback.cast_bleed_edge_vote(card, outcome.bleed_class)
                if bleed_vote is not None and not dry_run:
                    tag_votes_batch.append(bleed_vote)
            elif outcome.image_fetched:
                attributes.bleed_abstain_count += 1

        flush()
        if nice:
            time.sleep(_NICE_SLEEP_SECONDS)
        if progress_every and chunk_start % progress_every < len(chunk):
            print(f"  ... {chunk_start}/{total_cards} candidates processed")

    cards_not_attempted = len(all_selected_by_card_id) - cards_attempted
    for result in results.values():
        if not dry_run:
            result.gate_violations = all_gate_violations
        result.fetch_budget_exhausted = budget_exhausted
        result.cards_not_attempted_this_invocation = cards_not_attempted

    return results, attributes


def verify_zero_resolutions(card_ids: list[int], batch_size: int = 2000) -> list[int]:
    """Identical rationale/mechanism to cardpicker.deductive_backfill.verify_zero_resolutions -
    the *pure* resolve_printing (never resolve_and_persist_printing, which must never itself
    cause a write) re-checked against fresh DB state after the batch write above."""
    from cardpicker.printing_consensus import resolve_printing

    violations: list[int] = []
    for i in range(0, len(card_ids), batch_size):
        chunk = card_ids[i : i + batch_size]
        for card in Card.objects.filter(pk__in=chunk).iterator(chunk_size=batch_size):
            if resolve_printing(card) is not None:
                violations.append(card.pk)
    return violations


__all__ = [
    "OCR_ANONYMOUS_ID",
    "PHASH_ANONYMOUS_ID",
    "DEDUCTIVE_BACKFILL_ANONYMOUS_ID",
    "OCR_CONFIDENCE_BOTH",
    "OCR_CONFIDENCE_COLLECTOR_ONLY",
    "PHASH_CONFIDENCE",
    "CandidatePrinting",
    "CandidateNameIndex",
    "SelectedCard",
    "select_candidates",
    "get_worker_image_url",
    "fetch_card_image",
    "EngineVote",
    "CardOutcome",
    "CardComputeResult",
    "DEFAULT_WORKERS",
    "run_ocr_for_card",
    "run_phash_for_card",
    "PilotResult",
    "run_pilot",
    "verify_zero_resolutions",
]
