"""
Pass 2 fallback engine for the local printing-identification pilot
(cardpicker.local_identify_printing_tags, docs/features/printing-tags.md's Stage 8): fires only
when pass 1 (OCR/phash) yields no accepted vote for a card. The case that motivated it: old-
border frame cards have no collector line at all (an "Illus. <artist>" credit instead), and
their art frequently matches multiple reprints' art_crop near-identically, defeating phash's
distance/margin check by design, not by miscalibration - diagnosed live against real production
cards, 2026-07-15.

Evidence-combination model: each sub-check FILTERS the card's own name-candidates down to the
subset consistent with what it found, or produces no reading at all (in which case it doesn't
filter anything). A vote is written only when the intersection across every sub-check that DID
produce a reading narrows to EXACTLY ONE candidate, with the usual clear-margin rule inside the
sub-checks that need one (symbol matching). Distinct anonymous_id 'local-fallback-v1'.

Border-color sampling (2c) does double duty: besides filtering candidates here, it separately
casts a standalone CardTagVote on the matching border attribute chip tag (Black Border/White
Border/Silver Border/Borderless - see attribute_tags.py) for EVERY card either pass processes,
independent of whether a printing vote is ever cast - see cast_border_attribute_vote.

KNOWN FLOOR, handled by abstaining not straining: pre-Mirage core sets/expansions never printed
a set symbol on the card face at all (the concept didn't exist yet), so symbol matching can
never produce a reading for them - if border+artist evidence alone doesn't narrow to one
candidate either, these are expected permanent skips, not a bug. Not specially detected (would
need a hardcoded pre-Mirage set list, error-prone from memory) - just falls out naturally as an
"ambiguous"/"no-evidence" skip, which is the honest outcome for the same reason.
"""

import difflib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import imagehash
from PIL import Image, ImageDraw, ImageFont

from cardpicker import local_ocr
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)

if TYPE_CHECKING:
    from cardpicker.local_identify_printing_tags import CandidatePrinting, SelectedCard

logger = logging.getLogger(__name__)

FALLBACK_ANONYMOUS_ID = "local-fallback-v1"
FALLBACK_CONFIDENCE_MULTI_EVIDENCE = 0.8
FALLBACK_CONFIDENCE_SINGLE_EVIDENCE = 0.7
BORDER_ATTRIBUTE_VOTE_CONFIDENCE = 0.75
# used instead of BORDER_ATTRIBUTE_VOTE_CONFIDENCE/FRAME_VOTE_CONFIDENCE when the border/frame
# class comes from the matched printing's own CanonicalPrintingMetadata (Scryfall data) rather
# than this module's pixel/OCR heuristics - see run_pilot's ground-truth-preferred wiring.
# Purely informational (confidence isn't consumed by vote_consensus's weighting, only `source`
# is - see vote_consensus.py's _SOURCE_WEIGHTS), but an honest record of how much more certain
# a ground-truth reading is than an estimate from the same OCR-weight source.
GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE = 0.95

# ---------------------------------------------------------------------------------------------
# 2a: artist OCR - full-width bottom band (not pass 1's narrower left-side collector-line crop):
# old border prints "Illus. <name>" centred at the very bottom; modern frames put the artist
# name beside a brush glyph inside the same collector-line region pass 1 already crops, so this
# band is deliberately wider/taller to catch either.
# ---------------------------------------------------------------------------------------------

ARTIST_CROP_BOX: tuple[float, float, float, float] = (0.0, 0.82, 1.0, 1.0)
ARTIST_FUZZY_MATCH_THRESHOLD = 0.8

# tesseract commonly misreads "Illus." as "1llus."/"llus." (I/l/1 confusion at small sizes) -
# tolerant on the prefix, since the validation is the fuzzy artist-name match downstream, not
# this extraction.
_ILLUS_RE = re.compile(r"[il1]llus[.:]?\s*([A-Za-z][A-Za-z.'\- ]{2,40})", re.IGNORECASE)


def extract_artist_name(raw_text: str) -> Optional[str]:
    match = _ILLUS_RE.search(raw_text)
    if match is None:
        return None
    return match.group(1).strip().rstrip(".")


