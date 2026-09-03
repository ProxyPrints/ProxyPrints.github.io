"""
Frame-family identifier - the SHOWCASE-FAMILY channel (issues #829, #878, #952, #967, #974,
#968, #979).

WHY THIS EXISTS. The existing `layout_class` distinguishes black/white/silver/borderless but
cannot name the frame family (Showcase Magnified, Pipboy, Vault, Mystical Archive, Storybook,
...). The existing `art_edge_class` detects extended art but not which showcase variant
produced it. Stage D has no way to know whether a card is, say, a Pipboy frame vs. a
MysticalArchive frame - both are "black-bordered showcase" to the existing classifiers.
Frame-family identifiers close this gap by storing the family name alongside the evidence,
giving Stage D (and future consumers) a per-card, per-upload answer.

WHAT SHIPS. `frame_family_class` (a named family, `OTHER_SHOWCASE`, `STANDARD`, `CUSTOM`, or
blank = abstain), `frame_family_confidence` (0-3), and `frame_family_method` on
`ImageEvidence`, computed by `classify_frame_family` and wired into Stage C
(`compute_card_evidence`). The fallback chain, cheapest to costliest:

  1. STRUCTURAL CONSTRUCTION (confidence 3) - deterministic detectors for five visually
     unmistakable families: ShowcaseMagnified (circular art window), Pipboy (CRT scanline
     header), Vault (stepped corner brackets), MysticalArchive (dotted parchment nameplate),
     Storybook (vine-scroll border). These target construction, not colour.

  2. ARTBOUNDS DISTANCE (confidence 1) - pinline-spread check that the card edge is real and
     the frame is a standard bordered frame. Cannot name a showcase family; only ever yields
     `STANDARD` where `layout_class` names a border colour.

  Region-hash and furniture-colour methods are deliberately NOT shipped. Region-hash is
  closed by the frame-identification audit: its reference population was contaminated by the
  metadata label it was scored against, and a fixed-fraction crop band (left 7%) is the
  padding-blind geometry issue #735 records (real cards carry ~6-8% canvas padding, so that
  strip is often padding, not frame). Furniture-colour has no stored RGB swatch artifact yet.

CALIBRATION (the gate). A family ships as a NAMED value only where owner-verified truth exists
for it AND the method clears #829's bar (false positives at or near zero on ordinary frames).
That judgement lives in `NAMED_FAMILIES` below. As measured against the owner-verified labels
on disk (frame-groundtruth V2_KEY_SEALED / RECALL_KEY_SEALED, fable-judge FABLE_KEY_SEALED):
the structural detectors score **0/4 recall** on the four owner-confirmed positives (Storybook,
Vault, ShowcaseMagnified, Pipboy - one each) and fire spuriously on **27/40** owner-negative
cards, so **no family clears the bar and `NAMED_FAMILIES` is empty**. The identifier therefore
ships DORMANT: the schema and framework are in place and the tests prove the detector
mechanism on synthetic fixtures, but production extraction abstains (no named family is
supported) and the caster votes nothing until a method clears the bar. That is the honest
outcome of the calibration, reported in full in the PR body rather than asserted away.

SET NARROWING (issue #979 / the audit's own finding). Every method runs inside the
set-narrowed candidate family set: the card's name resolves through
`CandidateNameIndex.candidates_for` (imported, never reimplemented) to candidate printings,
whose expansion codes map through `SET_TO_FRAME_FAMILIES` to the named families that set
actually ships. A card whose name resolves to zero candidates abstains with the
`no-candidates` skip reason. Without this the detectors would answer a 48-way question
production never asks (38 of 52 cohort cards reduce to a single candidate family).

WHAT MUST NOT HAPPEN:
  - No protected-core edits (local_fallback.py, local_phash.py, local_identify_printing_tags.py
    are untouched; only their public functions are imported).
  - No committed image bytes - the detectors compute statistics in memory only, nothing is
    written to disk.
  - No `frame_effects` as a family label (Scryfall `frame_effects` describes the depicted
    printing, not the uploaded image's treatment).
  - No reimplemented name resolution - `CandidateNameIndex.candidates_for` is the existing
    normaliser, reused via import.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from cardpicker.local_identify_printing_tags import CandidateNameIndex, generate_run_id
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTagVote,
    ImageEvidence,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.vote_write import purge_and_write_votes

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version tag - bumped when the detection logic changes materially, staling
# every existing row so the next pass re-extracts under the new logic.
# ---------------------------------------------------------------------------
FRAME_FAMILY_EXTRACTOR_VERSION = "frame-family-v1"

# ---------------------------------------------------------------------------
# Family classes - the closed enumeration stored in frame_family_class.
# ---------------------------------------------------------------------------
FRAME_FAMILY_SHOWCASE_MAGNIFIED = "ShowcaseMagnified"
FRAME_FAMILY_PIPBOY = "Pipboy"
FRAME_FAMILY_VAULT = "Vault"
FRAME_FAMILY_MYSTICAL_ARCHIVE = "MysticalArchive"
FRAME_FAMILY_STORYBOOK = "Storybook"
FRAME_FAMILY_OTHER_SHOWCASE = "OTHER_SHOWCASE"
FRAME_FAMILY_STANDARD = "STANDARD"
FRAME_FAMILY_CUSTOM = "CUSTOM"

# All named structural families (fable-judge-confirmed as visually unmistakable constructions).
STRUCTURAL_FAMILIES: frozenset[str] = frozenset(
    {
        FRAME_FAMILY_SHOWCASE_MAGNIFIED,
        FRAME_FAMILY_PIPBOY,
        FRAME_FAMILY_VAULT,
        FRAME_FAMILY_MYSTICAL_ARCHIVE,
        FRAME_FAMILY_STORYBOOK,
    }
)

# ---------------------------------------------------------------------------
# CALIBRATION GATE. A family is emitted as a NAMED value only when it is in
# NAMED_FAMILIES - i.e. owner-verified truth exists for it AND its method
# cleared #829's bar (false positives at or near zero on ordinary frames).
#
# Measured against the owner-verified labels on disk:
#   - owner-confirmed positives (recall): Storybook 0/1, Vault 0/1,
#     ShowcaseMagnified 0/1, Pipboy 0/1 (MysticalArchive has no owner "Y";
#     its two owner labels are HELD and CLOSE). n = 1 per family.
#   - owner-negative pool (false positives): 27/40 - the detectors fire on
#     ordinary/custom frames far more often than zero. MysticalArchive 22,
#     Pipboy 5.
# No family clears the bar, so this set is empty and production extraction
# abstains. Populated only when a future calibration clears a family.
# ---------------------------------------------------------------------------
NAMED_FAMILIES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Detection method tags stored in frame_family_method.
# ---------------------------------------------------------------------------
METHOD_STRUCTURAL_CONSTRUCTION = "structural-construction"
METHOD_ARTBOUNDS_DISTANCE = "artbounds-distance"

# ---------------------------------------------------------------------------
# Confidence levels.
# ---------------------------------------------------------------------------
CONFIDENCE_ABSTAIN = 0
CONFIDENCE_MODERATE = 1
CONFIDENCE_HIGH = 2
CONFIDENCE_STRUCTURAL = 3

# ---------------------------------------------------------------------------
# Skip-reason vocabulary (docs/reference/skip-reasons.md declaration convention).
# ---------------------------------------------------------------------------
# issue #979: the card's name resolved to zero candidate printings, so there is no set to
# narrow the candidate families by - the detector cannot answer and abstains.
FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON = "no-candidates"
FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON = "no-evidence"
FRAME_FAMILY_NO_READING_SKIP_REASON = "no-reading"
FRAME_FAMILY_AMBIGUOUS_SKIP_REASON = "ambiguous"

# Rescannable = transient "nothing to look at YET" states a later pass can change.
FRAME_FAMILY_RESCANNABLE_SKIP_REASONS: frozenset[str] = frozenset(
    {
        FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON,
        FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON,
        FRAME_FAMILY_NO_READING_SKIP_REASON,
    }
)

# ---------------------------------------------------------------------------
# Caster identity (the anonymous_id stamped on CardTagVote/CardScanLog rows).
# ---------------------------------------------------------------------------
FRAME_FAMILY_ANONYMOUS_ID = "frame-family-v1"
FRAME_FAMILY_TAG_NAME = "Showcase"
FRAME_FAMILY_VOTE_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# SET -> FRAME FAMILIES (set narrowing, issue #979 / the audit's own finding).
#
# Single-template alternate-frame sets and the named family each ships, from
# the Scryfall frame_effects x expansion population table
# (pipeline-artifacts/frame-coverage-combined/report.md Part 2) - the
# definitional source for which family a set's showcase treatment is. Only the
# five structural families a detector can NAME are listed; every other set is
# deliberately absent, so a card from an unlisted set can never carry a named
# family verdict (it falls through to abstain / OTHER_SHOWCASE). Expansion
# codes are lowercased, matching CandidatePrinting.expansion_code.
# ---------------------------------------------------------------------------
SET_TO_FRAME_FAMILIES: dict[str, frozenset[str]] = {
    "mkm": frozenset({FRAME_FAMILY_SHOWCASE_MAGNIFIED}),  # Karlov Manor showcase
    "pip": frozenset({FRAME_FAMILY_PIPBOY}),  # Fallout Pip-Boy
    "big": frozenset({FRAME_FAMILY_VAULT}),  # Big Score
    "sta": frozenset({FRAME_FAMILY_MYSTICAL_ARCHIVE}),  # Strixhaven Mystical Archive
    "soa": frozenset({FRAME_FAMILY_MYSTICAL_ARCHIVE}),  # Mystical Archive (SOA)
    "eld": frozenset({FRAME_FAMILY_STORYBOOK}),  # Throne of Eldraine storybook
}


def candidate_frame_families(name: str, index: CandidateNameIndex) -> frozenset[str]:
    """The named frame families this card's name can resolve to, narrowed by set.

    Resolves the name through `CandidateNameIndex.candidates_for` (unmodified), maps each
    candidate's expansion code through `SET_TO_FRAME_FAMILIES`, and returns the union as a
    frozenset. An empty result means the name resolved to zero candidates (issue #979) OR to
    candidates whose sets ship no named family - either way the detector must abstain rather
    than guess.
    """
    families: set[str] = set()
    for candidate in index.candidates_for(name):
        families |= SET_TO_FRAME_FAMILIES.get(candidate.expansion_code, frozenset())
    return frozenset(families)


def build_candidate_frame_families_lookup() -> Callable[[str], frozenset[str]]:
    """A `name -> frozenset[family]` callable backed by the shared cached CandidateNameIndex.

    Mirrors `collector_line_artist.build_name_artist_lookup`'s shape: the index is built once
    (via `local_calculate_verdicts._get_cached_candidate_name_index`, the single cached entry
    point every batch-reachable caller must use) and only the resolved frozenset crosses the
    process-pool boundary. Called on the parent/worker's own driver loop, never inside a compute
    worker.
    """
    from cardpicker.local_calculate_verdicts import _get_cached_candidate_name_index

    index = _get_cached_candidate_name_index()

    def lookup(name: str) -> frozenset[str]:
        return candidate_frame_families(name, index)

    return lookup


# ---------------------------------------------------------------------------
# Structural detection thresholds (deterministic, shape/construction checks).
# These are pixel-geometry checks, not colour thresholds - they fire on
# construction, not palette.
# ---------------------------------------------------------------------------

# Circular art window: ShowcaseMagnified has a circular art window whose content fills the
# art box's vertical center (full width) and tapers to nothing at its top and bottom edges.
# A rectangular art window fills the top and bottom rows too.
_MAGNIFIED_MIDDLE_FILL_MIN = 0.8
_MAGNIFIED_EDGE_FILL_MAX = 0.25
# Minimum luminance contrast between art-box content and background before a shape can be read.
_MAGNIFIED_MIN_CONTRAST = 30

# CRT terminal / Pipboy: the header (top 15%) carries high-frequency horizontal scanlines.
# Scanlines are horizontal stripes, so the alternation is in the VERTICAL direction.
_PIPBOY_SCANLINE_FREQ_MIN = 0.3

# Vault: stepped metallic brackets produce L-shaped brightness gradients in the corners.
_VAULT_CORNER_GRADIENT_MIN = 0.15

# MysticalArchive: dotted parchment nameplate in the type-line region.
_MYSTICAL_ARCHIVE_DOT_DENSITY_MIN = 0.1

# Storybook: vine-scroll border irregularity along the card edge.
_STORYBOOK_BORDER_IRREGULARITY_MIN = 0.2


# ---------------------------------------------------------------------------
# Structural detectors (method 1 - deterministic, highest confidence).
# ---------------------------------------------------------------------------


def _detect_showcase_magnified(image: Any) -> bool:
    """Detect the circular art window of ShowcaseMagnified frames.

    A circular window's content (everything brighter than the art box's mid-luminance) fills
    the art box's vertical center at full width and tapers to nothing at the top and bottom
    edges, where a rectangular art window keeps full-width content edge to edge. The test
    reads the center row (must be ~full width) and the top/bottom rows (must be ~empty).
    """
    width, height = image.size
    art_left = int(0.07 * width)
    art_top = int(0.10 * height)
    art_right = int(0.93 * width)
    art_bottom = int(0.85 * height)
    art_region = image.crop((art_left, art_top, art_right, art_bottom)).convert("L")
    aw, ah = art_region.size
    if aw <= 0 or ah <= 0:
        return False

    pixels = list(art_region.getdata())
    lo, hi = min(pixels), max(pixels)
    if hi - lo < _MAGNIFIED_MIN_CONTRAST:
        return False
    threshold = (lo + hi) // 2

    row_widths = []
    for y in range(ah):
        row = pixels[y * aw : (y + 1) * aw]
        row_widths.append(sum(1 for p in row if p > threshold))

    middle_fill = row_widths[ah // 2] / aw
    top_fill = row_widths[0] / aw
    bottom_fill = row_widths[ah - 1] / aw
    return (
        middle_fill > _MAGNIFIED_MIDDLE_FILL_MIN
        and top_fill < _MAGNIFIED_EDGE_FILL_MAX
        and bottom_fill < _MAGNIFIED_EDGE_FILL_MAX
    )


def _detect_pipboy(image: Any) -> bool:
    """Detect the CRT scanline pattern of Pipboy frames.

    The Pipboy header (top 15%) carries high-frequency horizontal scanlines - alternating
    bright/dark horizontal stripes - so the intensity alternation is in the vertical
    direction. The test samples one column and counts vertical zero-crossings.
    """
    width, height = image.size
    header_bottom = int(0.15 * height)
    if header_bottom <= 0:
        return False
    header = image.crop((0, 0, width, header_bottom)).convert("L")
    pixels = list(header.getdata())
    col_x = width // 2
    col = [pixels[y * width + col_x] for y in range(header_bottom)]
    if len(col) < 3:
        return False
    transitions = sum(1 for i in range(2, len(col)) if (col[i] - col[i - 1]) * (col[i - 1] - col[i - 2]) < 0)
    freq = transitions / len(col)
    return freq > _PIPBOY_SCANLINE_FREQ_MIN


def _detect_vault(image: Any) -> bool:
    """Detect the stepped metallic bracket framing of Vault frames.

    Vault frames carry L-shaped brightness gradients in the four corners - a distinctive
    stepped bracket pattern. The test measures the brightness gradient in each corner region.
    """
    width, height = image.size
    corner_size = int(0.08 * min(width, height))
    if corner_size <= 0:
        return False
    corners = [
        (0, 0, corner_size, corner_size),
        (width - corner_size, 0, width, corner_size),
        (0, height - corner_size, corner_size, height),
        (width - corner_size, height - corner_size, width, height),
    ]
    gradients = []
    for x0, y0, x1, y1 in corners:
        region = image.crop((x0, y0, x1, y1)).convert("L")
        pixels = list(region.getdata())
        if len(pixels) < 4:
            continue
        mid = len(pixels) // 2
        first_half = pixels[:mid]
        second_half = pixels[mid:]
        if not first_half or not second_half:
            continue
        mean_first = sum(first_half) / len(first_half)
        mean_second = sum(second_half) / len(second_half)
        gradients.append(abs(mean_second - mean_first) / 255.0)
    if not gradients:
        return False
    avg_gradient = sum(gradients) / len(gradients)
    return avg_gradient > _VAULT_CORNER_GRADIENT_MIN


def _detect_mystical_archive(image: Any) -> bool:
    """Detect the dotted parchment nameplate of MysticalArchive frames.

    MysticalArchive frames have a dotted parchment nameplate in the type-line region. The
    test measures the density of small bright spots (pixels brighter than mean + 1 stddev)
    in the type-line band.
    """
    width, height = image.size
    type_line_top = int(0.55 * height)
    type_line_bottom = int(0.65 * height)
    if type_line_bottom <= type_line_top:
        return False
    band = image.crop((0, type_line_top, width, type_line_bottom)).convert("L")
    pixels = list(band.getdata())
    if not pixels:
        return False
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    stddev = math.sqrt(variance)
    threshold = mean + stddev
    bright_count = sum(1 for p in pixels if p > threshold)
    density = bright_count / len(pixels)
    return density > _MYSTICAL_ARCHIVE_DOT_DENSITY_MIN


def _detect_storybook(image: Any) -> bool:
    """Detect the vine scroll border of Storybook frames.

    Storybook frames have an irregular, vine-scroll border pattern. The test measures the
    irregularity (stddev of edge brightness) along the card's left border strip.
    """
    width, height = image.size
    border_width = int(0.03 * min(width, height))
    if border_width <= 0:
        return False
    left_strip = image.crop((0, 0, border_width, height)).convert("L")
    pixels = list(left_strip.getdata())
    if len(pixels) < 10:
        return False
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    stddev = math.sqrt(variance)
    irregularity = stddev / 255.0
    return irregularity > _STORYBOOK_BORDER_IRREGULARITY_MIN


# Map family name -> structural detector function.
STRUCTURAL_DETECTORS: dict[str, Any] = {
    FRAME_FAMILY_SHOWCASE_MAGNIFIED: _detect_showcase_magnified,
    FRAME_FAMILY_PIPBOY: _detect_pipboy,
    FRAME_FAMILY_VAULT: _detect_vault,
    FRAME_FAMILY_MYSTICAL_ARCHIVE: _detect_mystical_archive,
    FRAME_FAMILY_STORYBOOK: _detect_storybook,
}


# ---------------------------------------------------------------------------
# Detection result.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameFamilyResult:
    """One card's frame-family detection result, held between computation and storage."""

    family_class: str  # blank = abstain
    confidence: int  # 0-3
    method: str  # METHOD_* constant or blank
    skip_reason: str = ""  # abstention reason (FRAME_FAMILY_*_SKIP_REASON), "" on a verdict


