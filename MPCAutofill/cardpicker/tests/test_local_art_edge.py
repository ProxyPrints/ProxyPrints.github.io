"""
Tests for the extended-art channel (`cardpicker.local_art_edge`), retuned to a within-image
relative colour comparison (docs/reports/2026-08-06-art-edge-relative-comparison.md).

Cards are built as REAL images with precisely controlled per-band colours rather than by
stubbing the sampler, so both the geometry (which band lands where) and the colour comparison
are under test together. No network, no OCR, no Django DB except where a Tag row is genuinely
needed.
"""

import pytest
from PIL import Image

import cardpicker.local_art_edge as local_art_edge
import cardpicker.local_fallback as local_fallback
from cardpicker.local_art_edge import (
    ART_EDGE_ANONYMOUS_ID,
    ART_EDGE_EXTENDED,
    ART_EDGE_FRAMED,
    ART_EDGE_OPEN,
    cast_art_edge_continuity_vote,
    classify_art_edge_continuity,
)
from cardpicker.local_phash import ART_CROP_BOX
from cardpicker.models import VotePolarity, VoteSource
from cardpicker.tests.factories import CardFactory, TagFactory

_IMAGE_SIZE = (750, 1050)


def _clamp(value: int) -> int:
    return max(0, min(255, value))


def _patch(width: int, height: int, base_rgb: tuple[int, int, int], spread: int) -> Image.Image:
    """A deterministic per-pixel colour patch: each channel wobbles +/- spread/2 around
    base_rgb, sweeping a `(x * 37 + y * 17) % (spread + 1)` sawtooth - no RNG, so a failure is
    reproducible rather than seed-dependent. `spread` controls both how far the patch's own mean
    colour can be trusted (a large spread still averages back to base_rgb) and how "textured"
    (real-artwork-like, non-flat) it reads, independently of that mean colour - the two
    properties this classifier's predecessor conflated by testing only spread/variance."""
    r0, g0, b0 = base_rgb
    data = bytearray()
    for y in range(height):
        for x in range(width):
            wobble = (x * 37 + y * 17) % (spread + 1) - spread // 2
            data += bytes((_clamp(r0 + wobble), _clamp(g0 + wobble), _clamp(b0 + wobble)))
    return Image.frombytes("RGB", (width, height), bytes(data))


def _art_crop_px_for(bleed_class=None, size=_IMAGE_SIZE) -> list[int]:
    """Reproduces `image_evidence._crop_box_to_pixels` exactly - `ART_CROP_BOX` through
    `normalize_crop_box` for this `bleed_class`, then scaled to pixels."""
    width, height = size
    left, top, right, bottom = local_fallback.normalize_crop_box(ART_CROP_BOX, bleed_class)
    return [round(left * width), round(top * height), round(right * width), round(bottom * height)]