def match_artist(
    extracted_name: str, candidates: list["CandidatePrinting"], artist_by_pk: dict[int, str]
) -> Optional[set[int]]:
    """Fuzzy-matches `extracted_name` against each candidate's OWN artist only (never the full
    CanonicalArtist table - a card's candidates already narrow the search space, and matching
    outside it risks a plausible-sounding but wrong artist). Returns None (no reading) if
    nothing clears the threshold; a set of surviving candidate pks otherwise (usually 0 or 1,
    but ties are possible and left to the caller's intersection to resolve)."""
    surviving = set()
    for candidate in candidates:
        artist_name = artist_by_pk.get(candidate.pk)
        if artist_name is None:
            continue
        ratio = difflib.SequenceMatcher(None, extracted_name.lower(), artist_name.lower()).ratio()
        if ratio >= ARTIST_FUZZY_MATCH_THRESHOLD:
            surviving.add(candidate.pk)
    return surviving or None


def detect_illus_anchor(
    card_image: "Image.Image", ocr_raw_texts: list[str], bleed_class: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """The "Illus." extraction step, standalone from candidate matching - used both by
    run_fallback_for_card (which also needs the extracted name for match_artist) and by the
    frame-style classifier (which only needs to know whether the anchor fired at all, for
    every card regardless of whether pass 1 already produced a printing vote - see
    classify_frame_style). Returns (fired, extracted_name); reuses `ocr_raw_texts` (pass 1's
    already-computed OCR variants) before falling back to its own crop/OCR pass, same
    rationale as run_fallback_for_card's identical shortcut. `bleed_class` (from
    classify_bleed_edge, run once per card ahead of everything else - see run_pilot) remaps
    ARTIST_CROP_BOX for a trimmed image via normalize_crop_box; a no-op otherwise."""
    for text in ocr_raw_texts:
        name = extract_artist_name(text)
        if name is not None:
            return True, name
    artist_crop = local_ocr.crop_collector_line(card_image, normalize_crop_box(ARTIST_CROP_BOX, bleed_class))
    for variant in local_ocr.preprocess_variants(artist_crop):
        name = extract_artist_name(local_ocr.run_tesseract(variant))
        if name is not None:
            return True, name
    return False, None


# ---------------------------------------------------------------------------------------------
# 2b: set-symbol matching - keyrune glyph rendered locally (cardpicker/local_pilot_data/keyrune,
# vendored from the keyrune npm package, SIL OFL 1.1 - see that directory's LICENSE.md) compared
# against a scanned window of a right-side strip via phash. No network calls.
# ---------------------------------------------------------------------------------------------

_KEYRUNE_DIR = Path(__file__).parent / "local_pilot_data" / "keyrune"
_KEYRUNE_FONT_PATH = _KEYRUNE_DIR / "keyrune.ttf"
_KEYRUNE_CODEPOINTS_PATH = _KEYRUNE_DIR / "codepoints.json"

# right-side vertical strip spanning the type-line band across both frame geometries - modern
# frame's type line sits just below the art box (which ends ~58% down, see local_phash.py's
# ART_CROP_BOX), old frames run slightly earlier - generous on purpose, the window scan below
# is what actually locates the symbol rather than trusting one fixed y.
SYMBOL_STRIP_BOX: tuple[float, float, float, float] = (0.78, 0.55, 1.0, 0.80)
SYMBOL_WINDOW_HEIGHT_FRACTION = 0.09  # of full card height, slid down the strip
SYMBOL_WINDOW_STEP_FRACTION = 0.02
SYMBOL_RENDER_SIZE = 64

# NOT reliable evidence - measured live against real cards, 2026-07-15, and kept this strict
# deliberately: scanning a window of a real (photographed/JPEG, in-context, surrounded by
# frame chrome) card region against a clean vector-rendered keyrune glyph does not discriminate
# via phash at this scale. Concretely: the correct set's distance and several wrong sets'
# distances all cluster within 2-4 of each other (e.g. one real card: mir=22, som=24, ktk=20 -
# the WRONG set scored better than the right one), and this held across multiple unrelated
# cards, including ones with no visible symbol in frame at all - strong evidence the signal
# floor here is noise, not a tuning problem margin/threshold can fix. Rather than drop this
# sub-check's code (a smarter approach - real object detection, or plain pixel correlation
# instead of phash - might work better later), the threshold is set low enough that it never
# actually returns a match given the observed noise floor sits at 20+ - so it always reads as
# "no evidence" (None, filters nothing) instead of contributing a confidently-wrong reading.
# Tightening this threshold correctly is exactly what a future pass at this sub-check should
# revisit, not something to guess correctly right now.
SYMBOL_DISTANCE_THRESHOLD = 6
SYMBOL_MARGIN = 6


@lru_cache(maxsize=1)
def _load_keyrune_codepoints() -> dict[str, str]:
    import json

    with open(_KEYRUNE_CODEPOINTS_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_keyrune_font() -> "ImageFont.FreeTypeFont":
    return ImageFont.truetype(str(_KEYRUNE_FONT_PATH), SYMBOL_RENDER_SIZE)


def render_set_symbol(expansion_code: str) -> Optional["Image.Image"]:
    codepoints = _load_keyrune_codepoints()
    hex_codepoint = codepoints.get(expansion_code.lower())
    if hex_codepoint is None:
        return None
    char = chr(int(hex_codepoint, 16))
    image = Image.new("L", (SYMBOL_RENDER_SIZE, SYMBOL_RENDER_SIZE), 255)
    draw = ImageDraw.Draw(image)
    draw.text((0, 0), char, font=_load_keyrune_font(), fill=0)
    return image


def _scan_strip_for_best_symbol_window(strip: "Image.Image", reference: "Image.Image") -> int:
    """Slides a square window down `strip`, returns the minimum phash distance against
    `reference` across every window position - the symbol's exact y within the strip varies by
    frame era, so this searches rather than assumes one."""
    width, height = strip.size
    window_size = min(width, int(height * SYMBOL_WINDOW_HEIGHT_FRACTION / (SYMBOL_STRIP_BOX[3] - SYMBOL_STRIP_BOX[1])))
    window_size = max(window_size, 8)
    step = max(1, int(window_size * SYMBOL_WINDOW_STEP_FRACTION / SYMBOL_WINDOW_HEIGHT_FRACTION))
    reference_hash = imagehash.phash(reference)

    best_distance: Optional[int] = None
    y = 0
    while y + window_size <= height:
        window = strip.crop((0, y, min(width, window_size), y + window_size)).convert("L")
        distance = imagehash.phash(window) - reference_hash
        if best_distance is None or distance < best_distance:
            best_distance = distance
        y += step
    return best_distance if best_distance is not None else 999


def find_symbol_matches(
    card_image: "Image.Image",
    candidates: list["CandidatePrinting"],
    expansion_code_by_pk: dict[int, str],
    bleed_class: Optional[str] = None,
) -> Optional[set[int]]:
    """Compares the card's symbol strip against each DISTINCT candidate expansion's rendered
    keyrune glyph (candidates sharing an expansion never need re-comparing), returns the
    candidates whose expansion produced the best distance within threshold and clear of the
    margin - None if no expansion's glyph could even be rendered (unmapped code) or nothing
    cleared the threshold at all. `bleed_class` remaps SYMBOL_STRIP_BOX via normalize_crop_box
    for a trimmed image; a no-op otherwise."""
    width, height = card_image.size
    left, top, right, bottom = normalize_crop_box(SYMBOL_STRIP_BOX, bleed_class)
    strip = card_image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height))).convert(
        "L"
    )

    distance_by_expansion: dict[str, int] = {}
    for expansion_code in {expansion_code_by_pk[c.pk] for c in candidates if c.pk in expansion_code_by_pk}:
        reference = render_set_symbol(expansion_code)
        if reference is None:
            continue
        distance_by_expansion[expansion_code] = _scan_strip_for_best_symbol_window(strip, reference)

    if not distance_by_expansion:
        return None

    ranked = sorted(distance_by_expansion.items(), key=lambda pair: pair[1])
    best_expansion, best_distance = ranked[0]
    if best_distance > SYMBOL_DISTANCE_THRESHOLD:
        return None
    if len(ranked) > 1 and (ranked[1][1] - best_distance) <= SYMBOL_MARGIN:
        return None

    return {c.pk for c in candidates if expansion_code_by_pk.get(c.pk) == best_expansion}