def classify_frame_family(
    image: Any,
    *,
    candidate_families: Optional[frozenset[str]] = None,
    art_edge_class: str = "",
    layout_class: str = "",
    pinline_inset_frac_top: Optional[float] = None,
    pinline_inset_frac_bottom: Optional[float] = None,
    pinline_inset_frac_left: Optional[float] = None,
    pinline_inset_frac_right: Optional[float] = None,
    art_crop_px: Optional[list[int]] = None,
) -> FrameFamilyResult:
    """Classify the frame family of a fetched card image.

    Runs the detection-method fallback chain cheapest-to-costliest. Every method runs inside
    the set-narrowed candidate family set:

      - `candidate_families` of `frozenset()` means the card's name resolved to zero
        candidates (issue #979) and the detector abstains with the `no-candidates` reason;
      - a non-empty `candidate_families` restricts a structural detector to only claim a
        family the card's own set ships;
      - `None` (the default, e.g. a direct test call) skips narrowing.

      1. Structural construction (confidence 3) - only for families in `NAMED_FAMILIES`
         (the calibration gate: a family ships as NAMED only where owner-verified truth
         exists and the method cleared #829's bar).
      2. ArtBounds distance (confidence 1) - a consistent, measurable pinline inset plus a
         known border colour yields `STANDARD`. Cannot name a showcase family.

    Region-hash and furniture-colour are deliberately absent (see module docstring).
    """
    # --- issue #979: name resolved to zero candidates -> abstain, named reason ---
    if candidate_families is not None and not candidate_families:
        return FrameFamilyResult(
            family_class="",
            confidence=CONFIDENCE_ABSTAIN,
            method="",
            skip_reason=FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON,
        )

    # --- Method 1: Structural construction detectors (calibration-gated) ---
    for family, detector in STRUCTURAL_DETECTORS.items():
        if family not in NAMED_FAMILIES:
            continue  # not cleared to ship as named - see the calibration table
        if candidate_families is not None and family not in candidate_families:
            continue  # set narrowing: this card's set does not ship this family
        if detector(image):
            return FrameFamilyResult(
                family_class=family,
                confidence=CONFIDENCE_STRUCTURAL,
                method=METHOD_STRUCTURAL_CONSTRUCTION,
            )

    # --- Method 4: ArtBounds distance (pinline-spread check -> STANDARD only) ---
    if (
        pinline_inset_frac_top is not None
        and pinline_inset_frac_bottom is not None
        and pinline_inset_frac_left is not None
        and pinline_inset_frac_right is not None
    ):
        fracs = [pinline_inset_frac_top, pinline_inset_frac_bottom, pinline_inset_frac_left, pinline_inset_frac_right]
        spread = max(fracs) - min(fracs)
        avg_inset = sum(fracs) / len(fracs)
        # A real bordered frame has a consistent, measurable inset on all four sides.
        if spread < 0.02 and avg_inset > 0.01:
            if layout_class in ("black", "white", "silver"):
                return FrameFamilyResult(
                    family_class=FRAME_FAMILY_STANDARD,
                    confidence=CONFIDENCE_MODERATE,
                    method=METHOD_ARTBOUNDS_DISTANCE,
                )

    # --- Abstain ---
    return FrameFamilyResult(
        family_class="",
        confidence=CONFIDENCE_ABSTAIN,
        method="",
        skip_reason=FRAME_FAMILY_AMBIGUOUS_SKIP_REASON,
    )


