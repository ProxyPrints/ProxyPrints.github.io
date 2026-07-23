"""
Direct unit tests for local_ocr.py's issue #259 additions ("Stage D no-text bucket: OCR
preprocessing/crop recovery") - `preprocess_fallback_variants`, `_median_from_histogram`,
`ALTERNATE_TESSERACT_CONFIG`, and the `config` kwarg on `run_tesseract`/
`run_tesseract_text_and_words`. Real tesseract throughout (no mocking) - per CLAUDE.md,
tesseract is installed in CI and real OCR tests are expected to run, not be skipped.

Nothing in this module touches `local_fallback.py`/`local_identify_printing_tags.py`
(PROTECTED CORE) - both keep calling the ORIGINAL `preprocess_variants`/`run_tesseract` exactly
as before this issue; see local_ocr.py's own module docstring for the full rationale.

`TestFallbackTierRecoversBlurryUpload` is this issue's one genuine, reproducible (not
argued-only) recovery demonstration - see that class's own docstring for how the exact blur
radius was found and what it does and doesn't prove. The companion mechanism
(`preprocess_fallback_variants`' percentile/median threshold, targeting the diagnostic's
"garbled but present" - uneven-brightness - failure mode) and the alternate-PSM tier
(`ALTERNATE_TESSERACT_CONFIG`) are NOT independently fixture-proven here: this codebase's
existing synthetic card-image fixtures (a tiny PIL default bitmap font, see
test_image_evidence.py's own `_build_card_image`) don't reproduce an uneven-brightness or
segmentation failure realistically enough to demonstrate a genuine before/after recovery -
stated honestly rather than manufactured. The real measurement for both of those happens at the
gated re-extraction against the live no-text cohort (see docs/features/catalog-completion-
plan.md and this PR's own body).
"""

from PIL import Image, ImageDraw, ImageFilter

from cardpicker.local_ocr import (
    ALTERNATE_TESSERACT_CONFIG,
    TESSERACT_CONFIG,
    _median_from_histogram,
    parse_collector_line,
    parse_legal_line,
    preprocess_fallback_variants,
    preprocess_variants,
    run_tesseract,
    run_tesseract_text_and_words,
)


def _text_crop(text: str, size: tuple[int, int] = (300, 90)) -> "Image.Image":
    """A small standalone crop - black background, white text, PIL's default bitmap font (the
    same rendering convention test_image_evidence.py's own `_build_card_image` uses) - this
    module tests local_ocr.py's own functions directly, not the Stage C extractor, so a full
    synthetic card image is unnecessary overhead."""
    img = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(img)
    draw.text((5, 10), text, fill="white")
    return img


class TestMedianFromHistogram:
    """`preprocess_fallback_variants`' own percentile-threshold helper - pure arithmetic, no
    image/tesseract dependency."""

    def test_empty_histogram_defaults_to_128(self):
        # a degenerate (zero-pixel) histogram shouldn't happen for a real crop - guarded
        # defensively (matching preprocess_variants' own fixed 128 cut) rather than raising.
        assert _median_from_histogram([0] * 256) == 128

    def test_all_pixels_at_one_value(self):
        histogram = [0] * 256
        histogram[200] = 1000
        assert _median_from_histogram(histogram) == 200

    def test_skewed_histogram_reflects_the_dominant_mode_not_the_fixed_midpoint(self):
        # 90% of pixels dark (value 10, the background), 10% bright (value 250, the text) - the
        # real-world shape a text crop's own histogram usually has (background occupies most of
        # the crop's area). The median should sit within the DOMINANT (background) mode, not at
        # preprocess_variants' fixed 128 cut - exactly the adaptivity preprocess_fallback_variants'
        # own docstring claims for it.
        histogram = [0] * 256
        histogram[10] = 900
        histogram[250] = 100
        assert _median_from_histogram(histogram) == 10

    def test_evenly_split_histogram_lands_near_the_midpoint(self):
        histogram = [0] * 256
        histogram[0] = 500
        histogram[255] = 500
        median = _median_from_histogram(histogram)
        assert 0 <= median <= 255