# ---------------------------------------------------------------------------------------------
# 2c: border-color sample - nearly free, applied before 2a/2b in the filter chain per spec.
# Also independently casts a standalone attribute-chip CardTagVote for every card either pass
# processes (cast_border_attribute_vote), regardless of whether a printing vote ever lands.
# ---------------------------------------------------------------------------------------------

# thin bands just inside each edge, avoiding rounded-corner artifacts right at the corners
# themselves - (left, top, right, bottom) fractions of the full image.
_BORDER_SAMPLE_BANDS: list[tuple[float, float, float, float]] = [
    (0.03, 0.15, 0.05, 0.85),  # left edge
    (0.95, 0.15, 0.97, 0.85),  # right edge
    (0.15, 0.02, 0.85, 0.035),  # top edge
    (0.15, 0.965, 0.85, 0.98),  # bottom edge
]
_BORDER_UNIFORMITY_STD_THRESHOLD = 18.0  # per-channel std dev below this = "uniform enough"
_BLACK_MAX_BRIGHTNESS = 60
_WHITE_MIN_BRIGHTNESS = 210
_SILVER_BRIGHTNESS_RANGE = (140, 200)
_SILVER_MAX_SATURATION = 20  # small R/G/B spread = neutral gray, not a color

BORDER_COLOR_TO_TAG: dict[str, str] = {
    "black": "Black Border",
    "white": "White Border",
    "silver": "Silver Border",
    "borderless": "Borderless",
}


