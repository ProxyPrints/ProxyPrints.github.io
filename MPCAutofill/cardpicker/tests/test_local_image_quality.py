"""
Unit tests for cardpicker.local_image_quality (public issue #150's re-spec, "Stage C
visual-signal extractors") - pure image-math functions, tested in isolation against real PIL
images, no DB / no `extract_card_evidence` involvement (that wiring is covered by
test_image_evidence.py's TestExtractCardEvidenceQualitySignals/ColorProfile).

is_image_truncated is tested here (rather than through the full extraction pipeline) precisely
BECAUSE a genuinely truncated real file would also trip up earlier, real-pixel-reading
extractors (layout_class/collector_line_ocr/legal_line) that run before quality_signals in
extract_card_evidence's own order - a pre-existing, out-of-scope gap in those extractors, not
something to route around by picking a "safe" truncation point. Testing this function directly
against a real truncated JPEG is both the correct unit-test boundary and avoids that
entanglement entirely.
"""

import io

import pytest
from PIL import Image, ImageDraw

from cardpicker.local_image_quality import (
    compute_blur_variance,
    compute_color_profile,
    compute_entropy,
    is_image_truncated,
)


def _real_image(size: tuple[int, int] = (400, 560)) -> "Image.Image":
    img = Image.new("RGB", size, (200, 200, 200))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, size[0] - 20, size[1] // 2], fill=(30, 90, 160))
    draw.ellipse([40, size[1] // 2 + 10, size[0] - 40, size[1] - 40], fill=(220, 60, 40))
    return img


class TestIsImageTruncated:
    def test_a_complete_image_is_not_truncated(self):
        assert is_image_truncated(_real_image()) is False

    def test_a_genuinely_truncated_jpeg_is_truncated(self):
        buf = io.BytesIO()
        _real_image().save(buf, format="JPEG")
        full_bytes = buf.getvalue()
        truncated = Image.open(io.BytesIO(full_bytes[: len(full_bytes) // 2]))

        assert is_image_truncated(truncated) is True


class TestComputeBlurVariance:
    def test_returns_a_float(self):
        assert isinstance(compute_blur_variance(_real_image()), float)

    def test_a_flat_solid_image_has_exactly_zero_variance(self):
        # compute_blur_variance crops out PIL's own unprocessed 1-pixel filter border before
        # computing variance (see its own docstring) - a perfectly flat image's interior Laplacian
        # response is exactly zero, a clean, hand-verifiable floor case.
        flat = Image.new("RGB", (200, 200), (100, 100, 100))
        assert compute_blur_variance(flat) == pytest.approx(0.0, abs=1e-9)

    def test_a_sharp_edge_image_has_higher_variance_than_a_flat_one(self):
        flat = Image.new("RGB", (200, 200), (100, 100, 100))
        sharp = _real_image((200, 200))
        assert compute_blur_variance(sharp) > compute_blur_variance(flat)


class TestComputeEntropy:
    def test_returns_a_float(self):
        assert isinstance(compute_entropy(_real_image()), float)

    def test_a_flat_solid_image_has_zero_entropy(self):
        # a single pixel value fills the whole grayscale histogram - zero Shannon entropy, a
        # clean, hand-verifiable floor case.
        flat = Image.new("RGB", (200, 200), (100, 100, 100))
        assert compute_entropy(flat) == pytest.approx(0.0, abs=1e-6)

    def test_a_varied_image_has_higher_entropy_than_a_flat_one(self):
        flat = Image.new("RGB", (200, 200), (100, 100, 100))
        varied = _real_image((200, 200))
        assert compute_entropy(varied) > compute_entropy(flat)


class TestComputeColorProfile:
    def test_solid_color_image_has_exact_mean_and_zero_stddev(self):
        image = Image.new("RGB", (100, 140), (100, 150, 200))

        mean_rgb, stddev_rgb = compute_color_profile(image)

        assert mean_rgb == pytest.approx([100.0, 150.0, 200.0])
        assert stddev_rgb == pytest.approx([0.0, 0.0, 0.0])

    def test_returns_three_element_float_lists(self):
        mean_rgb, stddev_rgb = compute_color_profile(_real_image())

        assert len(mean_rgb) == 3
        assert len(stddev_rgb) == 3
        assert all(isinstance(v, float) for v in mean_rgb + stddev_rgb)
