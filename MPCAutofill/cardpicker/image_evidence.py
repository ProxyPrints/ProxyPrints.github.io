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

`back_face_flag`, also named in issue #148's title, was deliberately NOT built in that PR: no
signal for it existed in `Card`/`CanonicalCard` metadata or `local_fallback.py`'s exported
helpers at the time, and no doc/issue defined what visual signal it should measure. The owner
later settled it (issue #199) as NAME-based, not image-based - determined from Scryfall's
`card_faces` data, not this module's fetched image - so it was never added here as an
`ImageEvidence` field/extractor. See `printing_metadata_import.get_back_face_names`/
`is_back_face` for the actual implementation, and
`docs/features/catalog-completion-plan.md`'s "back-face flag" paragraph for the full rationale
(including why no `ImageEvidence`/`CanonicalCard` field was added).

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
exist, called not reimplemented) plus TSV word-level bounding boxes - both the raw text and the
word boxes for collector_line_ocr/collector_line_tsv come from a SINGLE tesseract call per
variant tried (`local_ocr.run_tesseract_text_and_words`, added 2026-07-20 as an OCR call-cost
reduction, docs/reports/2026-07-20-pipeline-compute-profile.md - supersedes an earlier version
of this PR that called `run_tesseract` and `local_ocr.run_tesseract_tsv` separately for the same
winning variant) - metadata per FINAL POSTURE item 2 ("full OCR text + TSV word boxes, parsed
fields"), never a verdict about which printing this is.

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

legal_line (public issue #151, "Legal-line extractor + moderator flag + volume report (task
#159)" - this PR builds the extractor + moderator-flag signal only, per that issue's own SCOPE;
the volume report half (task #159) is out of scope, tracked separately): a NEW, dedicated crop
region (`local_ocr.LEGAL_LINE_CROP_BOX`, NOT a reuse of `collector_line_crop_px` - verified
against real fetched production images before being locked in, see that constant's own comment),
turned into pixel coordinates the same way `crop_coordinates`/`symbol_region` derive their own
boxes. `local_ocr.parse_legal_line`'s tolerant parse (`legal_line_copyright_year`,
`legal_line_proxy_marker_detected`) - no candidate matching here either, same Stage-D-territory
reasoning every other OCR-adjacent extractor in this module gives. `legal_line_proxy_marker_
detected` is the moderator-flag signal: a raw True/False fact this extractor emits, consumed by
Stage D's calculator (task #151's pipeline-fidelity gate) - never acted on directly here, matching
every prior extractor's "emit signals, don't act on them" discipline.

color_profile / quality_signals (public issue #150's re-spec, "Stage C visual-signal extractors" -
the LAST Stage C manifest extractor group; the phash half of the original issue is DROPPED per the
owner's 2026-07-20 re-spec comment, superseded by user-submitted phash (task #203) - set-symbol
phash already shipped separately as symbol_region above, not touched by this PR): both consume the
SAME `local_image_quality.is_image_truncated(image)` call - `quality_signals` runs it first (right
after legal_line above) and stores the local `truncated` boolean for `color_profile` to reuse a few
lines later, rather than re-attempting (and re-catching) the same `OSError` a second time. This is
an explicit cross-extractor dependency, same category as `artist_ocr` reusing `collector_line_ocr`'s
own raw texts or `crop_coordinates` reusing `geometry_bleed`'s `bleed_class` - documented here for
the same reason those are documented in their own sections above.

`quality_signals`: `image_is_truncated` is a genuine integrity fact (Pillow only lazily decodes on
`Image.open()`, so a download cut off partway through can still open successfully and only raise
`OSError` once something forces a full pixel read - see `local_image_quality.is_image_truncated`'s
own docstring). Only if the image loaded cleanly does this extractor go on to compute
`blur_variance` (variance of a Laplacian-kernel edge response over the grayscale image - a standard
sharpness/blur proxy) and `image_entropy` (Pillow's own `Image.entropy()`, a built-in method, not
reimplemented) - a truncated image's partial pixel data would produce meaningless numbers for both,
not a real reading. Both are raw signals only: this extractor never decides what variance/entropy
counts as "too blurry"/"too flat" - that's Stage D calculator territory, same reasoning every other
extractor in this module gives for staying signal-only. A truncated image is reported through the
SAME `"fetch_failed"` skip reason `fetch_health` already uses (see that section below) rather than
a new string - Stage D doesn't need a finer bucket than "no usable image data," and inventing one
here would cross into the separately-invented-vocabulary problem `docs/features/catalog-completion-
plan.md`'s own `CardScanLog` design explicitly warns against.

`color_profile`: per-channel (R, G, B) mean and population standard deviation over the FULL fetched
image (`local_image_quality.compute_color_profile`, a first-party `PIL.ImageStat.Stat` call, not a
hand-rolled pixel loop) - "color statistics... store the math, not the strip" (FINAL POSTURE item
2). Skips (sharing `quality_signals`' own `truncated` finding, not a fresh decode attempt) under the
same `"fetch_failed"` skip reason for the same reason given above.

`local_image_quality.py` is NOT protected core (`docs/upstreaming/license-provenance.md` §2's file
list doesn't include it) - new helpers land there directly, matching `local_ocr.py`'s own precedent
for OCR-adjacent (non-protected) additions. No changes to `local_fallback.py`/`local_phash.py`
themselves (both PROTECTED CORE; not touched by this extractor group at all).

fetch_health completion (same re-spec): `fetch_latency_ms` (wall-clock time for the
`image_cdn_fetch.fetch_card_image` call, measured around the SAME call this extractor already
made - no second fetch) and `fetch_image_format` (the fetched image's own `PIL.Image.format`,
e.g. `"JPEG"`, blank-string-as-sentinel on fetch failure, matching `fetch_error_class`'s own
convention) complete the trivial substrate-PR version of this extractor (`fetch_ok`/
`fetch_error_class` only). `fetch_error_class`'s own value space is deliberately UNCHANGED -
still only `""`/`"fetch_failed"` - for the same separately-invented-vocabulary reason given above;
this PR adds new FIELDS, not a wider value space for an existing one. `FETCH_HEALTH_EXTRACTOR_
VERSION` is bumped (`v1` -> `v2`) to signal that a row bearing the OLD version tag was written
before these two fields existed - the "per-field completion/versioning map" ImageEvidence's own
docstring describes exists exactly to make this distinction readable by a future consumer.

RECONCILIATION LEDGER (owner directive 2026-07-19, task #155): `build_reconciliation_report`
answers "attempted = voted + each named skip-reason + dropped" for one extractor over one set
of cards, by querying ImageEvidence.extractor_versions + CardScanLog directly - see
ImageEvidence's own docstring for the exact voted/skipped/dropped definitions.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

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
from cardpicker.local_image_quality import (
    compute_blur_variance,
    compute_color_profile,
    compute_entropy,
    is_image_truncated,
)
from cardpicker.local_ocr import (
    ALTERNATE_TESSERACT_CONFIG,
    DEFAULT_CROP_BOX,
    LEGAL_LINE_CROP_BOX,
    TESSERACT_CONFIG,
    parse_collector_line,
    parse_legal_line,
    preprocess_fallback_variants,
    preprocess_variants,
    run_tesseract,
    run_tesseract_text_and_words,
)
from cardpicker.local_phash import ART_CROP_BOX
from cardpicker.models import Card, CardScanLog, ImageEvidence
from cardpicker.utils import twos_complement

logger = logging.getLogger(__name__)

# v1 -> v2 (issue #150's re-spec): completes this extractor with fetch_latency_ms/
# fetch_image_format - a row bearing the old "fetch-health-v1" tag predates those two fields.
FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v2"
GEOMETRY_BLEED_EXTRACTOR_VERSION = "geometry-bleed-v1"
LAYOUT_CLASS_EXTRACTOR_VERSION = "layout-class-v1"
CROP_COORDINATES_EXTRACTOR_VERSION = "crop-coordinates-v1"
COLLECTOR_LINE_OCR_EXTRACTOR_VERSION = "collector-line-ocr-v1"
ARTIST_OCR_EXTRACTOR_VERSION = "artist-ocr-v1"
COLLECTOR_LINE_TSV_EXTRACTOR_VERSION = "collector-line-tsv-v1"
SYMBOL_REGION_EXTRACTOR_VERSION = "symbol-region-v1"
LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"
QUALITY_SIGNALS_EXTRACTOR_VERSION = "quality-signals-v1"
COLOR_PROFILE_EXTRACTOR_VERSION = "color-profile-v1"

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

    `short_circuited` (2026-07-21, docs/features/catalog-completion-plan.md's "Recovery-arc
    lessons" item 1): True iff this card's `collector_line_ocr` pass hit the pre-classification
    short-circuit (tier-1 digit-free, tiers 2-3 skipped). Diagnostic-only, same "never persisted
    onto ImageEvidence" convention as `compute_card_evidence`'s own `profile` parameter - the
    plan's own "open verification gap" note calls for counting this population during the real
    197k-card run, not storing a fact per card; `persist_evidence` never reads this attribute.
    """

    card_id: int
    content_hash: Optional[int]
    fields: dict[str, Any] = field(default_factory=dict)
    extractor_versions: dict[str, str] = field(default_factory=dict)
    skip_reasons: dict[str, str] = field(default_factory=dict)
    short_circuited: bool = False


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


def _collector_line_ocr_attempts(cropped: Any) -> Iterator[tuple[Any, str, int]]:
    """
    Ordered, LAZY (image, tesseract_config, tier) attempts for the `collector_line_ocr` extractor
    (issue #259, "Stage D no-text bucket: OCR preprocessing/crop recovery") - cheapest/fastest
    first, each later tier strictly more expensive than the one before it. A generator (not a
    plain list) specifically so the caller's own "stop at the first attempt that parses a
    collector number" loop never actually pays for a later tier's preprocessing/OCR cost unless
    every earlier tier has already failed - `preprocess_fallback_variants(cropped)` below is not
    even CALLED, let alone OCR'd, for the common case where an early attempt already succeeds.
    The `tier` element (added for the "Recovery-arc lessons" item 1 pre-classification
    short-circuit, docs/features/catalog-completion-plan.md, 2026-07-21) lets the caller detect
    "both tier-1 attempts are now exhausted" without hardcoding or re-deriving tier boundaries
    from attempt position/count.

    - Tier 1 (attempts 1-2, PSM 6): `preprocess_variants`' original two polarity variants -
      UNCHANGED from before this issue, still the fast/happy path for the large majority of
      cards that already parse cleanly.
    - Tier 2 (attempts 3-6, PSM 6): `preprocess_fallback_variants`' four heavier-preprocessed
      variants (sharpen+heavier-upscale, percentile threshold) - targets the #259 diagnostic's
      two concrete B-bucket failure modes (blurry uploads, uneven-brightness "garbled but
      present" text) with better PIXELS, same page-segmentation assumption.
    - Tier 3 (attempts 7-8, PSM 11): tier 1's original variants again, but under
      `ALTERNATE_TESSERACT_CONFIG` - targets a genuinely different failure mode (tesseract's own
      block/line SEGMENTATION going wrong on a noisy crop), not a pixel-quality problem tier 2's
      preprocessing can fix. Retried against the original (not fallback-preprocessed) variants
      since PSM 11 already drops the block-structure assumption tier 2's heavier processing was
      never targeting in the first place.

    Worst case (a card that never parses anything, e.g. a genuine coverage-ceiling case) pays for
    all 8 attempts - up to 4x the pre-#259 cost (2 attempts), UNLESS the pre-classification
    short-circuit below fires first for a tier-1-digit-free card. This only hits cards whose
    collector line genuinely never resolves to a collector number under ANY of these attempts
    (and, since the short-circuit, whose tier-1 text also contains at least one digit character);
    the happy path (an early tier-1 parse) is unaffected in cost or behavior either way.
    """
    variants = preprocess_variants(cropped)
    for variant in variants:
        yield variant, TESSERACT_CONFIG, 1
    for variant in preprocess_fallback_variants(cropped):
        yield variant, TESSERACT_CONFIG, 2
    for variant in variants:
        yield variant, ALTERNATE_TESSERACT_CONFIG, 3


# Tier 1 is exactly `preprocess_variants`' own two polarity variants (see that function's own
# docstring - "both polarities of an adaptive-ish threshold") - hardcoded here rather than
# re-derived via a redundant extra preprocessing call just to learn the count. If that function's
# own variant count ever changes, this constant and `_collector_line_ocr_attempts`' own tier=1
# yield count must be updated together (already an implicit coupling the "8 attempts total"
# bookkeeping in that function's own docstring already assumes).
_COLLECTOR_LINE_TIER1_ATTEMPT_COUNT = 2

# Escape hatch for the pre-classification short-circuit (docs/features/catalog-completion-plan.md
# "Recovery-arc lessons" item 1, 2026-07-21) - STAGE_C_NO_SHORTCIRCUIT=1 (or "true"/"yes")
# disables it, for a measurement run that needs the full multi-tier escalation on every no-text
# card (e.g. to gather the "would a zero-digit-at-tier-1 card ever have recovered at a later
# tier" validation data the plan's own "open verification gap" note flags as not yet closeable
# from stored data alone). Same STAGE_C_* env-var convention as DEFAULT_WORKERS/
# DEFAULT_FETCH_THREADS in run_image_evidence_cohort.py.
STAGE_C_NO_SHORTCIRCUIT_ENV = "STAGE_C_NO_SHORTCIRCUIT"


def _short_circuit_enabled_by_env() -> bool:
    """Read at CALL TIME (not import time, so a test or a per-invocation env change takes effect
    without reimporting this module) - `compute_card_evidence`'s own `short_circuit=None` default
    resolves to this."""
    return os.environ.get(STAGE_C_NO_SHORTCIRCUIT_ENV, "").strip().lower() not in ("1", "true", "yes")


def _contains_digit(text: str) -> bool:
    """Cheap in-memory string scan (module docstring's "no new image work, no new tesseract
    call") - deliberately a plain character scan, NOT a re-run of `_COLLECTOR_NUMBER_RE` (that
    regex requires a specific bounded shape - see its own comment - so a digit CAN be present in
    text that regex still fails to extract a token from; the short-circuit's own condition is
    coarser and cheaper than the real parse on purpose, per the plan's own "STRUCTURE, not the
    parse itself" framing)."""
    return any(character.isdigit() for character in text)


def extract_card_evidence(
    card: Card,
    dpi: Optional[int] = DEFAULT_FETCH_DPI,
    profile: Optional[dict[str, float]] = None,
    short_circuit: Optional[bool] = None,
) -> ExtractionResult:
    """
    The per-card callable work unit - fetch, then compute. `card.content_phash` (not recomputed
    here) is the content hash this evidence is keyed against - hash-at-ingest (Part 2) already
    populates it for essentially every card by the time Stage C runs. If it's still null, the
    result's `content_hash` is None and `persist_evidence` will refuse to write a row, since
    ImageEvidence's "computed-once-forever" premise depends on a stable hash to key on.

    Split into a fetch step (here) + `compute_card_evidence` (2026-07-20, Stage C fetch/compute
    decoupling design, docs/features/catalog-completion-plan.md's Stage C section, #228) so a
    concurrent driver can run the fetch on an I/O-bound thread and the compute on a CPU-bound
    process, without this function's own single-caller behavior changing at all - every existing
    caller of `extract_card_evidence` (this pilot's tests, any future direct caller) still gets
    the exact same fetch-then-compute behavior in one call.

    `profile`, if given, is forwarded straight through to `compute_card_evidence` below and
    populated (in place) there with a `time.monotonic()`-delta timing breakdown - `fetch_ms`,
    `ocr_group_ms` (collector_line_ocr + artist_ocr + collector_line_tsv, the Tesseract-backed OCR
    group), `legal_line_ms` (the second Tesseract-backed extractor), `extraction_ms` (everything
    after fetch returns, i.e. every extractor combined), and `other_ms` (`extraction_ms` minus the
    two OCR-group figures - geometry_bleed/layout_class/crop_coordinates/symbol_region/
    quality_signals/color_profile combined). Diagnostic-only (2026-07-20,
    docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md) - `None` by default, zero behavior
    change and negligible overhead (a handful of extra `time.monotonic()` calls) when not passed;
    never persisted onto `ImageEvidence` itself, per docs/features/catalog-completion-plan.md's
    Stage C instrumentation spec ("aggregated into the run's own summary logging rather than a
    new persisted ImageEvidence field").

    `short_circuit`, if given, is forwarded straight through to `compute_card_evidence` below - see
    that function's own docstring for the pre-classification short-circuit this controls.
    """

    fetch_started_at = time.monotonic()
    try:
        image = fetch_card_image(card, dpi=dpi)
    except GoogleFetchLockoutError:
        # A 403 lockout is a hard stop for the whole run, not a per-card fetch-health
        # observation - propagate exactly as image_cdn_fetch.fetch_card_image's own docstring
        # requires every caller to.
        raise
    fetch_latency_ms = (time.monotonic() - fetch_started_at) * 1000

    return compute_card_evidence(
        card.pk, card.content_phash, image, fetch_latency_ms, profile=profile, short_circuit=short_circuit
    )


def compute_card_evidence(
    card_id: int,
    content_hash: Optional[int],
    image: Optional[Any],
    fetch_latency_ms: float,
    profile: Optional[dict[str, float]] = None,
    short_circuit: Optional[bool] = None,
) -> ExtractionResult:
    """
    Compute-only continuation of `extract_card_evidence` above - everything that function does
    AFTER its own fetch step, against an already-fetched `image` (a `PIL.Image.Image`, or `None`
    for a failed/skipped fetch) and a `fetch_latency_ms` the caller already measured. Takes a
    plain `card_id`/`content_hash` pair rather than a `Card` instance deliberately: this is the
    module-level, picklable entrypoint a `ProcessPoolExecutor` compute worker calls directly
    (`run_image_evidence_cohort.py`'s decoupled compute stage) once the fetch stage (a separate
    thread pool, I/O-bound, never itself CPU-heavy) has already produced `image` - a compute
    worker never touches the network, never calls `fetch_card_image`/`GoogleFetchLockoutError`
    can only ever originate in the fetch stage now. Never called with `image` freshly decoded
    from bytes on the FETCH side - the fetch stage hands over raw bytes
    (`image_cdn_fetch.fetch_card_image_bytes`) and the compute worker decodes them into an
    `Image` itself right before calling this, so the real pixel decode cost lands on the compute
    side, not the fetch side (see that function's own docstring for why this split matters for
    the hardware's network-vs-compute core allocation).

    `profile` (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md): see
    `extract_card_evidence`'s own docstring for the full field breakdown. `fetch_ms` is set here
    directly from the caller-supplied `fetch_latency_ms` (this function never measures its own
    fetch) - so the resulting profile shape is identical regardless of whether the caller is
    `extract_card_evidence` (bundled fetch+compute, one process/call) or the decoupled compute
    stage calling this directly with a `fetch_latency_ms` its own separate fetch stage already
    measured.

    `short_circuit` (2026-07-21, docs/features/catalog-completion-plan.md's "Recovery-arc lessons"
    item 1): controls the `collector_line_ocr` pre-classification short-circuit - once BOTH tier-1
    attempts fail to parse a collector number, if neither attempt's raw text contains a single
    digit character, tiers 2-3 (6 more tesseract calls) are skipped and the extractor goes
    straight to its existing "no-text" outcome, matching the measured finding that 99.7% of a
    real no-text cohort's tier-1 reads were already digit-free and never gained a collector number
    from the heavier tiers either. `None` (the default) resolves to `_short_circuit_enabled_by_env`
    (the `STAGE_C_NO_SHORTCIRCUIT` env var) - an explicit `True`/`False` overrides that
    resolution directly, which is what every test in this module and `run_image_evidence_cohort`'s
    own `--no-shortcircuit` CLI flag do, rather than relying on env-var monkeypatching. Digit-
    bearing tier-1 text that still fails to parse always escalates exactly as before - the
    short-circuit is strictly narrower than the full "no-text" outcome it pre-empts, never wider.
    """
    if short_circuit is None:
        short_circuit = _short_circuit_enabled_by_env()

    fields: dict[str, Any] = {"fetch_latency_ms": fetch_latency_ms}
    extractor_versions: dict[str, str] = {}
    skip_reasons: dict[str, str] = {}
    if profile is not None:
        profile["fetch_ms"] = fetch_latency_ms
    extraction_started_at = time.monotonic()

    if image is None:
        fields["fetch_ok"] = False
        fields["fetch_error_class"] = "fetch_failed"
        fields["fetch_image_format"] = ""
        skip_reasons["fetch_health"] = "fetch_failed"
    else:
        fields["fetch_ok"] = True
        fields["fetch_error_class"] = ""
        fields["fetch_image_format"] = getattr(image, "format", None) or ""
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
    _ocr_group_started_at = time.monotonic()
    card_short_circuited = False
    if image is None:
        skip_reasons["collector_line_ocr"] = "fetch_failed"
        skip_reasons["artist_ocr"] = "fetch_failed"
        skip_reasons["collector_line_tsv"] = "fetch_failed"
    else:
        collector_crop = image.crop(tuple(fields["collector_line_crop_px"]))

        # OCR call-cost reduction (docs/reports/2026-07-20-pipeline-compute-profile.md):
        # previously this ran run_tesseract (image_to_string) on EVERY variant unconditionally,
        # then a SEPARATE run_tesseract_tsv (image_to_data) call on whichever variant won - up to
        # 3 tesseract invocations per card for this one extractor. Now: one
        # run_tesseract_text_and_words call per variant TRIED (a single image_to_data call
        # yielding both the raw text and the word boxes at once - see that function's own
        # docstring), and the loop stops at the FIRST variant whose text parses a collector
        # number rather than always computing every variant - matches this same loop's own
        # pre-existing "first variant that produces something" precedence, just applied to WHEN
        # each variant gets OCR'd, not only to which one's result is kept.
        #
        # `_collector_line_ocr_attempts` (issue #259) supplies the FULL, lazily-evaluated
        # attempt order - the original two `preprocess_variants` polarities first (unchanged, the
        # happy path), then two fallback tiers (heavier-preprocessed variants, then an alternate
        # PSM re-try) that are only ever reached - and only ever cost a tesseract call - once
        # every earlier attempt has already failed to parse a collector number. See that
        # function's own docstring for the full tier breakdown and worst-case cost.
        #
        # Pre-classification short-circuit (2026-07-21, docs/features/catalog-completion-plan.md's
        # "Recovery-arc lessons" item 1): once both tier-1 attempts are exhausted with no parse, a
        # tier-1-digit-free card skips tiers 2-3 entirely rather than paying for 6 more tesseract
        # calls to re-read the same non-collector-number text more clearly - measured (2026-07-21,
        # a 6,643-card no-text cohort) at 99.7% of the genuinely-unrecoverable population, 0% loss
        # on that sample. A digit-bearing tier-1 read that still fails to parse always escalates
        # exactly as before - `_contains_digit` is a coarser, cheaper check than
        # `_COLLECTOR_NUMBER_RE` itself (see that helper's own docstring), so this can only ever
        # short-circuit a STRICT SUBSET of cards that would have ended in "no-text" anyway, never
        # a card that could have parsed at tier 1.
        collector_texts_and_words: list[tuple[str, list[dict[str, Any]]]] = []
        selected_index = 0
        parsed = parse_collector_line("")
        matched = False
        short_circuited = False
        tier1_raw_texts: list[str] = []
        for i, (variant, config, tier) in enumerate(_collector_line_ocr_attempts(collector_crop)):
            raw_text, word_boxes = run_tesseract_text_and_words(variant, config=config)
            collector_texts_and_words.append((raw_text, word_boxes))
            candidate_parse = parse_collector_line(raw_text)
            if candidate_parse.collector_number is not None:
                parsed = candidate_parse
                selected_index = i
                matched = True
                break
            if tier == 1:
                tier1_raw_texts.append(raw_text)
                if (
                    short_circuit
                    and len(tier1_raw_texts) == _COLLECTOR_LINE_TIER1_ATTEMPT_COUNT
                    and not any(_contains_digit(text) for text in tier1_raw_texts)
                ):
                    short_circuited = True
                    break
        if not matched and collector_texts_and_words:
            # every attempt actually tried (every tier, OR a short-circuit exit after tier 1)
            # found no parse - keep the first attempt's (empty-ish) parse as the deterministic
            # stored artifact, matching the pre-existing fallback precedence. Safe to reuse
            # unconditionally on a short-circuit exit too: `_contains_digit` false for both tier-1
            # texts means `_COLLECTOR_NUMBER_RE` (a strict subset check - see `_contains_digit`'s
            # own docstring) cannot have matched either, so re-parsing text[0] here can only ever
            # reproduce the same collector_number=None outcome already implied.
            parsed = parse_collector_line(collector_texts_and_words[0][0])
        card_short_circuited = short_circuited

        collector_raw_texts = [text for text, _words in collector_texts_and_words]
        fields["collector_line_raw_text"] = (
            collector_texts_and_words[selected_index][0] if collector_texts_and_words else ""
        )
        fields["collector_line_set_code"] = parsed.set_code or ""
        fields["collector_line_collector_number"] = parsed.collector_number or ""
        if parsed.collector_number is None:
            skip_reasons["collector_line_ocr"] = "no-text"

        # TSV word boxes: same winning variant the text parse above came from (computed by the
        # SAME tesseract call as that variant's raw text, not a second call) - so the word boxes
        # and the parsed text always describe the same underlying tesseract read.
        fields["collector_line_word_boxes"] = (
            collector_texts_and_words[selected_index][1] if collector_texts_and_words else []
        )

        # artist OCR: reuse collector_line_ocr's own raw texts first (see module docstring),
        # only cropping+OCR-ing artist_crop_px if none of those already contain an "Illus." match.
        # `collector_raw_texts` only contains as many entries as the loop above actually computed
        # (short-circuited once a collector number was found) - a real card whose collector-line
        # crop legitimately carries an "Illus." credit (old-border only, per this module's own
        # artist_ocr section) never has a genuine collector number to short-circuit on in the
        # first place, so the loop above runs to completion (computing every variant) for exactly
        # the population where this reuse would otherwise matter; verified against
        # TestExtractCardEvidenceArtistOcr's real-tesseract reuse test, not just argued.
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
    if profile is not None:
        profile["ocr_group_ms"] = (time.monotonic() - _ocr_group_started_at) * 1000

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

    # legal_line (issue #151, task #159's extractor half): a NEW, dedicated crop region (not a
    # reuse of collector_line_crop_px - see module docstring), OCR'd fresh (no reuse-before-
    # recompute here, unlike artist_ocr - the legal/copyright line's overlap with the collector
    # line region is coincidental, not the primary design point the way "Illus." credit's overlap
    # with the collector-line crop is), then a tolerant parse for copyright year + the proxy/
    # not-for-sale moderator-flag signal. No candidate matching (Stage D's job, same as every
    # other OCR-adjacent extractor above).
    _legal_line_started_at = time.monotonic()
    if image is None:
        skip_reasons["legal_line"] = "fetch_failed"
    else:
        fields["legal_line_crop_px"] = _crop_box_to_pixels(LEGAL_LINE_CROP_BOX, bleed_class, width, height)
        legal_crop = image.crop(tuple(fields["legal_line_crop_px"]))
        legal_variants = preprocess_variants(legal_crop)

        # OCR call-cost reduction (docs/reports/2026-07-20-pipeline-compute-profile.md): lazily
        # OCR each variant (run_tesseract, unchanged - no word boxes are stored for legal_line,
        # so there's no TSV call to batch here the way collector_line_ocr's does above), stopping
        # at the FIRST variant whose parse finds something (a year OR a proxy marker) rather than
        # always running tesseract against every variant - same "first variant that produces
        # something" precedence this selection already used, just applied to WHEN each variant
        # gets OCR'd too.
        legal_raw_texts: list[str] = []
        selected_index = 0
        legal_parsed = parse_legal_line("")
        for i, variant in enumerate(legal_variants):
            raw_text = run_tesseract(variant)
            legal_raw_texts.append(raw_text)
            legal_candidate_parse = parse_legal_line(raw_text)
            if legal_candidate_parse.copyright_year is not None or legal_candidate_parse.proxy_marker_detected:
                legal_parsed = legal_candidate_parse
                selected_index = i
                break
        else:
            if legal_raw_texts:
                legal_parsed = parse_legal_line(legal_raw_texts[0])

        fields["legal_line_raw_text"] = legal_raw_texts[selected_index] if legal_raw_texts else ""
        fields["legal_line_copyright_year"] = legal_parsed.copyright_year or ""
        fields["legal_line_proxy_marker_detected"] = legal_parsed.proxy_marker_detected
        if legal_parsed.copyright_year is None and not legal_parsed.proxy_marker_detected:
            skip_reasons["legal_line"] = "no-text"
    extractor_versions["legal_line"] = LEGAL_LINE_EXTRACTOR_VERSION
    if profile is not None:
        profile["legal_line_ms"] = (time.monotonic() - _legal_line_started_at) * 1000

    # quality_signals (issue #150's re-spec, the LAST Stage C manifest extractor): a degenerate
    # (zero/negative) width or height is guarded before anything else - the same "sub-floor"
    # input category geometry_bleed's own zero-height guard and symbol_region's degenerate-crop-
    # box guard handle for their own divisions/crops (see those sections above) - real fetched
    # images essentially never hit this. Truncation check next (is_image_truncated forces a full
    # pixel decode) - `truncated` is reused by color_profile just below rather than
    # re-attempting the same decode a second time (see module docstring for this explicit
    # cross-extractor dependency). blur_variance/image_entropy are only computed when the image
    # loaded cleanly - a truncated image's partial pixel data would produce meaningless numbers,
    # not a real reading.
    if image is None:
        skip_reasons["quality_signals"] = "fetch_failed"
    elif width <= 0 or height <= 0:
        truncated = False  # not truncated - never attempted, a degenerate size instead
        skip_reasons["quality_signals"] = "ambiguous"
    else:
        truncated = is_image_truncated(image)
        fields["image_is_truncated"] = truncated
        if truncated:
            # Shares fetch_health's own "fetch_failed" skip reason - see module docstring for
            # why this isn't a new, separately-invented skip-reason string.
            skip_reasons["quality_signals"] = "fetch_failed"
        else:
            fields["blur_variance"] = compute_blur_variance(image)
            fields["image_entropy"] = compute_entropy(image)
    extractor_versions["quality_signals"] = QUALITY_SIGNALS_EXTRACTOR_VERSION

    # color_profile (issue #150's re-spec): per-channel (R, G, B) mean/stddev over the FULL
    # fetched image - "color statistics... store the math, not the strip" (FINAL POSTURE item
    # 2). Reuses quality_signals' own degenerate-size guard and `truncated` finding above rather
    # than a fresh decode attempt.
    if image is None:
        skip_reasons["color_profile"] = "fetch_failed"
    elif width <= 0 or height <= 0:
        skip_reasons["color_profile"] = "ambiguous"
    elif truncated:
        skip_reasons["color_profile"] = "fetch_failed"
    else:
        mean_rgb, stddev_rgb = compute_color_profile(image)
        fields["color_mean_rgb"] = mean_rgb
        fields["color_stddev_rgb"] = stddev_rgb
    extractor_versions["color_profile"] = COLOR_PROFILE_EXTRACTOR_VERSION

    if profile is not None:
        profile["extraction_ms"] = (time.monotonic() - extraction_started_at) * 1000
        profile["other_ms"] = (
            profile["extraction_ms"] - profile.get("ocr_group_ms", 0.0) - profile.get("legal_line_ms", 0.0)
        )

    return ExtractionResult(
        card_id=card_id,
        content_hash=content_hash,
        fields=fields,
        extractor_versions=extractor_versions,
        skip_reasons=skip_reasons,
        short_circuited=card_short_circuited,
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
    "compute_card_evidence",
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
    "LEGAL_LINE_EXTRACTOR_VERSION",
    "QUALITY_SIGNALS_EXTRACTOR_VERSION",
    "COLOR_PROFILE_EXTRACTOR_VERSION",
]
