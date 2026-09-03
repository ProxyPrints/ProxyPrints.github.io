"""
Tests for the frame-family identifier (`cardpicker.local_frame_family`).

Structural detectors are tested against real PIL images with precisely
controlled per-region characteristics, matching `test_local_art_edge.py`'s
own approach of real geometry + real pixels rather than stubbed samplers.

The calibration gate (`NAMED_FAMILIES`) is empty by default, so the fallback
chain abstains and the caster votes nothing in production. Tests that need a
family to ship as NAMED monkeypatch `NAMED_FAMILIES` to enable it - the
mechanism is proven, the production gate is separately asserted to be shut.

No network, no OCR, no Django DB except where a Tag row is genuinely needed
(vote casting).
"""

import random

import pytest
from PIL import Image, ImageDraw

import cardpicker.local_frame_family as mod
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_frame_family import (
    CONFIDENCE_ABSTAIN,
    CONFIDENCE_MODERATE,
    CONFIDENCE_STRUCTURAL,
    FRAME_FAMILY_AMBIGUOUS_SKIP_REASON,
    FRAME_FAMILY_ANONYMOUS_ID,
    FRAME_FAMILY_CUSTOM,
    FRAME_FAMILY_MYSTICAL_ARCHIVE,
    FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON,
    FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON,
    FRAME_FAMILY_NO_READING_SKIP_REASON,
    FRAME_FAMILY_OTHER_SHOWCASE,
    FRAME_FAMILY_PIPBOY,
    FRAME_FAMILY_SHOWCASE_MAGNIFIED,
    FRAME_FAMILY_STANDARD,
    FRAME_FAMILY_STORYBOOK,
    FRAME_FAMILY_TAG_NAME,
    FRAME_FAMILY_VAULT,
    METHOD_ARTBOUNDS_DISTANCE,
    METHOD_STRUCTURAL_CONSTRUCTION,
    FrameFamilyResult,
    candidate_frame_families,
    cast_frame_family_vote,
    classify_frame_family,
    run_frame_family_cast,
)
from cardpicker.models import CardScanLog, CardTagVote, VotePolarity, VoteSource
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

_IMAGE_SIZE = (750, 1050)


# ---------------------------------------------------------------------------
# Synthetic image builders: one per structural detector.
# Each produces a card image that should trigger exactly one detector.
# ---------------------------------------------------------------------------


def _blank_card(width=750, height=1050, fill=(40, 30, 20)):
    """A uniform dark card — no detector should fire."""
    return Image.new("RGB", (width, height), fill)


def _showcase_magnified_card():
    """A card with a circular art window, mimicking ShowcaseMagnified's circular ring: the
    art box's vertical center is full-width content and its top/bottom rows are empty."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (40, 30, 20))
    draw = ImageDraw.Draw(img)
    art_left = int(0.07 * width)
    art_top = int(0.10 * height)
    art_right = int(0.93 * width)
    art_bottom = int(0.85 * height)
    cx = (art_left + art_right) // 2
    cy = (art_top + art_bottom) // 2
    radius = min(art_right - art_left, art_bottom - art_top) // 2
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(120, 90, 60),
    )
    return img


def _pipboy_card():
    """A card with a high-frequency alternating pattern in the header region,
    mimicking the CRT scanline aesthetic (horizontal stripes -> vertical alternation)."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (40, 30, 20))
    header_bottom = int(0.15 * height)
    for y in range(header_bottom):
        brightness = 200 if y % 2 == 0 else 20
        for x in range(width):
            img.putpixel((x, y), (brightness, brightness, 0))
    return img