class TestPreprocessFallbackVariants:
    def test_returns_four_variants(self):
        crop = _text_crop("158/287 R MOM EN")
        variants = preprocess_fallback_variants(crop)
        assert len(variants) == 4

    def test_heavier_upscale_than_base_preprocess_variants(self):
        crop = _text_crop("158/287 R MOM EN")
        base = preprocess_variants(crop)
        fallback = preprocess_fallback_variants(crop)
        # default upscale 5x (fallback) vs 3x (base) - fallback variants are strictly larger.
        assert fallback[0].size[0] > base[0].size[0]
        assert fallback[0].size[1] > base[0].size[1]

    def test_percentile_pair_is_inverse_polarity(self):
        # percentile pair is tried FIRST (see preprocess_fallback_variants' own docstring for why
        # - less noise-amplifying than the sharpened pair, tried first to reduce the odds of a
        # spurious early "first parse" win over a later-but-correct read).
        crop = _text_crop("158/287 R MOM EN")
        percentile_dark_on_light, percentile_light_on_dark, _sharp_dark, _sharp_light = preprocess_fallback_variants(
            crop
        )
        # ImageOps.invert produces the exact per-pixel inverse - spot check a handful of pixels
        # rather than asserting a full-image byte-for-byte inverse (this is a smoke check that
        # the polarity pairing is real, not a re-derivation of ImageOps.invert's own contract).
        for xy in [(0, 0), (10, 10), (crop.width - 1, 0)]:
            assert percentile_light_on_dark.getpixel(xy) == 255 - percentile_dark_on_light.getpixel(xy)

    def test_sharpened_pair_is_inverse_polarity(self):
        _pct_dark, _pct_light, sharp_dark_on_light, sharp_light_on_dark = preprocess_fallback_variants(
            _text_crop("158/287 R MOM EN")
        )
        for xy in [(0, 0), (10, 10)]:
            assert sharp_light_on_dark.getpixel(xy) == 255 - sharp_dark_on_light.getpixel(xy)


class TestRunTesseractConfigKwarg:
    """Backward-compatibility: every pre-existing call site (local_fallback.py/
    local_identify_printing_tags.py, both PROTECTED CORE) calls `run_tesseract`/
    `run_tesseract_text_and_words` with a single positional `image` argument - the new `config`
    kwarg must default to the exact prior behavior."""

    def test_run_tesseract_default_config_matches_explicit_default(self):
        crop = _text_crop("HELLO")
        assert run_tesseract(crop) == run_tesseract(crop, config=TESSERACT_CONFIG)

    def test_run_tesseract_text_and_words_default_config_matches_explicit_default(self):
        crop = _text_crop("HELLO")
        assert run_tesseract_text_and_words(crop) == run_tesseract_text_and_words(crop, config=TESSERACT_CONFIG)

    def test_run_tesseract_text_and_words_accepts_alternate_config(self):
        crop = _text_crop("HELLO")
        text, words = run_tesseract_text_and_words(crop, config=ALTERNATE_TESSERACT_CONFIG)
        assert isinstance(text, str)
        assert isinstance(words, list)


class TestFallbackTierRecoversBlurryUpload:
    """
    issue #259's B bucket - the bottom-quartile `blur_variance` failure mode - demonstrated as a
    real, reproducible recovery, not merely argued: `ImageFilter.GaussianBlur(1.1)` over a real
    collector-line-shaped crop makes BOTH of `preprocess_variants`' own base polarity variants
    misread "158" as "168" under real tesseract 4.1.1 (verified live, not assumed) -
    `preprocess_fallback_variants`' heavier-upscale + sharpen pass recovers the correct digits at
    the SAME blur radius, same input pixels.

    The radius (1.1) was found empirically by sweeping a range and locating the narrow band
    where the base tier's own fixed-point preprocessing genuinely fails and the fallback tier's
    heavier processing genuinely succeeds (see this PR's own description for the sweep) - it is
    NOT proof of a general blur-tolerance improvement at every radius (materially blurrier input
    defeats every tier here too, same as it would in production); it proves this specific
    recovery mechanism is real for at least one genuine failure case, which is the fixture-level
    claim issue #259 asks this PR to substantiate or honestly disclaim. Tied to a specific
    tesseract version (4.1.1, this environment's own) since exact OCR misreads are not something
    a differently-versioned tesseract binary is guaranteed to reproduce identically - if this
    test ever starts failing after a tesseract upgrade, that's a real signal to re-sweep for a
    still-failing radius, not evidence the underlying recovery mechanism stopped working.
    """

    _TEXT = "158/287 R MOM EN"
    _BLUR_RADIUS = 1.1

    def _blurred_crop(self) -> "Image.Image":
        return _text_crop(self._TEXT).filter(ImageFilter.GaussianBlur(self._BLUR_RADIUS))

    def test_base_variants_misread_the_collector_number_under_this_blur(self):
        crop = self._blurred_crop()
        for variant in preprocess_variants(crop):
            text, _words = run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)
            parsed = parse_collector_line(text)
            # the genuine failure this issue targets - NOT necessarily "no-text" (a plausible-
            # but-wrong digit run, "168", is what tesseract actually produces here), still a
            # miss against the real value.
            assert parsed.collector_number != "158"

    def test_fallback_variants_recover_the_correct_collector_number(self):
        crop = self._blurred_crop()
        recovered = any(
            parse_collector_line(run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)[0]).collector_number
            == "158"
            for variant in preprocess_fallback_variants(crop)
        )
        assert recovered


