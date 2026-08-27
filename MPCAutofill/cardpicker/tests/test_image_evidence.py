"""
Stage C substrate tests (docs/features/catalog-completion-plan.md, task #145): the per-card
callable extraction unit + persistence split, the fetch_health extractor riding along as
end-to-end proof, and the reconciliation ledger (task #155). No network - `fetch_card_image`
is monkeypatched throughout.

geometry_bleed (task #147) is exercised against a lightweight `_StubImage` rather than a real
PIL Image - `local_fallback.classify_bleed_edge` (the function this extractor calls, unmodified)
only ever reads `.size`, so a bare `(width, height)` stand-in is sufficient and keeps these tests
fast/dependency-light; the real classifier function itself is never mocked, only its input.

layout_class (issue #148) calls `local_fallback.classify_border_color`, which DOES need a real
image (`.crop()`/`.convert()`/`.getdata()`) - every existing test that feeds a `_StubImage`
through `fetch_and_compute_card_evidence_for_tests` now also monkeypatches `classify_border_color` itself (not just
its input) so those tests keep exercising only what they're actually about (fetch_health/
geometry_bleed) without needing a real PIL image. `TestExtractCardEvidenceLayoutClass` below is
the one test class that uses real `PIL.Image` objects, mirroring `test_local_fallback.py`'s own
`TestClassifyBorderColor` fixture style, since it's actually testing that classifier's real
output.

crop_coordinates (issue #148) never touches the image object itself (only `width`/`height` +
`bleed_class`, both already-computed numbers/strings), so it never needs the classify_border_color
patch - it's exercised directly against `_StubImage`/`_TRIMMED_IMAGE` like geometry_bleed is.

collector_line_ocr / artist_ocr / collector_line_tsv (issue #149, the OCR-group) call `image.crop`
directly on the fetched image (consuming `collector_line_crop_px`/`artist_crop_px`, already
computed by crop_coordinates above - see image_evidence.py's module docstring) - every existing
test that feeds a `_StubImage` through `fetch_and_compute_card_evidence_for_tests` now also stubs the OCR-group's own
crop/tesseract entry points via `_stub_ocr` below (mirroring `_stub_border_color`'s identical
rationale: `_StubImage` has no `.crop()`/`.convert()` a real PIL image needs).
`TestExtractCardEvidenceCollectorLineOcr`/`ArtistOcr`/`CollectorLineTsv` below use real PIL images
+ the REAL tesseract binary throughout (no monkeypatching of run_tesseract itself) - per CLAUDE.md,
tesseract is installed in CI and real OCR tests are expected to run, not be skipped.

symbol_region (issue #160, "Part 4b: symbol harness") also calls `image.crop(...).convert("L")`
directly (via `_compute_region_phash`) - every existing test that feeds a `_StubImage` through
`fetch_and_compute_card_evidence_for_tests` now also stubs `_compute_region_phash` itself via `_stub_symbol_region`
below (same rationale as `_stub_border_color`/`_stub_ocr`). `TestExtractCardEvidenceSymbolRegion`
below uses real PIL images throughout (mirrors `TestExtractCardEvidenceLayoutClass`'s own style),
since it's actually testing `_compute_region_phash`'s real output.

artbox_phash (public issue #480, "Artbox perceptual-hash extractor: evidence-only, rides the
next whole-catalog pass" - EVIDENCE ONLY, every consumer explicitly out of scope) reuses the same
`_compute_region_phash` helper `symbol_region` does - every existing test that feeds a
`_StubImage` through `fetch_and_compute_card_evidence_for_tests` and already stubs `_compute_region_phash` via
`_stub_symbol_region` (this extractor's own call is covered for free, same shared-function
rationale). Unlike `symbol_region`, this extractor's CROP BOX SELECTION itself depends on real
(never stubbed) `classify_frame_style` output, which in turn depends on the OCR-group's own
already-computed `collector_line_collector_number`/`illus_anchor_fired` facts - `_stub_ocr`'s
`collector_raw_text` argument is what drives old/modern/unclassifiable in the tests below (a
digit-bearing text reads "modern", an "Illus. <name>" text with no digit reads "old", neither
reads unclassifiable - see `TestExtractCardEvidenceArtboxPhash` below). NO golden-set fixtures
exist for this extractor at merge time (no local fixtures - `golden_set.py`'s own real,
DB-backed cards are unreachable from a worktree with no `docker/.env`/live network fetch path -
the same limitation issue #423's tesserocr engine-swap spike stated honestly rather than glossed
over) - `ARTBOX_OLD_CROP_BOX`'s own comment in `image_evidence.py` records this as an open
follow-up for a future golden-set pass with real old-border ground truth.

legal_line (public issue #151, "Legal-line extractor + moderator flag + volume report (task
#159)" - extractor + moderator-flag signal only, see image_evidence.py's own module docstring for
the scope split) crops its OWN dedicated region (`local_ocr.LEGAL_LINE_CROP_BOX`, not a reuse of
`collector_line_crop_px`) and OCRs it fresh - `_stub_ocr` below already covers this (it patches
`preprocess_variants`/`run_tesseract` at the module level, so any `_StubImage`-based test already
stubs legal_line's own crop+OCR pass for free, same as it does for collector_line_ocr/artist_ocr).
`TestExtractCardEvidenceLegalLine` below uses real PIL images + the real tesseract binary
throughout, same rationale as the other OCR-group test classes.

quality_signals (public issue #150's re-spec, the LAST Stage C manifest extractor
group) calls `local_image_quality.is_image_truncated`/`compute_blur_variance`/`compute_entropy`
directly on the fetched image - every existing test that feeds a
`_StubImage` with a non-degenerate width/height through `fetch_and_compute_card_evidence_for_tests` now also stubs
these via `_stub_quality_signals` below (same rationale as
`_stub_border_color`/`_stub_ocr`/`_stub_symbol_region`). `TestExtractCardEvidenceQualitySignals`
below uses real PIL images throughout (mirrors `TestExtractCardEvidenceLayoutClass`/
`SymbolRegion`'s own style), since it's actually testing these functions' real output,
including a genuinely truncated real JPEG for the integrity-check path.
"""

from dataclasses import dataclass

import pytest
from PIL import Image, ImageDraw

import cardpicker.image_evidence as module
from cardpicker.collector_line_artist import build_artist_lexicon
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import (
    ART_EDGE_EXTRACTOR_VERSION,
    ARTBOX_MODERN_CROP_BOX,
    ARTBOX_OLD_CROP_BOX,
    ARTBOX_PHASH_EXTRACTOR_VERSION,
    ARTIST_OCR_EXTRACTOR_VERSION,
    COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
    COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
    CROP_COORDINATES_EXTRACTOR_VERSION,
    EXTRACTOR_OWNED_FIELDS,
    FETCH_HEALTH_EXTRACTOR_VERSION,
    GEOMETRY_BLEED_EXTRACTOR_VERSION,
    LAYOUT_CLASS_EXTRACTOR_VERSION,
    LEGAL_LINE_EXTRACTOR_VERSION,
    PINLINE_INSET_EXTRACTOR_VERSION,
    QUALITY_SIGNALS_EXTRACTOR_VERSION,
    SYMBOL_REGION_EXTRACTOR_VERSION,
    ExtractionResult,
    build_reconciliation_report,
    compute_card_evidence,
    content_phash_bleed_regime_is_current,
    fetch_and_compute_card_evidence_for_tests,
    persist_evidence,
)
from cardpicker.local_fallback import (
    ARTIST_CROP_BOX,
    BLEED_ASPECT_RATIO,
    SYMBOL_STRIP_BOX,
    TRIM_ASPECT_RATIO,
    normalize_crop_box,
)
from cardpicker.local_ocr import DEFAULT_CROP_BOX, LEGAL_LINE_CROP_BOX
from cardpicker.local_phash import ART_CROP_BOX
from cardpicker.local_pinline_inset import (
    CALL_MEASURED,
    VERDICT_MEASURED,
    EdgeReading,
    PinlineInsetResult,
)
from cardpicker.models import CardScanLog, CardTagVote, ImageEvidence
from cardpicker.modern_artist_credit import build_lexicon_index
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory, TagFactory


@dataclass(frozen=True)
class _StubImage:
    size: tuple[int, int]

    def crop(self, box):
        # a fake crop - real cropping is never exercised through _StubImage, only through the
        # real-PIL-image test classes below (see _stub_ocr's own docstring for why this is safe).
        return self


# A real fetched image at DEFAULT_FETCH_DPI (460) is ~1702px tall - these stub sizes just need to
# land at the right aspect ratio, not the right absolute resolution, since classify_bleed_edge
# only looks at the width/height ratio.
_BLEED_IMAGE = _StubImage(size=(round(1000 * BLEED_ASPECT_RATIO), 1000))
_TRIMMED_IMAGE = _StubImage(size=(round(1000 * TRIM_ASPECT_RATIO), 1000))
_AMBIGUOUS_IMAGE = _StubImage(size=(1000, 1000))  # square - far from both known ratios


def _stub_border_color(monkeypatch, value=None):
    """`_StubImage` has no `.crop()`/`.convert()`/`.getdata()`, so any test feeding one through
    `fetch_and_compute_card_evidence_for_tests` must stub out `classify_border_color` itself (not just its image
    input) - it's a different function than `classify_bleed_edge`, which only ever reads
    `.size`. `value` defaults to None (ambiguous) but tests that don't care about layout_class's
    own outcome pass a fixed non-None value to keep skip_reasons/extractor_versions assertions
    unaffected by an incidental "ambiguous" entry."""
    monkeypatch.setattr(module, "classify_border_color", lambda image, bleed_class=None: value)


def _stub_art_edge(monkeypatch, value=None):
    """`_StubImage` has no `.crop()`/`.convert()`/`.getdata()`, so any test feeding one through
    `fetch_and_compute_card_evidence_for_tests` must stub out `classify_art_edge_continuity`
    itself (same rationale as `_stub_border_color` above - `art_edge` runs right after
    `crop_coordinates`, before every OCR-group/symbol/artbox extractor, so it needs stubbing
    wherever `_stub_border_color` does)."""
    monkeypatch.setattr(module, "classify_art_edge_continuity", lambda image, art_crop_px: value)


def _stub_ocr(monkeypatch, collector_raw_text: str = "158/287 R MOM EN"):
    """`_StubImage.crop()` returns a fake crop with no real pixel data - any test feeding one
    through `fetch_and_compute_card_evidence_for_tests` must stub the OCR-group's own crop/tesseract entry points
    (same rationale as `_stub_border_color` above). `preprocess_variants`/
    `run_tesseract_text_and_words` are stubbed unconditionally (they need a real image);
    `run_tesseract`/`run_tesseract_text_and_words` return a caller-supplied raw string so the REAL
    `parse_collector_line`/`extract_artist_name` (never stubbed - both are pure string parsing, no
    image/tesseract dependency) still exercise their own logic against it, keeping these stand-in
    tests honest about what's actually parsed rather than faking the parsed fields directly.
    Defaults to a realistic modern-frame collector line with no artist credit in it (matching real
    cards, where "Illus." text is an old-border-only convention) - `artist_ocr` genuinely skips
    ("no-text") under this default, which is the correct outcome for a modern card, not an
    oversight. `run_tesseract_text_and_words` (2026-07-20, OCR call-cost reduction - a single
    tesseract call returning both text and word boxes, see local_ocr.py's own docstring) replaces
    the old separate `run_tesseract`/`run_tesseract_tsv` calls collector_line_ocr's own winning
    variant used to make - stubbed here to return `(collector_raw_text, [])`, matching the old
    stub's "real text, empty word boxes" contract. Accepts (and ignores) a `config` kwarg (issue
    #259's `_collector_line_ocr_attempts` always passes one) - the default `collector_raw_text`
    always parses a collector number on this stub's very first attempt, so no test using the
    default ever reaches a tier where `config` would differ from PSM 6 anyway.

    `preprocess_variants` is stubbed to a TWO-element list (`[cropped, cropped]`), matching real
    `preprocess_variants`' own "both polarities" contract (`_COLLECTOR_LINE_TIER1_ATTEMPT_COUNT`)
    - issue #480's artbox_phash tests are the first ones in this file to pass a digit-free,
    never-parsing `collector_raw_text` through this stub, which surfaced a real gap: a
    single-element stub never lets tier-1's own attempt COUNT reach 2, so the pre-classification
    short-circuit's own `len(tier1_raw_texts) == _COLLECTOR_LINE_TIER1_ATTEMPT_COUNT` gate never
    fires, falling through into `preprocess_fallback_variants` - real, UNSTUBBED PIL preprocessing
    that crashes on a `_StubImage`'s fake `.crop()` result. Also stubs `preprocess_fallback_
    variants` itself (mirroring `preprocess_variants`) as a second line of defense - belt-and-
    braces, since a real card whose tier-1 attempts both come back non-blank-but-unparseable
    (digit-bearing) still escalates into tier 2 exactly as designed, and any future `_StubImage`
    test hitting that path must not crash for the same reason."""
    monkeypatch.setattr(module, "preprocess_variants", lambda cropped: [cropped, cropped])
    monkeypatch.setattr(module, "preprocess_fallback_variants", lambda cropped: [cropped, cropped, cropped, cropped])
    monkeypatch.setattr(module, "run_tesseract", lambda variant, config=None: collector_raw_text)
    monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda variant, config=None: (collector_raw_text, []))


def _stub_symbol_region(monkeypatch, value: int = 123456789):
    """`_StubImage` has no `.crop()`/`.convert()` a real PIL image needs, so any test feeding one
    through `fetch_and_compute_card_evidence_for_tests` must stub `_compute_region_phash` itself (same rationale as
    `_stub_border_color`/`_stub_ocr` above) - `symbol_crop_px` itself is still computed for real
    (it only needs width/height/bleed_class, same as crop_coordinates), only the phash of the
    (fake) cropped region is stubbed out."""
    monkeypatch.setattr(module, "_compute_region_phash", lambda image, box: value)