# ---------------------------------------------------------------------------
# Caster: votes the coarse "Showcase" tag on named, above-bar verdicts.
# ---------------------------------------------------------------------------


def cast_frame_family_vote(
    card: Card,
    frame_family_class: str,
    frame_family_confidence: int,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """An unsaved `CardTagVote` applying the pre-existing "Showcase" tag, or None.

    The gate reads the calibration table's outcome, not a hard-coded tier: a vote is cast
    only when the family is in `NAMED_FAMILIES` (owner-verified truth + #829's bar cleared)
    AND the confidence is structural. "STANDARD", "CUSTOM", "OTHER_SHOWCASE", and blank are
    deliberately silent rather than casting a negative "Showcase" vote: a negative vote from
    an unvalidated class is a claim, not an abstention. `NAMED_FAMILIES` is currently empty
    (the calibration failed #829's bar), so this function casts nothing today.
    """
    if frame_family_class not in NAMED_FAMILIES:
        return None
    if frame_family_confidence < CONFIDENCE_STRUCTURAL:
        return None
    if frame_family_class in (
        "",
        FRAME_FAMILY_STANDARD,
        FRAME_FAMILY_CUSTOM,
        FRAME_FAMILY_OTHER_SHOWCASE,
    ):
        return None
    tag = Tag.objects.filter(name=FRAME_FAMILY_TAG_NAME).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.APPLY,
        anonymous_id=FRAME_FAMILY_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=FRAME_FAMILY_VOTE_CONFIDENCE,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Cast infrastructure (mirrors local_art_edge.run_art_edge_continuity_cast).
# ---------------------------------------------------------------------------


@dataclass
class FrameFamilyCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)


