"""
Stage C's per-card callable extraction unit (docs/features/catalog-completion-plan.md, task
#145). Fetch -> extract -> return, no DB writes - a pure function safe to call from the bulk
harvest runner OR a future demand-driven lazy-mode task (FINAL POSTURE directive item 8a,
2026-07-19: "the per-card work unit must be a callable unit independent of the bulk runner" -
BINDING now, not deferred design). Modelled on local_identify_printing_tags._compute_card's
existing fetch/extract/no-side-effects shape, generalized and made importable rather than
module-private.

Persistence (`persist_evidence`) is a separate, thin step so callers control their own
transaction boundaries (the bulk runner's future atomic-batch-seam, task #147 item 3; a
lazy-mode task's own single-card transaction) - `extract_card_evidence` itself never touches
the DB, and image bytes never persist anywhere (CLAUDE.md's "Governing premise": we index, we
do not store images) - they go out of scope the moment this function returns.

Extend this module (not ImageEvidence's callers) when adding a new extractor: fetch once at
the top of `extract_card_evidence`, call each new pure extractor function against the same
in-memory image, and add its fields/version/skip-reason to the result. `fetch_health`,
`geometry_bleed` (task #147), `layout_class`/`crop_coordinates` (issue #148, the geometry-group),
and `collector_line_ocr`/`artist_ocr`/`collector_line_tsv` (issue #149, the OCR-group) exist
today - every subsequent extractor (visual-signal/phash, legal-line, symbol harness, etc.) lands
as its own follow-up PR per task #145's manifest and one-PR-per-extractor gate.

geometry_bleed calls `local_fallback.classify_bleed_edge` directly rather than re-deriving the
aspect-ratio math - that function is the exact classifier the live pilot/harvest vote path
already uses (`cast_bleed_edge_vote`'s own upstream input), so this extractor's stored
`bleed_class` is guaranteed to agree with what the shipped identification code would conclude
for the same image, not a second implementation that could quietly drift from it over time.

layout_class (issue #148) calls `local_fallback.classify_border_color` - the ONLY remaining
`classify_*` helper in `local_fallback.py` that doesn't require OCR output as an input.
`classify_frame_style(parsed_a_collector_number, illus_anchor_fired)` was considered and
rejected for this field: both its inputs come from a real OCR pass (pass-1 collector-number
parsing, `detect_illus_anchor`'s own OCR-text scan), which is issue #149's PR, not this one -
building it here would either fake those inputs or silently couple this PR to OCR, neither
acceptable. `classify_border_color` needs only the fetched image + `bleed_class` (already
computed by geometry_bleed above), so it's the one border/frame-adjacent classifier this PR can
honestly build. Stored under the `layout_class` field name to match issue #148's own title
wording, even though the underlying classifier is named for border color - documented here so a
future reader isn't confused by the name/semantics gap.

crop_coordinates (issue #148) turns three existing fixed-fraction crop-box constants
(`local_ocr.DEFAULT_CROP_BOX`, `local_fallback.ARTIST_CROP_BOX`, `local_phash.ART_CROP_BOX` -
the collector-line, artist-credit, and art-region boxes issue #149/#150's own future extractors
will crop against) into concrete PIXEL coordinates for this specific fetched image: each box is
remapped via `local_fallback.normalize_crop_box(box, bleed_class)` (a no-op for 'bleed'/None,
exactly as that function's own docstring specifies) then scaled by `width`/`height`. Crop
COORDINATES only - crop PIXELS are never computed or stored here, matching the FINAL POSTURE
directive (CLAUDE.md's "Governing premise").

`back_face_flag`, also named in issue #148's title, is deliberately NOT built in this PR: no
signal for it exists in `Card`/`CanonicalCard` metadata (no DFC-face field anywhere - the only
`face` field in the whole schema is `ProjectMember.face`, an unrelated per-slot print-request
concept) or in `local_fallback.py`'s exported helpers, and no other doc/issue in this repo
defines what visual signal it should measure. Flagged as an OPEN ITEM on this PR rather than
shipped as an invented heuristic with fabricated golden-set expectations.

collector_line_ocr / artist_ocr / collector_line_tsv (issue #149, the OCR-group): consume
`collector_line_crop_px`/`artist_crop_px` - the pixel boxes issue #148's crop_coordinates
extractor already computed earlier in this same pass - directly (`image.crop(...)`), rather than
recomputing them from `local_ocr.DEFAULT_CROP_BOX`/`local_fallback.ARTIST_CROP_BOX` +
`normalize_crop_box` a second time. Deliberately do NOT call
`local_ocr.validate_against_candidates` or `local_fallback.match_artist`: both require a card's
real `CandidatePrinting` list, which this per-card function never receives (`extract_card_
evidence` takes only a `Card`) - candidate matching is Stage D calculator territory (task #151's
pipeline-fidelity gate), not Stage C extraction. What's stored here is raw OCR text + a tolerant
parse (`local_ocr.parse_collector_line`, `local_fallback.extract_artist_name` - both already
exist, called not reimplemented) plus TSV word-level bounding boxes
(`local_ocr.run_tesseract_tsv`, new in this PR) - metadata per FINAL POSTURE item 2 ("full OCR
text + TSV word boxes, parsed fields"), never a verdict about which printing this is.

artist_ocr reuses collector_line_ocr's own raw texts first, before falling back to its own
crop+OCR pass over `artist_crop_px` - the same reuse-before-recompute convention
`local_fallback.detect_illus_anchor` already uses (an old-border card's "Illus. <artist>" credit
frequently lands inside the SAME crop region a modern card's collector line occupies). Does not
call `detect_illus_anchor` itself, since that function recomputes its own crop box from
`ARTIST_CROP_BOX` rather than consuming the already-computed `artist_crop_px` pixels - this PR's
own inline reuse-then-crop logic mirrors its structure without violating "consume the
crop-coordinate fields, don't recompute them".

symbol_region (issue #160, "Part 4b: symbol harness" - the SET half of the collector+set join
key Stage D uses for its Scryfall lookup, per docs/features/catalog-completion-plan.md's
Governing posture note that this re-plans as in-pass hash math, not a stored strip): turns
`local_fallback.SYMBOL_STRIP_BOX` (the same right-side vertical strip that module's own
`find_symbol_matches` sub-check scans) into a `symbol_crop_px` pixel box exactly the way
crop_coordinates derives its own three boxes (`_crop_box_to_pixels`, remapped via
`normalize_crop_box` for this row's `bleed_class` first), then computes a perceptual hash
(`imagehash.phash`) of that cropped region ONLY - the cropped pixels are discarded the moment
`_compute_region_phash` returns, never persisted (FINAL POSTURE item 2: "store the math, not the
strip"). Deliberately NOT `find_symbol_matches` itself: that sub-check compares the strip against
a rendered keyrune glyph for each of a card's real `CandidatePrinting`s, which this per-card
function never receives - candidate matching is Stage D calculator territory, same reasoning
issue #149's module docstring gives for OCR candidate matching. `symbol_phash` is therefore a raw
content signal for Stage D to consume, not a verdict about which set this is. Stored as a signed
64-bit int via `twos_complement` (`cardpicker.utils`, not protected core) - the exact
representation `local_phash.py`'s own private `_hash_to_int` uses for `Card.content_phash`/
`CanonicalCard.image_hash`, reproduced here rather than imported since that helper isn't exported
(kept internal to that PROTECTED CORE module), so the two hash columns stay bit-for-bit
comparable without reaching into local_phash.py's private internals. The only named skip is a
degenerate crop box (zero/negative width or height) - the same "sub-floor" guard geometry_bleed's
own `test_zero_height_image_guards_aspect_ratio_division` exercises for its own division, applied
here before hashing rather than letting `PIL.Image.crop`/`imagehash.phash` raise on an empty
region. Real fetched images essentially never hit this (mirrors crop_coordinates's own "no
ambiguous outcome here, only fetch_failed" - see that section's comment) - it exists as a genuine
mechanical guard against a real crash risk, not a tuned classification threshold, and is not
expected to fire against the golden set.

RECONCILIATION LEDGER (owner directive 2026-07-19, task #155): `build_reconciliation_report`
answers "attempted = voted + each named skip-reason + dropped" for one extractor over one set
of cards, by querying ImageEvidence.extractor_versions + CardScanLog directly - see
ImageEvidence's own docstring for the exact voted/skipped/dropped definitions.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import imagehash

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image
from cardpicker.local_fallback import (
    ARTIST_CROP_BOX,
    SYMBOL_STRIP_BOX,
    classify_bleed_edge,
    classify_border_color,
    extract_artist_name,
    normalize_crop_box,
)
from cardpicker.local_ocr import (
    DEFAULT_CROP_BOX,
    parse_collector_line,
    preprocess_variants,
    run_tesseract,
    run_tesseract_tsv,
)
from cardpicker.local_phash import ART_CROP_BOX
from cardpicker.models import Card, CardScanLog, ImageEvidence
from cardpicker.utils import twos_complement

logger = logging.getLogger(__name__)

FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v1"
GEOMETRY_BLEED_EXTRACTOR_VERSION = "geometry-bleed-v1"
LAYOUT_CLASS_EXTRACTOR_VERSION = "layout-class-v1"
CROP_COORDINATES_EXTRACTOR_VERSION = "crop-coordinates-v1"
COLLECTOR_LINE_OCR_EXTRACTOR_VERSION = "collector-line-ocr-v1"
ARTIST_OCR_EXTRACTOR_VERSION = "artist-ocr-v1"
COLLECTOR_LINE_TSV_EXTRACTOR_VERSION = "collector-line-tsv-v1"
SYMBOL_REGION_EXTRACTOR_VERSION = "symbol-region-v1"

# Bit width for the perceptual-hash int representation - matches local_phash.py's own private
# _hash_to_int/_HASH_BITS exactly (imagehash's default hash_size=8 -> a 64-bit hash), reproduced
# here rather than imported since that helper isn't exported from that PROTECTED CORE module.
_SYMBOL_HASH_BITS = 64


@dataclass(frozen=True)
class ExtractionResult:
    """
    Pure result of one card's extraction pass - no DB writes have happened yet. `fields` holds
    every ImageEvidence column this pass computed a value for. `extractor_versions` holds the
    version tag for every extractor that RAN TO COMPLETION for this card (whether it found a
    positive result or a named-skip outcome) - an extractor that raises/crashes omits its own
    key here, which is what makes it "dropped" rather than "skipped" for reconciliation
    purposes (see module docstring). `skip_reasons` holds a named reason for every extractor
    that ran but declined to produce a real value (e.g. fetch failure) - always a subset of
    extractor_versions' keys.
    """

    card_id: int
    content_hash: Optional[int]
    fields: dict[str, Any] = field(default_factory=dict)
    extractor_versions: dict[str, str] = field(default_factory=dict)
    skip_reasons: dict[str, str] = field(default_factory=dict)


def _crop_box_to_pixels(
    box: tuple[float, float, float, float], bleed_class: Optional[str], width: int, height: int
) -> list[int]:
    """Remaps a fixed-fraction crop box via `normalize_crop_box` (a no-op for 'bleed'/None) then
    scales it into this image's own pixel space - crop COORDINATES only, never crop pixels."""
    left, top, right, bottom = normalize_crop_box(box, bleed_class)
    return [round(left * width), round(top * height), round(right * width), round(bottom * height)]