def _stub_quality_signals(monkeypatch, truncated: bool = False, blur: float = 42.0, entropy: float = 5.0):
    """`_StubImage` has no `.load()`/`.convert()` a real PIL image needs, so any test feeding one
    through `fetch_and_compute_card_evidence_for_tests` (and whose image has a non-degenerate width/height, so the
    `quality_signals` extractor's own guard doesn't already skip it - see
    `image_evidence.py`'s module docstring) must stub `is_image_truncated`/`compute_blur_variance`/
    `compute_entropy` themselves (same rationale as `_stub_border_color`/`_stub_ocr`/
    `_stub_symbol_region` above)."""
    monkeypatch.setattr(module, "is_image_truncated", lambda image: truncated)
    monkeypatch.setattr(module, "compute_blur_variance", lambda image: blur)
    monkeypatch.setattr(module, "compute_entropy", lambda image: entropy)


def _a_pinline_inset_result() -> PinlineInsetResult:
    """A concrete, non-skip `measure_pinline_inset` outcome (all four edges confidently
    measured) - used by tests that stub `_StubImage` through the full pipeline but want
    `pinline_inset` to genuinely NOT skip, mirroring `_stub_border_color`'s own
    caller-supplied-non-None-value convention above."""
    reading = EdgeReading(inset_frac=0.01, call=CALL_MEASURED)
    return PinlineInsetResult(top=reading, bottom=reading, left=reading, right=reading, verdict=VERDICT_MEASURED)


def _stub_pinline_inset(monkeypatch, result=None):
    """`_StubImage` has no `.convert()`/pixel data a real PIL image needs, so any test feeding
    one through `fetch_and_compute_card_evidence_for_tests` (and whose image has a
    non-degenerate width/height, so the `pinline_inset` extractor's own guard doesn't already
    skip it - see `image_evidence.py`'s module docstring) must stub `measure_pinline_inset`
    itself (same rationale as `_stub_border_color`/`_stub_ocr`/`_stub_symbol_region`/
    `_stub_quality_signals` above). Defaults to `None` (the extractor's own degenerate-input
    abstention outcome) so tests that don't care about pinline_inset's own result keep an
    "ambiguous" skip_reasons entry rather than an incidental fields write."""
    monkeypatch.setattr(module, "measure_pinline_inset", lambda image: result)


def _build_card_image(
    regions: list[tuple[tuple[float, float, float, float], str]], bleed: bool = True
) -> "Image.Image":
    """A real white-background PIL image at BLEED_ASPECT_RATIO/TRIM_ASPECT_RATIO, with each
    (fixed-fraction box, text) pair rendered as a black rectangle + white text - shared real-
    tesseract fixture for the OCR-group extractor tests below (mirrors
    TestExtractCardEvidenceLayoutClass's own real-PIL-image style, since these extractors
    genuinely read pixels, not just width/height/bleed_class)."""
    ratio = BLEED_ASPECT_RATIO if bleed else TRIM_ASPECT_RATIO
    height = 1300
    width = round(height * ratio)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for (left, top, right, bottom), text in regions:
        box = [round(left * width), round(top * height), round(right * width), round(bottom * height)]
        draw.rectangle(box, fill="black")
        if text:
            draw.text((box[0] + 5, box[1] + 10), text, fill="white")
    return img