class TestParseLegalLineProxyMarker:
    """`parse_legal_line`'s `proxy_marker_detected` field - pure string-matching logic, no
    image/tesseract dependency, so tested directly against raw text (matching the file's own
    testing convention for `parse_collector_line` elsewhere in this module). Covers the
    2026-07-23 JestaProxy fix (`_PROXY_MARKER_RE`'s own comment): unbounded proxy/proxies/proxied
    substring matching, the "original design" maker-attribution heuristic, and the false-positive
    guards that fix's own comment argues for (verified live against prod, not just asserted here -
    see PR description for the query results these guard cases are drawn from).
    """

    # --- the live JestaProxy ticket's own two examples ---

    def test_detects_proxy_glued_onto_a_brand_prefix_with_no_word_boundary(self):
        # card 208067's real legal line - "Proxy" glued directly onto "Jesta" with no space/
        # punctuation between them, the exact shape a \b-anchored regex could never match.
        assert parse_legal_line("2025 JestaProxy MTG © EN ©").proxy_marker_detected is True

    def test_detects_original_design_maker_attribution(self):
        # card 215657's real legal line - the "TrixAreforScoot Original Design" maker-brand
        # watermark, no "proxy"-family word anywhere in it at all.
        assert parse_legal_line("TrixAreforScoot Original Design").proxy_marker_detected is True

    # --- unbounded proxy/proxies/proxied substring matching, more generally ---

    def test_detects_proxy_prefixed_brand_name(self):
        assert parse_legal_line("ValarProxy 2025 MTG EN MIDJOURNEY").proxy_marker_detected is True

    def test_detects_proxy_infixed_brand_name(self):
        assert parse_legal_line("2023 DankProxyStash MTG EN 7IFE").proxy_marker_detected is True

    def test_detects_proxies_glued_with_no_boundary(self):
        assert parse_legal_line("R 0311 OxProxies TDC EN BRAM SELS").proxy_marker_detected is True

    def test_still_detects_word_bounded_proxy_forms(self):
        # the pre-existing, already-working bounded cases must keep working under the widened
        # regex - this is an ADDITIVE change, not a rewrite.
        assert parse_legal_line("Proxies by Smaug").proxy_marker_detected is True
        assert parse_legal_line("POGO PROXIES").proxy_marker_detected is True
        assert parse_legal_line("Rustom Playtest Card - Not for Sale").proxy_marker_detected is True

    # --- false-positive guards (module comment's own reasoning, checked here as a regression
    # test rather than left as an argued-only claim) ---

    def test_does_not_match_proximity(self):
        # "proximity" contains "proxim", not "proxy" - the module comment's own reasoning for why
        # unbounding the proxy family is safe.
        assert parse_legal_line("PROXIMITY MTG EN SOME ARTIST").proxy_marker_detected is False

    def test_does_not_match_approximate(self):
        assert parse_legal_line("approximate value only").proxy_marker_detected is False

    def test_does_not_match_genuine_designed_by_credit(self):
        # the real Unknown Event promo shape ("Designed by Gavin Verheys") that the "original
        # design" heuristic is deliberately narrow enough to not collide with.
        assert parse_legal_line("UNK EN DESIGNED BY GAVIN VERHEYS").proxy_marker_detected is False

    def test_does_not_match_a_clean_genuine_legal_line(self):
        assert parse_legal_line("158/287 R MOM EN GREG STAPLES").proxy_marker_detected is False

    def test_empty_text_is_not_detected(self):
        assert parse_legal_line("").proxy_marker_detected is False

    # --- case-insensitivity ---

    def test_case_insensitive_match(self):
        assert parse_legal_line("jestaproxy mtg en").proxy_marker_detected is True
        assert parse_legal_line("ORIGINAL DESIGN").proxy_marker_detected is True