def _card(
    border_rgb: tuple[int, int, int],
    border_spread: int,
    adjacent_rgb: tuple[int, int, int],
    adjacent_spread: int,
    bleed_class=None,
    art_rgb: tuple[int, int, int] = (120, 90, 60),
    art_spread: int = 200,
) -> Image.Image:
    """A card whose edge bands read `border_rgb`/`border_spread` and whose art-adjacent strips
    read `adjacent_rgb`/`adjacent_spread` - the two samples this classifier compares. The art
    crop itself is filled with an unrelated placeholder patch: this classifier never samples
    inside it, only beside it, so its exact colour is irrelevant to every assertion here."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), border_rgb)
    art_left, art_top, art_right, art_bottom = _art_crop_px_for(bleed_class)
    edge_left = local_fallback.normalize_crop_box(local_fallback._BORDER_SAMPLE_BANDS[0], bleed_class)
    edge_right = local_fallback.normalize_crop_box(local_fallback._BORDER_SAMPLE_BANDS[1], bleed_class)
    el1 = int(edge_left[2] * width)
    er0 = int(edge_right[0] * width)

    def paste(x0, y0, x1, y1, rgb, spread):
        if x1 > x0 and y1 > y0:
            img.paste(_patch(x1 - x0, y1 - y0, rgb, spread), (x0, y0))

    paste(art_left, art_top, art_right, art_bottom, art_rgb, art_spread)
    paste(min(el1, art_left), art_top, art_left, art_bottom, adjacent_rgb, adjacent_spread)
    paste(art_right, art_top, max(er0, art_right), art_bottom, adjacent_rgb, adjacent_spread)
    return img


class TestClassifyArtEdgeContinuity:
    """The retuned relative comparison: does the art-adjacent strip's colour match the border
    colour `layout_class` already says this image has? See `local_art_edge`'s module docstring
    for why that within-image comparison replaced the old absolute-variance test."""

    # -- the relative comparison itself --------------------------------------------------------

    def test_adjacent_matching_black_border_reads_framed(self):
        img = _card((5, 5, 5), 4, (5, 5, 5), 4)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), "black") == ART_EDGE_FRAMED

    def test_adjacent_matching_white_border_reads_framed(self):
        """Proves the comparison is against the DETECTED border colour, not against darkness -
        a black-only case couldn't rule out a classifier that just checks "is this dark"."""
        img = _card((230, 230, 230), 4, (230, 230, 230), 4)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), "white") == ART_EDGE_FRAMED

    def test_dark_off_hue_artwork_beside_a_black_border_does_not_read_extended(self):
        """THE DEFECT THIS RETUNE FIXES, reproduced. Confirmed against the pre-retune code this
        PR replaces (docs/reports/2026-08-06-art-edge-relative-comparison.md): a dark, textured,
        off-hue (navy, not black) strip beside a genuine flat black border read 'extended' under
        the old absolute-variance test - the edge band read flat-and-dark exactly like a real
        border, and the adjacent band's real texture cleared the old uniformity bar for "not
        flat". Neither of those checks the strip's actual COLOUR against the border beside it.
        A navy strip ~36 RGB units from true black does not clear the retuned comparison's
        colour-distance threshold - reads 'framed', not 'extended'.
        """
        img = _card((5, 5, 5), 4, (10, 10, 40), 140)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), "black") == ART_EDGE_FRAMED

    def test_vivid_artwork_beside_a_black_border_reads_extended(self):
        """The genuine positive: artwork colour that is FAR from the border (not merely
        dark-vs-dark), with the outer edge still reading as a real border."""
        img = _card((14, 13, 26), 15, (120, 60, 30), 140)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), "black") == ART_EDGE_EXTENDED

    def test_borderless_layout_class_short_circuits_to_open_without_sampling(self, monkeypatch):
        """A card with no border cannot be extended-art by definition - decided from
        `layout_class` alone. Proved rather than merely asserted: pixel sampling must never run."""

        def _unreached(*args, **kwargs):
            raise AssertionError("classify_art_edge_continuity sampled pixels for a borderless card")

        monkeypatch.setattr(local_art_edge, "_sample_band", _unreached)
        img = _card((0, 0, 0), 0, (0, 0, 0), 0)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), "borderless") == ART_EDGE_OPEN

    def test_ambiguous_layout_class_abstains(self):
        """`layout_class is None` is `classify_border_color`'s own "uniform but not a colour
        this taxonomy covers" abstention - there is no border colour to compare against, so this
        classifier abstains too rather than inventing a comparison against nothing."""
        img = _card((5, 5, 5), 4, (5, 5, 5), 4)
        assert classify_art_edge_continuity(img, _art_crop_px_for(), None) is None

    @pytest.mark.parametrize(
        "mutated_threshold, expected",
        [
            (100_000.0, ART_EDGE_FRAMED),  # every distance reads "close enough to the border"
            (0.0, ART_EDGE_EXTENDED),  # no distance is ever small enough
        ],
    )
    def test_mutating_the_distance_comparison_collapses_every_case_together(
        self, monkeypatch, mutated_threshold, expected
    ):
        """MUTATION PROOF. The classifier is a comparison against
        `_ART_EDGE_COLOR_DISTANCE_THRESHOLD`; snip break that comparison in either direction and both
        a genuine border-colour match and a genuine colour mismatch must come back the SAME. If
        this passes while the happy-path cases above also pass, those cases were satisfied by
        something other than the threshold comparison."""
        monkeypatch.setattr(local_art_edge, "_ART_EDGE_COLOR_DISTANCE_THRESHOLD", mutated_threshold)
        matching = _card((5, 5, 5), 4, (5, 5, 5), 4)
        mismatched = _card((14, 13, 26), 15, (120, 60, 30), 140)
        results = {
            classify_art_edge_continuity(matching, _art_crop_px_for(), "black"),
            classify_art_edge_continuity(mismatched, _art_crop_px_for(), "black"),
        }
        assert results == {expected}, results

    # -- coordinate frames --------------------------------------------------------------------

    def test_trimmed_image_reads_the_art_adjacent_strip_in_its_own_frame(self):
        """The asymmetry in the docstring, pinned. On a TRIMMED image `art_crop_px` arrives
        already remapped while `_BORDER_SAMPLE_BANDS` has not been - the classifier must remap
        the edge band and NOT re-remap the art crop. A card whose art-adjacent colour genuinely
        matches its border must still read 'framed' once that remap is applied correctly."""
        img = _card((5, 5, 5), 4, (5, 5, 5), 4, bleed_class="trimmed")
        assert (
            classify_art_edge_continuity(img, _art_crop_px_for("trimmed"), "black", bleed_class="trimmed")
            == ART_EDGE_FRAMED
        )

    def test_double_remapping_the_art_crop_would_change_the_answer(self):
        """Proves the previous test is not vacuous - i.e. that the trimmed remap does something
        observable here. Feeding the classifier an `art_crop_px` remapped a SECOND time (the bug
        the docstring warns about) samples off the real art-adjacent strip and changes the
        verdict away from the correct 'framed' match."""
        width, height = _IMAGE_SIZE
        once = local_fallback.normalize_crop_box(ART_CROP_BOX, "trimmed")
        twice = local_fallback.normalize_crop_box(once, "trimmed")
        double_remapped = [
            round(twice[0] * width),
            round(twice[1] * height),
            round(twice[2] * width),
            round(twice[3] * height),
        ]
        assert double_remapped != _art_crop_px_for("trimmed")
        img = _card((5, 5, 5), 4, (5, 5, 5), 4, bleed_class="trimmed")
        assert classify_art_edge_continuity(img, double_remapped, "black", bleed_class="trimmed") != ART_EDGE_FRAMED

    # -- degenerate input ---------------------------------------------------------------------

    @pytest.mark.parametrize("art_crop_px", [None, [], [1, 2, 3], [10, 10, 5, 500], [10, 10, 500, 5]])
    def test_unusable_art_crop_px_abstains(self, art_crop_px):
        """`art_crop_px` is populated on 100% of `ImageEvidence` rows today (measured
        2026-07-28), but this classifier must not depend on that staying true - a null/short/
        inverted box is an abstention, not a crash."""
        img = _card((5, 5, 5), 4, (5, 5, 5), 4)
        assert classify_art_edge_continuity(img, art_crop_px, "black") is None