class TestExtractCardEvidence:
    def test_successful_fetch_marks_fetch_ok_and_records_no_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch, result=_a_pinline_inset_result())

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.card_id == card.pk
        assert result.content_hash == 12345
        assert result.fields["fetch_ok"] is True
        assert result.fields["fetch_error_class"] == ""
        assert result.fields["fetch_image_format"] == ""  # _StubImage has no .format attribute
        assert isinstance(result.fields["fetch_latency_ms"], float)
        assert result.extractor_versions == {
            "fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION,
            "geometry_bleed": GEOMETRY_BLEED_EXTRACTOR_VERSION,
            "layout_class": LAYOUT_CLASS_EXTRACTOR_VERSION,
            "crop_coordinates": CROP_COORDINATES_EXTRACTOR_VERSION,
            "art_edge": ART_EDGE_EXTRACTOR_VERSION,
            "collector_line_ocr": COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
            "artist_ocr": ARTIST_OCR_EXTRACTOR_VERSION,
            "collector_line_tsv": COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
            "artbox_phash": ARTBOX_PHASH_EXTRACTOR_VERSION,
            "symbol_region": SYMBOL_REGION_EXTRACTOR_VERSION,
            "legal_line": LEGAL_LINE_EXTRACTOR_VERSION,
            "quality_signals": QUALITY_SIGNALS_EXTRACTOR_VERSION,
            "pinline_inset": PINLINE_INSET_EXTRACTOR_VERSION,
        }
        # _stub_ocr's default raw text ("158/287 R MOM EN") is a realistic modern-frame collector
        # line with no artist credit in it - artist_ocr genuinely skips here, which is the
        # correct outcome for a modern card (see _stub_ocr's own docstring), not a gap. The same
        # text also carries no copyright year or proxy/not-for-sale marker, so legal_line
        # genuinely skips here too (it's fed the identical stubbed text - see _stub_ocr's own
        # module-level patch of run_tesseract). artbox_phash does NOT skip: the same stubbed text
        # parses a real collector number, so classify_frame_style reads "modern" - see
        # TestExtractCardEvidenceArtboxPhash below for the extractor's own dedicated tests.
        # pinline_inset does NOT skip either - _stub_pinline_inset above is given a concrete
        # non-skip result rather than its own default (see this test's own "no_skip" name).
        assert result.skip_reasons == {"artist_ocr": "no-text", "legal_line": "no-text"}

    def test_forwards_the_cards_own_md5_checksum_onto_the_result(self, db, monkeypatch):
        card = CardFactory(content_phash=12345, md5_checksum="abc123")
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["md5_checksum"] == "abc123"
        assert result.fields["sha256_checksum"] is None  # Card.sha256_checksum doesn't exist yet

    def test_failed_fetch_marks_fetch_not_ok_and_records_a_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["fetch_ok"] is False
        assert result.fields["fetch_error_class"] == "fetch_failed"
        assert result.fields["fetch_image_format"] == ""
        assert isinstance(result.fields["fetch_latency_ms"], float)
        # no other field is written on a fetch failure - quality_signals shares the
        # same root cause (see below) and withholds its own fields entirely, same as every other
        # extractor group.
        assert "image_is_truncated" not in result.fields
        assert "blur_variance" not in result.fields
        # extractor_versions is still set for every extractor - each ran to completion, it just
        # found a negative result (a fetch failure is a shared root cause, not a crash in any of
        # them). Only a crash omits an extractor's own key (see ExtractionResult's docstring).
        assert result.extractor_versions == {
            "fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION,
            "geometry_bleed": GEOMETRY_BLEED_EXTRACTOR_VERSION,
            "layout_class": LAYOUT_CLASS_EXTRACTOR_VERSION,
            "crop_coordinates": CROP_COORDINATES_EXTRACTOR_VERSION,
            "art_edge": ART_EDGE_EXTRACTOR_VERSION,
            "collector_line_ocr": COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
            "artist_ocr": ARTIST_OCR_EXTRACTOR_VERSION,
            "collector_line_tsv": COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
            "artbox_phash": ARTBOX_PHASH_EXTRACTOR_VERSION,
            "symbol_region": SYMBOL_REGION_EXTRACTOR_VERSION,
            "legal_line": LEGAL_LINE_EXTRACTOR_VERSION,
            "quality_signals": QUALITY_SIGNALS_EXTRACTOR_VERSION,
            "pinline_inset": PINLINE_INSET_EXTRACTOR_VERSION,
        }
        assert result.skip_reasons == {
            "fetch_health": "fetch_failed",
            "geometry_bleed": "fetch_failed",
            "layout_class": "fetch_failed",
            "crop_coordinates": "fetch_failed",
            "art_edge": "fetch_failed",
            "collector_line_ocr": "fetch_failed",
            "artist_ocr": "fetch_failed",
            "collector_line_tsv": "fetch_failed",
            "artbox_phash": "fetch_failed",
            "symbol_region": "fetch_failed",
            "legal_line": "fetch_failed",
            "quality_signals": "fetch_failed",
            "pinline_inset": "fetch_failed",
        }

    def test_null_content_phash_surfaces_as_none(self, db, monkeypatch):
        card = CardFactory(content_phash=None)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.content_hash is None

    def test_lockout_error_propagates_not_swallowed(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)

        def _raise_lockout(card, dpi=None):
            raise GoogleFetchLockoutError("locked out")

        monkeypatch.setattr(module, "fetch_card_image", _raise_lockout)

        with pytest.raises(GoogleFetchLockoutError):
            fetch_and_compute_card_evidence_for_tests(card)

    def test_no_db_writes_happen(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        fetch_and_compute_card_evidence_for_tests(card)

        assert ImageEvidence.objects.count() == 0
        assert CardScanLog.objects.count() == 0


class TestExtractCardEvidenceGeometryBleed:
    """task #147 - the first real manifest extractor."""

    def test_bleed_image_records_dims_ratio_and_bleed_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        width, height = _BLEED_IMAGE.size
        assert result.fields["width"] == width
        assert result.fields["height"] == height
        assert result.fields["aspect_ratio"] == pytest.approx(width / height)
        assert result.fields["bleed_class"] == "bleed"
        assert "geometry_bleed" not in result.skip_reasons

    def test_trimmed_image_records_trimmed_bleed_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _TRIMMED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["bleed_class"] == "trimmed"
        assert "geometry_bleed" not in result.skip_reasons

    def test_ambiguous_aspect_ratio_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _AMBIGUOUS_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        # bleed_class stores "" (not null) for the ambiguous case, matching fetch_error_class's
        # own blank-string-as-sentinel convention (see ImageEvidence's docstring).
        assert result.fields["bleed_class"] == ""
        assert result.skip_reasons["geometry_bleed"] == "ambiguous"
        # geometry_bleed still ran to completion (width/height/aspect_ratio were computable even
        # though bleed classification itself abstained) - only the fetch failure case below
        # withholds these fields entirely.
        assert result.fields["width"] == 1000
        assert result.fields["aspect_ratio"] == pytest.approx(1.0)

    def test_zero_height_image_guards_aspect_ratio_division(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _StubImage(size=(100, 0)))
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["aspect_ratio"] is None
        assert result.skip_reasons["geometry_bleed"] == "ambiguous"
        # artbox_phash (issue #480): _stub_ocr's default collector-number-bearing text reads
        # classify_frame_style as "modern" (a real, unstubbed call - see this extractor's own
        # section in image_evidence.py's module docstring), so ARTBOX_MODERN_CROP_BOX is picked -
        # height=0 then makes ITS pixel box degenerate too (top == bottom == 0), the same real,
        # non-fabricated guard symbol_region's own degenerate-crop-box check exercises just below.
        # No stub needed - _compute_region_phash is never called for a degenerate box. Present
        # and explicitly None, not absent (issue #925) - see compute_card_evidence's own comment
        # on this branch.
        assert result.fields["artbox_crop_px"] is None
        assert result.fields["artbox_phash"] is None
        assert result.skip_reasons["artbox_phash"] == "ambiguous"
        # symbol_region (issue #160): height=0 makes SYMBOL_STRIP_BOX's own pixel box degenerate
        # (top == bottom == 0) - the genuine, non-fabricated trigger of its degenerate-crop-box
        # guard (see image_evidence.py's module docstring: not expected to fire against the real
        # golden set, but a real mechanical guard, exercised for real here). No stub needed -
        # _compute_region_phash is never called for a degenerate box.
        assert "symbol_crop_px" not in result.fields
        assert "symbol_phash" not in result.fields
        assert result.skip_reasons["symbol_region"] == "ambiguous"
        # quality_signals (issue #150's re-spec) shares this same degenerate-size
        # guard - height=0 skips it as "ambiguous", no stub needed since is_image_truncated/
        # compute_blur_variance/compute_entropy are never called for a
        # degenerate size.
        assert "image_is_truncated" not in result.fields
        assert "blur_variance" not in result.fields
        assert result.skip_reasons["quality_signals"] == "ambiguous"

    def test_fetch_failure_withholds_geometry_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "width" not in result.fields
        assert "height" not in result.fields
        assert "aspect_ratio" not in result.fields
        assert "bleed_class" not in result.fields
        assert result.skip_reasons["geometry_bleed"] == "fetch_failed"
        # every geometry-group extractor shares the same root cause - see module docstring.
        assert "layout_class" not in result.fields
        assert result.skip_reasons["layout_class"] == "fetch_failed"
        assert "collector_line_crop_px" not in result.fields
        assert result.skip_reasons["crop_coordinates"] == "fetch_failed"
        # the OCR-group (issue #149) shares the same root cause too.
        assert "collector_line_raw_text" not in result.fields
        assert result.skip_reasons["collector_line_ocr"] == "fetch_failed"
        # symbol_region (issue #160) shares the same root cause too.
        assert "symbol_crop_px" not in result.fields
        assert result.skip_reasons["symbol_region"] == "fetch_failed"
        assert "artist_ocr_name" not in result.fields
        assert result.skip_reasons["artist_ocr"] == "fetch_failed"
        assert "collector_line_word_boxes" not in result.fields
        assert result.skip_reasons["collector_line_tsv"] == "fetch_failed"
        # artbox_phash (issue #480) shares the same root cause too.
        assert "artbox_crop_px" not in result.fields
        assert "artbox_phash" not in result.fields
        assert result.skip_reasons["artbox_phash"] == "fetch_failed"
        # legal_line (issue #151) shares the same root cause too.
        assert "legal_line_crop_px" not in result.fields
        assert result.skip_reasons["legal_line"] == "fetch_failed"
        # quality_signals (issue #150's re-spec) shares the same root cause too.
        assert "image_is_truncated" not in result.fields
        assert result.skip_reasons["quality_signals"] == "fetch_failed"

    def test_persist_writes_geometry_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"width": 925, "height": 1300, "aspect_ratio": 925 / 1300, "bleed_class": "bleed"},
            extractor_versions={"geometry_bleed": GEOMETRY_BLEED_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.width == 925
        assert evidence.height == 1300
        assert evidence.aspect_ratio == pytest.approx(925 / 1300)
        assert evidence.bleed_class == "bleed"


class TestExtractCardEvidenceLayoutClass:
    """issue #148 (geometry-group) - layout_class calls local_fallback.classify_border_color
    directly, unmodified. Real PIL images throughout (unlike geometry_bleed's _StubImage above)
    since classify_border_color genuinely samples pixel data - mirrors
    test_local_fallback.py::TestClassifyBorderColor's own fixture style."""

    @staticmethod
    def _bordered_image(border_rgb: tuple[int, int, int], bleed: bool = True) -> "Image.Image":
        ratio = BLEED_ASPECT_RATIO if bleed else TRIM_ASPECT_RATIO
        width = round(1000 * ratio)
        img = Image.new("RGB", (width, 1000), border_rgb)
        draw = ImageDraw.Draw(img)
        draw.rectangle([round(width * 0.08), 60, round(width * 0.92), 940], fill=(120, 80, 200))
        return img

    def test_black_border_records_layout_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._bordered_image((5, 5, 5)))

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["bleed_class"] == "bleed"
        assert result.fields["layout_class"] == "black"
        assert "layout_class" not in result.skip_reasons

    def test_white_border_records_layout_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._bordered_image((250, 250, 250)))

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["layout_class"] == "white"

    def test_ambiguous_color_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        # gold/yellow - explicitly outside the v1 taxonomy, see classify_border_color's own
        # docstring.
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._bordered_image((180, 140, 40)))

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["layout_class"] == ""
        assert result.skip_reasons["layout_class"] == "ambiguous"

    def test_fetch_failure_withholds_layout_class_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "layout_class" not in result.fields
        assert result.skip_reasons["layout_class"] == "fetch_failed"

    def test_persist_writes_layout_class(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"layout_class": "white"},
            extractor_versions={"layout_class": LAYOUT_CLASS_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.layout_class == "white"


class TestExtractCardEvidenceCropCoordinates:
    """issue #148 (geometry-group) - crop_coordinates turns DEFAULT_CROP_BOX/ARTIST_CROP_BOX/
    ART_CROP_BOX into pixel coordinates for this specific fetched image. Never touches the image
    object itself (only width/height + bleed_class), so it's exercised against _StubImage like
    geometry_bleed, with classify_border_color and the OCR-group's own entry points (_stub_ocr -
    issue #149 now also reads collector_line_crop_px/artist_crop_px, which _StubImage's fake
    .crop() satisfies) always stubbed out alongside it."""

    def test_ambiguous_bleed_class_applies_no_remap(self, db, monkeypatch):
        # 1000x2000 is not a real card aspect ratio - bleed_class comes out "" (ambiguous),
        # which is (like 'bleed') a no-op for normalize_crop_box, so the raw fixed-fraction
        # boxes apply directly with no remapping - a clean, hand-verifiable case.
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _StubImage(size=(1000, 2000)))
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        left, top, right, bottom = DEFAULT_CROP_BOX
        assert result.fields["collector_line_crop_px"] == [
            round(left * 1000),
            round(top * 2000),
            round(right * 1000),
            round(bottom * 2000),
        ]

    def test_trimmed_image_applies_normalize_crop_box_remap(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _TRIMMED_IMAGE)
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        width, height = _TRIMMED_IMAGE.size
        left, top, right, bottom = normalize_crop_box(ARTIST_CROP_BOX, "trimmed")
        assert result.fields["artist_crop_px"] == [
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        ]

    def test_bleed_image_computes_all_three_boxes(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        width, height = _BLEED_IMAGE.size
        for field_name, box in (
            ("collector_line_crop_px", DEFAULT_CROP_BOX),
            ("artist_crop_px", ARTIST_CROP_BOX),
            ("art_crop_px", ART_CROP_BOX),
        ):
            left, top, right, bottom = box  # 'bleed' is a no-op for normalize_crop_box
            assert result.fields[field_name] == [
                round(left * width),
                round(top * height),
                round(right * width),
                round(bottom * height),
            ]

    def test_fetch_failure_withholds_crop_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "collector_line_crop_px" not in result.fields
        assert "artist_crop_px" not in result.fields
        assert "art_crop_px" not in result.fields
        assert result.skip_reasons["crop_coordinates"] == "fetch_failed"
        # the OCR-group (issue #149) shares the same root cause too.
        assert result.skip_reasons["collector_line_ocr"] == "fetch_failed"
        assert result.skip_reasons["artist_ocr"] == "fetch_failed"
        assert result.skip_reasons["collector_line_tsv"] == "fetch_failed"
        # symbol_region (issue #160) shares the same root cause too.
        assert "symbol_crop_px" not in result.fields
        assert result.skip_reasons["symbol_region"] == "fetch_failed"
        # legal_line (issue #151) shares the same root cause too.
        assert "legal_line_crop_px" not in result.fields
        assert result.skip_reasons["legal_line"] == "fetch_failed"
        # quality_signals (issue #150's re-spec) shares the same root cause too.
        assert result.skip_reasons["quality_signals"] == "fetch_failed"

    def test_persist_writes_crop_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={
                "collector_line_crop_px": [60, 1800, 350, 1930],
                "artist_crop_px": [0, 1640, 1000, 2000],
                "art_crop_px": [70, 200, 930, 1160],
            },
            extractor_versions={"crop_coordinates": CROP_COORDINATES_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.collector_line_crop_px == [60, 1800, 350, 1930]
        assert evidence.artist_crop_px == [0, 1640, 1000, 2000]
        assert evidence.art_crop_px == [70, 200, 930, 1160]


class TestExtractCardEvidenceSymbolRegion:
    """issue #160, "Part 4b: symbol harness" - symbol_crop_px turns SYMBOL_STRIP_BOX into pixel
    coordinates the same way crop_coordinates derives its own three boxes; symbol_phash is a raw
    perceptual hash of that region only (never compared against any candidate here - see
    image_evidence.py's module docstring for why that's Stage D's job). Real PIL images
    throughout (mirrors TestExtractCardEvidenceLayoutClass's own style), since this extractor
    genuinely reads pixels via `_compute_region_phash`."""

    @staticmethod
    def _image_with_symbol_strip(width: int = 1000, height: int = 1000) -> "Image.Image":
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        left, top, right, bottom = SYMBOL_STRIP_BOX
        box = [round(left * width), round(top * height), round(right * width), round(bottom * height)]
        # a checkerboard, not a flat fill - phash's DCT-based hash is degenerate (near-identical
        # regardless of fill color) for a perfectly uniform region, the same reason
        # local_fallback.py's own keyrune-glyph comparison needs real edges/contrast to
        # discriminate at all (see that module's SYMBOL_DISTANCE_THRESHOLD comment) - a flat
        # rectangle isn't a realistic stand-in for a printed set symbol's actual edges.
        step = 6
        for y in range(box[1], box[3], step):
            for x in range(box[0], box[2], step):
                if (x // step + y // step) % 2 == 0:
                    draw.rectangle([x, y, x + step, y + step], fill=(10, 20, 30))
        return img

    def test_bleed_image_computes_symbol_crop_px(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = self._image_with_symbol_strip(1000, 1000)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        left, top, right, bottom = SYMBOL_STRIP_BOX  # 'ambiguous' bleed_class is a no-op remap
        assert result.fields["symbol_crop_px"] == [
            round(left * 1000),
            round(top * 1000),
            round(right * 1000),
            round(bottom * 1000),
        ]
        assert "symbol_region" not in result.skip_reasons

    def test_computes_a_real_phash_int(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = self._image_with_symbol_strip(1000, 1000)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert isinstance(result.fields["symbol_phash"], int)
        # a signed 64-bit int (twos_complement's own output range) - not asserting an exact value,
        # since the precise phash bits are a library-version-dependent implementation detail (same
        # "don't pin the continuous/brittle" rationale geometry_bleed's own comment gives for
        # width/height/aspect_ratio).
        assert -(2**63) <= result.fields["symbol_phash"] < 2**63

    def test_different_regions_hash_differently(self, db, monkeypatch):
        # a blank (all-white) card vs. one with a distinct rendered strip - real evidence the
        # hash actually reflects this region's own content, not a constant.
        card = CardFactory(content_phash=1)
        blank_image = Image.new("RGB", (1000, 1000), "white")
        marked_image = self._image_with_symbol_strip(1000, 1000)

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: blank_image)
        blank_result = fetch_and_compute_card_evidence_for_tests(card)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: marked_image)
        marked_result = fetch_and_compute_card_evidence_for_tests(card)

        assert blank_result.fields["symbol_phash"] != marked_result.fields["symbol_phash"]

    def test_degenerate_crop_box_records_named_skip_and_withholds_fields(self, db, monkeypatch):
        # height=0 collapses SYMBOL_STRIP_BOX's own pixel box to zero area (top == bottom == 0) -
        # the same real, non-fabricated trigger TestExtractCardEvidenceGeometryBleed's own
        # test_zero_height_image_guards_aspect_ratio_division exercises for geometry_bleed.
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _StubImage(size=(100, 0)))
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "symbol_crop_px" not in result.fields
        assert "symbol_phash" not in result.fields
        assert result.skip_reasons["symbol_region"] == "ambiguous"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "symbol_crop_px" not in result.fields
        assert "symbol_phash" not in result.fields
        assert result.skip_reasons["symbol_region"] == "fetch_failed"

    def test_persist_writes_symbol_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"symbol_crop_px": [780, 550, 1000, 800], "symbol_phash": -12345},
            extractor_versions={"symbol_region": SYMBOL_REGION_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.symbol_crop_px == [780, 550, 1000, 800]
        assert evidence.symbol_phash == -12345


class TestExtractCardEvidenceArtboxPhash:
    """public issue #480, "Artbox perceptual-hash extractor: evidence-only, rides the next
    whole-catalog pass" - EVIDENCE ONLY, every consumer explicitly out of scope for this
    extractor. See module docstring's own artbox_phash paragraph for the full test-setup
    rationale (why `_stub_ocr`'s `collector_raw_text` argument drives the frame classification
    these tests exercise, and the honest "no golden-set fixtures yet" limitation)."""

    def test_digit_bearing_text_reads_modern_and_uses_modern_crop_box(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch, "158/287 R MOM EN")  # digit-bearing -> a real collector number
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["artbox_frame_class"] == "modern"
        width, height = _BLEED_IMAGE.size
        left, top, right, bottom = ARTBOX_MODERN_CROP_BOX  # 'bleed' is a no-op remap
        assert result.fields["artbox_crop_px"] == [
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        ]
        assert "artbox_phash" in result.fields
        assert "artbox_phash" not in result.skip_reasons

    def test_illus_anchor_with_no_digit_reads_old_and_uses_old_crop_box(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        # no digit anywhere - _COLLECTOR_NUMBER_RE never matches, so collector_number stays None;
        # "Illus." anchor fires via extract_artist_name's own regex (see local_fallback.py).
        _stub_ocr(monkeypatch, "Illus. John Avon")
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["collector_line_collector_number"] == ""
        assert result.fields["illus_anchor_fired"] is True
        assert result.fields["artbox_frame_class"] == "old"
        width, height = _BLEED_IMAGE.size
        left, top, right, bottom = ARTBOX_OLD_CROP_BOX  # 'bleed' is a no-op remap
        assert result.fields["artbox_crop_px"] == [
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        ]
        assert "artbox_phash" in result.fields
        assert "artbox_phash" not in result.skip_reasons

    def test_neither_signal_is_unclassifiable_and_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        # neither a collector number nor an "Illus." credit - classify_frame_style's own
        # documented "neither -> abstain (None)" outcome (see local_fallback.py's own comment).
        _stub_ocr(monkeypatch, "no signal here at all")
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["artbox_frame_class"] == ""
        # issue #925: present and explicitly None, not absent - see compute_card_evidence's own
        # comment on this branch for why an unclassifiable frame must clear rather than withhold.
        assert result.fields["artbox_crop_px"] is None
        assert result.fields["artbox_phash"] is None
        assert result.skip_reasons["artbox_phash"] == "ambiguous"

    def test_trimmed_image_applies_normalize_crop_box_remap(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _TRIMMED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch, "158/287 R MOM EN")
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)

        width, height = _TRIMMED_IMAGE.size
        left, top, right, bottom = normalize_crop_box(ARTBOX_MODERN_CROP_BOX, "trimmed")
        assert result.fields["artbox_crop_px"] == [
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        ]

    def test_degenerate_crop_box_records_named_skip_and_withholds_fields(self, db, monkeypatch):
        # height=0 collapses ARTBOX_MODERN_CROP_BOX's own pixel box to zero area (top == bottom
        # == 0) - the same real, non-fabricated trigger symbol_region's own equivalent test
        # exercises.
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _StubImage(size=(100, 0)))
        _stub_border_color(monkeypatch)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch, "158/287 R MOM EN")

        result = fetch_and_compute_card_evidence_for_tests(card)

        # Same explicit-clear reasoning as the unclassifiable-frame test above: the box was
        # computed and rejected as degenerate, so this is also a genuine "no value" answer.
        assert result.fields["artbox_crop_px"] is None
        assert result.fields["artbox_phash"] is None
        assert result.skip_reasons["artbox_phash"] == "ambiguous"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "artbox_frame_class" not in result.fields
        assert "artbox_crop_px" not in result.fields
        assert "artbox_phash" not in result.fields
        assert result.skip_reasons["artbox_phash"] == "fetch_failed"

    @staticmethod
    def _image_with_marked_artbox(width: int = 1000, height: int = 1000) -> "Image.Image":
        """A real white-background PIL image with a checkerboard rendered across the FULL
        ARTBOX_MODERN_CROP_BOX region - mirrors TestExtractCardEvidenceSymbolRegion's own
        `_image_with_symbol_strip` checkerboard style (a flat fill is degenerate for phash's
        DCT-based hash, see that method's own comment), but covers this extractor's own box
        fully rather than reusing a different extractor's box that only partially overlaps it."""
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        left, top, right, bottom = ARTBOX_MODERN_CROP_BOX
        box = [round(left * width), round(top * height), round(right * width), round(bottom * height)]
        step = 6
        for y in range(box[1], box[3], step):
            for x in range(box[0], box[2], step):
                if (x // step + y // step) % 2 == 0:
                    draw.rectangle([x, y, x + step, y + step], fill=(10, 20, 30))
        return img

    def test_computes_a_real_phash_int_and_is_deterministic(self, db, monkeypatch):
        # Real PIL images (unlike the _StubImage-based tests above, which only exercise the crop
        # BOX math via a stubbed _compute_region_phash) - mirrors
        # TestExtractCardEvidenceSymbolRegion's own real-image style, since this checks the
        # actual hash output.
        image = self._image_with_marked_artbox(1000, 1000)
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        _stub_ocr(monkeypatch, "158/287 R MOM EN")

        first = fetch_and_compute_card_evidence_for_tests(card)
        second = fetch_and_compute_card_evidence_for_tests(card)

        assert isinstance(first.fields["artbox_phash"], int)
        # a signed 64-bit int (twos_complement's own output range) - not asserting an exact
        # value, same "don't pin the continuous/brittle" rationale symbol_region's own test gives.
        assert -(2**63) <= first.fields["artbox_phash"] < 2**63
        # determinism: hashing the exact same pixels twice must produce the exact same int.
        assert first.fields["artbox_phash"] == second.fields["artbox_phash"]

    def test_different_regions_hash_differently(self, db, monkeypatch):
        # a blank (all-white) card vs. one with a distinct rendered checkerboard inside the
        # art-box region - real evidence the hash reflects THIS region's own content, not a
        # constant.
        blank_image = Image.new("RGB", (1000, 1000), "white")
        marked_image = self._image_with_marked_artbox(1000, 1000)
        card = CardFactory(content_phash=1)

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: blank_image)
        _stub_ocr(monkeypatch, "158/287 R MOM EN")
        blank_result = fetch_and_compute_card_evidence_for_tests(card)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: marked_image)
        _stub_ocr(monkeypatch, "158/287 R MOM EN")
        marked_result = fetch_and_compute_card_evidence_for_tests(card)

        assert blank_result.fields["artbox_phash"] != marked_result.fields["artbox_phash"]

    def test_persist_writes_artbox_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"artbox_crop_px": [70, 100, 930, 620], "artbox_frame_class": "modern", "artbox_phash": -54321},
            extractor_versions={"artbox_phash": ARTBOX_PHASH_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.artbox_crop_px == [70, 100, 930, 620]
        assert evidence.artbox_frame_class == "modern"
        assert evidence.artbox_phash == -54321

    def test_persist_clears_a_pre_abstain_hash_when_reextraction_is_unclassifiable(self, db, monkeypatch):
        """issue #925: the row this simulates is exactly what a v1-tagged, `artbox_frame_class=""`
        row with a populated hash means today - a guess made by the pre-abstain two-way selector
        for a frame the classifier could not read. Re-extraction under the current selector must
        end with the stored hash and crop box gone, not merely re-stamped with the new version."""
        card = CardFactory(content_phash=1)
        ImageEvidenceFactory(
            card=card,
            content_hash=1,
            artbox_phash=-54321,
            artbox_crop_px=[70, 100, 930, 620],
            artbox_frame_class="modern",
            extractor_versions={"artbox_phash": "artbox-phash-v1"},
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch, "no signal here at all")
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        result = fetch_and_compute_card_evidence_for_tests(card)
        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.artbox_phash is None
        assert evidence.artbox_crop_px is None
        assert evidence.artbox_frame_class == ""

    def test_persist_keeps_the_existing_hash_when_reextraction_cannot_fetch(self, db, monkeypatch):
        """The opposite outcome from the test above, for the branch that must NOT clear: the
        extractor never ran at all here, so it has no basis to say the prior hash is wrong - a
        transient fetch failure must not read as evidence of anything about the stored value."""
        card = CardFactory(content_phash=1)
        stored = ImageEvidenceFactory(
            card=card,
            content_hash=1,
            artbox_phash=-54321,
            artbox_crop_px=[70, 100, 930, 620],
            artbox_frame_class="modern",
            extractor_versions={"artbox_phash": "artbox-phash-v1"},
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)
        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.pk == stored.pk
        assert evidence.artbox_phash == -54321
        assert evidence.artbox_crop_px == [70, 100, 930, 620]


class TestExtractCardEvidenceCollectorLineOcr:
    """issue #149 (OCR-group) - collector_line_ocr crops collector_line_crop_px (already
    computed by crop_coordinates above) and runs the SAME local_ocr.parse_collector_line the live
    pilot's pass-1 engine uses. Real PIL images + the REAL tesseract binary throughout (mirrors
    TestExtractCardEvidenceLayoutClass's own real-image style, since this extractor genuinely
    reads pixels) - per CLAUDE.md, tesseract is installed in CI and real OCR tests are expected
    to run, not be skipped. No candidate matching happens here - see module docstring."""

    def test_parses_set_code_and_collector_number(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["collector_line_set_code"] == "mom"
        assert result.fields["collector_line_collector_number"] == "158"
        assert result.fields["collector_line_raw_text"].strip() != ""
        assert "collector_line_ocr" not in result.skip_reasons

    def test_no_legible_text_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])  # a blank crop, no text at all
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["collector_line_set_code"] == ""
        assert result.fields["collector_line_collector_number"] == ""
        assert result.skip_reasons["collector_line_ocr"] == "no-text"

    def test_blank_tier_one_no_longer_short_circuits_by_default(self, db, monkeypatch):
        """2026-07-22, pipeline-fidelity parity replay #154's "unexplained" divergence autopsy
        (docs/features/catalog-completion-plan.md's "Recovery-arc lessons" item 1, tightened - see
        `_confidently_digit_free`'s own docstring): a blank crop's tier-1 attempts read back
        completely EMPTY, not "confidently digit-free" - `_confidently_digit_free` now requires
        non-blank text on both attempts too, so this case must escalate through every tier exactly
        like `test_no_legible_text_exhausts_every_fallback_tier_when_short_circuit_is_disabled`
        below, even with the short-circuit flag left at its default (True). Supersedes this test's
        own former "blank crop short-circuits" assertion - the replay found 155 of 373 conservative
        -abstention divergences were exactly this case (a real tier-1 read FAILURE wrongly treated
        as a confident "no collector number here" finding, silently skipping the deeper tiers that
        would have recovered the real collector line). Counted via a wrapper around
        `run_tesseract_text_and_words` rather than asserting a specific OCR result (a blank crop
        reliably reads as empty text under every config in this environment; the ATTEMPT COUNT,
        not the text, is what this test is about)."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        configs_used: list[str] = []
        original = module.run_tesseract_text_and_words

        def counting(image_arg, config):
            configs_used.append(config)
            return original(image_arg, config=config)

        monkeypatch.setattr(module, "run_tesseract_text_and_words", counting)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(configs_used) == 6  # blank tier-1 no longer qualifies - every tier tried
        assert configs_used.count(module.TESSERACT_CONFIG) == 6
        assert result.short_circuited is False

    def test_confidently_digit_free_tier_one_still_short_circuits_by_default(self, db, monkeypatch):
        """2026-07-22: the short-circuit's own perf win must still exist for the case it's
        actually meant for - tier-1 text tesseract genuinely READ (non-blank), just with no digit
        character in it (e.g. real but unrelated text, or a garbled-but-present line), as opposed
        to the blank/failed-read case the test above now excludes. Uses a monkeypatched
        `run_tesseract_text_and_words` (not real tesseract) for an exact, controlled non-blank
        digit-free tier-1 text, mirroring `test_digit_bearing_tier_one_failure_still_escalates_
        by_default` below's own style for the opposite (digit-bearing) case."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "no digits anywhere in this line", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(calls) == 2  # tier 1 only - confidently digit-free, still short-circuits
        assert calls == [module.TESSERACT_CONFIG] * 2
        assert result.short_circuited is True

    def test_no_legible_text_exhausts_every_fallback_tier_when_short_circuit_is_disabled(self, db, monkeypatch):
        """issue #259's original behavior, preserved behind the escape hatch (2026-07-21, item 1):
        a blank crop must genuinely try every tier (2 base + 4 fallback = 6 attempts, issue #677's
        collapsed ladder) before recording "no-text" when `short_circuit=False` - the
        measurement-run path a real re-profile would use to gather the plan's own "open
        verification gap" data."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        configs_used: list[str] = []
        original = module.run_tesseract_text_and_words

        def counting(image_arg, config):
            configs_used.append(config)
            return original(image_arg, config=config)

        monkeypatch.setattr(module, "run_tesseract_text_and_words", counting)

        result = fetch_and_compute_card_evidence_for_tests(card, short_circuit=False)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(configs_used) == 6
        assert configs_used.count(module.TESSERACT_CONFIG) == 6  # 2 base + 4 fallback, PSM 6
        assert result.short_circuited is False

    def test_digit_bearing_tier_one_failure_still_escalates_by_default(self, db, monkeypatch):
        """2026-07-21, item 1: the short-circuit's own condition is narrower than "tier 1 failed
        to parse" - a tier-1 read that contains a digit character but still fails to parse a
        collector number (`_contains_digit` is coarser than `_COLLECTOR_NUMBER_RE`, see that
        helper's own docstring) must still escalate through every tier exactly as before. Uses a
        monkeypatched `run_tesseract_text_and_words` (not real tesseract) to force an exact,
        controlled tier-1 text, since reliably provoking this specific OCR failure mode from a
        real rendered crop would be fragile."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        # A digit run with a word character directly abutting BOTH ends has no position where
        # `_COLLECTOR_NUMBER_RE`'s trailing `\b` can land next to a 1-4-digit token (verified
        # directly: `_COLLECTOR_NUMBER_RE.search("abc123456789xyz")` is `None`) - digit-bearing
        # (so `_contains_digit` is True), never parses. Real word boxes are irrelevant to this
        # test, so a fixed dummy is returned.
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "abc123456789xyz", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(calls) == 6  # every tier tried - digit-bearing tier-1 text never short-circuits
        assert result.short_circuited is False

    def test_short_circuit_only_fires_once_both_tier_one_attempts_are_digit_free(self, db, monkeypatch):
        """The short-circuit's own condition requires BOTH tier-1 attempts to be digit-free, not
        just the first - a card whose first tier-1 attempt happens to be digit-free but whose
        SECOND carries a digit (even an unparseable one - the same long-digit-run shape the
        previous test uses) must still escalate (matches `_collector_line_ocr_attempts`' own
        two-polarity tier-1 design - either attempt could be the one that reads real text)."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        # attempt 1: digit-free. attempt 2: digit-bearing but unparseable (same shape as
        # test_digit_bearing_tier_one_failure_still_escalates_by_default above). Attempts 3-6
        # (tier 2): blank, never parses either - the point is that escalation happens AT ALL,
        # not what tier 2 itself finds.
        texts = iter(["no digits here", "abc123456789xyz", "", "", "", ""])
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return next(texts), []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(calls) == 6  # escalated past tier 1 despite attempt 1 alone being digit-free
        assert result.short_circuited is False

    def test_happy_path_never_computes_fallback_preprocessing(self, db, monkeypatch):
        """issue #259: a card whose collector line parses cleanly on the very first (base, PSM
        6) attempt must never even CALL `preprocess_fallback_variants`, let alone OCR any of its
        output - the lazy attempt generator must not advance past tier 1 once the consuming
        loop's own early-break fires. Keeps the happy path's cost unchanged, per this issue's own
        "keep the happy path unchanged and fast" directive."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        def _boom(cropped):
            raise AssertionError("preprocess_fallback_variants must never be called on the happy path")

        monkeypatch.setattr(module, "preprocess_fallback_variants", _boom)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "collector_line_raw_text" not in result.fields
        assert "collector_line_set_code" not in result.fields
        assert "collector_line_collector_number" not in result.fields
        assert result.skip_reasons["collector_line_ocr"] == "fetch_failed"

    def test_persist_writes_collector_line_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={
                "collector_line_raw_text": "158/287 R MOM EN",
                "collector_line_set_code": "mom",
                "collector_line_collector_number": "158",
            },
            extractor_versions={"collector_line_ocr": COLLECTOR_LINE_OCR_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.collector_line_raw_text == "158/287 R MOM EN"
        assert evidence.collector_line_set_code == "mom"
        assert evidence.collector_line_collector_number == "158"


class TestExtractCardEvidenceCollectorLineOcrSetCodeLexiconGate:
    """2026-07-23, issue #370's own recorded follow-up: the escalation loop's acceptance
    criterion changes from "any parse" to "lexicon-valid parse, else keep escalating, else keep
    the best invalid candidate" (see `compute_card_evidence`'s own `known_set_codes` docstring
    paragraph for the full mechanism/autopsy). Uses a monkeypatched `run_tesseract_text_and_words`
    (not real tesseract) throughout for exact, controlled per-attempt text, mirroring
    `TestExtractCardEvidenceCollectorLineOcr`'s own style for controlled-text escalation tests
    above (`test_digit_bearing_tier_one_failure_still_escalates_by_default` etc.)."""

    def test_lexicon_invalid_parse_keeps_escalating_until_a_valid_one_is_found(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        # attempts 1-3 (tier 1's two + tier 2's first): a genuine collector-number-shaped read
        # whose set code ("fak") isn't real. Attempt 4 (still tier 2): a lexicon-valid parse -
        # escalation must stop there, never reaching attempts 5-8.
        texts = iter(["158/287 R FAK EN", "158/287 R FAK EN", "158/287 R FAK EN", "158/287 R MOM EN"])
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return next(texts), []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card, known_set_codes=frozenset({"mom"}))

        assert result.fields["collector_line_set_code"] == "mom"
        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons
        assert len(calls) == 4  # stopped the instant a lexicon-valid parse was found

    def test_all_invalid_parses_keep_the_best_invalid_candidate(self, db, monkeypatch):
        """No attempt across every tier ever produces a lexicon-valid parse - the stored outcome
        keeps the FIRST collector_number-bearing parse (by tier order), matching exactly what
        pre-2026-07-23 code already stored for this bucket (old code never distinguished valid
        from invalid) - byte-identical stored fields, only the path there (genuine escalation
        through every tier) changed."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "158/287 R FAK EN", []  # always the same out-of-lexicon parse

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card, known_set_codes=frozenset({"mom"}), short_circuit=False
        )

        assert result.fields["collector_line_set_code"] == "fak"
        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons  # a collector_number WAS found
        assert len(calls) == 6  # every tier tried - no attempt ever validated

    def test_pre_gate_stored_outcome_is_reproduced_exactly_when_gate_disabled(self, db, monkeypatch):
        """Same all-invalid scenario as above, but with known_set_codes=None (the gate disabled,
        e.g. an older/direct caller) - must accept the FIRST parse immediately (no escalation at
        all), reproducing the exact pre-2026-07-23 "any parse" behavior and stored fields."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "158/287 R FAK EN", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card)  # known_set_codes not passed - defaults to None

        assert result.fields["collector_line_set_code"] == "fak"
        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons
        assert len(calls) == 1  # accepted immediately - gate disabled, no escalation triggered

    def test_lexicon_valid_first_parse_short_circuits_exactly_as_before(self, db, monkeypatch):
        """A card whose first parse is already lexicon-valid (the overwhelming majority) sees
        IDENTICAL behavior and compute whether or not known_set_codes is threaded through -
        companion to test_happy_path_never_computes_fallback_preprocessing above, asserting the
        exact attempt count with the gate actively enabled this time."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        def _boom(cropped):
            raise AssertionError("preprocess_fallback_variants must never be called on the happy path")

        monkeypatch.setattr(module, "preprocess_fallback_variants", _boom)

        result = fetch_and_compute_card_evidence_for_tests(card, known_set_codes=frozenset({"mom"}))

        assert result.fields["collector_line_set_code"] == "mom"
        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons

    def test_collector_number_only_parse_unaffected_by_gate(self, db, monkeypatch):
        """The pre-M15 collector-number-only case (no set-code-shaped token found at all) is
        deliberately UNAFFECTED by the lexicon gate, same as `calculate_join_key_verdict`'s own
        carve-out - accepted immediately even though known_set_codes doesn't contain anything."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "158", []  # a bare collector number, no set-code-shaped token at all

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card, known_set_codes=frozenset())  # empty lexicon

        assert result.fields["collector_line_set_code"] == ""
        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons
        assert len(calls) == 1  # accepted immediately - set_code is None, gate doesn't apply

    def test_short_circuit_interplay_unaffected_by_lexicon_gate(self, db, monkeypatch):
        """The digit-free short-circuit (#340) governs whether escalation STARTS; the lexicon
        gate governs acceptance once it's already running - the two are independent. A confidently
        digit-free tier-1 read still short-circuits exactly as before, regardless of
        known_set_codes being threaded through (there's no collector_number at all here for the
        lexicon gate to ever evaluate)."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "no digits anywhere in this line", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card, known_set_codes=frozenset({"mom"}))

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(calls) == 2  # tier 1 only - short-circuit fires exactly as without the gate
        assert result.short_circuited is True


class TestExtractCardEvidenceCollectorLineArtistGate:
    """2026-07-29, the COLLECTOR-LINE ARTIST GATE (see `compute_card_evidence`'s own
    `artist_lexicon` docstring paragraph): the escalation loop's acceptance criterion gains a
    second half. A parse can be lexicon-valid - correct set code - and still be a MISREAD NUMBER,
    which `_parse_is_lexicon_valid` structurally cannot see; the artist printed in the SAME
    collector line is what catches it.

    THE POINT OF THESE TESTS IS THAT ESCALATION CONTINUES, not merely that a suspect read gets
    flagged. `test_artist_contradiction_does_not_terminate_escalation` was verified to FAIL against
    the pre-2026-07-29 loop (acceptance branch reverted, test re-run: the loop stops at attempt 1,
    `len(calls) == 1` instead of 3, and the stored collector number stays the misread `158`) - it
    is not a vacuously-green assertion over behaviour that already held.
    `test_gate_off_accepts_the_contradicted_parse_immediately` pins that old behaviour in place as
    the permanent control.

    Same controlled-text style as `TestExtractCardEvidenceCollectorLineOcrSetCodeLexiconGate`
    above: `run_tesseract_text_and_words` is monkeypatched for exact per-attempt text, and the
    printing-artist resolver is a plain dict-backed callable rather than the real
    `PrintingArtistLookup` (whose ORM query is covered by the Stage D tests) - this class is about
    the LOOP, not about how an artist name is fetched.
    """

    # The two printings the misread/correct number pair below resolve to.
    PRINTING_ARTISTS = {("mom", "158"): "Alessandra Pisano", ("mom", "159"): "Lindsey Look"}
    LEXICON = build_artist_lexicon(["Alessandra Pisano", "Lindsey Look", "Ron Spears"])

    @classmethod
    def _lookup(cls, set_code, collector_number):
        return cls.PRINTING_ARTISTS.get((set_code, collector_number))

    def test_artist_contradiction_does_not_terminate_escalation(self, db, monkeypatch):
        """The defect this whole feature exists for. Attempts 1-2 read the collector number as
        `158` - lexicon-valid ('mom' is real), so the pre-2026-07-29 loop accepted it and stopped.
        But `158` resolves to a printing by Alessandra Pisano while that same line plainly reads
        `LINDSEY L`: the parse contradicts its own source string. Escalation must CONTINUE, and
        attempt 3's correct `159` (whose printing IS by Lindsey Look) is what gets stored."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        texts = iter(
            [
                "158/281R\nMOM ¢ EN LINDSEY L",  # misread number, right set code, wrong artist
                "158/281R\nMOM ¢ EN LINDSEY L",
                "159/281R\nMOM ¢ EN LINDSEY L",  # the correct read - artist now agrees
            ]
        )
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return next(texts), []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
        )

        assert result.fields["collector_line_collector_number"] == "159"
        assert result.fields["collector_line_set_code"] == "mom"
        assert len(calls) == 3  # escalated past the contradicted parse, stopped at the good one
        assert "collector_line_ocr" not in result.skip_reasons

    def test_gate_off_accepts_the_contradicted_parse_immediately(self, db, monkeypatch):
        """The same three texts with the gate NOT wired - the pre-2026-07-29 behaviour, kept as
        the explicit control for the test above: attempt 1 is accepted, escalation never happens,
        and the misread `158` is what gets stored."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        texts = iter(
            [
                "158/281R\nMOM ¢ EN LINDSEY L",
                "158/281R\nMOM ¢ EN LINDSEY L",
                "159/281R\nMOM ¢ EN LINDSEY L",
            ]
        )
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return next(texts), []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(card, known_set_codes=frozenset({"mom"}))

        assert result.fields["collector_line_collector_number"] == "158"
        assert len(calls) == 1

    def test_all_attempts_contradicted_keeps_the_first_as_a_deterministic_artifact(self, db, monkeypatch):
        """Fallback precedence step 1: no attempt is ever both lexicon-valid and artist-consistent,
        so the FIRST lexicon-valid-but-contradicted parse becomes the stored outcome - a card that
        never parses cleanly still stores something deterministic, and every tier was genuinely
        tried on the way there."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "158/281R\nMOM ¢ EN LINDSEY L", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
            short_circuit=False,
        )

        assert result.fields["collector_line_collector_number"] == "158"
        assert result.fields["collector_line_set_code"] == "mom"
        assert "collector_line_ocr" not in result.skip_reasons  # a collector_number WAS found
        assert len(calls) == 6  # every tier tried before falling back

    def test_contradicted_parse_is_preferred_over_a_lexicon_invalid_one(self, db, monkeypatch):
        """Fallback precedence: a lexicon-valid-but-contradicted parse beats a lexicon-INVALID
        one even though the invalid one came first by tier order - its set code is at least real,
        making it the strictly better of two imperfect artifacts."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        texts = iter(["777/281R\nFAK ¢ EN LINDSEY L"] * 2 + ["158/281R\nMOM ¢ EN LINDSEY L"] * 6)
        monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda image_arg, config: (next(texts), []))

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
            short_circuit=False,
        )

        assert result.fields["collector_line_set_code"] == "mom"  # not the earlier 'fak'
        assert result.fields["collector_line_collector_number"] == "158"

    def test_unresolvable_printing_is_never_a_contradiction(self, db, monkeypatch):
        """Absent data is not evidence - a (set, number) pair the lookup can't resolve must
        terminate escalation exactly as before, not be treated as a disagreement."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "999/281R\nMOM ¢ EN LINDSEY L", []  # 'mom' 999 is in no lookup table

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
        )

        assert result.fields["collector_line_collector_number"] == "999"
        assert len(calls) == 1

    def test_unreadable_artist_is_never_a_contradiction(self, db, monkeypatch):
        """A collector line with no recoverable artist credit at all leaves the gate with nothing
        to say - accept immediately, exactly as before."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return "158/281R\nMOM ¢ EN", []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
        )

        assert result.fields["collector_line_collector_number"] == "158"
        assert len(calls) == 1

    def test_recovered_artist_populates_the_blank_artist_ocr_name(self, db, monkeypatch):
        """The storage half: `artist_ocr_name` is blank on 93.7% of production evidence rows
        because the "Illus." anchor never fires on modern frames - yet the collector line already
        carries the name. `illus_anchor_fired` and the `artist_ocr` skip reason are deliberately
        untouched: they describe the artist_ocr extractor's own outcome, not this recovery."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "")
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("159/281R\nMOM ¢ EN LINDSEY L", [])
        )

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
        )

        assert result.fields["artist_ocr_name"] == "Lindsey Look"  # canonical, never the OCR span
        assert result.fields["illus_anchor_fired"] is False
        assert result.skip_reasons["artist_ocr"] == "no-text"

    def test_illus_anchor_reading_is_never_overwritten(self, db, monkeypatch):
        """The anchor's own reading always wins - this recovery only ever fills a BLANK value."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module,
            "run_tesseract_text_and_words",
            lambda image_arg, config: ("159/281R\nMOM ¢ EN LINDSEY L\nIllus. Ron Spears", []),
        )

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
        )

        assert result.fields["artist_ocr_name"] == "Ron Spears"
        assert result.fields["illus_anchor_fired"] is True

    def test_ambiguous_reading_stores_nothing_but_still_gates_escalation(self, db, monkeypatch):
        """A reading compatible with more than one canonical artist is deliberately not storable
        (fuzzy matching yes, fuzzy storage no) - but it is still perfectly able to rule an artist
        OUT, so it must still be able to stop a contradicted parse from ending escalation."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "")

        ambiguous_lexicon = build_artist_lexicon(["Alessandra Pisano", "Lindsey Look", "Lindsey Lopez"])
        texts = iter(["158/281R\nMOM ¢ EN LINDSEY L", "159/281R\nMOM ¢ EN LINDSEY L"])
        calls: list[str] = []

        def _stub(image_arg, config):
            calls.append(config)
            return next(texts), []

        monkeypatch.setattr(module, "run_tesseract_text_and_words", _stub)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=ambiguous_lexicon,
            printing_artist_lookup=self._lookup,
        )

        assert len(calls) == 2  # 'Alessandra Pisano' is compatible with neither Lindsey
        assert result.fields["collector_line_collector_number"] == "159"
        assert result.fields["artist_ocr_name"] == ""  # ambiguous - nothing storable


