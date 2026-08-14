"""
Tests for the canvas-padding detector (local_canvas_padding.py) - real PIL images throughout,
mirroring test_local_fallback.py::TestClassifyBorderColor's own fixture style, since this module
genuinely samples pixel data rather than parsing already-extracted facts. No network, no
database, no tesseract - pure image-processing.
"""

from PIL import Image, ImageDraw

from cardpicker.local_canvas_padding import (
    CALL_AMBIGUOUS,
    CALL_BLACK_INDETERMINATE,
    CALL_CONFIDENT_NOPAD,
    CALL_CONFIDENT_PADDED,
    CALL_NO_TRANSITION_NONBLACK,
    HIGH_PAD_FRACTION,
    LOW_PAD_FRACTION,
    VERDICT_ABSTAIN_BLACK,
    VERDICT_AMBIGUOUS,
    VERDICT_NOT_PADDED,
    VERDICT_PADDED,
    detect_canvas_padding,
)

_IMAGE_WIDTH, _IMAGE_HEIGHT = 750, 1050


def _padded_card_image(
    padding_frac: float = 0.08,
    canvas_rgb: tuple = (240, 240, 240),
    card_rgb: tuple = (0, 0, 0),
    art_rgb: tuple = (120, 80, 200),
) -> "Image.Image":
    """A card of `card_rgb` (a uniform border colour) sitting on a `canvas_rgb` canvas, with the
    card itself inset by `padding_frac` of the image's own dimensions on every edge - the
    padding band the detector is meant to measure."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), canvas_rgb)
    draw = ImageDraw.Draw(img)
    left = round(_IMAGE_WIDTH * padding_frac)
    top = round(_IMAGE_HEIGHT * padding_frac)
    right = round(_IMAGE_WIDTH * (1 - padding_frac))
    bottom = round(_IMAGE_HEIGHT * (1 - padding_frac))
    draw.rectangle([left, top, right, bottom], fill=card_rgb)
    draw.rectangle(
        [left + 60, top + 60, right - 60, bottom - 60],
        fill=art_rgb,
    )
    return img


def _unpadded_card_image(border_rgb: tuple = (0, 0, 0), art_rgb: tuple = (120, 80, 200)) -> "Image.Image":
    """A card that fills the whole image - a plain printed border only (thinner than
    LOW_PAD_FRACTION of either dimension), no canvas around it."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), border_rgb)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, _IMAGE_WIDTH - 20, _IMAGE_HEIGHT - 20], fill=art_rgb)
    return img


class TestDetectCanvasPadding:
    def test_padded_image_measures_within_tolerance_on_all_four_edges(self):
        padding_frac = 0.08
        img = _padded_card_image(padding_frac=padding_frac)

        result = detect_canvas_padding(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.pad_frac is not None
            assert edge.call == CALL_CONFIDENT_PADDED
            assert abs(edge.pad_frac - padding_frac) < 0.02
        assert result.verdict == VERDICT_PADDED

    def test_unpadded_image_reads_no_padding(self):
        img = _unpadded_card_image()

        result = detect_canvas_padding(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.call == CALL_CONFIDENT_NOPAD
        assert result.verdict == VERDICT_NOT_PADDED

    def test_black_on_black_edge_is_indeterminate_not_zero(self):
        # a black-bordered card on a near-identical black canvas, with the transition into the
        # card's own border also sitting beyond the search cap - a colour scan can never see it,
        # since the whole search window reads as one uniform near-black zone. This must abstain,
        # not silently read as "no padding" (see module docstring's guard 2).
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), (5, 5, 5))

        result = detect_canvas_padding(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.pad_frac is None
            assert edge.call == CALL_BLACK_INDETERMINATE
        assert result.verdict == VERDICT_ABSTAIN_BLACK

    def test_uniformity_gate_rejects_a_borderless_cards_own_artwork(self):
        # No canvas padding at all - the card's own art runs edge-to-edge. A naive uniformity-
        # free walk would report the first colour change it meets (art content near the edge) as
        # though it were a canvas boundary; the uniformity gate must reject that read instead.
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT))
        pixels = img.load()
        for x in range(0, _IMAGE_WIDTH, 2):
            for y in range(0, _IMAGE_HEIGHT, 2):
                pixels[x, y] = ((x * 7) % 255, (y * 13) % 255, ((x + y) * 5) % 255)

        result = detect_canvas_padding(img)

        assert result is not None
        # No edge may confidently call this "padded" - the non-uniform zone the walk crosses
        # before any qualifying transition must be rejected by the uniformity gate, leaving each
        # edge either a non-read or (if a run happens to land within an early uniform run of
        # pixels) ambiguous - never a confident padded call from pure art noise.
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.call != CALL_CONFIDENT_PADDED
        assert result.verdict != VERDICT_PADDED

    def test_degenerate_zero_size_image_abstains_rather_than_raises(self):
        class _StubImage:
            size = (0, 0)

        assert detect_canvas_padding(_StubImage()) is None

    def test_degenerate_single_colour_image_abstains_rather_than_raises(self):
        img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), (128, 128, 128))

        result = detect_canvas_padding(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.pad_frac is None
            assert edge.call == CALL_NO_TRANSITION_NONBLACK
        assert result.verdict == VERDICT_AMBIGUOUS

    def test_ambiguous_padding_fraction_between_thresholds(self):
        midpoint = (LOW_PAD_FRACTION + HIGH_PAD_FRACTION) / 2
        img = _padded_card_image(padding_frac=midpoint)

        result = detect_canvas_padding(img)

        assert result is not None
        for edge in (result.top, result.bottom, result.left, result.right):
            assert edge.pad_frac is not None
            assert edge.call == CALL_AMBIGUOUS
        assert result.verdict == VERDICT_AMBIGUOUS