def _vault_card():
    """A card with L-shaped brightness gradients in the four corners,
    mimicking Vault's stepped metallic bracket framing."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (40, 30, 20))
    corner_size = int(0.08 * min(width, height))
    for y in range(corner_size):
        for x in range(corner_size):
            dist = (x + y) / (2 * corner_size)
            val = int(255 * (1 - dist))
            img.putpixel((x, y), (val, val, val))
    for y in range(corner_size):
        for x in range(width - corner_size, width):
            dist = ((width - 1 - x) + y) / (2 * corner_size)
            val = int(255 * (1 - dist))
            img.putpixel((x, y), (val, val, val))
    for y in range(height - corner_size, height):
        for x in range(corner_size):
            dist = (x + (height - 1 - y)) / (2 * corner_size)
            val = int(255 * (1 - dist))
            img.putpixel((x, y), (val, val, val))
    for y in range(height - corner_size, height):
        for x in range(width - corner_size, width):
            dist = ((width - 1 - x) + (height - 1 - y)) / (2 * corner_size)
            val = int(255 * (1 - dist))
            img.putpixel((x, y), (val, val, val))
    return img


def _mystical_archive_card():
    """A card with many small bright spots in the type-line region (55-65% of height),
    mimicking the dotted parchment nameplate."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (40, 30, 20))
    type_top = int(0.55 * height)
    type_bottom = int(0.65 * height)
    for y in range(type_top, type_bottom):
        for x in range(width):
            img.putpixel((x, y), (30, 25, 15))
    rng = random.Random(42)
    for _ in range(int(width * (type_bottom - type_top) * 0.20)):
        x = rng.randint(0, width - 1)
        y = rng.randint(type_top, type_bottom - 1)
        img.putpixel((x, y), (220, 210, 180))
    return img


def _storybook_card():
    """A card with high irregularity (stddev) along the left border strip,
    mimicking the vine-scroll border pattern."""
    width, height = _IMAGE_SIZE
    img = Image.new("RGB", (width, height), (40, 30, 20))
    border_width = max(int(0.03 * min(width, height)), 3)
    rng = random.Random(42)
    for y in range(height):
        for x in range(border_width):
            val = rng.randint(0, 255)
            img.putpixel((x, y), (val, val, val))
    return img


# ---------------------------------------------------------------------------
# Tests for individual structural detectors.
# ---------------------------------------------------------------------------


class TestStructuralDetectors:
    def test_showcase_magnified_detector_fires_on_narrow_art_window(self):
        img = _showcase_magnified_card()
        assert mod._detect_showcase_magnified(img) is True

    def test_showcase_magnified_detector_rejects_full_width_art(self):
        width, height = _IMAGE_SIZE
        img = Image.new("RGB", (width, height), (40, 30, 20))
        draw = ImageDraw.Draw(img)
        draw.rectangle(
            [int(0.07 * width), int(0.10 * height), int(0.93 * width), int(0.85 * height)],
            fill=(120, 90, 60),
        )
        assert mod._detect_showcase_magnified(img) is False

    def test_pipboy_detector_fires_on_scanline_pattern(self):
        img = _pipboy_card()
        assert mod._detect_pipboy(img) is True

    def test_pipboy_detector_rejects_solid_header(self):
        img = _blank_card()
        assert mod._detect_pipboy(img) is False

    def test_vault_detector_fires_on_corner_gradients(self):
        img = _vault_card()
        assert mod._detect_vault(img) is True

    def test_vault_detector_rejects_solid_corners(self):
        img = _blank_card()
        assert mod._detect_vault(img) is False

    def test_mystical_archive_detector_fires_on_dotted_nameplate(self):
        img = _mystical_archive_card()
        assert mod._detect_mystical_archive(img) is True

    def test_mystical_archive_detector_rejects_solid_type_line(self):
        img = _blank_card()
        assert mod._detect_mystical_archive(img) is False

    def test_storybook_detector_fires_on_irregular_border(self):
        img = _storybook_card()
        assert mod._detect_storybook(img) is True

    def test_storybook_detector_rejects_solid_border(self):
        img = _blank_card()
        assert mod._detect_storybook(img) is False


# ---------------------------------------------------------------------------
# Tests for classify_frame_family (the full fallback chain).
# ---------------------------------------------------------------------------