class TestExtractCardEvidenceWidenedArtistRead:
    """2026-07-29, WIDENING THE READ + CARD-NAME NARROWING (see `compute_card_evidence`'s own
    `artist_lexicon` docstring paragraph, and `collector_line_artist`'s two docstring sections).

    `legal_line_crop_px` covers the IDENTICAL y band as `collector_line_crop_px`
    (`LEGAL_LINE_CROP_BOX` (0.0, 0.90, 1.0, 0.965) vs `DEFAULT_CROP_BOX` (0.06, 0.90, 0.35,
    0.965)) at the FULL card width, so it has been storing the untruncated artist credit since
    issue #151 - which is why the "widen the collector crop" fix needs no geometry change, no new
    tesseract call, and no extractor version bump. These tests pin that the artist recovery
    actually consumes it, and that the compute hoist (`_extract_legal_line`) left the legal_line
    extractor's own stored output alone.

    `run_tesseract_text_and_words` supplies the collector-line attempts, `run_tesseract` the
    legal-line ones - the same monkeypatch split the classes above already use."""

    LEXICON = build_artist_lexicon(["Ron Spears", "Ron Spencer", "Lindsey Look"])

    @staticmethod
    def _lookup(set_code, collector_number):
        return None  # no printing resolution - these tests are about the READING, not the gate

    def test_the_untruncated_legal_line_read_is_what_gets_stored(self, db, monkeypatch):
        """`RON SPEA` alone is compatible with two real artists and is therefore deliberately
        unstorable. The full-width read of the SAME print row says `RON SPEARS`, which is
        decisive - and it was already in hand, extracted by a different extractor on this same
        pass."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("059/274R\nDMR ¢ EN RON SPEA", [])
        )
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "059/274R\nDMR ¢ EN RON SPEARS")

        result = fetch_and_compute_card_evidence_for_tests(
            card, artist_lexicon=self.LEXICON, printing_artist_lookup=self._lookup
        )

        assert result.fields["artist_ocr_name"] == "Ron Spears"
        assert result.fields["illus_anchor_fired"] is False  # the anchor genuinely never fired

    def test_the_same_row_stores_nothing_when_the_legal_line_is_blank(self, db, monkeypatch):
        """The control: byte-identical inputs with an empty legal-line read, reproducing the
        pre-2026-07-29 collector-line-only behaviour - `RON SPEA` stays ambiguous and unstorable.
        Proves the storage above comes from the widened read, not from the fixture."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("059/274R\nDMR ¢ EN RON SPEA", [])
        )
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "")

        result = fetch_and_compute_card_evidence_for_tests(
            card, artist_lexicon=self.LEXICON, printing_artist_lookup=self._lookup
        )

        assert result.fields["artist_ocr_name"] == ""

    def test_card_name_narrowing_makes_an_otherwise_ambiguous_read_storable(self, db, monkeypatch):
        """The second lever, on the same ambiguous `RON SPEA` read and with NO legal line at all:
        scoped to the artists who illustrated a printing of this card's own name, the reading is
        decisive. `name_artist_lookup` is resolved by `fetch_and_compute_card_evidence_for_tests` against `card.name`
        (a plain callable here - its real `CandidateNameIndex` backing is covered in
        `test_collector_line_artist.py`)."""
        card = CardFactory(name="Mystic Remora", content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("059/274R\nDMR ¢ EN RON SPEA", [])
        )
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "")

        seen: list[str] = []

        def _name_artists(name):
            seen.append(name)
            return ("Ron Spears",)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
            name_artist_lookup=_name_artists,
        )

        assert seen == ["Mystic Remora"]  # resolved against the card's OWN name, once
        assert result.fields["artist_ocr_name"] == "Ron Spears"

    def test_an_unresolvable_card_name_falls_back_rather_than_losing_the_recovery(self, db, monkeypatch):
        """A decorated or genuinely custom name resolves to no printing at all. That must cost
        nothing: the reading falls back to the full lexicon and behaves exactly as if no lookup
        had been threaded."""
        card = CardFactory(name="TreacheryGame_04", content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("204/361R\nCLB ¢ EN LINDSEY L", [])
        )
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "")

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
            name_artist_lookup=lambda name: (),
        )

        assert result.fields["artist_ocr_name"] == "Lindsey Look"

    def test_hoisting_the_legal_line_compute_left_its_stored_output_untouched(self, db, monkeypatch):
        """`_extract_legal_line` now runs BEFORE the OCR group so its text is available to the
        artist recovery, but its results are still written at this extractor's own original
        position. Every legal_line field, its skip reason, and its extractor version must be
        exactly what they were - this is precisely why no version needed bumping."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda image_arg, config: ("", []))
        monkeypatch.setattr(
            module, "run_tesseract", lambda variant, **kwargs: "\u00a9 2022 Wizards of the Coast NOT FOR SALE"
        )

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["legal_line_raw_text"] == "\u00a9 2022 Wizards of the Coast NOT FOR SALE"
        assert result.fields["legal_line_copyright_year"] == "2022"
        assert result.fields["legal_line_proxy_marker_detected"] is True
        assert result.fields["legal_line_crop_px"] == module._crop_box_to_pixels(
            module.LEGAL_LINE_CROP_BOX, result.fields["bleed_class"], result.fields["width"], result.fields["height"]
        )
        assert "legal_line" not in result.skip_reasons
        assert result.extractor_versions["legal_line"] == module.LEGAL_LINE_EXTRACTOR_VERSION

    def test_a_failed_fetch_still_reports_the_legal_line_as_skipped(self, db, monkeypatch):
        """The hoist must not turn a fetch failure into a crash or a silently-absent skip reason -
        `None` in, `fetch_failed` out, exactly as before."""
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.skip_reasons["legal_line"] == "fetch_failed"
        assert "legal_line_raw_text" not in result.fields


class TestExtractCardEvidenceArtistCropFallback:
    """2026-08-04, the ARTIST-CROP FALLBACK (see `compute_card_evidence`'s own
    `modern_artist_lexicon` docstring paragraph). Real production rows (evidence ids 221241,
    221268, 221274) carry NO collector line and NO legal line at all - an old-border proxy's only
    on-card credit is a centred "Illus. <name>" line, OCR'd into `artist_ocr_raw_text` but missed
    by the anchor regex to ordinary noise (`Soot Itus.` never matches `_ILLUS_RE`). Neither the
    anchor nor `recover_artist_from_card_text` (which reads only the two bottom-print-row fields)
    can ever reach that population; `modern_artist_credit.recognize_artist_credit`, re-reading
    `artist_ocr_raw_text` itself, can.

    `run_tesseract` backs both the legal-line crop and the artist-crop fallback pass; the two
    crops have very different pixel heights (`LEGAL_LINE_CROP_BOX` is a thin strip,
    `ARTIST_CROP_BOX` a much taller band), so the stub below distinguishes them by `variant.size`
    rather than by call order.
    """

    LEXICON = build_artist_lexicon(["Aaron Miller"])
    MODERN_LEXICON = build_lexicon_index(["Aaron Miller"])

    @staticmethod
    def _lookup(set_code, collector_number):
        return None  # no printing resolution - these tests are about the READING, not the gate

    @staticmethod
    def _run_tesseract_by_crop_height(variant, **kwargs):
        if variant.size[1] < 400:
            return ""  # the legal-line crop: blank, matching "no bottom print row at all"
        return "Soot Itus. Aaron Miller ~ *"  # the artist crop: the real card-30-shaped OCR text

    def test_recovers_a_name_the_anchor_and_print_row_recovery_both_missed(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda image_arg, config: ("", []))
        monkeypatch.setattr(module, "run_tesseract", self._run_tesseract_by_crop_height)

        result = fetch_and_compute_card_evidence_for_tests(
            card,
            artist_lexicon=self.LEXICON,
            printing_artist_lookup=self._lookup,
            modern_artist_lexicon=self.MODERN_LEXICON,
        )

        assert result.fields["artist_ocr_name"] == "Aaron Miller"
        assert result.fields["illus_anchor_fired"] is False  # the anchor genuinely never fired
        assert result.fields["collector_line_raw_text"] == ""
        assert result.fields["legal_line_raw_text"] == ""

    def test_without_the_lexicon_the_gap_stays_open(self, db, monkeypatch):
        """Control: byte-identical inputs with `modern_artist_lexicon` left at its `None` default
        - every pre-2026-08-04 caller's behaviour, unchanged."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda image_arg, config: ("", []))
        monkeypatch.setattr(module, "run_tesseract", self._run_tesseract_by_crop_height)

        result = fetch_and_compute_card_evidence_for_tests(
            card, artist_lexicon=self.LEXICON, printing_artist_lookup=self._lookup
        )

        assert result.fields["artist_ocr_name"] == ""

    def test_the_illus_anchor_still_wins_when_it_fires(self, db, monkeypatch):
        """The anchor's own reading always wins - this fallback only ever fills a BLANK value,
        same invariant `TestExtractCardEvidenceCollectorLineArtistGate` already pins for the
        print-row recovery."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda image_arg, config: ("", []))
        monkeypatch.setattr(module, "run_tesseract", lambda variant, **kwargs: "Illus. Ron Spears")

        lexicon = build_artist_lexicon(["Ron Spears", "Aaron Miller"])
        modern_lexicon = build_lexicon_index(["Ron Spears", "Aaron Miller"])
        result = fetch_and_compute_card_evidence_for_tests(
            card, artist_lexicon=lexicon, printing_artist_lookup=self._lookup, modern_artist_lexicon=modern_lexicon
        )

        assert result.fields["artist_ocr_name"] == "Ron Spears"
        assert result.fields["illus_anchor_fired"] is True

    def test_print_row_recovery_still_wins_over_the_artist_crop_fallback(self, db, monkeypatch):
        """Precedence: when the collector/legal-line recovery finds something storable, it is
        never second-guessed by the artist-crop fallback, even though the artist crop's own OCR
        text names a DIFFERENT, equally real, lexicon artist. The legal-line crop is left BLANK
        here (unlike `test_recovers_a_name_...` above) so the print-row recovery's own answer
        comes from the collector line alone, not the wider legal-line read winning on a tie-break."""
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(
            module, "run_tesseract_text_and_words", lambda image_arg, config: ("059/274R\nDMR ¢ EN RON SPEARS", [])
        )

        def _run_tesseract(variant, **kwargs):
            return "" if variant.size[1] < 400 else "Aaron Miller"

        monkeypatch.setattr(module, "run_tesseract", _run_tesseract)

        lexicon = build_artist_lexicon(["Ron Spears", "Aaron Miller"])
        modern_lexicon = build_lexicon_index(["Ron Spears", "Aaron Miller"])
        result = fetch_and_compute_card_evidence_for_tests(
            card, artist_lexicon=lexicon, printing_artist_lookup=self._lookup, modern_artist_lexicon=modern_lexicon
        )

        assert result.fields["artist_ocr_name"] == "Ron Spears"  # the print row, not the art crop


class TestCollectorLineOcrAttempts:
    """Direct tests of `_collector_line_ocr_attempts` (issue #259, collapsed from 3 tiers to 2 by
    issue #677) - the lazy, ordered (image, tesseract_config, tier) generator `collector_line_ocr`'s
    own loop consumes. The `tier` element (2026-07-21, "Recovery-arc lessons" item 1) lets the
    caller detect "both tier-1 attempts exhausted" for the pre-classification short-circuit. No
    tesseract call happens in these tests (only `preprocess_variants`' PIL-only grayscale/threshold
    work, plus - when the fallback tier is actually reached - `preprocess_fallback_variants`' own
    PIL-only work) - these tests are about the ORDERING/laziness contract, not OCR output, so
    they're fast and don't need a real card image."""

    def test_yields_six_attempts_in_the_documented_tier_order(self):
        crop = Image.new("RGB", (60, 24), "black")

        attempts = list(module._collector_line_ocr_attempts(crop))

        assert len(attempts) == 6  # issue #677 collapsed the old 3-tier/8-attempt ladder to 2/6
        configs = [config for _variant, config, _tier in attempts]
        assert configs == [module.TESSERACT_CONFIG] * 6
        tiers = [tier for _variant, _config, tier in attempts]
        assert tiers == [1, 1, 2, 2, 2, 2]

    def test_never_calls_fallback_variants_if_consumer_stops_after_tier_one(self, monkeypatch):
        crop = Image.new("RGB", (60, 24), "black")

        def _boom(cropped):
            raise AssertionError("preprocess_fallback_variants must not be called")

        monkeypatch.setattr(module, "preprocess_fallback_variants", _boom)

        attempts = module._collector_line_ocr_attempts(crop)
        first_two = [next(attempts) for _ in range(2)]  # tier 1 only - the generator's own laziness

        assert len(first_two) == 2


class TestExtractCardEvidenceArtistOcr:
    """issue #149 (OCR-group) - local_fallback.extract_artist_name's tolerant "Illus. <name>"
    parse. Reuses collector_line_ocr's own raw texts first (see module docstring's rationale,
    mirroring local_fallback.detect_illus_anchor's identical reuse-before-recompute convention)
    before falling back to a fresh crop+OCR pass over artist_crop_px. Real tesseract throughout,
    same rationale as TestExtractCardEvidenceCollectorLineOcr above."""

    def test_finds_artist_within_collector_line_crop_without_a_second_ocr_pass(self, db, monkeypatch):
        # an old-border card's "Illus. <artist>" credit frequently lands INSIDE the same crop
        # region a modern card's collector line occupies - place the text there and assert the
        # fallback crop/OCR pass over artist_crop_px never runs (preprocess_variants call count).
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "Illus. Jane Doe")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        calls: list["Image.Image"] = []
        original_preprocess = module.preprocess_variants

        def counting_preprocess(cropped):
            calls.append(cropped)
            return original_preprocess(cropped)

        monkeypatch.setattr(module, "preprocess_variants", counting_preprocess)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["artist_ocr_name"] == "Jane Doe"
        assert result.fields["illus_anchor_fired"] is True
        assert "artist_ocr" not in result.skip_reasons
        # 2, not 1: the collector-line crop (reused by artist_ocr, no second call) plus
        # legal_line's own independent crop+OCR pass (issue #151 - deliberately NOT a
        # reuse-before-recompute like artist_ocr's, see image_evidence.py's module docstring).
        assert len(calls) == 2

    def test_falls_back_to_artist_crop_when_not_in_collector_text(self, db, monkeypatch):
        # placed just above the collector-line crop's own top boundary (0.90) but still within
        # ARTIST_CROP_BOX's wider band (0.82-1.0) - collector_line_ocr's own crop never sees it.
        card = CardFactory(content_phash=1)
        image = _build_card_image([((0.0, 0.83, 1.0, 0.88), "Illus. John Smith")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["artist_ocr_name"] == "John Smith"
        assert result.fields["illus_anchor_fired"] is True
        assert "artist_ocr" not in result.skip_reasons

    def test_no_artist_credit_anywhere_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["artist_ocr_name"] == ""
        assert result.fields["illus_anchor_fired"] is False
        assert result.skip_reasons["artist_ocr"] == "no-text"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "artist_ocr_raw_text" not in result.fields
        assert "artist_ocr_name" not in result.fields
        assert "illus_anchor_fired" not in result.fields
        assert result.skip_reasons["artist_ocr"] == "fetch_failed"

    def test_persist_writes_artist_ocr_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={
                "artist_ocr_raw_text": "Illus. Jane Doe",
                "artist_ocr_name": "Jane Doe",
                "illus_anchor_fired": True,
            },
            extractor_versions={"artist_ocr": ARTIST_OCR_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.artist_ocr_name == "Jane Doe"
        assert evidence.illus_anchor_fired is True


class TestExtractCardEvidenceCollectorLineTsv:
    """issue #149 (OCR-group) - word-level bounding boxes (local_ocr.run_tesseract_tsv, new in
    this PR) for the SAME crop/variant collector_line_ocr's own raw text came from. Real
    tesseract throughout, same rationale as the sibling classes above."""

    def test_word_boxes_present_for_legible_text(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        word_boxes = result.fields["collector_line_word_boxes"]
        assert isinstance(word_boxes, list)
        assert len(word_boxes) > 0
        for word in word_boxes:
            assert set(word) == {"text", "left", "top", "width", "height", "conf"}
        assert "collector_line_tsv" not in result.skip_reasons

    def test_empty_word_list_for_a_blank_crop(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["collector_line_word_boxes"] == []
        # collector_line_tsv "ran to completion" regardless - no skip for an honestly-empty read.
        assert "collector_line_tsv" not in result.skip_reasons

    def test_fetch_failure_withholds_field_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "collector_line_word_boxes" not in result.fields
        assert result.skip_reasons["collector_line_tsv"] == "fetch_failed"

    def test_persist_writes_word_boxes(self, db):
        card = CardFactory(content_phash=999)
        word_boxes = [{"text": "158", "left": 1, "top": 2, "width": 3, "height": 4, "conf": 90.0}]
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"collector_line_word_boxes": word_boxes},
            extractor_versions={"collector_line_tsv": COLLECTOR_LINE_TSV_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.collector_line_word_boxes == word_boxes


class TestExtractCardEvidenceLegalLine:
    """public issue #151, "Legal-line extractor + moderator flag + volume report (task #159)" -
    this PR builds the extractor + moderator-flag signal only (task #159's volume report stays
    out of scope). legal_line crops its OWN dedicated region (LEGAL_LINE_CROP_BOX - NOT a reuse
    of collector_line_crop_px, see image_evidence.py's module docstring) and runs
    local_ocr.parse_legal_line against it. Real PIL images + the REAL tesseract binary throughout,
    same rationale as the other OCR-group test classes above. No candidate matching happens here -
    see module docstring."""

    def test_parses_copyright_year(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(LEGAL_LINE_CROP_BOX, "TM and (c) 2019 Wizards of the Coast")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["legal_line_copyright_year"] == "2019"
        assert result.fields["legal_line_proxy_marker_detected"] is False
        assert result.fields["legal_line_raw_text"].strip() != ""
        assert "legal_line" not in result.skip_reasons

    def test_detects_not_for_sale_marker(self, db, monkeypatch):
        # the real motivating case (task #151/#159): a proxy watermark reading as
        # plausible-looking legal-line text to a tolerant parser.
        card = CardFactory(content_phash=1)
        image = _build_card_image([(LEGAL_LINE_CROP_BOX, "MTG EN NOT FOR SALE (c) 2022")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["legal_line_proxy_marker_detected"] is True
        assert result.fields["legal_line_copyright_year"] == "2022"
        assert "legal_line" not in result.skip_reasons

    def test_no_legible_text_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(LEGAL_LINE_CROP_BOX, "")])  # a blank crop, no text at all
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["legal_line_copyright_year"] == ""
        assert result.fields["legal_line_proxy_marker_detected"] is False
        assert result.skip_reasons["legal_line"] == "no-text"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "legal_line_crop_px" not in result.fields
        assert "legal_line_raw_text" not in result.fields
        assert "legal_line_copyright_year" not in result.fields
        # null (not False) only on fetch failure - matches illus_anchor_fired's own convention.
        assert "legal_line_proxy_marker_detected" not in result.fields
        assert result.skip_reasons["legal_line"] == "fetch_failed"

    def test_persist_writes_legal_line_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={
                "legal_line_crop_px": [0, 832, 680, 893],
                "legal_line_raw_text": "NOT FOR SALE (c) 2022",
                "legal_line_copyright_year": "2022",
                "legal_line_proxy_marker_detected": True,
            },
            extractor_versions={"legal_line": LEGAL_LINE_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.legal_line_crop_px == [0, 832, 680, 893]
        assert evidence.legal_line_copyright_year == "2022"
        assert evidence.legal_line_proxy_marker_detected is True


class TestExtractCardEvidenceQualitySignals:
    """public issue #150's re-spec, "Stage C visual-signal extractors" - the LAST Stage C
    manifest extractor group (the phash half of the original issue is DROPPED, see
    image_evidence.py's own module docstring). is_image_truncated/compute_blur_variance/
    compute_entropy are called directly on the fetched image via
    cardpicker.local_image_quality - real PIL images throughout (mirrors
    TestExtractCardEvidenceLayoutClass/SymbolRegion's own style), including a genuinely
    truncated real JPEG for the integrity-check path."""

    @staticmethod
    def _real_card_image(width: int = 800, height: int = 1120) -> "Image.Image":
        img = Image.new("RGB", (width, height), (200, 200, 200))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, width - 40, height // 2], fill=(30, 90, 160))
        draw.ellipse([80, height // 2 + 20, width - 80, height - 80], fill=(220, 60, 40))
        return img

    def test_clean_image_records_blur_and_entropy_not_truncated(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = self._real_card_image()
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["image_is_truncated"] is False
        assert isinstance(result.fields["blur_variance"], float)
        assert isinstance(result.fields["image_entropy"], float)
        assert result.fields["image_entropy"] > 0  # a real image with shapes has real entropy
        assert "quality_signals" not in result.skip_reasons

    def test_truncated_image_records_flag_and_withholds_blur_entropy(self, db, monkeypatch):
        # is_image_truncated's own REAL behavior against a genuinely truncated JPEG is proven in
        # test_local_image_quality.py, in isolation - going through the full fetch_and_compute_card_evidence_for_tests
        # pipeline with a real truncated file here would also trip up EARLIER real-pixel-reading
        # extractors (layout_class/collector_line_ocr/legal_line, all upstream of quality_signals
        # in extraction order), which is a pre-existing, out-of-scope gap in those extractors, not
        # something this PR's own tests should paper over by picking a truncation point that
        # happens to dodge it. This test instead proves fetch_and_compute_card_evidence_for_tests's own WIRING - that a
        # True `is_image_truncated` result is recorded and blur/entropy are correctly withheld -
        # the same "stub the function being tested elsewhere, prove the wiring here" split
        # TestExtractCardEvidenceSymbolRegion's own degenerate-box test already uses.
        card = CardFactory(content_phash=1)
        image = self._real_card_image()
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "is_image_truncated", lambda image: True)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert result.fields["image_is_truncated"] is True
        assert "blur_variance" not in result.fields
        assert "image_entropy" not in result.fields
        # shares fetch_health's own "fetch_failed" skip reason - see image_evidence.py's module
        # docstring for why this isn't a new, separately-invented skip-reason string.
        assert result.skip_reasons["quality_signals"] == "fetch_failed"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = fetch_and_compute_card_evidence_for_tests(card)

        assert "image_is_truncated" not in result.fields
        assert "blur_variance" not in result.fields
        assert "image_entropy" not in result.fields
        assert result.skip_reasons["quality_signals"] == "fetch_failed"

    def test_persist_writes_quality_signal_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"image_is_truncated": False, "blur_variance": 123.45, "image_entropy": 6.7},
            extractor_versions={"quality_signals": QUALITY_SIGNALS_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.image_is_truncated is False
        assert evidence.blur_variance == pytest.approx(123.45)
        assert evidence.image_entropy == pytest.approx(6.7)


class TestTheTestOnlyWrapperCastsNoVoteAtAll:
    """
    THIS CLASS INVERTED ON 2026-07-30, deliberately, and the inversion is the finding.

    It used to assert that `extract_card_evidence` cast one border `CardTagVote` per card - a real
    machine vote, from a function with ZERO production callers. Both engines
    (`run_image_evidence_cohort`, `stage_e_dispatch._run_stage_c`) call `fetch_card_image` and
    `compute_card_evidence` + `persist_evidence` themselves, and have done since the 2026-07-20
    fetch/compute decoupling - so `test_classified_border_casts_one_vote_per_card` was a green test
    over a channel that had not existed for four months. That is how the 2026-07-29 composition
    audit came to find border/frame/bleed chips at zero rows: a vote cast in an uncalled function
    looks like a wired channel to any grep, and a passing test looks like proof it works.

    The chips are now cast by `local_attribute_chip_cast` and `local_layout_class_cast`, both
    reading stored `ImageEvidence` with no fetch and both wired into
    `stage_e_dispatch._run_stage_d`. `test_local_attribute_chip_cast.py` is where the real chip
    assertions live now. What is left here is the guard against re-adding a write to this wrapper.

    Each case stubs a DIFFERENT border outcome, so this cannot pass merely because the classifier
    abstained: `test_a_confidently_classified_border_still_casts_nothing` is the one that would go
    green under the deleted code, and it is the one that must stay red against it.
    """

    def test_a_confidently_classified_border_still_casts_nothing(self, db, monkeypatch):
        """THE MUTATION TARGET. A confident `black` reading is exactly the input the deleted
        `cast_border_attribute_vote(...).save()` acted on."""
        TagFactory(name="Black Border")
        cards = [CardFactory(content_phash=i + 1) for i in range(3)]
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        for card in cards:
            fetch_and_compute_card_evidence_for_tests(card)

        assert CardTagVote.objects.count() == 0

    def test_an_ambiguous_border_casts_nothing(self, db, monkeypatch):
        TagFactory(name="Black Border")
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, None)
        _stub_art_edge(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch)

        fetch_and_compute_card_evidence_for_tests(card)

        assert CardTagVote.objects.count() == 0

    def test_a_fetch_failure_casts_nothing(self, db, monkeypatch):
        TagFactory(name="Black Border")
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        fetch_and_compute_card_evidence_for_tests(card)

        assert CardTagVote.objects.count() == 0


class TestPersistEvidence:
    def test_writes_a_new_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True, "fetch_error_class": ""},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result, run_id="run-1")

        assert evidence is not None
        assert evidence.card_id == card.pk
        assert evidence.content_hash == 999
        assert evidence.fetch_ok is True
        assert evidence.run_id == "run-1"
        assert evidence.extractor_versions == {"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION}

    def test_null_content_hash_refuses_to_write(self, db):
        card = CardFactory(content_phash=None)
        result = ExtractionResult(card_id=card.pk, content_hash=None, fields={"fetch_ok": True})

        evidence = persist_evidence(result)

        assert evidence is None
        assert ImageEvidence.objects.count() == 0

    def test_rerun_against_same_card_and_hash_updates_in_place(self, db):
        card = CardFactory(content_phash=999)
        first = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            )
        )
        second = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": True, "fetch_error_class": ""},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        assert ImageEvidence.objects.count() == 1
        assert first is not None
        assert second is not None
        assert second.pk == first.pk
        assert second.fetch_ok is True

    def test_different_extractors_merge_without_clobbering(self, db):
        card = CardFactory(content_phash=999)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": True, "fetch_error_class": ""},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        evidence = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={},
                extractor_versions={"some_future_extractor": "v1"},
            )
        )

        assert evidence is not None
        assert evidence.extractor_versions == {
            "fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION,
            "some_future_extractor": "v1",
        }
        # fetch_health's own fields survive an unrelated extractor's pass untouched.
        assert evidence.fetch_ok is True

    def test_different_content_hash_creates_a_new_row_not_overwrite(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(ExtractionResult(card_id=card.pk, content_hash=1, fields={"fetch_ok": True}))
        persist_evidence(ExtractionResult(card_id=card.pk, content_hash=2, fields={"fetch_ok": False}))

        assert ImageEvidence.objects.filter(card=card).count() == 2

    def test_skip_reasons_write_a_card_scan_log_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            skip_reasons={"fetch_health": "fetch_failed"},
        )

        persist_evidence(result, run_id="run-1")

        log = CardScanLog.objects.get(card=card)
        assert log.anonymous_id == "fetch_health"
        assert log.skip_reason == "fetch_failed"
        assert log.run_id == "run-1"

    def test_no_skip_reasons_writes_no_card_scan_log_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True, "fetch_error_class": ""},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        persist_evidence(result)

        assert CardScanLog.objects.count() == 0

    def test_multiple_skip_reasons_are_written_in_a_single_bulk_create(self, db, monkeypatch):
        # 2026-07-24 IO audit finding 3: persist_evidence must batch every skip-reason row into
        # one bulk_create(), not one CardScanLog.objects.create() call per reason, matching every
        # other CardScanLog writer in the codebase.
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            skip_reasons={
                "fetch_health": "fetch_failed",
                "geometry_bleed": "fetch_failed",
                "layout_class": "fetch_failed",
                "collector_line_ocr": "no-text",
                "artist_ocr": "no-text",
            },
        )

        bulk_create_calls: list[int] = []
        original_bulk_create = CardScanLog.objects.bulk_create

        def counting_bulk_create(objs, *args, **kwargs):
            objs = list(objs)
            bulk_create_calls.append(len(objs))
            return original_bulk_create(objs, *args, **kwargs)

        monkeypatch.setattr(CardScanLog.objects, "bulk_create", counting_bulk_create)

        persist_evidence(result, run_id="run-1")

        # exactly one bulk_create call, carrying all 5 rows - not 5 individual .create() calls.
        assert bulk_create_calls == [5]
        assert CardScanLog.objects.filter(card=card, run_id="run-1").count() == 5

    def test_stamps_md5_and_sha256_when_present(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True, "md5_checksum": "abc123", "sha256_checksum": "deadbeef"},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result, run_id="run-1")

        assert evidence is not None
        assert evidence.md5_checksum == "abc123"
        assert evidence.sha256_checksum == "deadbeef"

    def test_stamps_are_null_when_not_supplied(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.md5_checksum is None
        assert evidence.sha256_checksum is None

    def test_real_extraction_clears_a_prior_transferred_flag(self, db):
        """A row previously created via evidence_transfer.transfer_evidence (transferred=True) that
        later receives a REAL extraction pass must have `transferred` reset - persist_evidence is
        the only caller for a genuine extraction, so it's the right place to enforce this (issue
        #473 PR-2's own interim-guard correctness note, see persist_evidence's own docstring)."""
        card = CardFactory(content_phash=999)
        evidence = ImageEvidenceFactory(card=card, content_hash=999, transferred=True, transferred_from_card_id=12345)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        updated = persist_evidence(result, run_id="run-2")

        assert updated is not None
        assert updated.pk == evidence.pk
        assert updated.transferred is False
        assert updated.transferred_from_card_id is None


class TestCurrentEvidenceQueryset:
    def test_content_hash_mismatch_is_stale(self, db):
        card = CardFactory(content_phash=999)
        ImageEvidenceFactory(card=card, content_hash=111)  # a prior image version

        assert list(module.current_evidence_queryset(card)) == []

    def test_matching_content_hash_no_md5_stamp_is_current(self, db):
        """Null-tolerant: a legacy row with no md5_checksum stamp stays current regardless of
        whether the card itself carries an md5 - explicit per this PR's own scope."""
        card = CardFactory(content_phash=999, md5_checksum="abc123")
        evidence = ImageEvidenceFactory(card=card, content_hash=999, md5_checksum=None)

        assert list(module.current_evidence_queryset(card)) == [evidence]

    def test_card_with_no_md5_is_current_regardless_of_evidence_stamp(self, db):
        card = CardFactory(content_phash=999, md5_checksum=None)
        evidence = ImageEvidenceFactory(card=card, content_hash=999, md5_checksum="stale-leftover")

        assert list(module.current_evidence_queryset(card)) == [evidence]

    def test_matching_md5_stamp_is_current(self, db):
        card = CardFactory(content_phash=999, md5_checksum="abc123")
        evidence = ImageEvidenceFactory(card=card, content_hash=999, md5_checksum="abc123")

        assert list(module.current_evidence_queryset(card)) == [evidence]

    def test_stamped_md5_mismatch_is_stale(self, db):
        """The staleness fix's own core case: content_hash still matches (the perceptual hash
        didn't change) but the stamped md5 disagrees with the card's own live md5 - an in-place
        file replacement at the same Drive location. Both non-null and disagreeing => stale."""
        card = CardFactory(content_phash=999, md5_checksum="new-md5")
        ImageEvidenceFactory(card=card, content_hash=999, md5_checksum="old-md5")

        assert list(module.current_evidence_queryset(card)) == []


class TestContentPhashBleedRegimeIsCurrent:
    """content_phash_bleed_regime_is_current (2026-08-22): `Card.content_phash`'s own crop-remap
    depends on `local_fallback.classify_bleed_edge` - the IDENTICAL calculator `geometry_bleed`
    already versions under `GEOMETRY_BLEED_EXTRACTOR_VERSION` - so this reads that existing
    `extractor_versions["geometry_bleed"]` entry directly rather than a new stored field. See the
    function's own docstring for the full structural argument."""

    def test_current_regime_is_not_flagged(self, db):
        """A row whose geometry_bleed entry matches the live version tag exactly - the ordinary
        case for every row a current Stage C pass just wrote - must NOT be falsely flagged."""
        card = CardFactory(content_phash=999)
        evidence = ImageEvidenceFactory(
            card=card, content_hash=999, extractor_versions={"geometry_bleed": GEOMETRY_BLEED_EXTRACTOR_VERSION}
        )

        assert content_phash_bleed_regime_is_current(evidence) is True

    def test_stale_regime_is_detected(self, db):
        """A row stamped under an OLDER geometry_bleed version (the same shape a future
        classify_bleed_edge-affecting change, correctly bumping GEOMETRY_BLEED_EXTRACTOR_VERSION
        per check_extractor_manifest_sync.py's own tether, would leave behind on every
        not-yet-reprocessed row) is a detectable mismatch."""
        card = CardFactory(content_phash=999)
        evidence = ImageEvidenceFactory(
            card=card, content_hash=999, extractor_versions={"geometry_bleed": "geometry-bleed-v0"}
        )

        assert content_phash_bleed_regime_is_current(evidence) is False

    def test_missing_geometry_bleed_key_is_detected(self, db):
        """A row that has never had geometry_bleed run at all (e.g. every extractor before this
        one dropped due to a fetch failure) carries no entry - absence is treated the same as a
        stale mismatch, not silently treated as current."""
        card = CardFactory(content_phash=999)
        evidence = ImageEvidenceFactory(card=card, content_hash=999, extractor_versions={})

        assert content_phash_bleed_regime_is_current(evidence) is False

    def test_no_current_evidence_row_is_detected(self, db):
        """No CURRENT ImageEvidence row at all for this card (current_evidence_queryset empty) -
        an unconfirmed regime is not a verified-current one."""
        assert content_phash_bleed_regime_is_current(None) is False

    def test_real_compute_card_evidence_pass_stamps_the_current_regime(self, db, monkeypatch):
        """End-to-end: a real compute_card_evidence pass (geometry_bleed non-stale) against a
        persisted row is read back as current - proves the detection wires up against the real
        extractor, not just a hand-built extractor_versions dict."""
        card = CardFactory(content_phash=999)
        _stub_border_color(monkeypatch, "black")
        _stub_art_edge(monkeypatch, "framed")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch, result=_a_pinline_inset_result())

        result = compute_card_evidence(card.pk, card.content_phash, _BLEED_IMAGE, fetch_latency_ms=1.0)
        evidence = persist_evidence(result)

        assert content_phash_bleed_regime_is_current(evidence) is True


class TestBuildReconciliationReport:
    def test_all_voted(self, db):
        cards = [CardFactory(content_phash=i) for i in range(1, 4)]
        for card in cards:
            persist_evidence(
                ExtractionResult(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    fields={"fetch_ok": True},
                    extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                )
            )

        report = build_reconciliation_report("fetch_health", [c.pk for c in cards])

        assert report.attempted == 3
        assert report.voted == 3
        assert report.skipped_by_reason == {}
        assert report.dropped == 0
        assert report.is_consistent()

    def test_mixed_voted_skipped_dropped(self, db):
        voted_card = CardFactory(content_phash=1)
        skipped_card = CardFactory(content_phash=2)
        dropped_card = CardFactory(content_phash=3)  # attempted but never persisted at all

        persist_evidence(
            ExtractionResult(
                card_id=voted_card.pk,
                content_hash=1,
                fields={"fetch_ok": True},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )
        persist_evidence(
            ExtractionResult(
                card_id=skipped_card.pk,
                content_hash=2,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            )
        )

        report = build_reconciliation_report("fetch_health", [voted_card.pk, skipped_card.pk, dropped_card.pk])

        assert report.attempted == 3
        assert report.voted == 1
        assert report.skipped_by_reason == {"fetch_failed": 1}
        assert report.dropped == 1
        assert report.is_consistent()

    def test_run_id_scopes_the_skip_side(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=1,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            ),
            run_id="run-a",
        )

        report_matching_run = build_reconciliation_report("fetch_health", [card.pk], run_id="run-a")
        report_other_run = build_reconciliation_report("fetch_health", [card.pk], run_id="run-b")

        assert report_matching_run.skipped_by_reason == {"fetch_failed": 1}
        assert report_other_run.skipped_by_reason == {}
        # the card still "ran" (extractor_versions is unscoped by run_id) but with no matching
        # skip row for run-b, it counts as voted rather than dropped or skipped.
        assert report_other_run.voted == 1

    def test_different_extractor_name_is_independent(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=1,
                fields={"fetch_ok": True},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        report = build_reconciliation_report("some_other_extractor", [card.pk])

        assert report.attempted == 1
        assert report.voted == 0
        assert report.dropped == 1
        assert report.is_consistent()


class TestPerExtractorReextraction:
    """perf/per-extractor-reextraction (2026-08-19): `compute_card_evidence`'s
    `stale_extractor_keys`/`stored_evidence_fields`/`stored_extractor_versions` carry-forward
    path. Every test here poisons its stubs between the "stored" pass and the "current" pass -
    each stub returns a DIFFERENT value the second time - so a field that ends up matching the
    STORED value proves it was genuinely carried forward, not recomputed and coincidentally
    identical."""

    def _stub_everything(self, monkeypatch, border_color, art_edge, collector_raw_text, symbol_phash, blur):
        _stub_border_color(monkeypatch, border_color)
        _stub_art_edge(monkeypatch, art_edge)
        _stub_ocr(monkeypatch, collector_raw_text)
        _stub_symbol_region(monkeypatch, symbol_phash)
        _stub_quality_signals(monkeypatch, blur=blur)
        _stub_pinline_inset(monkeypatch, result=_a_pinline_inset_result())

    def _compute(self, card, image, **overrides):
        return compute_card_evidence(card.pk, card.content_phash, image, fetch_latency_ms=1.0, **overrides)

    def test_non_stale_extractors_are_carried_forward_byte_identical(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        self._stub_everything(
            monkeypatch,
            border_color="black",
            art_edge="framed",
            collector_raw_text="158/287 R MOM EN",
            symbol_phash=111,
            blur=42.0,
        )
        stored = self._compute(card, _BLEED_IMAGE)

        # Every stub now returns something ELSE - if any non-stale extractor actually reran, its
        # field would pick up one of these instead of the stored value below.
        self._stub_everything(
            monkeypatch,
            border_color="white",
            art_edge="mixed",
            collector_raw_text="200/287 M MOM EN",
            symbol_phash=999,
            blur=1000.0,
        )
        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset({"art_edge"}),
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=stored.extractor_versions,
        )

        assert result.extractor_versions == stored.extractor_versions
        # art_edge is the one stale key - it alone reflects the fresh (poisoned) stub.
        assert result.fields["art_edge_class"] == "mixed"
        assert stored.fields["art_edge_class"] == "framed"
        # every other extractor's owned fields are byte-identical to the stored pass, proving
        # they were carried forward rather than recomputed against the poisoned stubs.
        for extractor_key, owned in EXTRACTOR_OWNED_FIELDS.items():
            if extractor_key == "art_edge":
                continue
            for field_name in owned:
                assert result.fields.get(field_name) == stored.fields.get(field_name), field_name
        # skip_reasons is NOT carried forward - a carried-forward extractor did not run THIS
        # pass, so it must not write a fresh CardScanLog row claiming it did (persist_evidence
        # writes one row per ExtractionResult.skip_reasons entry); art_edge is the only key that
        # ran, and it produced a real value ("mixed"), not a skip.
        assert result.skip_reasons == {}

    def test_stale_extractor_reads_a_carried_forward_dependency(self, db, monkeypatch):
        """art_edge reads crop_coordinates' own art_crop_px - proves a stale extractor sees its
        non-stale dependency's value from storage, not from a fresh (never-run) computation."""
        card = CardFactory(content_phash=12345)
        received_boxes = []
        monkeypatch.setattr(
            module,
            "classify_art_edge_continuity",
            lambda image, art_crop_px: received_boxes.append(art_crop_px) or "framed",
        )
        _stub_border_color(monkeypatch, "black")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_pinline_inset(monkeypatch, result=_a_pinline_inset_result())
        stored = self._compute(card, _BLEED_IMAGE)
        assert stored.fields["art_crop_px"]

        received_boxes.clear()
        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset({"art_edge"}),
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=stored.extractor_versions,
        )

        assert received_boxes == [stored.fields["art_crop_px"]]
        assert result.fields["collector_line_crop_px"] == stored.fields["collector_line_crop_px"]
        assert "crop_coordinates" not in (result.extractor_versions.keys() - stored.extractor_versions.keys())

    def test_ocr_group_is_one_staleness_unit(self, db, monkeypatch):
        """collector_line_ocr/artist_ocr/collector_line_tsv share one tesseract escalation loop -
        marking only artist_ocr stale must still rerun (and therefore reflect fresh text in)
        collector_line_ocr/collector_line_tsv too, since there is no stored per-attempt text to
        carry forward artist_ocr's own reuse-before-recompute pass from."""
        card = CardFactory(content_phash=12345)
        self._stub_everything(
            monkeypatch,
            border_color="black",
            art_edge="framed",
            collector_raw_text="158/287 R MOM EN",
            symbol_phash=111,
            blur=42.0,
        )
        stored = self._compute(card, _BLEED_IMAGE)
        assert stored.fields["collector_line_collector_number"] == "158"

        _stub_ocr(monkeypatch, "200/287 M MOM EN")
        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset({"artist_ocr"}),
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=stored.extractor_versions,
        )

        assert result.fields["collector_line_collector_number"] == "200"

    def test_ocr_group_staleness_forces_artbox_phash_recompute(self, db, monkeypatch):
        """artbox_phash reads the OCR group's own collector_line_collector_number/
        illus_anchor_fired as classify_frame_style's inputs. This test's own stale_extractor_keys
        marks only artist_ocr stale, not artbox_phash's own version - the same shape as the real
        regression (4ca2368f bumped the OCR group for an engine swap and missed this indirect
        dependent). artbox_phash must still recompute against the fresh OCR facts rather than
        carrying forward a frame class read under the old ones."""
        card = CardFactory(content_phash=12345)
        self._stub_everything(
            monkeypatch,
            border_color="black",
            art_edge="framed",
            collector_raw_text="158/287 R MOM EN",  # digit-bearing -> "modern"
            symbol_phash=111,
            blur=42.0,
        )
        stored = self._compute(card, _BLEED_IMAGE)
        assert stored.fields["artbox_frame_class"] == "modern"

        _stub_ocr(monkeypatch, "Illus. John Avon")  # no digit, "Illus." anchor -> "old"
        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset({"artist_ocr"}),
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=stored.extractor_versions,
        )

        assert result.fields["artbox_frame_class"] == "old"
        # `_compute_region_phash` is stubbed to a fixed value regardless of crop box (see
        # `_stub_symbol_region`), so the phash INT can't distinguish recompute from carry-forward
        # here - `artbox_crop_px` can: ARTBOX_OLD_CROP_BOX != ARTBOX_MODERN_CROP_BOX, so a genuine
        # recompute against the fresh "old" frame_class must select a different crop box than the
        # stored "modern" pass did. A carried-forward value would still read "modern"'s box.
        assert result.fields["artbox_crop_px"] != stored.fields["artbox_crop_px"]
        assert result.extractor_versions["artbox_phash"] == ARTBOX_PHASH_EXTRACTOR_VERSION

    def test_whole_card_carry_forward_recomputes_nothing(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        self._stub_everything(
            monkeypatch,
            border_color="black",
            art_edge="framed",
            collector_raw_text="158/287 R MOM EN",
            symbol_phash=111,
            blur=42.0,
        )
        stored = self._compute(card, _BLEED_IMAGE)

        calls = {"n": 0}
        monkeypatch.setattr(
            module, "classify_bleed_edge", lambda image: calls.__setitem__("n", calls["n"] + 1) or "bleed"
        )

        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset(),
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=stored.extractor_versions,
        )

        assert calls["n"] == 0
        assert result.fields == stored.fields
        assert result.extractor_versions == stored.extractor_versions
        # Nothing ran this pass, so skip_reasons is empty - see the sibling test above for why.
        assert result.skip_reasons == {}

    def test_a_key_missing_from_stored_versions_is_treated_as_stale(self, db, monkeypatch):
        """An extractor this row has never run (no stored version at all) cannot be carried
        forward from nothing - it must compute, regardless of stale_extractor_keys membership."""
        card = CardFactory(content_phash=12345)
        self._stub_everything(
            monkeypatch,
            border_color="black",
            art_edge="framed",
            collector_raw_text="158/287 R MOM EN",
            symbol_phash=111,
            blur=42.0,
        )
        stored = self._compute(card, _BLEED_IMAGE)
        incomplete_versions = {k: v for k, v in stored.extractor_versions.items() if k != "art_edge"}

        result = self._compute(
            card,
            _BLEED_IMAGE,
            stale_extractor_keys=frozenset(),  # caller says "nothing is stale"...
            stored_evidence_fields=stored.fields,
            stored_extractor_versions=incomplete_versions,  # ...but art_edge was never stored
        )

        assert result.extractor_versions["art_edge"] == ART_EDGE_EXTRACTOR_VERSION
        assert result.fields["art_edge_class"] == "framed"
