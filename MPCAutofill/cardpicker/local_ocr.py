"""
L1 engine for the local printing-identification pilot (cardpicker.local_identify_printing_tags,
docs/features/printing-tags.md's Stage 8): Tesseract OCR on the collector-line crop.

The validation rail is what makes weak OCR safe to vote on at all: a parsed (set, collector
number) pair only casts a vote when it matches EXACTLY ONE of the card's own name-candidates
(cardpicker.local_identify_printing_tags.CandidateNameIndex) - this module extracts a
best-effort reading, it never has to be trusted on its own.
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import pytesseract
from PIL import Image, ImageOps

if TYPE_CHECKING:
    from cardpicker.local_identify_printing_tags import CandidatePrinting

logger = logging.getLogger(__name__)

# left 6-35% width, bottom 90-96.5% height - tuned against real production images (2026-07-15):
# the original 85% top boundary caught a full trailing line of rules text above the collector
# line on several real cards, which confused tesseract's line segmentation into garbage output
# even with PSM 6. (left, top, right, bottom), each a fraction of the full image.
#
# Tightened from an original (0.0, 0.90, 0.35, 1.0) via pre-scale program item 3c/addendum item
# 6b (2026-07-15): tesseract's TSV bbox output, sampled across 30 real production cards, showed
# every observed collector-number-shaped text line landing within the top 41.2% / right-hand
# 74.4% of that original crop's own area - the bottom ~59% and left ~26% were dead space. New
# boundaries applied a safety margin over the observed range rather than cutting exactly to it
# (~1.5x on the trimmed bottom, ~0.7x on the trimmed left), specifically BECAUSE physical bleed
# margin varies by card/source and a tight cut against one sample's exact observed range risks
# clipping a card with more bleed than this sample happened to show. The right edge was left
# UNCHANGED despite being a plausible-looking trim target - text was observed touching that
# boundary already (right_frac max = 1.000), meaning trimming it would be a real clipping risk,
# not a safe optimization. Validated (not just derived) against the same 30-card sample: OCR
# match count and the exact set of matched cards were IDENTICAL between the old and new box (8/30
# both ways, same 8 card pks) - zero yield regression on this sample. 30 cards is a real but
# modest validation bar (matching the addendum's own ask); watch for regression during the actual
# scaled run rather than treating this as proven at full-catalog scale.
DEFAULT_CROP_BOX: tuple[float, float, float, float] = (0.06, 0.90, 0.35, 0.965)

# tesseract page-segmentation mode 6 = "assume a single uniform block of text" - the real
# collector "line" is usually two lines (rarity+number, then set+lang+artist), which PSM 7
# ("single text line") cannot handle: verified live against a real card image, PSM 7 jumbled
# both lines into nonsense ("is : 7") while PSM 6 read them cleanly ("R146" / "MIR EN...").
TESSERACT_CONFIG = "--psm 6"

# set code: 3-5 alnum (covers the common 3-char case and 4-5 char codes like promo/commander
# sets); collector number: digits, optionally with a single trailing letter (variant suffix,
# e.g. "123a") or a leading star (special/promo numbering, e.g. "★123"), stripped not matched
# since it doesn't appear in CanonicalCard.collector_number. Deliberately NOT anchored to
# whitespace/string-start before the digits (an earlier version was, and missed real matches
# live: a rarity letter directly abutting the number with no space, e.g. "R146", is common
# enough in real OCR output - possibly a genuine missing space in the source image, possibly
# tesseract dropping a thin space - that requiring one silently discarded correct reads).
_SET_CODE_RE = re.compile(r"\b([A-Za-z0-9]{3,5})\b")
_COLLECTOR_NUMBER_RE = re.compile(r"★?(\d{1,4}[A-Za-z]?)\b")

# legal/copyright line (Stage C issue #151/task #159): same y-band DEFAULT_CROP_BOX was tuned
# against (bottom 90-96.5% height - see that constant's own comment for the tuning history),
# widened to the FULL card width rather than DEFAULT_CROP_BOX's narrow left-hand 6-35% window -
# a real MTG copyright legend ("™ & © 2023 Wizards of the Coast") sits on the same physical
# print row as the collector line but commonly runs further right than DEFAULT_CROP_BOX's own
# crop captures. Verified against real fetched production images (golden-set gathering, see
# golden_set.py's own "legal_line" comment) before being locked in, per the same "don't invent a
# box from memory" discipline every other *_crop_px field in this pipeline followed.
LEGAL_LINE_CROP_BOX: tuple[float, float, float, float] = (0.0, 0.90, 1.0, 0.965)

# copyright year: prefer a year anchored to an actual copyright glyph/word ("©", "(c)",
# "copyright") over a bare 4-digit run elsewhere in the line - a 4-digit collector number (e.g. a
# Secret Lair/promo product's numbering) could otherwise be misread as a year. \D{0,10} tolerates
# the "&"/"™"/whitespace noise tesseract commonly inserts between the glyph and the digits.
_COPYRIGHT_YEAR_RE = re.compile(r"(?:©|\(c\)|copyright)\D{0,10}((?:19|20)\d{2})", re.IGNORECASE)
_BARE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Proxy/non-authentic markers (the real motivating case, task #151/#159: a "MTG★EN ... NOT FOR
# SALE ©2022" watermark misparsed as a genuine collector line). Deliberately a plain, easy-to-audit
# literal match rather than a fuzzier OCR-noise-tolerant pattern (unlike _COLLECTOR_NUMBER_RE's
# no-space tolerance, which fixed a real missed-match case) - a missed marker here silently drops
# the moderator flag with no other downstream signal to catch it, so a pattern that could start
# matching genuine legal text this taxonomy hasn't seen is a worse trade than an occasional miss
# on garbled OCR. Case-insensitive, tolerant of "NOT-FOR-SALE"/"NOT   FOR SALE" spacing/hyphen
# variants only - not of letter-substitution noise.
_PROXY_MARKER_RE = re.compile(r"not[\s-]*for[\s-]*sale|\bproxy\b", re.IGNORECASE)


@dataclass(frozen=True)
class OcrParseResult:
    raw_text: str
    set_code: Optional[str]  # lowercased, or None if nothing plausible was found
    collector_number: Optional[str]  # lowercased, or None


@dataclass(frozen=True)
class LegalLineParseResult:
    raw_text: str
    copyright_year: Optional[str]  # 4-digit string, or None if nothing plausible was found
    proxy_marker_detected: bool  # "NOT FOR SALE" / "PROXY" - see _PROXY_MARKER_RE's own comment


def _normalize_collector_number(number: str) -> str:
    """Leading zeros and case don't carry meaning in a collector number ("0093" and "93" are the
    same printing) - real OCR reads add spurious leading zeros often enough (a stray dark pixel
    column at the crop's left edge, a rarity-letter glyph tesseract folds into the digit run)
    that literal string comparison silently drops otherwise-correct reads. Verified against real
    production no-match cases, 2026-07-15 - see docs/features/printing-tags.md's Stage 8 no-match
    autopsy: this alone accounted for the majority of a 47/176 (26.7%) yield-delta fix."""
    number = number.lower()
    letter = number[-1] if number and number[-1].isalpha() else ""
    digits = number[:-1] if letter else number
    digits = digits.lstrip("0") or "0"
    return digits + letter


def crop_collector_line(
    image: "Image.Image", crop_box: tuple[float, float, float, float] = DEFAULT_CROP_BOX
) -> "Image.Image":
    width, height = image.size
    left, top, right, bottom = crop_box
    return image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))


def preprocess_variants(cropped: "Image.Image", upscale: int = 3) -> list["Image.Image"]:
    """
    Grayscale + upscale, then both polarities of an adaptive-ish threshold (a fixed-point
    threshold on a per-image-normalized histogram, not a true adaptive/local one - simple and
    fast enough for a corner crop, "adaptive" in the sense of adjusting to each image's own
    brightness range rather than a hardcoded pixel value). Modern frames print the collector
    line white-on-black; older/foil/borderless frames vary, hence trying both polarities
    rather than assuming one.
    """
    grayscale = ImageOps.grayscale(cropped)
    upscaled = grayscale.resize((grayscale.width * upscale, grayscale.height * upscale), Image.Resampling.LANCZOS)
    normalised = ImageOps.autocontrast(upscaled)
    dark_text_on_light = normalised.point(lambda p: 255 if p > 128 else 0)
    light_text_on_dark = ImageOps.invert(dark_text_on_light)
    return [dark_text_on_light, light_text_on_dark]


def run_tesseract(image: "Image.Image") -> str:
    return pytesseract.image_to_string(image, config=TESSERACT_CONFIG)


def run_tesseract_tsv(image: "Image.Image") -> list[dict[str, Any]]:
    """
    Word-level bounding boxes via tesseract's TSV output (`pytesseract.image_to_data`), filtered
    to rows with a non-blank recognized word (tesseract's TSV emits a row for every detected
    layout box - block/paragraph/line/word - most of which carry no text at all; only the word
    rows are useful here). Coordinates are in the INPUT image's own pixel space (i.e. whatever
    crop/preprocessing variant was passed in, not the full card image) - a caller wanting
    full-card coordinates must add its own crop box's left/top offset itself, same convention as
    every fixed-fraction crop box elsewhere in this module. Metadata only (text + box
    coordinates + confidence) - the image itself is never touched beyond this one read, matching
    CLAUDE.md's "Governing premise: we index, we do not store images".
    """
    data = pytesseract.image_to_data(image, config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)
    words: list[dict[str, Any]] = []
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        words.append(
            {
                "text": text,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "conf": float(data["conf"][i]),
            }
        )
    return words


def parse_collector_line(raw_text: str) -> OcrParseResult:
    """
    Tolerant extraction, not validation - a plausible-looking (set, collector) pair from noisy
    OCR text. The actual correctness check is validate_against_candidates below, which requires
    an exact match against real data; this function is deliberately permissive about what counts
    as "found something" so the validation rail (not this parser) is what decides trust.
    """
    collector_match = _COLLECTOR_NUMBER_RE.search(raw_text)
    collector_number = collector_match.group(1).lower() if collector_match else None

    set_code = None
    if collector_match:
        # a real MTG collector line always prints the number FIRST, then "SET . LANG ..." on
        # the same or next line - a plausible-looking 3-5 char token found BEFORE the number is
        # virtually always leading noise (a watermark, a rarity-letter glyph merging with a
        # stray digit into something that coincidentally looks like a code), not a genuine
        # layout variant. Search the text AFTER the collector number first, only falling back
        # to before it if nothing plausible follows. Verified against real production no-match
        # cases, 2026-07-15 - see docs/features/printing-tags.md's Stage 8 no-match autopsy.
        before = raw_text[: collector_match.start()]
        after = raw_text[collector_match.end() :]

        def _find_set_code(segment: str) -> Optional[str]:
            for candidate in _SET_CODE_RE.findall(segment):
                # a pure-digit token is never a set code (it's more collector-number noise); a
                # token that's actually the collector number's own digits (stray re-match) is
                # skipped too
                if candidate.isdigit() or candidate.lower() == collector_number:
                    continue
                return candidate.lower()
            return None

        set_code = _find_set_code(after) or _find_set_code(before)

    return OcrParseResult(raw_text=raw_text, set_code=set_code, collector_number=collector_number)


def parse_legal_line(raw_text: str) -> LegalLineParseResult:
    """
    Tolerant extraction, not validation - matches parse_collector_line's own "extract, don't
    validate" contract. No candidate matching happens here (that's Stage D's job, same as every
    other extractor's raw parse - see image_evidence.py's module docstring); `copyright_year`/
    `proxy_marker_detected` are raw signals for Stage D's calculator to weigh, most notably the
    moderator-flag case: a proxy/not-for-sale marker detected here is exactly what lets Stage D
    reject a false-accept a tolerant collector-line parse would otherwise wave through (the real
    motivating case, task #151/#159's own "MTG★EN ... NOT FOR SALE ©2022" watermark).
    """
    year_match = _COPYRIGHT_YEAR_RE.search(raw_text) or _BARE_YEAR_RE.search(raw_text)
    copyright_year = year_match.group(1) if year_match else None
    proxy_marker_detected = bool(_PROXY_MARKER_RE.search(raw_text))
    return LegalLineParseResult(
        raw_text=raw_text, copyright_year=copyright_year, proxy_marker_detected=proxy_marker_detected
    )


def find_matching_candidates(
    parsed: OcrParseResult, candidates: list["CandidatePrinting"]
) -> list["CandidatePrinting"]:
    """
    The candidate-narrowing filter `validate_against_candidates` itself uses internally,
    exposed separately (Stage D, docs/features/catalog-completion-plan.md) so a caller holding
    genuine ADDITIONAL evidence - Stage D's set-symbol phash tie-break, for the pre-M15
    collector-number-only case - can inspect an ambiguous match set directly instead of only
    learning that ambiguity occurred. Same (set_code, collector_number) matching rules
    `validate_against_candidates` documents; an empty result means "no plausible match at all",
    which that function reports as "parsed-but-no-match" whenever a collector_number was parsed.
    Returns `[]` (not `candidates`) when `parsed.collector_number is None` - there is nothing to
    match against, this is a pure filter, not a validation/skip-reason decision (that stays in
    `validate_against_candidates`, this function's own caller).
    """
    if parsed.collector_number is None:
        return []

    normalized_parsed_number = _normalize_collector_number(parsed.collector_number)
    if parsed.set_code is not None:
        return [
            c
            for c in candidates
            if c.expansion_code == parsed.set_code
            and _normalize_collector_number(c.collector_number) == normalized_parsed_number
        ]
    # pre-M15 cards have no set code on the collector line at all - fall back to matching on
    # collector number alone, which is enough when the name's candidates don't share a number
    # across sets (usually true, but not guaranteed - hence "ambiguous" below).
    return [c for c in candidates if _normalize_collector_number(c.collector_number) == normalized_parsed_number]


def validate_against_candidates(
    parsed: OcrParseResult, candidates: list["CandidatePrinting"]
) -> tuple["Optional[CandidatePrinting]", str]:
    """
    Returns (matched_candidate, skip_reason) - matched_candidate is None whenever skip_reason
    is non-empty. skip_reason is one of "no-text" (nothing parsed at all), "parsed-but-no-match"
    (a plausible (set, collector) pair that matches none of this card's candidates - probably a
    misread, possibly a genuinely wrong crop), or "ambiguous" (matches more than one candidate -
    can't happen when a set code was parsed, since (expansion, collector_number) is unique per
    CanonicalCard, but a collector-number-only match against a name that spans multiple sets
    with an overlapping number is a real case). Empty string means matched. A thin wrapper
    around `find_matching_candidates` (behavior-preserving extraction, 2026-07-20, Stage D) -
    the actual filtering logic lives there now, so a caller with independent tie-break evidence
    for the "ambiguous" case can reuse the exact same filter this function's own decision is
    built from, rather than a second implementation that could drift from it.
    """
    if parsed.collector_number is None:
        return None, "no-text"

    matches = find_matching_candidates(parsed, candidates)
    if not matches:
        return None, "parsed-but-no-match"
    if len(matches) > 1:
        return None, "ambiguous"
    return matches[0], ""


__all__ = [
    "DEFAULT_CROP_BOX",
    "LEGAL_LINE_CROP_BOX",
    "OcrParseResult",
    "LegalLineParseResult",
    "crop_collector_line",
    "preprocess_variants",
    "run_tesseract",
    "run_tesseract_tsv",
    "parse_collector_line",
    "parse_legal_line",
    "find_matching_candidates",
    "validate_against_candidates",
]