def _compute_region_phash(image: Any, box: list[int]) -> int:
    """Crops `box` from `image`, converts to grayscale, and returns `imagehash.phash` as a signed
    64-bit int via `twos_complement` - see module docstring's `symbol_region` section for why this
    reproduces (rather than imports) local_phash.py's own private hash-to-int convention. The
    cropped region never leaves this function's stack frame - only the int it returns persists
    (FINAL POSTURE item 2: "store the math, not the strip")."""
    region = image.crop(tuple(box)).convert("L")
    return twos_complement(str(imagehash.phash(region)), _SYMBOL_HASH_BITS)


def extract_card_evidence(card: Card, dpi: Optional[int] = DEFAULT_FETCH_DPI) -> ExtractionResult:
    """
    The per-card callable work unit. `card.content_phash` (not recomputed here) is the content
    hash this evidence is keyed against - hash-at-ingest (Part 2) already populates it for
    essentially every card by the time Stage C runs. If it's still null, the result's
    `content_hash` is None and `persist_evidence` will refuse to write a row, since
    ImageEvidence's "computed-once-forever" premise depends on a stable hash to key on.
    """

    fields: dict[str, Any] = {}
    extractor_versions: dict[str, str] = {}
    skip_reasons: dict[str, str] = {}

    try:
        image = fetch_card_image(card, dpi=dpi)
    except GoogleFetchLockoutError:
        # A 403 lockout is a hard stop for the whole run, not a per-card fetch-health
        # observation - propagate exactly as image_cdn_fetch.fetch_card_image's own docstring
        # requires every caller to.
        raise

    if image is None:
        fields["fetch_ok"] = False
        fields["fetch_error_class"] = "fetch_failed"
        skip_reasons["fetch_health"] = "fetch_failed"
    else:
        fields["fetch_ok"] = True
        fields["fetch_error_class"] = ""
    # Set even on skip - fetch_health RAN TO COMPLETION either way, it just didn't find a
    # positive result. Omitted only if this function raises before reaching here.
    extractor_versions["fetch_health"] = FETCH_HEALTH_EXTRACTOR_VERSION

    # geometry_bleed (task #147): depends on the same fetched image - if the fetch itself
    # failed, this extractor never gets to run either, but that's a named skip (same root cause
    # fetch_health already recorded), not a crash, so it still gets its own extractor_versions
    # entry - matching fetch_health's own "ran to completion, found nothing" convention above.
    if image is None:
        skip_reasons["geometry_bleed"] = "fetch_failed"
    else:
        width, height = image.size
        fields["width"] = width
        fields["height"] = height
        fields["aspect_ratio"] = (width / height) if height else None
        bleed_class = classify_bleed_edge(image)
        fields["bleed_class"] = bleed_class or ""
        if bleed_class is None:
            # classify_bleed_edge's own documented "genuinely non-standard image" outcome -
            # "ambiguous" is the pipeline's own pre-existing skip-reason vocabulary
            # (docs/features/catalog-completion-plan.md's CardScanLog section), not a new string.
            skip_reasons["geometry_bleed"] = "ambiguous"
    extractor_versions["geometry_bleed"] = GEOMETRY_BLEED_EXTRACTOR_VERSION

    # layout_class (issue #148): reuses this same fetched image + the bleed_class just computed
    # above - see module docstring for why classify_border_color, not classify_frame_style.
    if image is None:
        skip_reasons["layout_class"] = "fetch_failed"
    else:
        layout_class = classify_border_color(image, bleed_class)
        fields["layout_class"] = layout_class or ""
        if layout_class is None:
            # classify_border_color's own documented ambiguous outcome (non-uniform sample or a
            # color outside this taxonomy) - "ambiguous" is the same pre-existing skip-reason
            # vocabulary geometry_bleed's own abstention above uses, not a new string.
            skip_reasons["layout_class"] = "ambiguous"
    extractor_versions["layout_class"] = LAYOUT_CLASS_EXTRACTOR_VERSION

    # crop_coordinates (issue #148): three existing fixed-fraction crop-box constants, remapped
    # via normalize_crop_box (a no-op for 'bleed'/None) and scaled to this image's own pixel
    # space. Unlike layout_class/geometry_bleed, normalize_crop_box never abstains - there is no
    # "ambiguous" outcome here, only fetch_failed.
    if image is None:
        skip_reasons["crop_coordinates"] = "fetch_failed"
    else:
        fields["collector_line_crop_px"] = _crop_box_to_pixels(DEFAULT_CROP_BOX, bleed_class, width, height)
        fields["artist_crop_px"] = _crop_box_to_pixels(ARTIST_CROP_BOX, bleed_class, width, height)
        fields["art_crop_px"] = _crop_box_to_pixels(ART_CROP_BOX, bleed_class, width, height)
    extractor_versions["crop_coordinates"] = CROP_COORDINATES_EXTRACTOR_VERSION

    # collector_line_ocr / artist_ocr / collector_line_tsv (issue #149, the OCR-group): consume
    # the *_crop_px pixel boxes crop_coordinates just computed above rather than recomputing them
    # - see module docstring. No candidate matching happens here (Stage D's job).
    if image is None:
        skip_reasons["collector_line_ocr"] = "fetch_failed"
        skip_reasons["artist_ocr"] = "fetch_failed"
        skip_reasons["collector_line_tsv"] = "fetch_failed"
    else:
        collector_crop = image.crop(tuple(fields["collector_line_crop_px"]))
        collector_variants = preprocess_variants(collector_crop)
        collector_raw_texts: list[str] = [run_tesseract(variant) for variant in collector_variants]

        # prefer the first variant whose text actually parses a collector number - matches
        # run_ocr_for_card's own "first variant that produces something" precedence - falling
        # back to the first variant's (empty) parse if none did, so the stored artifact is
        # deterministic either way.
        selected_index = 0
        parsed = parse_collector_line(collector_raw_texts[0]) if collector_raw_texts else parse_collector_line("")
        for i, raw_text in enumerate(collector_raw_texts):
            candidate_parse = parse_collector_line(raw_text)
            if candidate_parse.collector_number is not None:
                parsed = candidate_parse
                selected_index = i
                break

        fields["collector_line_raw_text"] = collector_raw_texts[selected_index] if collector_raw_texts else ""
        fields["collector_line_set_code"] = parsed.set_code or ""
        fields["collector_line_collector_number"] = parsed.collector_number or ""
        if parsed.collector_number is None:
            skip_reasons["collector_line_ocr"] = "no-text"

        # TSV word boxes: same winning variant the text parse above came from, so the word boxes
        # and the parsed text always describe the same underlying tesseract read.
        fields["collector_line_word_boxes"] = (
            run_tesseract_tsv(collector_variants[selected_index]) if collector_variants else []
        )

        # artist OCR: reuse collector_line_ocr's own raw texts first (see module docstring),
        # only cropping+OCR-ing artist_crop_px if none of those already contain an "Illus." match.
        artist_name: Optional[str] = None
        artist_raw_text = ""
        for raw_text in collector_raw_texts:
            artist_name = extract_artist_name(raw_text)
            if artist_name is not None:
                artist_raw_text = raw_text
                break
        if artist_name is None:
            artist_crop = image.crop(tuple(fields["artist_crop_px"]))
            for variant in preprocess_variants(artist_crop):
                raw_text = run_tesseract(variant)
                if not artist_raw_text:
                    artist_raw_text = raw_text  # keep at least one attempt as a stored artifact
                artist_name = extract_artist_name(raw_text)
                if artist_name is not None:
                    artist_raw_text = raw_text
                    break

        fields["artist_ocr_raw_text"] = artist_raw_text
        fields["artist_ocr_name"] = artist_name or ""
        # whether the "Illus." anchor was found at all, independent of whether the extracted name
        # would go on to fuzzy-match a real candidate (that's Stage D's job) - same convention as
        # local_fallback.detect_illus_anchor's own (fired, name) return.
        fields["illus_anchor_fired"] = artist_name is not None
        if artist_name is None:
            skip_reasons["artist_ocr"] = "no-text"

    extractor_versions["collector_line_ocr"] = COLLECTOR_LINE_OCR_EXTRACTOR_VERSION
    extractor_versions["artist_ocr"] = ARTIST_OCR_EXTRACTOR_VERSION
    extractor_versions["collector_line_tsv"] = COLLECTOR_LINE_TSV_EXTRACTOR_VERSION

    # symbol_region (issue #160, "Part 4b: symbol harness"): SYMBOL_STRIP_BOX turned into pixel
    # coordinates the same way crop_coordinates derives its own three boxes, then a raw phash of
    # that region only - see module docstring for why this is a raw signal (Stage D's job to
    # compare against a candidate's rendered glyph), not a verdict, and why the only named skip is
    # a degenerate crop box rather than a tuned classification threshold.
    if image is None:
        skip_reasons["symbol_region"] = "fetch_failed"
    else:
        symbol_crop_px = _crop_box_to_pixels(SYMBOL_STRIP_BOX, bleed_class, width, height)
        left, top, right, bottom = symbol_crop_px
        if right <= left or bottom <= top:
            # A degenerate (zero/negative-area) crop box - the same "sub-floor" input category
            # geometry_bleed's own zero-height guard handles for its aspect-ratio division (see
            # module docstring) - guarded here before PIL.Image.crop/imagehash.phash would raise
            # on an empty region. Real fetched images essentially never hit this; not expected to
            # fire against the golden set (see module docstring).
            skip_reasons["symbol_region"] = "ambiguous"
        else:
            fields["symbol_crop_px"] = symbol_crop_px
            fields["symbol_phash"] = _compute_region_phash(image, symbol_crop_px)
    extractor_versions["symbol_region"] = SYMBOL_REGION_EXTRACTOR_VERSION

    return ExtractionResult(
        card_id=card.pk,
        content_hash=card.content_phash,
        fields=fields,
        extractor_versions=extractor_versions,
        skip_reasons=skip_reasons,
    )