def _eligible_cards_queryset(
    card_ids: Optional[Any] = None,
) -> "QuerySet[Card]":
    """Every card not already voted on by this caster's own identity, and not
    already carrying a non-rescannable CardScanLog row from a prior invocation."""
    non_rescannable_qs = CardScanLog.objects.filter(anonymous_id=FRAME_FAMILY_ANONYMOUS_ID,).exclude(
        skip_reason__in=FRAME_FAMILY_RESCANNABLE_SKIP_REASONS,
    )
    if card_ids is not None:
        non_rescannable_qs = non_rescannable_qs.filter(card_id__in=card_ids)

    scanned_card_ids = set(non_rescannable_qs.values_list("card_id", flat=True))

    qs = Card.objects.exclude(
        tag_votes__anonymous_id=FRAME_FAMILY_ANONYMOUS_ID,
    ).distinct()
    if card_ids is not None:
        qs = qs.filter(pk__in=card_ids)
    if scanned_card_ids:
        qs = qs.exclude(pk__in=scanned_card_ids)
    return qs


def run_frame_family_cast(
    *,
    dry_run: bool = False,
    run_id: Optional[str] = None,
    card_ids: Optional[Any] = None,
    chunk_size: int = 500,
) -> FrameFamilyCastResult:
    """Cast coarse "Showcase" votes from stored frame-family evidence.

    Mirrors `local_art_edge.run_art_edge_continuity_cast`'s own pattern: eligible cards ->
    read stored evidence -> cast if above-bar -> log skips. The bar is `cast_frame_family_vote`'s
    own calibration gate (`NAMED_FAMILIES`), which is empty today, so this run casts nothing.
    """
    run_id = run_id or generate_run_id()

    tag = Tag.objects.filter(name=FRAME_FAMILY_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(f"Tag '{FRAME_FAMILY_TAG_NAME}' not found. Run seed_default_tags() before casting.")

    result = FrameFamilyCastResult(dry_run=dry_run, run_id=run_id)

    scan_log_batch: list[CardScanLog] = []

    def _skip(card_id: int, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card_id,
                    anonymous_id=FRAME_FAMILY_ANONYMOUS_ID,
                    run_id=run_id,
                    skip_reason=reason,
                )
            )

    votes_batch: list[CardTagVote] = []

    for card in _eligible_cards_queryset(card_ids).iterator(chunk_size=chunk_size):
        evidence = ImageEvidence.objects.filter(card=card).order_by("-created_at").first()
        if evidence is None:
            _skip(card.pk, FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON)
            continue

        result.cards_considered += 1
        family_class = evidence.frame_family_class
        family_confidence = evidence.frame_family_confidence

        if not family_class:
            _skip(card.pk, FRAME_FAMILY_NO_READING_SKIP_REASON)
            continue

        vote = cast_frame_family_vote(
            card,
            family_class,
            family_confidence,
            run_id=run_id,
        )
        if vote is None:
            if family_class not in NAMED_FAMILIES:
                reason = f"uncalibrated-{family_class}"
            elif family_confidence < CONFIDENCE_STRUCTURAL:
                reason = f"confidence-{family_confidence}"
            else:
                reason = f"family-{family_class}"
            _skip(card.pk, reason)
            continue

        result.votes_would_cast += 1
        if not dry_run:
            votes_batch.append(vote)

    if not dry_run:
        purge_and_write_votes(
            CardTagVote,
            votes_batch,
            anonymous_id=FRAME_FAMILY_ANONYMOUS_ID,
            target_field="card_id",
            ignore_conflicts=True,
        )
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.votes_written = len(votes_batch)

    return result


__all__ = [
    "FRAME_FAMILY_EXTRACTOR_VERSION",
    "FRAME_FAMILY_ANONYMOUS_ID",
    "FRAME_FAMILY_TAG_NAME",
    "FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON",
    "FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON",
    "FRAME_FAMILY_NO_READING_SKIP_REASON",
    "FRAME_FAMILY_AMBIGUOUS_SKIP_REASON",
    "FRAME_FAMILY_RESCANNABLE_SKIP_REASONS",
    "NAMED_FAMILIES",
    "SET_TO_FRAME_FAMILIES",
    "candidate_frame_families",
    "build_candidate_frame_families_lookup",
    "FrameFamilyResult",
    "classify_frame_family",
    "cast_frame_family_vote",
    "FrameFamilyCastResult",
    "run_frame_family_cast",
    "STRUCTURAL_FAMILIES",
]
