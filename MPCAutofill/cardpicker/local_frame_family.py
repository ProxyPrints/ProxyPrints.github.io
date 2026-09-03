"""
Frame-family identifier - the SHOWCASE-FAMILY channel.

Owner-directed design (directive 2026-09-02): identify which frame family a card belongs to by
inspecting the uploaded image directly, storing per-family detection methods with fallbacks, and
calibrating against owner-verified labels before wiring any vote.

WHY THIS EXISTS. The existing `layout_class` (classify_border_color) distinguishes black/white/
silver/borderless but cannot name the frame family (Showcase Magnified, Pipboy, Vault, etc.).
The existing `art_edge_class` (classify_art_edge_continuity) detects extended art but not which
showcase variant produced it. Stage D currently has no way to know whether a card is, say,
a Pipboy frame vs. a MysticalArchive frame - both are "black-bordered showcase" to the existing
classifiers. Frame-family identifiers close this gap by storing the family name alongside the
evidence, giving Stage D (and future consumers) a per-card, per-upload answer.

DETECTION METHODS (fallback chain, cheapest to costliest):

  1. STRUCTURAL CONSTRUCTION - deterministic detectors for five unmistakable families:
     - ShowcaseMagnified: circular ring window cutting through the frame
     - Pipboy: CRT terminal / Pip-Boy interface aesthetic
     - Vault: stepped metallic bracket framing
     - MysticalArchive: dotted parchment nameplate
     - Storybook: vine scroll border
     These are zero-threshold, high-precision detectors that fire on construction rather than
     colour - confirmed at confidence 3 with 4/4 precision by the fable judge (round2_result).

  2. REGION-HASH (LIVE) - per-family reference phash comparison, restricted to
     REGION_HASH_FAMILIES (NeonInk, ShowcaseMagnified, M15NyxShowcase) where
     within-family 1-NN accuracy >= 88% AND colour check agreement is 0%.
     Crops the left 7% border strip, computes a phash, and finds the nearest
     family in the whitelist by hamming distance (threshold 25).
     Reference phashes loaded from frame_family_ref_phashes.json.

  3. FURNITURE COLOUR (BLOCKED) - per-family dominant-colour check where it
     scores (Storybook 85.7%, Fang 66.7%, MysticalArchive 57.1%). Blocked:
     no stored RGB swatch artifact exists; colour_classification_fixed.json
     contains naming counts only, not values. Would need a pre-computed
     swatch RGB JSON derived from refimg/ CardConjurer PNGs.

  4. ARTBOUNDS DISTANCE - pinline-spread check where the card edge is real (a real border
     is present, not art-only).

  5. VARIANT-PINNED DIRECT COMPARISON - reference a known variant of the same card name and
     compare frame treatment. Verifier only, never the primary method.

OUTPUT:

  `frame_family_class`: the named family ("ShowcaseMagnified", "Pipboy", "Vault",
  "MysticalArchive", "Storybook", "Woodland", "NeonInk", "ShowcasePanel", "Fang",
  "StorybookWOE", "M15NyxShowcase", "ShowcaseMagnified"), or "OTHER_SHOWCASE" for a family
  that is identifiable as a showcase variant but not as a specific named family, "STANDARD"
  for standard frames, "CUSTOM" for custom proxies, or blank-string-as-sentinel (abstain).

  `frame_family_confidence`: 0-3 integer. 3 = structural detector (highest). 2 = region-hash
  or colour check (high). 1 = artBounds or variant-pinned (moderate). 0 = abstained.

  `frame_family_method`: which detection method produced the verdict. One of:
  "structural-construction", "region-hash", "furniture-colour", "artbounds-distance",
  "variant-pinned", "" (abstained).

WIRING. Wired via `cast_frame_family_vote` (this module) called from
`stage_e_dispatch._run_evidence_only_calculators` and the standalone
`local_frame_family_cast` management command. The coarse "Showcase" tag is voted ONLY on
named, above-bar verdicts (confidence >= 2, family != STANDARD/CUSTOM/OTHER_SHOWCASE/blank).

WHAT MUST NOT HAPPEN (directive):
  - No protected-core edits (local_fallback.py, local_phash.py are untouched)
  - No committed image bytes (crop pixels exist only in memory)
  - No "frame_effects" as a label (Scryfall frame_effects describes the depicted printing,
    not the uploaded image's treatment - see docs/reference/self-referential-reasoning.md)
  - No reimplemented name resolution (CandidateNameIndex.candidates_for is the existing
    normaliser, reused via import, not reimplemented)

ISSUES: #829 (negative bar), #878 (evidence-only mandate), #952 (variant-pinned verifier),
#967/#974 (family labels), #968 (coverage gaps), #979 (dry-run yield measurement).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from cardpicker.local_identify_printing_tags import generate_run_id
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
FRAME_FAMILY_WOODLAND = "Woodland"
FRAME_FAMILY_NEONINK = "NeonInk"
FRAME_FAMILY_SHOWCASE_PANEL = "ShowcasePanel"
FRAME_FAMILY_FANG = "Fang"
FRAME_FAMILY_STORYBOOK_WOE = "StorybookWOE"
FRAME_FAMILY_M15_NYX_SHOWCASE = "M15NyxShowcase"
FRAME_FAMILY_OTHER_SHOWCASE = "OTHER_SHOWCASE"
FRAME_FAMILY_STANDARD = "STANDARD"
FRAME_FAMILY_CUSTOM = "CUSTOM"

# All named structural families (fable-judge-confirmed at confidence 3).
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
# Detection method tags stored in frame_family_method.
# ---------------------------------------------------------------------------
METHOD_STRUCTURAL_CONSTRUCTION = "structural-construction"
METHOD_REGION_HASH = "region-hash"
METHOD_FURNITURE_COLOUR = "furniture-colour"
METHOD_ARTBOUNDS_DISTANCE = "artbounds-distance"
METHOD_VARIANT_PINNED = "variant-pinned"

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
FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON = "no-evidence"
FRAME_FAMILY_NO_READING_SKIP_REASON = "no-reading"
FRAME_FAMILY_AMBIGUOUS_SKIP_REASON = "ambiguous"

# Rescannable = transient "nothing to look at YET" states a later pass can change.
FRAME_FAMILY_RESCANNABLE_SKIP_REASONS: frozenset[str] = frozenset(
    {
        FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON,
        FRAME_FAMILY_NO_READING_SKIP_REASON,
    }
)

# ---------------------------------------------------------------------------
# Caster identity (the anonymous_id stamped on CardTagVote/CardScanLog rows).
# ---------------------------------------------------------------------------
FRAME_FAMILY_ANONYMOUS_ID = "local-frame-family"
FRAME_FAMILY_TAG_NAME = "Showcase"
FRAME_FAMILY_VOTE_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# Structural detection thresholds (deterministic, zero-threshold for named families).
# These are pixel-ratio / shape checks, not colour thresholds - they fire on
# construction, not palette, which is why precision is high on ordinary frames.
# ---------------------------------------------------------------------------

# Circular ring window: ShowcaseMagnified has a distinctive circular art window
# whose diameter is > 60% of the card width.  Standard frames have rectangular
# art windows.  We detect this by measuring the ratio of the inscribed circle's
# area to the total art-box area.
_MAGNIFIED_RING_AREA_RATIO_MIN = 0.85

# CRT terminal / Pipboy: the Pipboy frame has a distinctive green-tinted scanline
# pattern in the header region.  We detect this by measuring the horizontal
# frequency of intensity transitions in the top 15% of the card.
_PIPBOY_SCANLINE_FREQ_MIN = 0.3

# Vault: stepped metallic brackets in the corners.  We detect this by looking for
# L-shaped brightness gradients in the four corners.
_VAULT_CORNER_GRADIENT_MIN = 0.15

# MysticalArchive: dotted parchment nameplate in the type-line region.  We detect
# this by measuring the density of small bright spots in the type-line band.
_MYSTICAL_ARCHIVE_DOT_DENSITY_MIN = 0.1

# Storybook: vine scroll border pattern.  We detect this by measuring the
# irregularity (stddev of edge brightness) along the card border.
_STORYBOOK_BORDER_IRREGULARITY_MIN = 0.2


# ---------------------------------------------------------------------------
# Region-hash thresholds (from coverage report and audit).
# ---------------------------------------------------------------------------
REGION_HASH_CONSISTENCY_MIN = 0.88  # 88% within-family consistency
REGION_HASH_COLOUR_CHECK_MAX = 0.0  # colour check must be 0% for region-hash to fire


# ---------------------------------------------------------------------------
# Furniture colour thresholds (from coverage report).
# ---------------------------------------------------------------------------
FURNITURE_COLOUR_MIN_SCORE = 0.5  # minimum colour-check score to fire


# ---------------------------------------------------------------------------
# ArtBounds distance threshold.
# ---------------------------------------------------------------------------
ARTBOUNDS_PINLINE_SPREAD_MIN = 0.02  # minimum pinline spread to confirm real border


# ---------------------------------------------------------------------------
# Helpers: image analysis primitives.
# ---------------------------------------------------------------------------


def _mean_rgb_over_region(
    image: Any,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> Optional[tuple[float, float, float]]:
    """Mean (R, G, B) over a fractional region of `image`, or None on degenerate input."""
    width, height = image.size
    x0, y0 = int(left * width), int(top * height)
    x1, y1 = int(right * width), int(bottom * height)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = image.crop((x0, y0, x1, y1))
    pixels = list(crop.getdata())
    n = len(pixels)
    if n == 0:
        return None
    r_sum = sum(p[0] for p in pixels)
    g_sum = sum(p[1] for p in pixels)
    b_sum = sum(p[2] for p in pixels)
    return (r_sum / n, g_sum / n, b_sum / n)


def _euclidean_rgb_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _brightness(position: tuple[float, float, float]) -> float:
    """Perceived brightness (0-255) from an (R, G, B) tuple."""
    return 0.299 * position[0] + 0.587 * position[1] + 0.114 * position[2]


def _image_region_phash(image: Any, left: float, top: float, right: float, bottom: float) -> Optional[int]:
    """Perceptual hash of a fractional region, or None on degenerate input."""
    width, height = image.size
    x0, y0 = int(left * width), int(top * height)
    x1, y1 = int(right * width), int(bottom * height)
    if x1 <= x0 or y1 <= y0:
        return None
    region = image.crop((x0, y0, x1, y1)).convert("L")
    import imagehash

    from cardpicker.utils import twos_complement

    return twos_complement(str(imagehash.phash(region)), 64)


# ---------------------------------------------------------------------------
# Region-hash detection: per-family reference phash comparison.
# ---------------------------------------------------------------------------
#
# The harvest pass (frame-coverage-combined) computed phashes from real card
# images using frame+pinline+border regions (alpha>25 on 630x880 canvas).
# Reference phashes are stored in frame_family_ref_phashes.json (no pixels,
# only hex strings).  At runtime, we crop the same border region from the
# uploaded image, compute its phash, and find the nearest reference family.
#
# Families qualify for region-hash when their within-family 1-NN accuracy
# is >= 88% on held-out images (nn_classification.json) AND the colour
# check agreement is 0% (meaning colour is unreliable for this family).
# From the coverage data, these are: NeonInk (100%), ShowcaseMagnified
# (92.3%), M15NyxShowcase (100%).  Woodland and StorybookWOE have good
# 1-NN accuracy but non-zero colour check, so they use furniture-colour
# instead.  All families in the reference set are checked; the threshold
# filtering happens via the hamming distance gate.
# ---------------------------------------------------------------------------

# Left border strip crop: captures the frame pattern without the art window.
# The art window typically starts at ~7% from the left edge (see
# _detect_showcase_magnified's art_left = 0.07), so this strip is
# purely frame/border/pinline content.
_FRAME_HASH_CROP_LEFT = 0.0
_FRAME_HASH_CROP_TOP = 0.0
_FRAME_HASH_CROP_RIGHT = 0.07
_FRAME_HASH_CROP_BOTTOM = 1.0

# Maximum hamming distance for a region-hash match.  The coverage data
# shows within-family distances ranging from 0-40 (mean ~18-32 depending
# on family), with between-family distances generally > 25.  A threshold
# of 25 balances recall against false positives on ordinary frames.
_FRAME_HASH_DISTANCE_MAX = 25

# Only search within families that qualify: ≥88% 1-NN accuracy on held-out
# images AND 0% colour check agreement (meaning colour is unreliable).
# From nn_classification.json: NeonInk (100%), ShowcaseMagnified (92.3%),
# M15NyxShowcase (100%).  Other families either have working colour checks
# or lack sufficient reference images.
REGION_HASH_FAMILIES: frozenset[str] = frozenset(
    {
        "NeonInk",
        "ShowcaseMagnified",
        "M15NyxShowcase",
    }
)

# Lazy-loaded reference phashes: family -> list of int phashes.
# Populated on first call to _detect_region_hash.
_ref_phashes_by_family: Optional[dict[str, list[int]]] = None


def _load_ref_phashes() -> dict[str, list[int]]:
    """Load reference phashes from the JSON artifact and convert to ints.

    The artifact (frame_family_ref_phashes.json) contains only hex strings -
    no pixels, no image data - satisfying the directive to store abstractions
    only.  This function is called once and cached in _ref_phashes_by_family.
    """
    import json
    from pathlib import Path

    json_path = Path(__file__).parent / "frame_family_ref_phashes.json"
    with open(json_path) as f:
        raw = json.load(f)

    from cardpicker.utils import twos_complement

    result: dict[str, list[int]] = {}
    for family, hex_list in raw.items():
        result[family] = [twos_complement(h, 64) for h in hex_list]
    return result


def _hamming_distance(a: int, b: int) -> int:
    """Hamming distance between two 64-bit phashes stored as signed ints."""
    return (a ^ b).bit_count()


def _detect_region_hash(image: Any) -> Optional[FrameFamilyResult]:
    """Detect frame family by perceptual hash comparison against references.

    Crops the left border strip from the uploaded image, computes a phash,
    and finds the nearest family in the reference set.  Returns a result
    with confidence CONFIDENCE_HIGH (2) when the best match is within
    _FRAME_HASH_DISTANCE_MAX hamming distance, or None otherwise.

    This method covers families where the colour check is unreliable
    (agreement 0%) but the frame texture is consistent enough for
    1-NN classification (within-family consistency >= 88%).
    """
    global _ref_phashes_by_family
    if _ref_phashes_by_family is None:
        _ref_phashes_by_family = _load_ref_phashes()

    image_phash = _image_region_phash(
        image,
        _FRAME_HASH_CROP_LEFT,
        _FRAME_HASH_CROP_TOP,
        _FRAME_HASH_CROP_RIGHT,
        _FRAME_HASH_CROP_BOTTOM,
    )
    if image_phash is None:
        return None

    best_family: Optional[str] = None
    best_distance: int = _FRAME_HASH_DISTANCE_MAX + 1

    for family, ref_hashes in _ref_phashes_by_family.items():
        if family not in REGION_HASH_FAMILIES:
            continue
        for ref_hash in ref_hashes:
            dist = _hamming_distance(image_phash, ref_hash)
            if dist < best_distance:
                best_distance = dist
                best_family = family

    if best_family is None or best_distance > _FRAME_HASH_DISTANCE_MAX:
        return None

    return FrameFamilyResult(
        family_class=best_family,
        confidence=CONFIDENCE_HIGH,
        method=METHOD_REGION_HASH,
    )


# ---------------------------------------------------------------------------
# Structural detectors (method 1 - deterministic, highest confidence).
# ---------------------------------------------------------------------------


def _detect_showcase_magnified(image: Any) -> bool:
    """Detect the circular ring window of ShowcaseMagnified frames.

    ShowcaseMagnified has a distinctive circular art window.  We detect this
    by measuring how much the content width varies across rows: a circle has
    content widest at the center and narrower at the edges, while a rectangle
    has uniform content width.  The fill-ratio (avg / max content width)
    for a circle is ~pi/4 (~0.785); for a full rectangle it is 1.0.
    """
    width, height = image.size
    art_left = int(0.07 * width)
    art_top = int(0.10 * height)
    art_right = int(0.93 * width)
    art_bottom = int(0.85 * height)

    art_region = image.crop((art_left, art_top, art_right, art_bottom)).convert("L")
    art_w, art_h = art_region.size
    if art_w <= 0 or art_h <= 0:
        return False

    pixels = list(art_region.getdata())
    sorted_px = sorted(pixels)
    median = sorted_px[len(sorted_px) // 2]

    row_widths = []
    for y in range(art_h):
        row_start = y * art_w
        row = pixels[row_start : row_start + art_w]
        row_widths.append(sum(1 for p in row if p > median))

    max_width = max(row_widths)
    if max_width <= 0:
        return False

    avg_width = sum(row_widths) / len(row_widths)
    fill_ratio = avg_width / max_width
    return fill_ratio < _MAGNIFIED_RING_AREA_RATIO_MIN


def _detect_pipboy(image: Any) -> bool:
    """Detect the CRT terminal / Pipboy frame aesthetic.

    Pipboy frames have a distinctive green-tinted scanline pattern in the header
    region.  We detect this by measuring the horizontal frequency of intensity
    transitions in the top 15% of the card.
    """
    width, height = image.size
    header_bottom = int(0.15 * height)
    if header_bottom <= 0:
        return False
    header = image.crop((0, 0, width, header_bottom)).convert("L")
    pixels = list(header.getdata())
    if len(pixels) < 10:
        return False
    # Count zero-crossings (intensity transitions) across the middle row
    mid_row_start = (header_bottom // 2) * width
    mid_row = pixels[mid_row_start : mid_row_start + width]
    if len(mid_row) < 3:
        return False
    transitions = sum(
        1
        for i in range(1, len(mid_row))
        if (mid_row[i] - mid_row[i - 1]) * (mid_row[i - 1] - mid_row[max(0, i - 2)]) < 0
    )
    freq = transitions / len(mid_row)
    return freq > _PIPBOY_SCANLINE_FREQ_MIN


def _detect_vault(image: Any) -> bool:
    """Detect the stepped metallic bracket framing of Vault frames.

    Vault frames have L-shaped brightness gradients in the four corners - a
    distinctive stepped bracket pattern.  We detect this by measuring the
    brightness gradient in each corner region.
    """
    width, height = image.size
    corner_size = int(0.08 * min(width, height))
    if corner_size <= 0:
        return False
    corners = [
        (0, 0, corner_size, corner_size),  # top-left
        (width - corner_size, 0, width, corner_size),  # top-right
        (0, height - corner_size, corner_size, height),  # bottom-left
        (width - corner_size, height - corner_size, width, height),  # bottom-right
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

    MysticalArchive frames have a distinctive dotted parchment nameplate in the
    type-line region.  We detect this by measuring the density of small bright
    spots in the type-line band.
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
    # Count pixels brighter than the mean + 1 standard deviation (bright spots)
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    stddev = math.sqrt(variance)
    threshold = mean + stddev
    bright_count = sum(1 for p in pixels if p > threshold)
    density = bright_count / len(pixels)
    return density > _MYSTICAL_ARCHIVE_DOT_DENSITY_MIN


def _detect_storybook(image: Any) -> bool:
    """Detect the vine scroll border of Storybook frames.

    Storybook frames have an irregular, vine-scroll border pattern.  We detect
    this by measuring the irregularity (stddev of edge brightness) along the
    card border.
    """
    width, height = image.size
    border_width = int(0.03 * min(width, height))
    if border_width <= 0:
        return False
    # Sample the left border strip
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


def classify_frame_family(
    image: Any,
    *,
    # Existing evidence fields consumed by fallback methods.
    art_edge_class: str = "",
    layout_class: str = "",
    pinline_inset_frac_top: Optional[float] = None,
    pinline_inset_frac_bottom: Optional[float] = None,
    pinline_inset_frac_left: Optional[float] = None,
    pinline_inset_frac_right: Optional[float] = None,
    art_crop_px: Optional[list[int]] = None,
) -> FrameFamilyResult:
    """Classify the frame family of a fetched card image.

    Runs the detection-method fallback chain cheapest-to-costliest:
      1. Structural construction (deterministic, confidence 3)
      2. Region-hash (confidence 2) - per-family reference phash comparison
         where colour check is unreliable (agreement 0%)
      3. Furniture colour (confidence 2) - skipped in this evidence-only pass
         (requires per-family reference colours)
      4. ArtBounds distance (confidence 1) - uses pinline_inset to check for
         a real border
      5. Variant-pinned (confidence 1) - skipped in this evidence-only pass
         (requires candidate name resolution)

    Method 3 and 5 require reference data that does not exist yet in this
    evidence-only pass.  They are stubbed here to return None so the fallback
    chain is structurally complete and future wiring is straightforward.
    """
    # --- Method 1: Structural construction detectors ---
    for family, detector in STRUCTURAL_DETECTORS.items():
        if detector(image):
            return FrameFamilyResult(
                family_class=family,
                confidence=CONFIDENCE_STRUCTURAL,
                method=METHOD_STRUCTURAL_CONSTRUCTION,
            )

    # --- Method 2: Region-hash (per-family reference phash comparison) ---
    region_hash_result = _detect_region_hash(image)
    if region_hash_result is not None:
        return region_hash_result

    # --- Method 3: Furniture colour (stubbed - no reference colours yet) ---
    # Requires per-family dominant-colour references.
    # pass

    # --- Method 4: ArtBounds distance (pinline-spread check) ---
    if (
        pinline_inset_frac_top is not None
        and pinline_inset_frac_bottom is not None
        and pinline_inset_frac_left is not None
        and pinline_inset_frac_right is not None
    ):
        top = pinline_inset_frac_top
        bottom = pinline_inset_frac_bottom
        left = pinline_inset_frac_left
        right = pinline_inset_frac_right
        # A real border has measurable inset on all four sides.  The spread
        # (max - min) indicates whether the border is consistent or if one
        # side is art reaching the edge (extended).
        fracs = [f for f in (top, bottom, left, right) if f is not None]
        if len(fracs) >= 3:
            spread = max(fracs) - min(fracs)
            avg_inset = sum(fracs) / len(fracs)
            # A real border has consistent inset (low spread) and measurable
            # average inset.  Extended art has high spread (one side near zero).
            if spread < ARTBOUNDS_PINLINE_SPREAD_MIN and avg_inset > 0.01:
                # Real border present - but we can't name the family from
                # pinline alone.  Mark as "standard" if layout_class is set,
                # otherwise abstain.
                if layout_class in ("black", "white", "silver"):
                    return FrameFamilyResult(
                        family_class=FRAME_FAMILY_STANDARD,
                        confidence=CONFIDENCE_MODERATE,
                        method=METHOD_ARTBOUNDS_DISTANCE,
                    )

    # --- Method 5: Variant-pinned (stubbed - needs candidate resolution) ---
    # Requires CandidateNameIndex.candidates_for, not available here.
    # pass

    # --- Abstain ---
    return FrameFamilyResult(
        family_class="",
        confidence=CONFIDENCE_ABSTAIN,
        method="",
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

    ONLY named, above-bar verdicts vote.  "STANDARD", "CUSTOM", "OTHER_SHOWCASE",
    and blank (abstain) are deliberately silent rather than casting a negative
    "Showcase" vote: a negative vote from an unvalidated class is a claim, not
    an abstention.

    Above-bar = confidence >= 2 AND family is one of the named structural families
    (the five fable-judge-confirmed families) or the named region-hash families.
    """
    if frame_family_confidence < CONFIDENCE_HIGH:
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
) -> FrameFamilyCastResult:
    """Cast coarse "Showcase" votes from stored frame-family evidence.

    Mirrors `local_art_edge.run_art_edge_continuity_cast`'s own pattern:
    eligible cards -> read stored evidence -> cast if above-bar -> log skips.
    """
    # Fail fast if the tag hasn't been seeded — same convention as
    # run_art_edge_continuity_cast: the caller (stage_e_dispatch) catches
    # and degrades gracefully; this function itself must not silently
    # swallow a missing tag.
    run_id = run_id or generate_run_id()

    tag = Tag.objects.filter(name=FRAME_FAMILY_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(f"Tag '{FRAME_FAMILY_TAG_NAME}' not found. " "Run seed_default_tags() before casting.")

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

    for card in _eligible_cards_queryset(card_ids).iterator():
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
            if family_confidence < CONFIDENCE_HIGH:
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
    "FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON",
    "FRAME_FAMILY_NO_READING_SKIP_REASON",
    "FRAME_FAMILY_AMBIGUOUS_SKIP_REASON",
    "FRAME_FAMILY_RESCANNABLE_SKIP_REASONS",
    "FrameFamilyResult",
    "classify_frame_family",
    "cast_frame_family_vote",
    "FrameFamilyCastResult",
    "run_frame_family_cast",
    "STRUCTURAL_FAMILIES",
]