def classify_border_color(card_image: "Image.Image", bleed_class: Optional[str] = None) -> Optional[str]:
    """Returns 'black'/'white'/'silver'/'borderless', or None if the sample is ambiguous
    (non-uniform - e.g. art bleeding right to the edge in a way that doesn't read as a clean
    'borderless' card, or a color this taxonomy doesn't cover, e.g. gold/yellow - out of scope,
    see docs/features/printing-tags.md's chip taxonomy v1 exclusions). `bleed_class` remaps each
    of _BORDER_SAMPLE_BANDS via normalize_crop_box for a trimmed image; a no-op otherwise -
    empirically checked (2026-07-15) that solid-color borders read identical RGB with or without
    this remap on real bleed-inclusive images (border color extends uniformly through the bleed
    margin), so applying it here unconditionally doesn't risk the majority case."""
    import statistics

    width, height = card_image.size
    samples: list[tuple[int, int, int]] = []
    stds: list[float] = []
    for left, top, right, bottom in (normalize_crop_box(band, bleed_class) for band in _BORDER_SAMPLE_BANDS):
        band = card_image.crop(
            (int(left * width), int(top * height), int(right * width), int(bottom * height))
        ).convert("RGB")
        pixels = list(band.getdata())
        if not pixels:
            continue
        r = statistics.mean(p[0] for p in pixels)
        g = statistics.mean(p[1] for p in pixels)
        b = statistics.mean(p[2] for p in pixels)
        samples.append((r, g, b))
        stds.append(statistics.pstdev([p[0] for p in pixels]))

    if not samples:
        return None

    avg_r = statistics.mean(s[0] for s in samples)
    avg_g = statistics.mean(s[1] for s in samples)
    avg_b = statistics.mean(s[2] for s in samples)
    brightness = (avg_r + avg_g + avg_b) / 3
    saturation = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)
    uniform = statistics.mean(stds) < _BORDER_UNIFORMITY_STD_THRESHOLD

    if not uniform:
        # high-variance edge pixels = actual image content right at the border, not a
        # painted/printed border at all
        return "borderless"
    if brightness <= _BLACK_MAX_BRIGHTNESS:
        return "black"
    if brightness >= _WHITE_MIN_BRIGHTNESS:
        return "white"
    if (
        _SILVER_BRIGHTNESS_RANGE[0] <= brightness <= _SILVER_BRIGHTNESS_RANGE[1]
        and saturation <= _SILVER_MAX_SATURATION
    ):
        return "silver"
    return None


