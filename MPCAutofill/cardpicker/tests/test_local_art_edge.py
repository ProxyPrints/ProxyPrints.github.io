"""
Tests for the extended-art channel (`cardpicker.local_art_edge`).

The three card types are built as REAL images rather than by stubbing the sampler, so the
geometry - which band lands where, and in which coordinate frame - is under test alongside the
comparison logic. No network, no OCR, no Django DB except where a Tag row is genuinely needed.

Deliberately NOT keyed on any set code, expansion, or card name: this classifier's whole claim is
about pixels, and a fixture that asserted "Aetherdrift cards read as extended" would pass on a
coincidence in current catalogue data rather than on the property being checked.
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
from cardpicker.models import VotePolarity, VoteSource
from cardpicker.tests.factories import CardFactory, TagFactory

_IMAGE_SIZE = (750, 1050)


def _texture(width: int, height: int) -> Image.Image:
    """A deterministic high-variance fill standing in for artwork. `(x * 37 + y * 17) % 256`
    sweeps the whole 0-255 range, giving a per-band red-channel pstdev around 74 - comfortably
    over `_BORDER_UNIFORMITY_STD_THRESHOLD` (18.0) without being tuned to sit just past it. No
    RNG, so a failure is reproducible rather than seed-dependent."""
    data = bytes(((x * 37 + y * 17) % 256) for y in range(height) for x in range(width))
    return Image.frombytes("L", (width, height), data).convert("RGB")


def _art_crop_px_for(bleed_class=None, size=_IMAGE_SIZE) -> list[int]:
    """Reproduces `image_evidence._crop_box_to_pixels` exactly - `ART_CROP_BOX` through
    `normalize_crop_box` for this `bleed_class`, then scaled to pixels. Derived rather than
    hardcoded so this fixture tracks `ART_CROP_BOX` if it ever moves, and so the test exercises
    the same remap-then-scale order production does."""
    from cardpicker.local_phash import ART_CROP_BOX

    width, height = size
    left, top, right, bottom = local_fallback.normalize_crop_box(ART_CROP_BOX, bleed_class)
    return [round(left * width), round(top * height), round(right * width), round(bottom * height)]


def _card(case: str, bleed_class=None) -> Image.Image:
    """Builds the three cards the classifier has to separate, plus the impossible fourth.

    All start as a solid black card and differ ONLY in how far the artwork spreads sideways -
    which is precisely the physical difference between the real card types, and means a test
    that passes here passed because of the art's horizontal extent and nothing else.
    """
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (0, 0, 0))
    art_left, art_top, art_right, art_bottom = _art_crop_px_for(bleed_class)
    edge_left = local_fallback.normalize_crop_box(local_fallback._BORDER_SAMPLE_BANDS[0], bleed_class)
    edge_right = local_fallback.normalize_crop_box(local_fallback._BORDER_SAMPLE_BANDS[1], bleed_class)
    el0, el1 = int(edge_left[0] * width), int(edge_left[2] * width)
    er0, er1 = int(edge_right[0] * width), int(edge_right[2] * width)
    edge_top, edge_bottom = int(edge_left[1] * height), int(edge_left[3] * height)

    def paste(x0, y0, x1, y1):
        if x1 > x0 and y1 > y0:
            img.paste(_texture(x1 - x0, y1 - y0), (x0, y0))

    if case == "framed":
        # artwork confined to the art crop: frame survives between art and both side edges
        paste(art_left, art_top, art_right, art_bottom)
    elif case == "extended":
        # artwork spreads out to the inner edge of both edge bands - the border itself survives
        paste(el1, art_top, er0, art_bottom)
    elif case == "open":
        # artwork reaches the physical edges: borderless / full-art
        paste(0, 0, width, height)
    elif case == "contradictory":
        # artwork ONLY in the edge bands, flat frame inboard of them. No real card does this;
        # it is the geometry-failure signature the classifier must abstain on rather than name.
        paste(el0, edge_top, el1, edge_bottom)
        paste(er0, edge_top, er1, edge_bottom)
    else:  # pragma: no cover - guards against a typo'd case name silently testing "framed"
        raise AssertionError(f"unknown art-edge case {case!r}")
    return img


class TestClassifyArtEdgeContinuity:
    """The owner's two-sample-point method: one band at the card edge, one adjacent to the art
    crop. See `local_art_edge`'s module docstring for why one point cannot do this job."""

    # -- the three real card types ------------------------------------------------------------

    @pytest.mark.parametrize(
        "case, expected",
        [
            ("framed", ART_EDGE_FRAMED),
            ("extended", ART_EDGE_EXTENDED),
            ("open", ART_EDGE_OPEN),
            ("contradictory", None),
        ],
    )
    def test_each_case_gets_its_own_class(self, case, expected):
        assert classify_art_edge_continuity(_card(case), _art_crop_px_for()) == expected

    def test_the_three_real_cases_are_mutually_distinct(self):
        """Guards the property the parametrised case above cannot: that the three classes are
        actually DIFFERENT from each other. A classifier hardcoded to return one value would
        satisfy one row of the table above but not this."""
        verdicts = [classify_art_edge_continuity(_card(c), _art_crop_px_for()) for c in ("framed", "extended", "open")]
        assert len(set(verdicts)) == 3, verdicts

    # -- the discriminator itself -------------------------------------------------------------

    def test_the_edge_sample_is_what_separates_extended_from_open(self):
        """THE POINT OF THE SECOND SAMPLE POINT, proved rather than asserted.

        On the extended-art card and the borderless card the ART-ADJACENT band reaches the SAME
        verdict - both read as artwork - so a one-point classifier looking only there cannot
        tell them apart. The EDGE band is where they diverge. Asserting that the art-adjacent
        readings agree while the verdicts differ is what makes the second sample point
        load-bearing rather than decorative, and it fails if the edge sample is ever dropped -
        which no amount of testing the three happy paths would catch.

        The assertion is on which SIDE of `_BORDER_UNIFORMITY_STD_THRESHOLD` each band falls,
        not on raw equality: the two images paste the same texture at different offsets, so
        their std devs are both emphatically "artwork" without being the same float.
        """
        threshold = local_fallback._BORDER_UNIFORMITY_STD_THRESHOLD
        art_crop_px = _art_crop_px_for()
        width, height = _IMAGE_SIZE
        art_left, art_top, _art_right, art_bottom = art_crop_px
        adjacent_box = (
            local_fallback._BORDER_SAMPLE_BANDS[0][2],
            art_top / height,
            art_left / width,
            art_bottom / height,
        )
        edge_box = local_fallback._BORDER_SAMPLE_BANDS[0]

        readings = {
            case: (
                local_fallback._sample_band(_card(case), adjacent_box)[1],
                local_fallback._sample_band(_card(case), edge_box)[1],
            )
            for case in ("extended", "open")
        }

        # the art-adjacent point says "artwork" for BOTH - on its own it cannot discriminate...
        assert readings["extended"][0] >= threshold
        assert readings["open"][0] >= threshold
        # ...while the edge point says "border" for one and "artwork" for the other.
        assert readings["extended"][1] < threshold
        assert readings["open"][1] >= threshold
        # ...and that is exactly where the two verdicts come apart.
        assert classify_art_edge_continuity(_card("extended"), art_crop_px) == ART_EDGE_EXTENDED
        assert classify_art_edge_continuity(_card("open"), art_crop_px) == ART_EDGE_OPEN

    @pytest.mark.parametrize(
        "mutated_threshold, collapses_to",
        [
            (10_000.0, ART_EDGE_FRAMED),  # every band reads "uniform"
            (0.0, ART_EDGE_OPEN),  # no band ever reads "uniform"
        ],
    )
    def test_mutating_the_uniformity_comparison_collapses_every_case_together(
        self, monkeypatch, mutated_threshold, collapses_to
    ):
        """MUTATION PROOF. The classifier is a comparison against
        `_BORDER_UNIFORMITY_STD_THRESHOLD`; break that comparison in either direction and all
        three physically distinct cards must come back as the SAME class. If this ever passes
        while the happy-path cases also pass, those cases were being satisfied by something
        other than the comparison."""
        monkeypatch.setattr(local_art_edge, "_BORDER_UNIFORMITY_STD_THRESHOLD", mutated_threshold)
        verdicts = {
            case: classify_art_edge_continuity(_card(case), _art_crop_px_for())
            for case in ("framed", "extended", "open")
        }
        assert set(verdicts.values()) == {collapses_to}, verdicts

    # -- coordinate frames --------------------------------------------------------------------

    def test_trimmed_image_reads_the_art_adjacent_strip_in_its_own_frame(self):
        """The asymmetry in the docstring, pinned. On a TRIMMED image `art_crop_px` arrives
        already remapped (`image_evidence` applied `normalize_crop_box` before scaling to
        pixels) while `_BORDER_SAMPLE_BANDS` has not been. The classifier must remap the edge
        band and NOT re-remap the art crop.

        The trimmed remap moves the left edge band's inner bound from 0.05 to ~0.0046 and the
        art crop's left from 0.07 to ~0.027. Reading the strip between the two RAW constants
        instead would run from 0.05 to 0.027 - inverted, i.e. an empty crop and a silently
        skipped band. A card whose art genuinely stops at the art crop must still read 'framed'.
        """
        assert (
            classify_art_edge_continuity(
                _card("framed", bleed_class="trimmed"), _art_crop_px_for("trimmed"), bleed_class="trimmed"
            )
            == ART_EDGE_FRAMED
        )

    def test_trimmed_extended_art_still_reads_extended(self):
        assert (
            classify_art_edge_continuity(
                _card("extended", bleed_class="trimmed"), _art_crop_px_for("trimmed"), bleed_class="trimmed"
            )
            == ART_EDGE_EXTENDED
        )

    def test_double_remapping_the_art_crop_would_change_the_answer(self):
        """Proves the previous two tests are not vacuous - i.e. that the trimmed remap is doing
        something observable here at all. Feeding the classifier an art_crop_px that has been
        remapped a SECOND time (the bug the docstring warns about) moves the sampled strip off
        the frame and changes the verdict away from 'framed'."""
        from cardpicker.local_phash import ART_CROP_BOX

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
        img = _card("framed", bleed_class="trimmed")
        assert classify_art_edge_continuity(img, double_remapped, bleed_class="trimmed") != ART_EDGE_FRAMED

    # -- degenerate input ---------------------------------------------------------------------

    @pytest.mark.parametrize("art_crop_px", [None, [], [1, 2, 3], [10, 10, 5, 500], [10, 10, 500, 5]])
    def test_unusable_art_crop_px_abstains(self, art_crop_px):
        """`art_crop_px` is populated on 100% of `ImageEvidence` rows today (220,579 of
        220,579, measured 2026-07-28), but this classifier must not depend on that staying
        true - a null/short/inverted box is an abstention, not a crash."""
        assert classify_art_edge_continuity(_card("framed"), art_crop_px) is None


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
