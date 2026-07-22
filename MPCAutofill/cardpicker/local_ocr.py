"""
L1 engine for the local printing-identification pilot (cardpicker.local_identify_printing_tags,
docs/features/printing-tags.md's Stage 8): Tesseract OCR on the collector-line crop.

The validation rail is what makes weak OCR safe to vote on at all: a parsed (set, collector
number) pair only casts a vote when it matches EXACTLY ONE of the card's own name-candidates
(cardpicker.local_identify_printing_tags.CandidateNameIndex) - this module extracts a
best-effort reading, it never has to be trusted on its own.

`preprocess_fallback_variants`/`ALTERNATE_TESSERACT_CONFIG` (issue #259, "Stage D no-text bucket:
OCR preprocessing/crop recovery") are FALLBACK-ONLY additions - callers decide when to reach for
them (image_evidence.py's `collector_line_ocr` extractor's own multi-tier attempt loop is the one
call site that does, since that extractor is what the #259 diagnostic was run against; this
module's other two consumers, `local_fallback.py` and `local_identify_printing_tags.py` - both
PROTECTED CORE - are untouched and still only ever call the ORIGINAL `preprocess_variants`/
`run_tesseract`, exactly as before). Nothing in this module changes what those two callers do -
`run_tesseract`/`run_tesseract_text_and_words` gained an optional `config` kwarg (default
unchanged, `TESSERACT_CONFIG`), so every existing single-argument call site keeps its exact prior
behavior.
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import pytesseract
from PIL import Image, ImageFilter, ImageOps

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

# FALLBACK-ONLY (issue #259's B bucket, "garbled but present" text - 76.8% of the no-text skip
# population): PSM 6's "single uniform block" assumption is exactly what TESSERACT_CONFIG's own
# comment above picked it FOR, but that same assumption is a liability once the crop is noisy
# enough that tesseract's line/block segmentation itself goes wrong (not just the character
# recognition) - forcing two real lines into one garbled block, or splitting one real line into
# nonsense fragments. PSM 11 ("sparse text - find as much text as possible, in no particular
# order") drops the block-structure assumption entirely, which recovers real text specifically
# WHEN the failure is segmentation, not pixel quality - a different failure mode than
# `preprocess_fallback_variants` below targets (which re-processes the pixels, not the page-
# segmentation assumption). Only ever tried as a later attempt, after every PSM-6 attempt
# (original + fallback-preprocessed variants) has already failed to parse a collector number -
# see image_evidence.py's own `collector_line_ocr` extractor for the attempt ordering.
ALTERNATE_TESSERACT_CONFIG = "--psm 11"

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

# print-run denominator + rarity, glued together with no separating space (e.g. "361R" in a
# real "354/361R\nCMR ¢ EN..." collector line, card_id 59, run staged-write-20260721T0434Z) -
# looks exactly like a plausible 3-5 char set-code token to _SET_CODE_RE (alnum, not pure
# digits), but it's the SAME kind of OCR-glued noise _COLLECTOR_NUMBER_RE's own no-space
# tolerance already documents above, just on the other side of the slash. Real MTG collector
# lines never print a genuine set code directly after a "/" - that position is exclusively the
# print-run denominator's own territory - so this is detected by POSITION (immediately preceded
# by "/", ignoring intervening whitespace), not by shape alone: a real code CAN be digit-led
# (e.g. "40K" for the Warhammer 40,000 Universes Beyond set), so a blanket "digit-run + trailing
# letter" shape-only skip would risk discarding a genuine code elsewhere in the line.
_DENOMINATOR_RARITY_TOKEN_RE = re.compile(r"^\d{1,4}[A-Za-z]?$")

# language-marker character glued onto the tail of a set code (2026-07-22, pipeline-fidelity
# parity replay #154's "unexplained" divergence autopsy, canonical case card_id 41559, "Verazol,
# the Split Current": raw "239/280 R\nZNRe EN b> DAARKEN" parses set_code="znre" - the real set
# is "znr" (confirmed against CandidateNameIndex), with a stray lowercase "e" glued onto its tail,
# immediately followed by a real language marker ("EN") that reads out cleanly on its own right
# after it. Same family of OCR-glued noise `_DENOMINATOR_RARITY_TOKEN_RE` above already documents
# (an adjacent, correctly-read token's own leading edge bleeding onto the PRECEDING token, not a
# genuine extra character printed on the card) - extends that guard's own POSITION-based
# detection (not shape alone) to a different adjacency: this time to whatever immediately follows
# the candidate token, not what precedes it.
#
# Deliberately narrow / no candidate lookup: `parse_collector_line` has no access to a card's real
# candidate set list (module docstring - "no candidate matching happens here, that's Stage D's
# job"), so this can only ever fire on a POSITIONAL/SHAPE signal, exactly like the denominator
# guard - never on "does the de-glued form match something real". The signal used: the
# candidate's OWN trailing character, case-INsensitively, equals the first letter of an
# immediately-following (whitespace-only gap) recognized language-marker token. This is
# deliberately strict enough to fire on the confirmed 41559/165637 case only, not on other
# glued-extra-character cases sampled from the same "is_no_match" bucket that don't share this
# exact adjacency (e.g. card_id 9934's "A25S" -> real "a25", glued to a rarity SYMBOL, not a
# language marker; card_id 181116's "WWkK" -> real "wwk", also glued ahead of a symbol, not
# directly before the marker) - those remain unfixed by this guard, a deliberate scope boundary,
# not an oversight (see docs/reports for this task's own per-ID breakdown).
_LANGUAGE_MARKER_CODES = frozenset({"EN", "DE", "FR", "IT", "ES", "PT", "JA", "KO", "RU", "ZHS", "ZHT"})
_LANGUAGE_MARKER_ADJACENCY_RE = re.compile(r"\s*([A-Za-z]{2,3})\b")

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
# on garbled OCR. Case-insensitive. Three families, each a plain, complete literal word/phrase -
# no letter-substitution/OCR-noise tolerance for any of them:
#   1. "not for sale", tolerant of "NOT-FOR-SALE"/"NOT   FOR SALE" spacing/hyphen variants only.
#   2. "proxy"/"proxies"/"proxied" as distinct word-bounded alternatives (a marker diagnostic,
#      2026-07-21, found ~512 marker-absent evidence rows carrying the exact substring
#      "proxies"/"proxied" - e.g. "Proxies by Smaug", "POGO PROXIES", "PROXIED" - that a
#      singular-only \bproxy\b could never match, since \b requires a word break immediately
#      after the "y") - the same mechanical plural/passive gap as an earlier missed-match fix
#      elsewhere in this module, not a relaxation of the exactness this comment argues for above.
#   3. "play test"/"play-test"/"playtest" (owner decision, 2026-07-21: playtest cards and their
#      variants count as proxy markers) - tolerant of the same spacing/hyphen variants as "not for
#      sale" above. Deliberately only \b-anchored on the LEFT (before "play"), not the right (after
#      "test"): this still excludes a "play" embedded in a longer word with no boundary before it
#      (e.g. "cosplay"/"display"/"replay" - \b fails between two word characters, so "test" that
#      happens to follow one of those doesn't get pulled in), but DOES deliberately let a suffix
#      after "test" through (e.g. "playtester", "playtesting") - a real diagnostic sample
#      ("OMNIPROXY - PLAYTEST COPY") already matches on the bare word alone, but any
#      playtest-prefixed token signals the same non-authentic-card fact, so a trailing \b would
#      only narrow this family for no safety benefit. Same diagnostic found ~14 additional
#      marker-absent evidence rows (distinct from the ~512 proxy-plural rows above) carrying this
#      exact family, e.g. "OMNIPROXY - PLAYTEST COPY", "Rustom Playtest Card - Not for Sale".
_PROXY_MARKER_RE = re.compile(r"not[\s-]*for[\s-]*sale|\bprox(?:y|ies|ied)\b|\bplay[\s-]*test", re.IGNORECASE)


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


def _median_from_histogram(histogram: list[int]) -> int:
    """The pixel value (0-255) at which an 8-bit grayscale histogram's cumulative count first
    reaches half its total - i.e. the image's own median intensity. `128` (a reasonable default
    for a genuinely empty/degenerate histogram, matching `preprocess_variants`' own fixed cut)
    if the histogram is empty (zero total pixels - shouldn't happen for a real crop, guarded
    defensively rather than raising a ZeroDivisionError)."""
    total = sum(histogram)
    if total == 0:
        return 128
    half = total / 2
    cumulative = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= half:
            return value
    return 255


def preprocess_fallback_variants(cropped: "Image.Image", upscale: int = 5) -> list["Image.Image"]:
    """
    FALLBACK-ONLY additional preprocessing (issue #259, "Stage D no-text bucket: OCR
    preprocessing/crop recovery") - never on the happy path. Callers should only reach for this
    once every `preprocess_variants` attempt has already failed to parse a collector number (see
    image_evidence.py's own `collector_line_ocr` extractor for the attempt ordering this is
    designed to slot into) - it is strictly more expensive per variant (a larger upscale factor,
    an extra filter pass) than `preprocess_variants`, and exists to recover the two failure modes
    the #259 diagnostic identified over the no-text skip population, NOT to replace the fast
    path for the common case.

    Two independent recovery angles, both polarities each (matching `preprocess_variants`' own
    dark-on-light/light-on-dark rationale - frame color varies by card, not knowable upfront).
    The PERCENTILE pair is tried first, the SHARPENED pair second - deliberately, not
    alphabetically/arbitrarily: `collector_line_ocr`'s own caller stops at the first attempt
    whose text parses *any* plausible collector number, and an `UnsharpMask` pass amplifies
    high-frequency content indiscriminately (real text edges AND noise alike) - live-verified
    (not just argued) to occasionally manufacture a spurious digit-shaped fragment from pure
    noise on a heavily-blurred crop, which would otherwise win the "first parse" race over the
    percentile pair's genuinely-correct-but-later read. Trying the less noise-amplifying
    transform first reduces (does not eliminate - Stage D's own candidate-matching validation
    rail is what actually screens a false parse out, per this module's own opening docstring)
    how often that ordering-sensitive false-positive risk fires in practice.

    1. A percentile (median-anchored) threshold instead of `preprocess_variants`' fixed 128 cut -
       targets the "garbled but present" failure mode (76.8% of the #259 no-text population): a
       genuinely uneven-brightness crop (glare, foil, an off-center bleed margin caught in the
       crop) can have its real text/background split sitting well off the 0-255 midpoint, which
       `ImageOps.autocontrast` alone doesn't correct for (autocontrast stretches the FULL
       observed range to 0-255, it does not relocate WHERE the true split point falls within
       that stretched range). Anchoring the cut to the crop's own median intensity
       (`_median_from_histogram`) adapts to that per-image imbalance instead of assuming it's
       centered, the same "adjust to each image's own range" spirit `preprocess_variants`' own
       docstring already claims for its fixed cut - this is the version of that idea that
       actually holds for an unevenly-lit crop.
    2. Heavier upscale (default 5x vs `preprocess_variants`' 3x) + an `ImageFilter.UnsharpMask`
       pass BEFORE thresholding - targets the blurry-upload failure mode (the #259 diagnostic's
       bottom-quartile `blur_variance` finding): a soft/blurry crop's true edges are smeared
       across more pixels than a sharp one, so sharpening before the binary threshold recovers an
       edge a flat fixed-point cut would otherwise blur into a false middle-gray.
    """
    grayscale = ImageOps.grayscale(cropped)
    upscaled = grayscale.resize((grayscale.width * upscale, grayscale.height * upscale), Image.Resampling.LANCZOS)
    normalised = ImageOps.autocontrast(upscaled)

    median = _median_from_histogram(normalised.histogram())
    percentile_dark_on_light = normalised.point(lambda p: 255 if p > median else 0)
    percentile_light_on_dark = ImageOps.invert(percentile_dark_on_light)

    sharpened = normalised.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    sharp_dark_on_light = sharpened.point(lambda p: 255 if p > 128 else 0)
    sharp_light_on_dark = ImageOps.invert(sharp_dark_on_light)

    return [percentile_dark_on_light, percentile_light_on_dark, sharp_dark_on_light, sharp_light_on_dark]


def run_tesseract(image: "Image.Image", config: str = TESSERACT_CONFIG) -> str:
    return pytesseract.image_to_string(image, config=config)


def _words_from_tesseract_data(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Shared row-filtering logic behind `run_tesseract_tsv`/`run_tesseract_text_and_words` -
    tesseract's TSV emits a row for every detected layout box (block/paragraph/line/word), most
    of which carry no text at all; only the word rows (non-blank text) are useful here."""
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


def _text_from_tesseract_data(data: dict[str, list[Any]]) -> str:
    """Reconstructs an `image_to_string`-shaped raw text from `image_to_data`'s own per-word rows
    - words within the same (block, paragraph, line) triple are joined with a single space, and
    each distinct line is joined with a newline, in the order tesseract emitted them (already
    reading order, not re-sorted). Not byte-identical to `pytesseract.image_to_string`'s own
    output (that runs a different internal recognition pass, not just a different report format
    of the same one) but equivalent for this module's own regex-based tolerant parsing
    (`parse_collector_line`/`parse_legal_line` both `.search()` for a pattern anywhere in the
    string, not position- or whitespace-exact) - this is what lets `run_tesseract_text_and_words`
    below derive both the raw text AND the word boxes from a SINGLE tesseract call instead of one
    call per representation of the same underlying OCR pass."""
    lines: list[list[str]] = []
    current_key: Optional[tuple[int, int, int]] = None
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != current_key:
            lines.append([])
            current_key = key
        lines[-1].append(text)
    return "\n".join(" ".join(words) for words in lines)


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
    return _words_from_tesseract_data(data)


def run_tesseract_text_and_words(
    image: "Image.Image", config: str = TESSERACT_CONFIG
) -> tuple[str, list[dict[str, Any]]]:
    """
    OCR call-cost reduction (2026-07-20, docs/reports/2026-07-20-pipeline-compute-profile.md's
    ocr_group/legal_line finding, 58% of Stage C's per-card compute cost): a single
    `pytesseract.image_to_data` call, returning BOTH a raw text string (`_text_from_tesseract_data`)
    and the word-level bounding boxes (`_words_from_tesseract_data`) `run_tesseract_tsv` already
    returns - the exact same underlying tesseract invocation, read two ways, instead of the two
    separate tesseract calls (`run_tesseract` + `run_tesseract_tsv`) `image_evidence.py`'s
    collector-line pass used to make for the SAME winning variant. Deliberately a NEW function
    rather than a change to `run_tesseract`/`run_tesseract_tsv`'s own signatures - both of those
    are called directly by `local_fallback.py` (PROTECTED CORE) and `local_identify_printing_tags
    .py`'s live pilot pass, neither of which this cost-reduction pass touches or needs to change.

    `config` (issue #259 addition): defaults to `TESSERACT_CONFIG` (PSM 6, unchanged for every
    pre-existing call site that doesn't pass one explicitly) - image_evidence.py's
    `collector_line_ocr` extractor passes `ALTERNATE_TESSERACT_CONFIG` for its own alternate-PSM
    fallback tier, once every PSM-6 attempt has already failed to parse a collector number.
    """
    data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
    return _text_from_tesseract_data(data), _words_from_tesseract_data(data)


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
            for match in _SET_CODE_RE.finditer(segment):
                candidate = match.group(1)
                # a pure-digit token is never a set code (it's more collector-number noise); a
                # token that's actually the collector number's own digits (stray re-match) is
                # skipped too
                if candidate.isdigit() or candidate.lower() == collector_number:
                    continue
                # print-run denominator glued to its rarity letter (see
                # _DENOMINATOR_RARITY_TOKEN_RE's own comment) - only skipped when the token is
                # actually positioned right after a "/", never on shape alone
                preceding = segment[: match.start()].rstrip()
                if preceding.endswith("/") and _DENOMINATOR_RARITY_TOKEN_RE.match(candidate):
                    continue
                # language-marker character glued onto this token's own tail (see
                # _LANGUAGE_MARKER_ADJACENCY_RE's own comment) - only de-glued (not skipped
                # entirely, unlike the denominator case above) when the token's OWN last
                # character, case-insensitively, matches the first letter of a real language
                # marker immediately following it (whitespace-only gap) - never on shape alone,
                # and never wider than stripping that single trailing character.
                following = segment[match.end() :]
                marker_match = _LANGUAGE_MARKER_ADJACENCY_RE.match(following)
                if (
                    len(candidate) >= 4
                    and marker_match is not None
                    and marker_match.group(1).upper() in _LANGUAGE_MARKER_CODES
                    and candidate[-1].lower() == marker_match.group(1)[0].lower()
                ):
                    candidate = candidate[:-1]
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
    "TESSERACT_CONFIG",
    "ALTERNATE_TESSERACT_CONFIG",
    "OcrParseResult",
    "LegalLineParseResult",
    "crop_collector_line",
    "preprocess_variants",
    "preprocess_fallback_variants",
    "run_tesseract",
    "run_tesseract_tsv",
    "run_tesseract_text_and_words",
    "parse_collector_line",
    "parse_legal_line",
    "find_matching_candidates",
    "validate_against_candidates",
]