def filter_by_border_color(
    border_color: Optional[str], candidates: list["CandidatePrinting"], border_color_by_pk: dict[int, str]
) -> Optional[set[int]]:
    if border_color is None:
        return None
    matching = {c.pk for c in candidates if border_color_by_pk.get(c.pk) == border_color}
    return matching or None


def cast_border_attribute_vote(
    card: Card,
    border_color: Optional[str],
    confidence: float = BORDER_ATTRIBUTE_VOTE_CONFIDENCE,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """An unsaved CardTagVote instance ready for bulk_create, or None if the sample was
    ambiguous or the classified color has no attribute-chip tag (gold/yellow - excluded from
    the v1 taxonomy, see attribute_tags.py). Caller batches these across the whole pilot run.
    `confidence` defaults to the heuristic tier - callers pass GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE
    when `border_color` came from the matched printing's own metadata instead of the pixel sample.
    `run_id`: docs/features/catalog-completion-plan.md's Part 1 - the caller's own per-invocation
    run_id, threaded through so this vote is revocable the same way printing votes are."""
    if border_color is None:
        return None
    tag_name = BORDER_COLOR_TO_TAG.get(border_color)
    if tag_name is None:
        return None
    tag = Tag.objects.filter(name=tag_name).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.APPLY,
        anonymous_id=FALLBACK_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=confidence,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------------------------
# Frame-style votes (existing "Old Border"/"Modern Border" attribute chip tags only - see
# attribute_tags.py; never seeds new tags, per instruction). Classification reuses signals the
# pipeline already extracts, no new image processing:
#   - pass 1 (OCR) extracted a plausible collector number, with or without a set code (2015/M15
#     prints a full "set collector" strip; 2003-2014 prints just a brush-glyph + number, no set
#     code - both are post-2003 "modern" frame families, and this taxonomy only distinguishes
#     old/modern/future, not the finer 2003-vs-2015 split, so both collapse to the same tag) ->
#     "modern"
#   - the "Illus." anchor fired (2a) instead -> "old" (retro frame, pre-2003 - no collector
#     line printed on the card face at all, just a centred artist credit)
#   - neither -> abstain (None), counted
# ---------------------------------------------------------------------------------------------

FRAME_VOTE_CONFIDENCE = 0.7  # heuristic tier - lower than the border sample's 0.75

FRAME_STYLE_TO_TAG: dict[str, str] = {
    "old": "Old Border",
    "modern": "Modern Border",
}

# CanonicalPrintingMetadata.frame raw values -> this taxonomy's two reachable classes ("future"
# has its own "Future Frame" tag, but nothing in this classifier's signal set can ever produce
# it - a future-frame printing will always read as a consistency mismatch against whatever this
# classifier says, an accepted limitation given how rare that frame is, see module docstring).
FRAME_VALUE_TO_CLASS: dict[str, str] = {
    "1993": "old",
    "1997": "old",
    "2003": "modern",
    "2015": "modern",
}


def classify_frame_style(parsed_a_collector_number: bool, illus_anchor_fired: bool) -> Optional[str]:
    if parsed_a_collector_number:
        return "modern"
    if illus_anchor_fired:
        return "old"
    return None


def cast_frame_style_vote(
    card: Card,
    frame_class: Optional[str],
    confidence: float = FRAME_VOTE_CONFIDENCE,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """`confidence` defaults to the heuristic tier - callers pass
    GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE when `frame_class` came from the matched printing's
    own metadata (via FRAME_VALUE_TO_CLASS) instead of this module's OCR/Illus.-anchor signals.
    `run_id`: see cast_border_attribute_vote's own docstring - identical rationale."""
    if frame_class is None:
        return None
    tag_name = FRAME_STYLE_TO_TAG.get(frame_class)
    if tag_name is None:
        return None
    tag = Tag.objects.filter(name=tag_name).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.APPLY,
        anonymous_id=FALLBACK_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=confidence,
        run_id=run_id,
    )


def frame_style_is_consistent(frame_class: Optional[str], printing_frame_value: Optional[str]) -> bool:
    """True when there's nothing to compare (either side unresolved/unknown - e.g. no frame
    reading this run, or the matched printing predates/postdates the two reachable classes) OR
    the two agree. False ONLY on a confirmed disagreement - the caller withholds the printing
    vote in that case (see module docstring's CONSISTENCY CHECK), since an art match landing on
    a printing whose real frame contradicts what's actually visible on the card face means the
    image most likely doesn't faithfully depict that specific printing (a frame-converted
    proxy), not that the printing match itself was wrong."""
    if frame_class is None or not printing_frame_value:
        return True
    expected_class = FRAME_VALUE_TO_CLASS.get(printing_frame_value)
    if expected_class is None:
        return True
    return expected_class == frame_class


# ---------------------------------------------------------------------------------------------
# 2c.5: bleed-edge classification, addendum item 7. Owner-directed design (2026-07-15): measure
# the image's own aspect ratio against chilli_axe's two known reference ratios (trim-only vs.
# trim-plus-bleed) rather than any pixel/color heuristic - geometric, resolution/DPI-independent,
# and (unlike a color-uniformity approach) inherently unaffected by whether the card's own border
# is visually a normal frame or borderless full-art, since the file's raw pixel dimensions carry
# the same trim/bleed math either way. Votes on the PRE-EXISTING `appropriate-bleed` SENSITIVE
# tag (sensitive_tags.py) - a moderator co-sign is still required to resolve it either direction,
# per that tag's own design; this heuristic is one more signal, not an override.
# ---------------------------------------------------------------------------------------------

# frontend/src/common/constants.ts's CardWidthMM/CardHeightMM - the standard MTG trim size
# (63x88mm) chilli_axe's own frame templates are built against.
_CARD_TRIM_WIDTH_MM = 63
_CARD_TRIM_HEIGHT_MM = 88
_BLEED_MARGIN_MM = 3.175  # 1/8 inch per edge - the standard proxy-print bleed convention

TRIM_ASPECT_RATIO = _CARD_TRIM_WIDTH_MM / _CARD_TRIM_HEIGHT_MM
BLEED_ASPECT_RATIO = (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM) / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)