class TestClassifyFrameFamily:
    def _enable_all(self, monkeypatch):
        monkeypatch.setattr(mod, "NAMED_FAMILIES", mod.STRUCTURAL_FAMILIES)

    def test_structural_showcase_magnified(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_showcase_magnified_card())
        assert result.family_class == FRAME_FAMILY_SHOWCASE_MAGNIFIED
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION

    def test_structural_pipboy(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_pipboy_card())
        assert result.family_class == FRAME_FAMILY_PIPBOY
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION

    def test_structural_vault(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_vault_card())
        assert result.family_class == FRAME_FAMILY_VAULT
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION

    def test_structural_mystical_archive(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_mystical_archive_card())
        assert result.family_class == FRAME_FAMILY_MYSTICAL_ARCHIVE
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION

    def test_structural_storybook(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_storybook_card())
        assert result.family_class == FRAME_FAMILY_STORYBOOK
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION

    def test_abstains_when_no_family_calibrated(self):
        """With NAMED_FAMILIES empty (the shipped calibration state) the structural detectors
        are gated off and the chain abstains, even on a synthetic positive."""
        result = classify_frame_family(_showcase_magnified_card())
        assert result.family_class == ""
        assert result.confidence == CONFIDENCE_ABSTAIN
        assert result.method == ""
        assert result.skip_reason == FRAME_FAMILY_AMBIGUOUS_SKIP_REASON

    def test_zero_candidates_abstains_with_no_candidates_reason(self, monkeypatch):
        """issue #979: a name resolving to zero candidates abstains with a named skip reason."""
        self._enable_all(monkeypatch)
        result = classify_frame_family(_showcase_magnified_card(), candidate_families=frozenset())
        assert result.family_class == ""
        assert result.skip_reason == FRAME_FAMILY_NO_CANDIDATES_SKIP_REASON

    def test_set_narrowing_blocks_family_not_in_candidate_set(self, monkeypatch):
        """A structural detector fires, but the family is not in the card's own candidate set,
        so the chain does not claim it."""
        self._enable_all(monkeypatch)
        result = classify_frame_family(_pipboy_card(), candidate_families=frozenset({FRAME_FAMILY_VAULT}))
        assert result.family_class == ""
        assert result.skip_reason == FRAME_FAMILY_AMBIGUOUS_SKIP_REASON

    def test_abstains_on_blank_card(self, monkeypatch):
        self._enable_all(monkeypatch)
        result = classify_frame_family(_blank_card())
        assert result.family_class == ""
        assert result.confidence == CONFIDENCE_ABSTAIN
        assert result.method == ""

    def test_artbounds_distance_fires_on_consistent_pinline(self):
        img = _blank_card()
        result = classify_frame_family(
            img,
            pinline_inset_frac_top=0.05,
            pinline_inset_frac_bottom=0.06,
            pinline_inset_frac_left=0.055,
            pinline_inset_frac_right=0.045,
            layout_class="black",
        )
        assert result.family_class == FRAME_FAMILY_STANDARD
        assert result.confidence == CONFIDENCE_MODERATE
        assert result.method == METHOD_ARTBOUNDS_DISTANCE

    def test_artbounds_distance_abstains_without_layout_class(self):
        img = _blank_card()
        result = classify_frame_family(
            img,
            pinline_inset_frac_top=0.05,
            pinline_inset_frac_bottom=0.06,
            pinline_inset_frac_left=0.055,
            pinline_inset_frac_right=0.045,
            layout_class="",
        )
        assert result.family_class == ""
        assert result.confidence == CONFIDENCE_ABSTAIN

    def test_structural_detector_takes_priority_over_artbounds(self, monkeypatch):
        self._enable_all(monkeypatch)
        img = _pipboy_card()
        result = classify_frame_family(
            img,
            pinline_inset_frac_top=0.05,
            pinline_inset_frac_bottom=0.06,
            pinline_inset_frac_left=0.055,
            pinline_inset_frac_right=0.045,
            layout_class="black",
        )
        assert result.family_class == FRAME_FAMILY_PIPBOY
        assert result.confidence == CONFIDENCE_STRUCTURAL
        assert result.method == METHOD_STRUCTURAL_CONSTRUCTION


# ---------------------------------------------------------------------------
# Tests for candidate_frame_families (set narrowing).
# ---------------------------------------------------------------------------


class _FakeIndex:
    def __init__(self, by_name):
        self._by_name = by_name

    def candidates_for(self, name):
        return self._by_name.get(name, [])


class _FakeCandidate:
    def __init__(self, expansion_code):
        self.expansion_code = expansion_code


