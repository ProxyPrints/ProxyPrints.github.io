import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hash_my_cards import (  # noqa: E402
    ART_CROP_BOX,
    TRIM_ASPECT_RATIO,
    classify_bleed_edge,
    compute_content_phash,
    find_matches,
    hamming_distance,
    hash_folder,
    normalize_crop_box,
)


def _make_image(width: int, height: int, color: tuple[int, int, int] = (128, 64, 200)) -> Image.Image:
    return Image.new("RGB", (width, height), color)


class TestClassifyBleedEdge:
    def test_bleed_ratio_classifies_as_bleed(self):
        # BLEED_ASPECT_RATIO ~= 0.7350; 694x944 ~= 0.7351
        assert classify_bleed_edge(_make_image(694, 944)) == "bleed"

    def test_trim_ratio_classifies_as_trimmed(self):
        # TRIM_ASPECT_RATIO = 63/88 exactly for a 630x880 image
        assert classify_bleed_edge(_make_image(630, 880)) == "trimmed"

    def test_far_from_both_is_ambiguous(self):
        assert classify_bleed_edge(_make_image(500, 500)) is None

    def test_zero_height_is_ambiguous_not_a_crash(self):
        # Image.new won't produce a 0-height image in practice, but the function must not
        # divide by zero if it's ever handed a degenerate size - fake just the .size attribute
        # the function actually reads, rather than trying to construct a real 0-height image.
        class _FakeImage:
            size = (100, 0)

        assert classify_bleed_edge(_FakeImage()) is None  # type: ignore[arg-type]

    def test_ratio_nudged_towards_trim_classifies_as_trimmed(self):
        width = round(TRIM_ASPECT_RATIO * 1000) + 1
        assert classify_bleed_edge(_make_image(width, 1000)) == "trimmed"


class TestNormalizeCropBox:
    def test_bleed_is_a_no_op(self):
        assert normalize_crop_box(ART_CROP_BOX, "bleed") == ART_CROP_BOX

    def test_none_is_a_no_op(self):
        assert normalize_crop_box(ART_CROP_BOX, None) == ART_CROP_BOX

    def test_trimmed_rescales_and_stays_in_bounds(self):
        rescaled = normalize_crop_box(ART_CROP_BOX, "trimmed")
        assert rescaled != ART_CROP_BOX
        for fraction in rescaled:
            assert 0.0 <= fraction <= 1.0

    def test_trimmed_rescale_widens_the_box(self):
        # Removing the bleed margin means the same physical art region now occupies a LARGER
        # fraction of the (smaller) trimmed image - left should decrease, right should increase.
        left, top, right, bottom = ART_CROP_BOX
        r_left, r_top, r_right, r_bottom = normalize_crop_box(ART_CROP_BOX, "trimmed")
        assert r_left < left
        assert r_right > right


class TestComputeContentPhash:
    def test_returns_16_hex_chars(self):
        content_hash = compute_content_phash(_make_image(694, 944))
        assert len(content_hash) == 16
        int(content_hash, 16)  # must not raise

    def test_same_image_same_hash(self):
        image_a = _make_image(694, 944, color=(10, 20, 30))
        image_b = _make_image(694, 944, color=(10, 20, 30))
        assert compute_content_phash(image_a) == compute_content_phash(image_b)

    def test_different_content_usually_different_hash(self):
        solid = _make_image(694, 944, color=(200, 10, 10))
        gradient = Image.new("RGB", (694, 944))
        for x in range(694):
            for y in range(0, 944, 40):  # sparse fill, fast enough for a unit test
                gradient.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
        assert compute_content_phash(solid) != compute_content_phash(gradient)

    def test_trimmed_and_bleed_versions_of_the_same_art_converge(self):
        # A trimmed image is the bleed-inclusive image with exactly the bleed margin cropped off
        # - using the module's own margin-fraction constants (not a hand-guessed pixel count) to
        # build the trimmed version keeps this test precise rather than approximate; the first
        # attempt at this test used arbitrary crop amounts and genuinely failed (22 bits apart,
        # not a flake) because they didn't match the real margin fractions.
        from hash_my_cards import _HEIGHT_MARGIN_FRACTION, _WIDTH_MARGIN_FRACTION

        bleed_image = Image.new("RGB", (694, 944))
        for x in range(0, 694, 10):
            for y in range(0, 944, 10):
                bleed_image.putpixel((x, y), (x % 256, y % 256, 128))

        margin_x = round(694 * _WIDTH_MARGIN_FRACTION)
        margin_y = round(944 * _HEIGHT_MARGIN_FRACTION)
        trimmed_image = bleed_image.crop((margin_x, margin_y, 694 - margin_x, 944 - margin_y)).resize((630, 880))

        distance = hamming_distance(compute_content_phash(bleed_image), compute_content_phash(trimmed_image))
        assert distance < 20  # same spec-doc threshold this tool's own docs quote