# What fraction of the full image the bleed margin occupies per edge, on each axis - derived
# from the same reference geometry above, not a separate guess. Every fixed-fraction crop box
# in this module and local_ocr/local_phash (DEFAULT_CROP_BOX, ART_CROP_BOX, ARTIST_CROP_BOX,
# SYMBOL_STRIP_BOX, _BORDER_SAMPLE_BANDS) was empirically tuned against real fetched images,
# which are ~97.5% bleed-inclusive (see the 40-source validation above) - meaning those boxes
# are already implicitly calibrated for THAT convention, not a separate one needing correction.
# The ~2.5% TRIMMED minority is the one case where a box tuned against bleed-inclusive images
# lands in the wrong place: removing the bleed margin shifts where the same physical card
# position falls as a fraction of the (now smaller) full image.
_WIDTH_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM)
_HEIGHT_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)


def normalize_crop_box(
    box: tuple[float, float, float, float], bleed_class: Optional[str]
) -> tuple[float, float, float, float]:
    """Remaps a fixed-fraction crop box (tuned against a bleed-inclusive image, per the module
    comment above) onto a TRIMMED image's own coordinate space - a no-op (returns `box`
    unchanged) for 'bleed' or None (abstain - no confident reading, so no correction to apply
    either), since those cases are already the convention the box was tuned against.

    Empirically checked before use (2026-07-15, not just derived): sampled real bleed-classified
    cards' border-color bands with and without this remap applied - solid-color borders (the
    common case) read IDENTICAL RGB regardless of exact sample position within the bleed zone
    (border color extends uniformly through the bleed margin), confirming this is safe to apply
    unconditionally across all five fixed-fraction crop sites without a special case for any one
    of them.
    """
    if bleed_class != "trimmed":
        return box
    left, top, right, bottom = box

    def _rescale(fraction: float, margin_fraction: float) -> float:
        # clamped to [0, 1]: a box (or band, like _BORDER_SAMPLE_BANDS' edge samples) that sat
        # entirely within the bleed margin on the original bleed-inclusive convention rescales
        # to at-or-past the trimmed image's own edge - genuinely degenerate for a trimmed image
        # (that content doesn't exist anymore, it was cut off), not a bug in the math. Callers
        # already handle a resulting zero-area crop gracefully (empty-sample skip, see
        # classify_border_color).
        return min(1.0, max(0.0, (fraction - margin_fraction) / (1 - 2 * margin_fraction)))

    return (
        _rescale(left, _WIDTH_MARGIN_FRACTION),
        _rescale(top, _HEIGHT_MARGIN_FRACTION),
        _rescale(right, _WIDTH_MARGIN_FRACTION),
        _rescale(bottom, _HEIGHT_MARGIN_FRACTION),
    )


