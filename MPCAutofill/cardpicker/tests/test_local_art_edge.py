"""
Tests for the extended-art channel (`cardpicker.local_art_edge`), redesigned to a fully
self-referential three-region comparison (issue #830 defect 3) - see the module's own docstring
for why it no longer consults `classify_border_color`/`layout_class` at all.

Cards are built as REAL images with precisely controlled per-region colours rather than by
stubbing the sampler, so both the geometry (which region lands where) and the colour comparison
are under test together. No network, no OCR, no Django DB except where a Tag row is genuinely
needed.
"""

import pytest
from PIL import Image

import cardpicker.local_art_edge as local_art_edge
import cardpicker.local_fallback as local_fallback
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_art_edge import (
    ART_EDGE_ANONYMOUS_ID,
    ART_EDGE_EXTENDED,
    ART_EDGE_FRAMED,
    ART_EDGE_FRAMED_SKIP_REASON,
    ART_EDGE_MIXED,
    ART_EDGE_MIXED_SKIP_REASON,
    ART_EDGE_NO_EVIDENCE_SKIP_REASON,
    ART_EDGE_NO_READING_SKIP_REASON,
    cast_art_edge_continuity_vote,
    classify_art_edge_continuity,
    run_art_edge_continuity_cast,
)
from cardpicker.local_phash import ART_CROP_BOX
from cardpicker.models import CardScanLog, CardTagVote, VotePolarity, VoteSource
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory, TagFactory

# width/height ratio 0.7143 - close enough to TRIM_ASPECT_RATIO (0.7159) to classify as
# "trimmed" under the 0.03 tolerance, same fixture shape `test_local_fallback.py`'s own
# TestClassifyBorderColor cards use.
_IMAGE_SIZE = (750, 1050)


def _clamp(value: int) -> int:
    return max(0, min(255, value))


def _patch(width: int, height: int, base_rgb: tuple[int, int, int], spread: int) -> Image.Image:
    """A deterministic per-pixel colour patch: each channel wobbles +/- spread/2 around
    base_rgb, sweeping a `(x * 37 + y * 17) % (spread + 1)` sawtooth - no RNG, so a failure is
    reproducible rather than seed-dependent."""
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
    test_rgb: tuple[int, int, int],
    test_spread: int,
    background_rgb: tuple[int, int, int] = (5, 5, 5),
    background_spread: int = 4,
    reference_a_rgb: tuple[int, int, int] = None,
    reference_a_spread: int = None,
    art_rgb: tuple[int, int, int] = (120, 90, 60),
    art_spread: int = 200,
) -> Image.Image:
    """A card whose TEST region (the art-adjacent strips) reads `test_rgb`/`test_spread`.
    `background_rgb`/`background_spread` fills the whole canvas first - covering Reference B (the
    top band, above the art, never overwritten) and, by default, Reference A (the below-art
    strips) too. Passing `reference_a_rgb` paints Reference A separately, letting a test make the
    two references disagree (the 'mixed' case). The art crop itself is filled with an unrelated
    placeholder patch: this classifier never samples inside it, only beside/below it."""
    if reference_a_rgb is None:
        reference_a_rgb = background_rgb
        reference_a_spread = background_spread

    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), background_rgb)
    art_left, art_top, art_right, art_bottom = _art_crop_px_for()
    left_edge_box = local_fallback.project_mm_box_to_fractions(local_fallback._BORDER_SAMPLE_BANDS_MM["left"], img)
    right_edge_box = local_fallback.project_mm_box_to_fractions(local_fallback._BORDER_SAMPLE_BANDS_MM["right"], img)
    left_gap_outer = min(int(left_edge_box[2] * width), art_left) if left_edge_box is not None else art_left
    right_gap_outer = max(int(right_edge_box[0] * width), art_right) if right_edge_box is not None else art_right

    def paste(x0, y0, x1, y1, rgb, spread):
        if x1 > x0 and y1 > y0:
            img.paste(_patch(x1 - x0, y1 - y0, rgb, spread), (x0, y0))

    paste(art_left, art_top, art_right, art_bottom, art_rgb, art_spread)
    paste(left_gap_outer, art_top, art_left, art_bottom, test_rgb, test_spread)
    paste(art_right, art_top, right_gap_outer, art_bottom, test_rgb, test_spread)

    art_span = art_bottom - art_top
    reference_a_bottom = min(height, art_bottom + art_span)
    paste(left_gap_outer, art_bottom, art_left, reference_a_bottom, reference_a_rgb, reference_a_spread)
    paste(art_right, art_bottom, right_gap_outer, reference_a_bottom, reference_a_rgb, reference_a_spread)
    return img


