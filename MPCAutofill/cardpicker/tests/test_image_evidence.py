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
through `extract_card_evidence` now also monkeypatches `classify_border_color` itself (not just
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
test that feeds a `_StubImage` through `extract_card_evidence` now also stubs the OCR-group's own
crop/tesseract entry points via `_stub_ocr` below (mirroring `_stub_border_color`'s identical
rationale: `_StubImage` has no `.crop()`/`.convert()` a real PIL image needs).
`TestExtractCardEvidenceCollectorLineOcr`/`ArtistOcr`/`CollectorLineTsv` below use real PIL images
+ the REAL tesseract binary throughout (no monkeypatching of run_tesseract itself) - per CLAUDE.md,
tesseract is installed in CI and real OCR tests are expected to run, not be skipped.

symbol_region (issue #160, "Part 4b: symbol harness") also calls `image.crop(...).convert("L")`
directly (via `_compute_region_phash`) - every existing test that feeds a `_StubImage` through
`extract_card_evidence` now also stubs `_compute_region_phash` itself via `_stub_symbol_region`
below (same rationale as `_stub_border_color`/`_stub_ocr`). `TestExtractCardEvidenceSymbolRegion`
below uses real PIL images throughout (mirrors `TestExtractCardEvidenceLayoutClass`'s own style),
since it's actually testing `_compute_region_phash`'s real output.

legal_line (public issue #151, "Legal-line extractor + moderator flag + volume report (task
#159)" - extractor + moderator-flag signal only, see image_evidence.py's own module docstring for
the scope split) crops its OWN dedicated region (`local_ocr.LEGAL_LINE_CROP_BOX`, not a reuse of
`collector_line_crop_px`) and OCRs it fresh - `_stub_ocr` below already covers this (it patches
`preprocess_variants`/`run_tesseract` at the module level, so any `_StubImage`-based test already
stubs legal_line's own crop+OCR pass for free, same as it does for collector_line_ocr/artist_ocr).
`TestExtractCardEvidenceLegalLine` below uses real PIL images + the real tesseract binary
throughout, same rationale as the other OCR-group test classes.

quality_signals / color_profile (public issue #150's re-spec, the LAST Stage C manifest extractor
group) call `local_image_quality.is_image_truncated`/`compute_blur_variance`/`compute_entropy`/
`compute_color_profile` directly on the fetched image - every existing test that feeds a
`_StubImage` with a non-degenerate width/height through `extract_card_evidence` now also stubs
these via `_stub_quality_signals`/`_stub_color_profile` below (same rationale as
`_stub_border_color`/`_stub_ocr`/`_stub_symbol_region`). `TestExtractCardEvidenceQualitySignals`/
`ColorProfile` below use real PIL images throughout (mirrors `TestExtractCardEvidenceLayoutClass`/
`SymbolRegion`'s own style), since they're actually testing these functions' real output,
including a genuinely truncated real JPEG for the integrity-check path.
"""

from dataclasses import dataclass

import pytest
from PIL import Image, ImageDraw

import cardpicker.image_evidence as module
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import (
    ARTIST_OCR_EXTRACTOR_VERSION,
    COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
    COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
    COLOR_PROFILE_EXTRACTOR_VERSION,
    CROP_COORDINATES_EXTRACTOR_VERSION,
    FETCH_HEALTH_EXTRACTOR_VERSION,
    GEOMETRY_BLEED_EXTRACTOR_VERSION,
    LAYOUT_CLASS_EXTRACTOR_VERSION,
    LEGAL_LINE_EXTRACTOR_VERSION,
    QUALITY_SIGNALS_EXTRACTOR_VERSION,
    SYMBOL_REGION_EXTRACTOR_VERSION,
    ExtractionResult,
    build_reconciliation_report,
    extract_card_evidence,
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
from cardpicker.models import CardScanLog, ImageEvidence
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CardFactory,
    SourceFactory,
)

_SHARED_FACTORIES = [CardFactory, SourceFactory, CanonicalArtistFactory, CanonicalExpansionFactory]


@dataclass(frozen=True)
class _StubImage:
    size: tuple[int, int]

    def crop(self, box):
        # a fake crop - real cropping is never exercised through _StubImage, only through the
        # real-PIL-image test classes below (see _stub_ocr's own docstring for why this is safe).
        return self


# A real fetched image at DEFAULT_FETCH_DPI (250) is ~925px tall - these stub sizes just need to
# land at the right aspect ratio, not the right absolute resolution, since classify_bleed_edge
# only looks at the width/height ratio.
_BLEED_IMAGE = _StubImage(size=(round(1000 * BLEED_ASPECT_RATIO), 1000))
_TRIMMED_IMAGE = _StubImage(size=(round(1000 * TRIM_ASPECT_RATIO), 1000))
_AMBIGUOUS_IMAGE = _StubImage(size=(1000, 1000))  # square - far from both known ratios


def _stub_border_color(monkeypatch, value=None):
    """`_StubImage` has no `.crop()`/`.convert()`/`.getdata()`, so any test feeding one through
    `extract_card_evidence` must stub out `classify_border_color` itself (not just its image
    input) - it's a different function than `classify_bleed_edge`, which only ever reads
    `.size`. `value` defaults to None (ambiguous) but tests that don't care about layout_class's
    own outcome pass a fixed non-None value to keep skip_reasons/extractor_versions assertions
    unaffected by an incidental "ambiguous" entry."""
    monkeypatch.setattr(module, "classify_border_color", lambda image, bleed_class=None: value)


def _stub_ocr(monkeypatch, collector_raw_text: str = "158/287 R MOM EN"):
    """`_StubImage.crop()` returns a fake crop with no real pixel data - any test feeding one
    through `extract_card_evidence` must stub the OCR-group's own crop/tesseract entry points
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
    default ever reaches a tier where `config` would differ from PSM 6 anyway."""
    monkeypatch.setattr(module, "preprocess_variants", lambda cropped: [cropped])
    monkeypatch.setattr(module, "run_tesseract", lambda variant, config=None: collector_raw_text)
    monkeypatch.setattr(module, "run_tesseract_text_and_words", lambda variant, config=None: (collector_raw_text, []))


def _stub_symbol_region(monkeypatch, value: int = 123456789):
    """`_StubImage` has no `.crop()`/`.convert()` a real PIL image needs, so any test feeding one
    through `extract_card_evidence` must stub `_compute_region_phash` itself (same rationale as
    `_stub_border_color`/`_stub_ocr` above) - `symbol_crop_px` itself is still computed for real
    (it only needs width/height/bleed_class, same as crop_coordinates), only the phash of the
    (fake) cropped region is stubbed out."""
    monkeypatch.setattr(module, "_compute_region_phash", lambda image, box: value)


def _stub_quality_signals(monkeypatch, truncated: bool = False, blur: float = 42.0, entropy: float = 5.0):
    """`_StubImage` has no `.load()`/`.convert()` a real PIL image needs, so any test feeding one
    through `extract_card_evidence` (and whose image has a non-degenerate width/height, so the
    `quality_signals`/`color_profile` extractors' own guard doesn't already skip them - see
    `image_evidence.py`'s module docstring) must stub `is_image_truncated`/`compute_blur_variance`/
    `compute_entropy` themselves (same rationale as `_stub_border_color`/`_stub_ocr`/
    `_stub_symbol_region` above)."""
    monkeypatch.setattr(module, "is_image_truncated", lambda image: truncated)
    monkeypatch.setattr(module, "compute_blur_variance", lambda image: blur)
    monkeypatch.setattr(module, "compute_entropy", lambda image: entropy)


def _stub_color_profile(monkeypatch, mean_rgb=(10.0, 20.0, 30.0), stddev_rgb=(1.0, 2.0, 3.0)):
    """Same rationale as `_stub_quality_signals` above - `_StubImage` has no `.convert()` a real
    PIL image needs for `compute_color_profile`."""
    monkeypatch.setattr(module, "compute_color_profile", lambda image: (list(mean_rgb), list(stddev_rgb)))


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


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


class TestExtractCardEvidence:
    def test_successful_fetch_marks_fetch_ok_and_records_no_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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
            "collector_line_ocr": COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
            "artist_ocr": ARTIST_OCR_EXTRACTOR_VERSION,
            "collector_line_tsv": COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
            "symbol_region": SYMBOL_REGION_EXTRACTOR_VERSION,
            "legal_line": LEGAL_LINE_EXTRACTOR_VERSION,
            "quality_signals": QUALITY_SIGNALS_EXTRACTOR_VERSION,
            "color_profile": COLOR_PROFILE_EXTRACTOR_VERSION,
        }
        # _stub_ocr's default raw text ("158/287 R MOM EN") is a realistic modern-frame collector
        # line with no artist credit in it - artist_ocr genuinely skips here, which is the
        # correct outcome for a modern card (see _stub_ocr's own docstring), not a gap. The same
        # text also carries no copyright year or proxy/not-for-sale marker, so legal_line
        # genuinely skips here too (it's fed the identical stubbed text - see _stub_ocr's own
        # module-level patch of run_tesseract).
        assert result.skip_reasons == {"artist_ocr": "no-text", "legal_line": "no-text"}

    def test_failed_fetch_marks_fetch_not_ok_and_records_a_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

        assert result.fields["fetch_ok"] is False
        assert result.fields["fetch_error_class"] == "fetch_failed"
        assert result.fields["fetch_image_format"] == ""
        assert isinstance(result.fields["fetch_latency_ms"], float)
        # no other field is written on a fetch failure - quality_signals/color_profile share the
        # same root cause (see below) and withhold their own fields entirely, same as every other
        # extractor group.
        assert "image_is_truncated" not in result.fields
        assert "blur_variance" not in result.fields
        assert "color_mean_rgb" not in result.fields
        # extractor_versions is still set for every extractor - each ran to completion, it just
        # found a negative result (a fetch failure is a shared root cause, not a crash in any of
        # them). Only a crash omits an extractor's own key (see ExtractionResult's docstring).
        assert result.extractor_versions == {
            "fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION,
            "geometry_bleed": GEOMETRY_BLEED_EXTRACTOR_VERSION,
            "layout_class": LAYOUT_CLASS_EXTRACTOR_VERSION,
            "crop_coordinates": CROP_COORDINATES_EXTRACTOR_VERSION,
            "collector_line_ocr": COLLECTOR_LINE_OCR_EXTRACTOR_VERSION,
            "artist_ocr": ARTIST_OCR_EXTRACTOR_VERSION,
            "collector_line_tsv": COLLECTOR_LINE_TSV_EXTRACTOR_VERSION,
            "symbol_region": SYMBOL_REGION_EXTRACTOR_VERSION,
            "legal_line": LEGAL_LINE_EXTRACTOR_VERSION,
            "quality_signals": QUALITY_SIGNALS_EXTRACTOR_VERSION,
            "color_profile": COLOR_PROFILE_EXTRACTOR_VERSION,
        }
        assert result.skip_reasons == {
            "fetch_health": "fetch_failed",
            "geometry_bleed": "fetch_failed",
            "layout_class": "fetch_failed",
            "crop_coordinates": "fetch_failed",
            "collector_line_ocr": "fetch_failed",
            "artist_ocr": "fetch_failed",
            "collector_line_tsv": "fetch_failed",
            "symbol_region": "fetch_failed",
            "legal_line": "fetch_failed",
            "quality_signals": "fetch_failed",
            "color_profile": "fetch_failed",
        }

    def test_null_content_phash_surfaces_as_none(self, db, monkeypatch):
        card = CardFactory(content_phash=None)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

        assert result.content_hash is None

    def test_lockout_error_propagates_not_swallowed(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)

        def _raise_lockout(card, dpi=None):
            raise GoogleFetchLockoutError("locked out")

        monkeypatch.setattr(module, "fetch_card_image", _raise_lockout)

        with pytest.raises(GoogleFetchLockoutError):
            extract_card_evidence(card)

    def test_no_db_writes_happen(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch)
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        extract_card_evidence(card)

        assert ImageEvidence.objects.count() == 0
        assert CardScanLog.objects.count() == 0


class TestExtractCardEvidenceGeometryBleed:
    """task #147 - the first real manifest extractor."""

    def test_bleed_image_records_dims_ratio_and_bleed_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _BLEED_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

        assert result.fields["bleed_class"] == "trimmed"
        assert "geometry_bleed" not in result.skip_reasons

    def test_ambiguous_aspect_ratio_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _AMBIGUOUS_IMAGE)
        _stub_border_color(monkeypatch, "black")
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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
        _stub_ocr(monkeypatch)

        result = extract_card_evidence(card)

        assert result.fields["aspect_ratio"] is None
        assert result.skip_reasons["geometry_bleed"] == "ambiguous"
        # symbol_region (issue #160): height=0 makes SYMBOL_STRIP_BOX's own pixel box degenerate
        # (top == bottom == 0) - the genuine, non-fabricated trigger of its degenerate-crop-box
        # guard (see image_evidence.py's module docstring: not expected to fire against the real
        # golden set, but a real mechanical guard, exercised for real here). No stub needed -
        # _compute_region_phash is never called for a degenerate box.
        assert "symbol_crop_px" not in result.fields
        assert "symbol_phash" not in result.fields
        assert result.skip_reasons["symbol_region"] == "ambiguous"
        # quality_signals/color_profile (issue #150's re-spec) share this same degenerate-size
        # guard - height=0 skips both as "ambiguous", no stub needed since is_image_truncated/
        # compute_blur_variance/compute_entropy/compute_color_profile are never called for a
        # degenerate size.
        assert "image_is_truncated" not in result.fields
        assert "blur_variance" not in result.fields
        assert result.skip_reasons["quality_signals"] == "ambiguous"
        assert "color_mean_rgb" not in result.fields
        assert result.skip_reasons["color_profile"] == "ambiguous"

    def test_fetch_failure_withholds_geometry_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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
        # legal_line (issue #151) shares the same root cause too.
        assert "legal_line_crop_px" not in result.fields
        assert result.skip_reasons["legal_line"] == "fetch_failed"
        # quality_signals/color_profile (issue #150's re-spec) share the same root cause too.
        assert "image_is_truncated" not in result.fields
        assert result.skip_reasons["quality_signals"] == "fetch_failed"
        assert "color_mean_rgb" not in result.fields
        assert result.skip_reasons["color_profile"] == "fetch_failed"

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

        result = extract_card_evidence(card)

        assert result.fields["bleed_class"] == "bleed"
        assert result.fields["layout_class"] == "black"
        assert "layout_class" not in result.skip_reasons

    def test_white_border_records_layout_class(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._bordered_image((250, 250, 250)))

        result = extract_card_evidence(card)

        assert result.fields["layout_class"] == "white"

    def test_ambiguous_color_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        # gold/yellow - explicitly outside the v1 taxonomy, see classify_border_color's own
        # docstring.
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._bordered_image((180, 140, 40)))

        result = extract_card_evidence(card)

        assert result.fields["layout_class"] == ""
        assert result.skip_reasons["layout_class"] == "ambiguous"

    def test_fetch_failure_withholds_layout_class_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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
        _stub_ocr(monkeypatch)
        _stub_symbol_region(monkeypatch)
        _stub_quality_signals(monkeypatch)
        _stub_color_profile(monkeypatch)

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

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
        # quality_signals/color_profile (issue #150's re-spec) share the same root cause too.
        assert result.skip_reasons["quality_signals"] == "fetch_failed"
        assert result.skip_reasons["color_profile"] == "fetch_failed"

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

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

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
        blank_result = extract_card_evidence(card)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: marked_image)
        marked_result = extract_card_evidence(card)

        assert blank_result.fields["symbol_phash"] != marked_result.fields["symbol_phash"]

    def test_degenerate_crop_box_records_named_skip_and_withholds_fields(self, db, monkeypatch):
        # height=0 collapses SYMBOL_STRIP_BOX's own pixel box to zero area (top == bottom == 0) -
        # the same real, non-fabricated trigger TestExtractCardEvidenceGeometryBleed's own
        # test_zero_height_image_guards_aspect_ratio_division exercises for geometry_bleed.
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: _StubImage(size=(100, 0)))
        _stub_border_color(monkeypatch)
        _stub_ocr(monkeypatch)

        result = extract_card_evidence(card)

        assert "symbol_crop_px" not in result.fields
        assert "symbol_phash" not in result.fields
        assert result.skip_reasons["symbol_region"] == "ambiguous"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

        assert result.fields["collector_line_set_code"] == "mom"
        assert result.fields["collector_line_collector_number"] == "158"
        assert result.fields["collector_line_raw_text"].strip() != ""
        assert "collector_line_ocr" not in result.skip_reasons

    def test_no_legible_text_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "")])  # a blank crop, no text at all
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = extract_card_evidence(card)

        assert result.fields["collector_line_set_code"] == ""
        assert result.fields["collector_line_collector_number"] == ""
        assert result.skip_reasons["collector_line_ocr"] == "no-text"

    def test_no_legible_text_exhausts_every_fallback_tier_before_giving_up(self, db, monkeypatch):
        """issue #259: a blank crop must genuinely try every tier (2 base + 4 fallback + 2
        alternate-PSM = 8 attempts) before recording "no-text" - counted via a wrapper around
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

        result = extract_card_evidence(card)

        assert result.skip_reasons["collector_line_ocr"] == "no-text"
        assert len(configs_used) == 8
        assert configs_used.count(module.TESSERACT_CONFIG) == 6  # 2 base + 4 fallback, PSM 6
        assert configs_used.count(module.ALTERNATE_TESSERACT_CONFIG) == 2  # base variants, PSM 11

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

        result = extract_card_evidence(card)

        assert result.fields["collector_line_collector_number"] == "158"
        assert "collector_line_ocr" not in result.skip_reasons

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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


class TestCollectorLineOcrAttempts:
    """Direct tests of `_collector_line_ocr_attempts` (issue #259) - the lazy, ordered
    (image, tesseract_config) generator `collector_line_ocr`'s own loop consumes. No tesseract
    call happens in these tests (only `preprocess_variants`' PIL-only grayscale/threshold work,
    plus - when the fallback tier is actually reached - `preprocess_fallback_variants`' own
    PIL-only work) - these tests are about the ORDERING/laziness contract, not OCR output, so
    they're fast and don't need a real card image."""

    def test_yields_eight_attempts_in_the_documented_tier_order(self):
        crop = Image.new("RGB", (60, 24), "black")

        attempts = list(module._collector_line_ocr_attempts(crop))

        assert len(attempts) == 8
        configs = [config for _variant, config in attempts]
        assert configs == [module.TESSERACT_CONFIG] * 6 + [module.ALTERNATE_TESSERACT_CONFIG] * 2

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

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

        assert result.fields["artist_ocr_name"] == "John Smith"
        assert result.fields["illus_anchor_fired"] is True
        assert "artist_ocr" not in result.skip_reasons

    def test_no_artist_credit_anywhere_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(DEFAULT_CROP_BOX, "158/287 R MOM EN")])
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = extract_card_evidence(card)

        assert result.fields["artist_ocr_name"] == ""
        assert result.fields["illus_anchor_fired"] is False
        assert result.skip_reasons["artist_ocr"] == "no-text"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

        assert result.fields["collector_line_word_boxes"] == []
        # collector_line_tsv "ran to completion" regardless - no skip for an honestly-empty read.
        assert "collector_line_tsv" not in result.skip_reasons

    def test_fetch_failure_withholds_field_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

        assert result.fields["legal_line_proxy_marker_detected"] is True
        assert result.fields["legal_line_copyright_year"] == "2022"
        assert "legal_line" not in result.skip_reasons

    def test_no_legible_text_records_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        image = _build_card_image([(LEGAL_LINE_CROP_BOX, "")])  # a blank crop, no text at all
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = extract_card_evidence(card)

        assert result.fields["legal_line_copyright_year"] == ""
        assert result.fields["legal_line_proxy_marker_detected"] is False
        assert result.skip_reasons["legal_line"] == "no-text"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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

        result = extract_card_evidence(card)

        assert result.fields["image_is_truncated"] is False
        assert isinstance(result.fields["blur_variance"], float)
        assert isinstance(result.fields["image_entropy"], float)
        assert result.fields["image_entropy"] > 0  # a real image with shapes has real entropy
        assert "quality_signals" not in result.skip_reasons

    def test_truncated_image_records_flag_and_withholds_blur_entropy(self, db, monkeypatch):
        # is_image_truncated's own REAL behavior against a genuinely truncated JPEG is proven in
        # test_local_image_quality.py, in isolation - going through the full extract_card_evidence
        # pipeline with a real truncated file here would also trip up EARLIER real-pixel-reading
        # extractors (layout_class/collector_line_ocr/legal_line, all upstream of quality_signals
        # in extraction order), which is a pre-existing, out-of-scope gap in those extractors, not
        # something this PR's own tests should paper over by picking a truncation point that
        # happens to dodge it. This test instead proves extract_card_evidence's own WIRING - that a
        # True `is_image_truncated` result is recorded and blur/entropy are correctly withheld -
        # the same "stub the function being tested elsewhere, prove the wiring here" split
        # TestExtractCardEvidenceSymbolRegion's own degenerate-box test already uses.
        card = CardFactory(content_phash=1)
        image = self._real_card_image()
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)
        monkeypatch.setattr(module, "is_image_truncated", lambda image: True)

        result = extract_card_evidence(card)

        assert result.fields["image_is_truncated"] is True
        assert "blur_variance" not in result.fields
        assert "image_entropy" not in result.fields
        # shares fetch_health's own "fetch_failed" skip reason - see image_evidence.py's module
        # docstring for why this isn't a new, separately-invented skip-reason string.
        assert result.skip_reasons["quality_signals"] == "fetch_failed"
        # color_profile (below) shares this same finding, without a fresh decode attempt.
        assert "color_mean_rgb" not in result.fields
        assert result.skip_reasons["color_profile"] == "fetch_failed"

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

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


class TestExtractCardEvidenceColorProfile:
    """public issue #150's re-spec, same extractor group as TestExtractCardEvidenceQualitySignals
    above - color_profile computes per-channel (R, G, B) mean/stddev over the FULL fetched image
    via cardpicker.local_image_quality.compute_color_profile. Real PIL images throughout, same
    rationale as TestExtractCardEvidenceQualitySignals above."""

    @staticmethod
    def _solid_color_image(rgb: tuple[int, int, int], size: tuple[int, int] = (200, 280)) -> "Image.Image":
        return Image.new("RGB", size, rgb)

    def test_solid_color_image_records_exact_mean_zero_stddev(self, db, monkeypatch):
        # a solid-color image has a trivially exact, hand-verifiable expected mean (the fill
        # color itself) and zero stddev (every pixel is identical) - a clean, non-brittle
        # positive assertion, unlike pinning stats against a real photographic image.
        card = CardFactory(content_phash=1)
        image = self._solid_color_image((100, 150, 200))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = extract_card_evidence(card)

        assert result.fields["color_mean_rgb"] == pytest.approx([100.0, 150.0, 200.0])
        assert result.fields["color_stddev_rgb"] == pytest.approx([0.0, 0.0, 0.0])
        assert "color_profile" not in result.skip_reasons

    def test_different_images_produce_different_profiles(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._solid_color_image((10, 10, 10)))
        dark_result = extract_card_evidence(card)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: self._solid_color_image((240, 240, 240)))
        light_result = extract_card_evidence(card)

        assert dark_result.fields["color_mean_rgb"] != light_result.fields["color_mean_rgb"]

    def test_fetch_failure_withholds_fields_and_shares_skip_reason(self, db, monkeypatch):
        card = CardFactory(content_phash=1)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

        assert "color_mean_rgb" not in result.fields
        assert "color_stddev_rgb" not in result.fields
        assert result.skip_reasons["color_profile"] == "fetch_failed"

    def test_persist_writes_color_profile_fields(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"color_mean_rgb": [100.0, 150.0, 200.0], "color_stddev_rgb": [10.0, 20.0, 30.0]},
            extractor_versions={"color_profile": COLOR_PROFILE_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result)

        assert evidence is not None
        assert evidence.color_mean_rgb == [100.0, 150.0, 200.0]
        assert evidence.color_stddev_rgb == [10.0, 20.0, 30.0]


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