class TestCastArtEdgeContinuityVote:
    def test_extended_reading_produces_an_unsaved_vote_on_the_existing_tag(self, db):
        card = CardFactory()
        tag = TagFactory(name=local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME)
        vote = cast_art_edge_continuity_vote(card, ART_EDGE_EXTENDED)
        assert vote is not None
        assert vote.pk is None  # unsaved - the caller batches these
        assert vote.card_id == card.pk
        assert vote.tag == tag
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == ART_EDGE_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == local_art_edge.ART_EDGE_VOTE_CONFIDENCE

    def test_its_identity_is_its_own_not_the_border_samples(self, db):
        """A shared `anonymous_id` would make these votes indistinguishable from the border
        sample's in every audit that groups by identity - see the constant's own comment."""
        TagFactory(name=local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME)
        vote = cast_art_edge_continuity_vote(CardFactory(), ART_EDGE_EXTENDED)
        assert vote.anonymous_id != local_fallback.FALLBACK_ANONYMOUS_ID

    @pytest.mark.parametrize("art_edge_class", [None, ART_EDGE_FRAMED, ART_EDGE_OPEN, "nonsense"])
    def test_only_the_extended_reading_ever_votes(self, db, art_edge_class):
        """'framed' and 'open' are silent by design - see the function's docstring on why an
        unvalidated class must abstain rather than cast a negative."""
        TagFactory(name=local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME)
        assert cast_art_edge_continuity_vote(CardFactory(), art_edge_class) is None

    def test_unseeded_tag_degrades_to_no_vote(self, db):
        assert cast_art_edge_continuity_vote(CardFactory(), ART_EDGE_EXTENDED) is None

    def test_the_tag_it_votes_on_is_one_the_seeders_already_create(self, db):
        """This channel deliberately seeds NOTHING new: "Extended" is a pre-existing
        `DEFAULT_TAGS` row and already an attribute chip, so it needs no owner seeding action in
        production. Asserted rather than left in prose because a rename of that tag would
        otherwise silently disable this vote - the same failure mode PR #606 pinned for
        `BORDER_COLOR_TO_TAG`."""
        from cardpicker.attribute_tags import (
            ATTRIBUTE_CHIP_TAG_NAMES,
            seed_attribute_tags,
        )
        from cardpicker.default_tags import seed_default_tags
        from cardpicker.models import Tag

        seed_default_tags()
        seed_attribute_tags()
        assert Tag.objects.filter(name=local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME).exists()
        assert local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME in ATTRIBUTE_CHIP_TAG_NAMES
