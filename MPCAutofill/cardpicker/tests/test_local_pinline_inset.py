"""
Tests for the pinline-inset measurement (local_pinline_inset.py) - real PIL images throughout,
mirroring test_local_fallback.py::TestClassifyBorderColor's own fixture style, since this module
genuinely samples pixel data rather than parsing already-extracted facts. No network, no
database, no tesseract - pure image-processing.
"""

from PIL import Image, ImageDraw

from cardpicker.local_pinline_inset import (
    CALL_INDETERMINATE_BLACK,
    CALL_MEASURED,
    CALL_NO_TRANSITION,
    VERDICT_AMBIGUOUS,
    VERDICT_INDETERMINATE,
    VERDICT_MEASURED,
    measure_pinline_inset,
)

_IMAGE_WIDTH, _IMAGE_HEIGHT = 750, 1050


def _card_image_with_inset(
    inset_frac: float = 0.08,
    background_rgb: tuple = (240, 240, 240),
    border_rgb: tuple = (0, 0, 0),
    art_rgb: tuple = (120, 80, 200),
) -> "Image.Image":
    """A `border_rgb`-coloured card sitting on a `background_rgb` background, inset by
    `inset_frac` of the image's own dimensions on every edge - the distance the scan is meant to
    measure from the image's own edge to the first sustained colour transition."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), background_rgb)
    draw = ImageDraw.Draw(img)
    left = round(_IMAGE_WIDTH * inset_frac)
    top = round(_IMAGE_HEIGHT * inset_frac)
    right = round(_IMAGE_WIDTH * (1 - inset_frac))
    bottom = round(_IMAGE_HEIGHT * (1 - inset_frac))
    draw.rectangle([left, top, right, bottom], fill=border_rgb)
    draw.rectangle(
        [left + 60, top + 60, right - 60, bottom - 60],
        fill=art_rgb,
    )
    return img


def _thin_border_card_image(border_rgb: tuple = (0, 0, 0), art_rgb: tuple = (120, 80, 200)) -> "Image.Image":
    """A card that fills the whole image - a plain printed border only, no wider background band
    around it - so the transition the scan finds sits close to the image's own edge."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), border_rgb)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, _IMAGE_WIDTH - 20, _IMAGE_HEIGHT - 20], fill=art_rgb)
    return img