# real-world validation (2026-07-15, 40 cards sampled across 40 distinct sources): the bleed
# cluster spread 0.7325-0.7393 (theoretical 0.7350), the one trimmed example measured 0.7163
# (theoretical 0.7159) - a clean, well-separated bimodal signal with nothing observed in the
# gap between clusters. 0.03 comfortably covers the observed bleed spread on either side while
# still abstaining on an aspect ratio implausible for a standard MTG card altogether (a
# double-faced composite scan, a token, a corrupted fetch).
_BLEED_CLASSIFICATION_TOLERANCE = 0.03

BLEED_EDGE_TAG_NAME = "appropriate-bleed"
BLEED_EDGE_VOTE_CONFIDENCE = 0.7


def classify_bleed_edge(card_image: "Image.Image") -> Optional[str]:
    """Returns 'bleed'/'trimmed', or None if the image's aspect ratio is too far from BOTH known
    reference ratios to classify confidently (ambiguous - a genuinely non-standard image, not
    just a borderline case)."""
    width, height = card_image.size
    if height == 0:
        return None
    ratio = width / height
    dist_to_trim = abs(ratio - TRIM_ASPECT_RATIO)
    dist_to_bleed = abs(ratio - BLEED_ASPECT_RATIO)
    if min(dist_to_trim, dist_to_bleed) > _BLEED_CLASSIFICATION_TOLERANCE:
        return None
    return "bleed" if dist_to_bleed < dist_to_trim else "trimmed"


def cast_bleed_edge_vote(card: Card, bleed_class: Optional[str], run_id: Optional[str] = None) -> Optional[CardTagVote]:
    """Negative-only (2026-07-15, consolidated respec item 4b, supersedes this function's
    original both-directions design): a vote is cast ONLY for a clearly 'trimmed' reading
    (NOT_APPLICABLE) - no vote at all for 'bleed' (the ~97.5% common case, per the 40-source
    validation) or an ambiguous/unclassifiable reading. Absence of any vote is the documented
    convention for "this card has normal bleed" - see BLEED_EDGE_TAG_NAME's own description and
    docs/features/printing-tags.md's Stage 8 section. Rationale: `appropriate-bleed` is a
    SENSITIVE tag needing moderator co-sign regardless of machine votes - voting APPLY on the
    routine 97.5% case would flood moderation with confirmations of normalcy rather than
    surfacing the rare real exception, which is what a SENSITIVE tag is for. `run_id`: see
    cast_border_attribute_vote's own docstring - identical rationale."""
    if bleed_class != "trimmed":
        return None
    tag = Tag.objects.filter(name=BLEED_EDGE_TAG_NAME).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.NOT_APPLICABLE,
        anonymous_id=FALLBACK_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=BLEED_EDGE_VOTE_CONFIDENCE,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------------------------
# 2d: combine
# ---------------------------------------------------------------------------------------------


@dataclass
class FallbackOutcome:
    printing_pk: Optional[int] = None
    evidence_types_used: list[str] = field(default_factory=list)
    skip_reason: str = ""
    # whether the "Illus." anchor was found at all (independent of whether the extracted name
    # went on to fuzzy-match a candidate) - the frame-style classifier's "old border" signal,
    # see classify_frame_style.
    illus_anchor_fired: bool = False