class TestCandidateFrameFamilies:
    def test_maps_set_codes_to_families(self):
        index = _FakeIndex({"foo": [_FakeCandidate("mkm"), _FakeCandidate("eld")]})
        assert candidate_frame_families("foo", index) == frozenset(
            {FRAME_FAMILY_SHOWCASE_MAGNIFIED, FRAME_FAMILY_STORYBOOK}
        )

    def test_empty_for_unknown_name(self):
        index = _FakeIndex({})
        assert candidate_frame_families("unknown", index) == frozenset()

    def test_empty_for_sets_without_named_family(self):
        index = _FakeIndex({"foo": [_FakeCandidate("znr")]})
        assert candidate_frame_families("foo", index) == frozenset()


# ---------------------------------------------------------------------------
# Tests for cast_frame_family_vote.
# ---------------------------------------------------------------------------


class TestCastFrameFamilyVote:
    def _enable(self, monkeypatch, families):
        monkeypatch.setattr(mod, "NAMED_FAMILIES", frozenset(families))

    def test_above_bar_vote(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        card = CardFactory()
        vote = cast_frame_family_vote(card, FRAME_FAMILY_SHOWCASE_MAGNIFIED, CONFIDENCE_STRUCTURAL)
        assert vote is not None
        assert vote.card_id == card.pk
        assert vote.tag.name == FRAME_FAMILY_TAG_NAME
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == FRAME_FAMILY_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == mod.FRAME_FAMILY_VOTE_CONFIDENCE

    def test_uncalibrated_family_abstains(self, db):
        """The shipped calibration state (NAMED_FAMILIES empty) casts nothing."""
        seed_default_tags()
        vote = cast_frame_family_vote(CardFactory(), FRAME_FAMILY_SHOWCASE_MAGNIFIED, CONFIDENCE_STRUCTURAL)
        assert vote is None

    def test_below_bar_confidence_abstains(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        vote = cast_frame_family_vote(CardFactory(), FRAME_FAMILY_SHOWCASE_MAGNIFIED, CONFIDENCE_MODERATE)
        assert vote is None

    @pytest.mark.parametrize(
        "family_class",
        ["", FRAME_FAMILY_STANDARD, FRAME_FAMILY_CUSTOM, FRAME_FAMILY_OTHER_SHOWCASE],
    )
    def test_non_named_family_abstains(self, db, monkeypatch, family_class):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        vote = cast_frame_family_vote(CardFactory(), family_class, CONFIDENCE_STRUCTURAL)
        assert vote is None

    def test_unseeded_tag_degrades_to_no_vote(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        vote = cast_frame_family_vote(CardFactory(), FRAME_FAMILY_SHOWCASE_MAGNIFIED, CONFIDENCE_STRUCTURAL)
        assert vote is None

    def test_its_identity_is_its_own(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_VAULT])
        seed_default_tags()
        vote = cast_frame_family_vote(CardFactory(), FRAME_FAMILY_VAULT, CONFIDENCE_STRUCTURAL)
        assert vote is not None
        assert vote.anonymous_id == FRAME_FAMILY_ANONYMOUS_ID


# ---------------------------------------------------------------------------
# Tests for run_frame_family_cast (the full cast infrastructure).
# ---------------------------------------------------------------------------


def _evidence(card, **overrides):
    defaults = dict(content_hash=card.content_phash or 0, extractor_versions={"frame_family": "frame-family-v1"})
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestRunFrameFamilyCast:
    def _enable(self, monkeypatch, families):
        monkeypatch.setattr(mod, "NAMED_FAMILIES", frozenset(families))

    def test_structural_reading_casts_a_vote(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card, frame_family_class=FRAME_FAMILY_SHOWCASE_MAGNIFIED, frame_family_confidence=CONFIDENCE_STRUCTURAL
        )

        result = run_frame_family_cast(dry_run=False)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert result.votes_written == 1
        vote = CardTagVote.objects.get(card=card, anonymous_id=FRAME_FAMILY_ANONYMOUS_ID)
        assert vote.tag.name == FRAME_FAMILY_TAG_NAME

    def test_uncalibrated_reading_abstains(self, db):
        """Shipped calibration state: no family is NAMED, so a stored named reading casts nothing."""
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card, frame_family_class=FRAME_FAMILY_SHOWCASE_MAGNIFIED, frame_family_confidence=CONFIDENCE_STRUCTURAL
        )

        result = run_frame_family_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {f"uncalibrated-{FRAME_FAMILY_SHOWCASE_MAGNIFIED}": 1}

    def test_dry_run_counts_without_writing(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card, frame_family_class=FRAME_FAMILY_SHOWCASE_MAGNIFIED, frame_family_confidence=CONFIDENCE_STRUCTURAL
        )

        result = run_frame_family_cast(dry_run=True)

        assert result.votes_would_cast == 1
        assert result.votes_written == 0
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_blank_reading_abstains_as_no_reading(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, frame_family_class="", frame_family_confidence=CONFIDENCE_ABSTAIN)

        result = run_frame_family_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {FRAME_FAMILY_NO_READING_SKIP_REASON: 1}

    def test_no_current_evidence_abstains_as_no_evidence(self, db):
        seed_default_tags()
        CardFactory(content_phash=1)

        result = run_frame_family_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON: 1}

    def test_standard_family_abstains(self, db):
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, frame_family_class=FRAME_FAMILY_STANDARD, frame_family_confidence=CONFIDENCE_STRUCTURAL)

        result = run_frame_family_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {f"uncalibrated-{FRAME_FAMILY_STANDARD}": 1}

    def test_low_confidence_abstains(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, frame_family_class=FRAME_FAMILY_SHOWCASE_MAGNIFIED, frame_family_confidence=CONFIDENCE_MODERATE)

        result = run_frame_family_cast(dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {"confidence-1": 1}

    def test_idempotence(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_SHOWCASE_MAGNIFIED])
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card, frame_family_class=FRAME_FAMILY_SHOWCASE_MAGNIFIED, frame_family_confidence=CONFIDENCE_STRUCTURAL
        )

        first = run_frame_family_cast(dry_run=False)
        second = run_frame_family_cast(dry_run=False)

        assert first.votes_written == 1
        assert second.cards_considered == 0
        assert second.votes_written == 0

    def test_rescannable_skip_allows_rescan(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_PIPBOY])
        seed_default_tags()
        card = CardFactory(content_phash=1)
        _no_ev_result = run_frame_family_cast(dry_run=False)
        assert _no_ev_result.skip_counts.get(FRAME_FAMILY_NO_EVIDENCE_SKIP_REASON, 0) == 1

        _evidence(card, frame_family_class=FRAME_FAMILY_PIPBOY, frame_family_confidence=CONFIDENCE_STRUCTURAL)
        second = run_frame_family_cast(dry_run=False)

        assert second.votes_written == 1

    def test_card_ids_scopes_to_provided_list(self, db, monkeypatch):
        self._enable(monkeypatch, [FRAME_FAMILY_VAULT])
        seed_default_tags()
        in_scope = CardFactory(content_phash=1)
        out_of_scope = CardFactory(content_phash=2)
        _evidence(in_scope, frame_family_class=FRAME_FAMILY_VAULT, frame_family_confidence=CONFIDENCE_STRUCTURAL)
        _evidence(out_of_scope, frame_family_class=FRAME_FAMILY_VAULT, frame_family_confidence=CONFIDENCE_STRUCTURAL)

        result = run_frame_family_cast(dry_run=False, card_ids=[in_scope.pk])

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=in_scope, anonymous_id=FRAME_FAMILY_ANONYMOUS_ID).exists()
        assert not CardTagVote.objects.filter(card=out_of_scope, anonymous_id=FRAME_FAMILY_ANONYMOUS_ID).exists()

    def test_unseeded_tag_raises(self, db):
        CardFactory(content_phash=1)
        with pytest.raises(RuntimeError):
            run_frame_family_cast(dry_run=False)


# ---------------------------------------------------------------------------
# Tests for FrameFamilyResult dataclass.
# ---------------------------------------------------------------------------


class TestFrameFamilyResult:
    def test_frozen(self):
        result = FrameFamilyResult(family_class="Test", confidence=2, method="test-method")
        with pytest.raises(AttributeError):
            result.family_class = "Changed"

    def test_fields(self):
        result = FrameFamilyResult(family_class="", confidence=0, method="")
        assert result.family_class == ""
        assert result.confidence == 0
        assert result.method == ""