def persist_evidence(result: ExtractionResult, run_id: Optional[str] = None) -> Optional[ImageEvidence]:
    """
    The thin, separate DB-write step (see module docstring for why this is split from
    `extract_card_evidence`). Refuses to write if `content_hash` is None. Uses
    `get_or_create` + field merge (not a blind create) so a re-run against the SAME (card,
    content_hash) pair updates in place rather than erroring on the unique constraint - this is
    what makes independently-landing extractor PRs additive: each one's own pass only ever
    touches its own fields/version key, never clobbers another extractor's already-written data.

    Also writes a `CardScanLog` row for every entry in `result.skip_reasons` (the
    reconciliation ledger's "named skip" leg - see module docstring), tagged
    `anonymous_id=<extractor name>` so it correlates back to `extractor_versions`' own keys.
    """

    if result.content_hash is None:
        logger.warning("Skipping ImageEvidence persist for card %s: content_phash is null", result.card_id)
        return None

    evidence, _ = ImageEvidence.objects.get_or_create(card_id=result.card_id, content_hash=result.content_hash)
    for field_name, value in result.fields.items():
        setattr(evidence, field_name, value)
    evidence.extractor_versions = {**evidence.extractor_versions, **result.extractor_versions}
    evidence.run_id = run_id
    evidence.save()

    for extractor_name, skip_reason in result.skip_reasons.items():
        CardScanLog.objects.create(
            card_id=result.card_id, anonymous_id=extractor_name, skip_reason=skip_reason, run_id=run_id
        )

    return evidence