class TestHammingDistance:
    def test_identical_hashes_zero_distance(self):
        assert hamming_distance("a1b2c3d4e5f60718", "a1b2c3d4e5f60718") == 0

    def test_one_bit_differs(self):
        assert hamming_distance("0000000000000000", "0000000000000001") == 1

    def test_all_bits_differ(self):
        assert hamming_distance("0000000000000000", "ffffffffffffffff") == 64


class TestHashFolder:
    def test_hashes_every_image_recursively(self, tmp_path: Path):
        _make_image(694, 944).save(tmp_path / "Card A.png")
        (tmp_path / "nested").mkdir()
        _make_image(694, 944).save(tmp_path / "nested" / "Card B.jpg")
        (tmp_path / "not_an_image.txt").write_text("hello")

        results = hash_folder(tmp_path)

        assert set(results.keys()) == {"Card A.png", str(Path("nested") / "Card B.jpg")}
        for content_hash in results.values():
            assert len(content_hash) == 16

    def test_skips_unreadable_file_without_crashing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        (tmp_path / "corrupt.png").write_bytes(b"not a real png")
        results = hash_folder(tmp_path)
        assert results == {}
        assert "Skipping" in capsys.readouterr().err


class TestFindMatches:
    def test_finds_exact_match_at_zero_distance(self):
        local = {"Card A.png": "a1b2c3d4e5f60718"}
        export = [{"content_phash": "a1b2c3d4e5f60718", "printing": {"set": "znr", "collector_number": "135"}}]
        matches = find_matches(local, export, threshold=20)
        assert len(matches["Card A.png"]) == 1
        record, distance = matches["Card A.png"][0]
        assert distance == 0
        assert record["printing"]["set"] == "znr"

    def test_no_match_beyond_threshold(self):
        local = {"Card A.png": "0000000000000000"}
        export = [{"content_phash": "ffffffffffffffff", "printing": {}}]
        matches = find_matches(local, export, threshold=20)
        assert matches["Card A.png"] == []

    def test_records_missing_content_phash_are_skipped(self):
        local = {"Card A.png": "a1b2c3d4e5f60718"}
        export = [{"printing": {"set": "znr", "collector_number": "135"}}]
        matches = find_matches(local, export, threshold=20)
        assert matches["Card A.png"] == []

    def test_results_sorted_nearest_first(self):
        local = {"Card A.png": "0000000000000000"}
        export = [
            {"content_phash": "0000000000000003", "printing": {"set": "far"}},
            {"content_phash": "0000000000000001", "printing": {"set": "near"}},
        ]
        matches = find_matches(local, export, threshold=20)
        assert [record["printing"]["set"] for record, _ in matches["Card A.png"]] == ["near", "far"]


class TestExportParsing:
    def test_jsonl_lines_parse_independently(self, tmp_path: Path):
        # find_matches doesn't parse JSONL itself, but this locks in the shape fetch_export's
        # str.splitlines()/json.loads pairing expects - one JSON object per line, blank lines
        # skipped.
        lines = [
            json.dumps({"content_phash": "a1b2c3d4e5f60718", "printing": {"set": "znr"}}),
            "",
            json.dumps({"content_phash": "1122334455667788", "printing": {"set": "mid"}}),
        ]
        parsed = [json.loads(line) for line in lines if line.strip()]
        assert len(parsed) == 2