def run_fallback_for_card(
    selected: "SelectedCard",
    card_image: "Image.Image",
    ocr_raw_texts: list[str],
    bleed_class: Optional[str] = None,
) -> FallbackOutcome:
    """`ocr_raw_texts` reuses pass 1's already-computed OCR variants where available (the
    orchestrator passes whatever it already ran) - this only runs the extra full-width artist
    crop/OCR pass when pass 1's own text didn't already contain an "Illus." match, avoiding a
    redundant tesseract call on cards where the artist line already happened to be visible in
    the narrower pass-1 crop. `bleed_class` (from classify_bleed_edge, run once per card ahead
    of everything else - see run_pilot) is threaded through to every sub-check's own
    fixed-fraction crop box via normalize_crop_box."""
    candidate_pks = {c.pk for c in selected.candidates}
    canonicals = {
        c.pk: c
        for c in CanonicalCard.objects.select_related("artist", "printing_metadata").filter(pk__in=candidate_pks)
    }
    artist_by_pk = {pk: c.artist.name for pk, c in canonicals.items()}
    expansion_code_by_pk = {c.pk: c.expansion_code for c in selected.candidates}
    border_color_by_pk = {
        pk: c.printing_metadata.border_color
        for pk, c in canonicals.items()
        if getattr(c, "printing_metadata", None) is not None and c.printing_metadata.border_color
    }

    border_color = classify_border_color(card_image, bleed_class)
    border_filtered = filter_by_border_color(border_color, selected.candidates, border_color_by_pk)

    illus_anchor_fired, artist_name = detect_illus_anchor(card_image, ocr_raw_texts, bleed_class)
    artist_filtered = match_artist(artist_name, selected.candidates, artist_by_pk) if artist_name else None

    symbol_filtered = find_symbol_matches(card_image, selected.candidates, expansion_code_by_pk, bleed_class)

    survivors = set(candidate_pks)
    evidence_types_used: list[str] = []
    for name, filtered in (("border", border_filtered), ("artist", artist_filtered), ("symbol", symbol_filtered)):
        if filtered is not None:
            survivors &= filtered
            evidence_types_used.append(name)

    if not evidence_types_used:
        return FallbackOutcome(skip_reason="no-evidence", illus_anchor_fired=illus_anchor_fired)
    if len(survivors) == 0:
        return FallbackOutcome(
            skip_reason="eliminated", evidence_types_used=evidence_types_used, illus_anchor_fired=illus_anchor_fired
        )
    if len(survivors) > 1:
        return FallbackOutcome(
            skip_reason="ambiguous", evidence_types_used=evidence_types_used, illus_anchor_fired=illus_anchor_fired
        )

    return FallbackOutcome(
        printing_pk=next(iter(survivors)),
        evidence_types_used=evidence_types_used,
        illus_anchor_fired=illus_anchor_fired,
    )


__all__ = [
    "FALLBACK_ANONYMOUS_ID",
    "FALLBACK_CONFIDENCE_MULTI_EVIDENCE",
    "FALLBACK_CONFIDENCE_SINGLE_EVIDENCE",
    "BORDER_ATTRIBUTE_VOTE_CONFIDENCE",
    "GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE",
    "BORDER_COLOR_TO_TAG",
    "FRAME_VOTE_CONFIDENCE",
    "FRAME_STYLE_TO_TAG",
    "FRAME_VALUE_TO_CLASS",
    "ARTIST_CROP_BOX",
    "extract_artist_name",
    "match_artist",
    "detect_illus_anchor",
    "render_set_symbol",
    "find_symbol_matches",
    "classify_border_color",
    "filter_by_border_color",
    "cast_border_attribute_vote",
    "classify_frame_style",
    "cast_frame_style_vote",
    "frame_style_is_consistent",
    "TRIM_ASPECT_RATIO",
    "BLEED_ASPECT_RATIO",
    "BLEED_EDGE_TAG_NAME",
    "BLEED_EDGE_VOTE_CONFIDENCE",
    "classify_bleed_edge",
    "cast_bleed_edge_vote",
    "normalize_crop_box",
    "FallbackOutcome",
    "run_fallback_for_card",
]