def _card_image_with_border_band(
    inset_frac: float = 0.08,
    border_width_frac: float = 0.04,
    background_rgb: tuple = (240, 240, 240),
    border_rgb: tuple = (0, 0, 0),
    art_rgb: tuple = (120, 80, 200),
) -> "Image.Image":
    """Three nested rectangles - background, then a `border_rgb` band `border_width_frac` of each
    dimension wide starting at `inset_frac`, then `art_rgb` - so the scan crosses TWO sustained
    colour transitions per edge: background->border at `inset_frac` (the first transition), then
    border->art at `inset_frac + border_width_frac` (the second)."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), background_rgb)
    draw = ImageDraw.Draw(img)
    left = round(_IMAGE_WIDTH * inset_frac)
    top = round(_IMAGE_HEIGHT * inset_frac)
    right = round(_IMAGE_WIDTH * (1 - inset_frac))
    bottom = round(_IMAGE_HEIGHT * (1 - inset_frac))
    draw.rectangle([left, top, right, bottom], fill=border_rgb)
    inner_frac = inset_frac + border_width_frac
    inner_left = round(_IMAGE_WIDTH * inner_frac)
    inner_top = round(_IMAGE_HEIGHT * inner_frac)
    inner_right = round(_IMAGE_WIDTH * (1 - inner_frac))
    inner_bottom = round(_IMAGE_HEIGHT * (1 - inner_frac))
    draw.rectangle([inner_left, inner_top, inner_right, inner_bottom], fill=art_rgb)
    return img


class TestMeasurePinlineInset:
    def test_wide_inset_image_measures_within_tolerance_on_all_four_edges(self):
        inset_frac = 0.08
        img = _card_image_with_inset(inset_frac=inset_frac)

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.inset_frac is not None
            assert edge.call == CALL_MEASURED
            assert abs(edge.inset_frac - inset_frac) < 0.02
        assert result.verdict == VERDICT_MEASURED

    def test_thin_border_image_still_reports_a_measured_inset(self):
        # A magnitude this small used to be read as "confidently unpadded" - a claim about
        # absence this module cannot support (see module docstring). It is still a real,
        # confidently-located transition, so it must still call MEASURED.
        img = _thin_border_card_image()

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.inset_frac is not None
            assert edge.call == CALL_MEASURED
            # Only one band on this fixture (border straight to art) - there is nothing past the
            # first transition to find, so the second scan must report a genuine non-read, not a
            # guess.
            assert edge.second_inset_frac is None
            assert edge.second_call == CALL_NO_TRANSITION
        assert result.verdict == VERDICT_MEASURED

    def test_two_band_image_measures_second_transition_as_border_width(self):
        inset_frac = 0.08
        border_width_frac = 0.04
        img = _card_image_with_border_band(inset_frac=inset_frac, border_width_frac=border_width_frac)

        result = measure_pinline_inset(img)

        assert result is not None
        expected_second_frac = inset_frac + border_width_frac
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.call == CALL_MEASURED
            assert abs(edge.inset_frac - inset_frac) < 0.02
            assert edge.second_call == CALL_MEASURED
            assert edge.second_inset_frac is not None
            assert abs(edge.second_inset_frac - expected_second_frac) < 0.02
        assert result.verdict == VERDICT_MEASURED

    def test_high_contrast_interruption_in_border_band_causes_abstention_not_a_guess(self):
        # A stripe of a wildly different colour partway through the border band (simulating a
        # text stroke crossing it) breaks that band's own uniformity - the SAME uniformity gate
        # the first transition uses, reused rather than a bespoke text detector. The real
        # border/art boundary further inward still triggers a sustained colour departure, but its
        # zone now spans the stripe, so the gate correctly abstains instead of reporting a
        # second-transition distance it cannot vouch for: exactly the "distinguishable from a
        # text-stop, or explicitly abstain" property this measurement needs on the bottom edge.
        inset_frac = 0.08
        border_width_frac = 0.06
        img = _card_image_with_border_band(inset_frac=inset_frac, border_width_frac=border_width_frac)
        draw = ImageDraw.Draw(img)
        stripe_y = round(_IMAGE_HEIGHT * (inset_frac + border_width_frac / 2))
        draw.rectangle([0, stripe_y, _IMAGE_WIDTH, stripe_y + 1], fill=(255, 255, 0))

        result = measure_pinline_inset(img)

        assert result is not None
        assert result.top.call == CALL_MEASURED
        assert abs(result.top.inset_frac - inset_frac) < 0.02
        assert result.top.second_call == CALL_NO_TRANSITION
        assert result.top.second_inset_frac is None

    def test_measured_call_does_not_depend_on_inset_magnitude(self):
        # A mid-sized inset used to fall in a "confidence gap" between two magnitude thresholds
        # and read as AMBIGUOUS. That gap no longer exists: a confidently located transition is
        # MEASURED regardless of how wide or narrow it is - only whether the scan found one at
        # all determines the call.
        target_frac = 0.0425
        img = _card_image_with_inset(inset_frac=target_frac)

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.inset_frac is not None
            assert edge.call == CALL_MEASURED
            assert abs(edge.inset_frac - target_frac) < 0.005
        assert result.verdict == VERDICT_MEASURED

    def test_black_on_black_edge_is_indeterminate_not_a_measured_zero(self):
        # a black-bordered card on a near-identical black background, with the transition into
        # the card's own border also sitting beyond the search cap - a colour scan can never see
        # it, since the whole search window reads as one uniform near-black zone. This must
        # abstain, not silently read as a measured zero-distance inset (see module docstring's
        # guard 2).
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), (5, 5, 5))

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.inset_frac is None
            assert edge.call == CALL_INDETERMINATE_BLACK
            # No first transition, so no second scan was ever attempted - the second call
            # propagates the same indeterminate reason rather than inventing a distinct one.
            assert edge.second_inset_frac is None
            assert edge.second_call == CALL_INDETERMINATE_BLACK
        assert result.verdict == VERDICT_INDETERMINATE

    def test_uniformity_gate_rejects_a_borderless_cards_own_artwork(self):
        # No printed border at all - the card's own art runs edge-to-edge. A naive uniformity-
        # free walk would report the first colour change it meets (art content near the edge) as
        # though it were a real pinline; the uniformity gate must reject that read instead, so no
        # edge may ever report a confidently MEASURED reading from pure art noise.
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT))
        pixels = img.load()
        for x in range(0, _IMAGE_WIDTH, 2):
            for y in range(0, _IMAGE_HEIGHT, 2):
                pixels[x, y] = ((x * 7) % 255, (y * 13) % 255, ((x + y) * 5) % 255)

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.call != CALL_MEASURED
            assert edge.second_call != CALL_MEASURED
            assert edge.second_inset_frac is None
        assert result.verdict != VERDICT_MEASURED

    def test_degenerate_zero_size_image_abstains_rather_than_raises(self):
        class _StubImage:
            size = (0, 0)

        assert measure_pinline_inset(_StubImage()) is None

    def test_degenerate_single_colour_image_abstains_rather_than_raises(self):
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), (128, 128, 128))

        result = measure_pinline_inset(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.inset_frac is None
            assert edge.call == CALL_NO_TRANSITION
            assert edge.second_inset_frac is None
            assert edge.second_call == CALL_NO_TRANSITION
        assert result.verdict == VERDICT_AMBIGUOUS