@dataclass(frozen=True)
class ReconciliationReport:
    """See ImageEvidence's own docstring for the exact voted/skipped/dropped definitions."""

    extractor_name: str
    attempted: int
    voted: int
    skipped_by_reason: dict[str, int]
    dropped: int

    def is_consistent(self) -> bool:
        return self.attempted == self.voted + sum(self.skipped_by_reason.values()) + self.dropped


def build_reconciliation_report(
    extractor_name: str, card_ids: list[int], run_id: Optional[str] = None
) -> ReconciliationReport:
    """
    Queries ImageEvidence + CardScanLog directly rather than a separately-maintained counter,
    so the report can never drift from what was actually persisted. `run_id`, if given, scopes
    the CardScanLog side to that run only (matching CardScanLog's own run_id-scoped query
    convention elsewhere) - ImageEvidence's own `run_id` is a last-writer field, not filtered
    here, since a card's evidence may have been written by an earlier run and only skipped (or
    not attempted at all) in this one.
    """

    attempted = len(card_ids)

    ran_card_ids = set(
        ImageEvidence.objects.filter(card_id__in=card_ids, extractor_versions__has_key=extractor_name).values_list(
            "card_id", flat=True
        )
    )

    skip_qs = CardScanLog.objects.filter(card_id__in=card_ids, anonymous_id=extractor_name)
    if run_id is not None:
        skip_qs = skip_qs.filter(run_id=run_id)

    skipped_by_reason: dict[str, int] = {}
    skipped_card_ids: set[int] = set()
    for card_id, skip_reason in skip_qs.values_list("card_id", "skip_reason"):
        skipped_by_reason[skip_reason] = skipped_by_reason.get(skip_reason, 0) + 1
        skipped_card_ids.add(card_id)

    voted = len(ran_card_ids - skipped_card_ids)
    dropped = attempted - len(ran_card_ids | skipped_card_ids)

    return ReconciliationReport(
        extractor_name=extractor_name,
        attempted=attempted,
        voted=voted,
        skipped_by_reason=skipped_by_reason,
        dropped=dropped,
    )


__all__ = [
    "ExtractionResult",
    "extract_card_evidence",
    "persist_evidence",
    "ReconciliationReport",
    "build_reconciliation_report",
    "FETCH_HEALTH_EXTRACTOR_VERSION",
    "GEOMETRY_BLEED_EXTRACTOR_VERSION",
    "LAYOUT_CLASS_EXTRACTOR_VERSION",
    "CROP_COORDINATES_EXTRACTOR_VERSION",
    "COLLECTOR_LINE_OCR_EXTRACTOR_VERSION",
    "ARTIST_OCR_EXTRACTOR_VERSION",
    "COLLECTOR_LINE_TSV_EXTRACTOR_VERSION",
    "SYMBOL_REGION_EXTRACTOR_VERSION",
]