class TestClassifyArtEdgeContinuity:
    """The self-referential comparison: does the art-adjacent strip's colour match TWO other
    samples of this same image (below the art, and the top band)? See `local_art_edge`'s module
    docstring for why this replaced the `layout_class`-dependent comparison."""

    def test_test_region_matching_both_references_reads_framed(self):
        img = _card(test_rgb=(5, 5, 5), test_spread=4, background_rgb=(5, 5, 5), background_spread=4)
        assert classify_art_edge_continuity(img, _art_crop_px_for()) == ART_EDGE_FRAMED

    def test_test_region_matching_neither_reference_reads_extended(self):
        img = _card(test_rgb=(120, 60, 30), test_spread=140, background_rgb=(14, 13, 26), background_spread=15)
        assert classify_art_edge_continuity(img, _art_crop_px_for()) == ART_EDGE_EXTENDED

    def test_test_region_matching_only_reference_a_reads_mixed(self):
        """Reference A (below the art) agrees with the test region; Reference B (the top band,
        left at the background colour) does not - a genuinely ambiguous within-image reading,
        not forced into either verdict."""
        img = _card(
            test_rgb=(120, 60, 30),
            test_spread=20,
            background_rgb=(5, 5, 5),
            background_spread=4,
            reference_a_rgb=(120, 60, 30),
            reference_a_spread=20,
        )
        assert classify_art_edge_continuity(img, _art_crop_px_for()) == ART_EDGE_MIXED

    def test_test_region_matching_only_reference_b_reads_mixed(self):
        """The inverse asymmetry: Reference B (the top band, left at the background colour)
        agrees with the test region; Reference A (below the art, painted differently) does not."""
        img = _card(
            test_rgb=(5, 5, 5),
            test_spread=4,
            background_rgb=(5, 5, 5),
            background_spread=4,
            reference_a_rgb=(120, 60, 30),
            reference_a_spread=20,
        )
        assert classify_art_edge_continuity(img, _art_crop_px_for()) == ART_EDGE_MIXED

    @pytest.mark.parametrize(
        "mutated_threshold, expected",
        [
            (100_000.0, ART_EDGE_FRAMED),  # every distance reads "close enough to a reference"
            (0.0, ART_EDGE_EXTENDED),  # no distance is ever small enough
        ],
    )
    def test_mutating_the_distance_comparison_collapses_every_case_together(
        self, monkeypatch, mutated_threshold, expected
    ):
        """MUTATION PROOF. The classifier is a comparison against
        `_ART_EDGE_COLOR_DISTANCE_THRESHOLD`; break that comparison in either direction and both
        a genuine match and a genuine mismatch must come back the SAME. If this passes while the
        happy-path cases above also pass, those cases were satisfied by something other than the
        threshold comparison."""
        monkeypatch.setattr(local_art_edge, "_ART_EDGE_COLOR_DISTANCE_THRESHOLD", mutated_threshold)
        matching = _card(test_rgb=(5, 5, 5), test_spread=4, background_rgb=(5, 5, 5), background_spread=4)
        mismatched = _card(test_rgb=(120, 60, 30), test_spread=140, background_rgb=(14, 13, 26), background_spread=15)
        results = {
            classify_art_edge_continuity(matching, _art_crop_px_for()),
            classify_art_edge_continuity(mismatched, _art_crop_px_for()),
        }
        assert results == {expected}, results

    def test_missing_reference_b_abstains_without_falling_back_to_a_single_reference(self, monkeypatch):
        """Reference B (the top band) failing to project (see `project_mm_box_to_fractions`'s own
        MIN_USABLE_BAND_PX refusal) must abstain the whole reading, not silently degrade to
        Reference A alone - a single-reference variant has different, unvalidated false-positive
        characteristics (measured separately, worse, in this PR's own report)."""
        monkeypatch.setattr(local_art_edge, "project_mm_box_to_fractions", lambda mm_box, card_image: None)
        img = _card(test_rgb=(5, 5, 5), test_spread=4, background_rgb=(5, 5, 5), background_spread=4)
        assert classify_art_edge_continuity(img, _art_crop_px_for()) is None

    # -- degenerate input ---------------------------------------------------------------------

    @pytest.mark.parametrize("art_crop_px", [None, [], [1, 2, 3], [10, 10, 5, 500], [10, 10, 500, 5]])
    def test_unusable_art_crop_px_abstains(self, art_crop_px):
        """`art_crop_px` is populated on 100% of `ImageEvidence` rows today (measured
        2026-07-28), but this classifier must not depend on that staying true - a null/short/
        inverted box is an abstention, not a crash."""
        img = _card(test_rgb=(5, 5, 5), test_spread=4, background_rgb=(5, 5, 5), background_spread=4)
        assert classify_art_edge_continuity(img, art_crop_px) is None


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

    @pytest.mark.parametrize("art_edge_class", [None, ART_EDGE_FRAMED, ART_EDGE_MIXED, "nonsense"])
    def test_only_the_extended_reading_ever_votes(self, db, art_edge_class):
        """'framed' and 'mixed' are silent by design - see the function's docstring on why an
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


def _evidence(card, **overrides):
    """A CURRENT `ImageEvidence` row for `card`, matching `test_stage_e_dispatch._full_evidence`'s
    own `content_hash=card.content_phash or 0` convention so `current_evidence_queryset` treats it
    as current."""
    defaults = dict(content_hash=card.content_phash or 0, extractor_versions={"art_edge": "art-edge-v1"})
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestRunArtEdgeContinuityCast:
    def test_extended_reading_casts_a_vote(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_EXTENDED)

        result = run_art_edge_continuity_cast(dry_run=False)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert result.votes_written == 1
        vote = CardTagVote.objects.get(card=card, anonymous_id=ART_EDGE_ANONYMOUS_ID)
        assert vote.tag.name == local_art_edge.ART_EDGE_CONTINUITY_TAG_NAME

    def test_dry_run_counts_without_writing(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_EXTENDED)

        result = run_art_edge_continuity_cast(dry_run=True)

        assert result.votes_would_cast == 1
        assert result.votes_written == 0
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_framed_reading_abstains_with_its_own_skip_reason(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_FRAMED)

        result = run_art_edge_continuity_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {ART_EDGE_FRAMED_SKIP_REASON: 1}
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=ART_EDGE_ANONYMOUS_ID)
        assert scan_log.skip_reason == ART_EDGE_FRAMED_SKIP_REASON

    def test_mixed_reading_abstains_with_its_own_skip_reason(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_MIXED)

        result = run_art_edge_continuity_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {ART_EDGE_MIXED_SKIP_REASON: 1}
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=ART_EDGE_ANONYMOUS_ID)
        assert scan_log.skip_reason == ART_EDGE_MIXED_SKIP_REASON

    def test_blank_reading_abstains_as_no_reading(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class="")

        result = run_art_edge_continuity_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {ART_EDGE_NO_READING_SKIP_REASON: 1}

    def test_no_current_evidence_abstains_as_no_evidence(self, db):
        seed_default_tags()
        CardFactory(content_phash=1)  # no ImageEvidence row at all

        result = run_art_edge_continuity_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {ART_EDGE_NO_EVIDENCE_SKIP_REASON: 1}
        assert result.cards_considered == 0  # never reached a usable evidence row

    def test_a_second_run_over_the_same_extended_card_casts_nothing_new(self, db):
        """Idempotence - once this identity has voted a card, `_eligible_cards_queryset` excludes
        it from every later invocation."""
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_EXTENDED)

        first = run_art_edge_continuity_cast(dry_run=False)
        second = run_art_edge_continuity_cast(dry_run=False)

        assert first.votes_written == 1
        assert second.cards_considered == 0
        assert second.votes_written == 0
        assert CardTagVote.objects.filter(anonymous_id=ART_EDGE_ANONYMOUS_ID).count() == 1

    def test_a_second_run_over_the_same_framed_card_does_not_rescan_it(self, db):
        """`framed`/`mixed` are NOT rescannable skip reasons - a stored non-'extended' reading is
        a permanent conclusion against this content_hash's current evidence."""
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, art_edge_class=ART_EDGE_FRAMED)

        run_art_edge_continuity_cast(dry_run=False)
        second = run_art_edge_continuity_cast(dry_run=False)

        assert second.cards_considered == 0
        assert CardScanLog.objects.filter(card=card, anonymous_id=ART_EDGE_ANONYMOUS_ID).count() == 1

    def test_card_ids_scopes_both_the_outer_query_and_the_scan_log_subquery(self, db):
        seed_default_tags()
        in_scope = CardFactory(content_phash=1)
        out_of_scope = CardFactory(content_phash=2)
        _evidence(in_scope, art_edge_class=ART_EDGE_EXTENDED)
        _evidence(out_of_scope, art_edge_class=ART_EDGE_EXTENDED)

        result = run_art_edge_continuity_cast(dry_run=False, card_ids=[in_scope.pk])

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=in_scope, anonymous_id=ART_EDGE_ANONYMOUS_ID).exists()
        assert not CardTagVote.objects.filter(card=out_of_scope, anonymous_id=ART_EDGE_ANONYMOUS_ID).exists()

    def test_unseeded_tag_raises(self, db):
        """A MISSING TAG SEED must raise for a direct call - `stage_e_dispatch.
        _run_evidence_only_calculators` is the caller that catches this and degrades gracefully;
        this runner itself must not silently swallow it, same convention as
        `run_bleed_calculator_cast`."""
        CardFactory(content_phash=1)
        with pytest.raises(RuntimeError):
            run_art_edge_continuity_cast(dry_run=False)
