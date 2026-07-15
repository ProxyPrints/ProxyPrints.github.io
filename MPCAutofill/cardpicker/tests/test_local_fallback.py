"""
Tests for the pass-2 fallback engine (docs/features/printing-tags.md's Stage 8) - old-border
frame handling (no collector line, no discriminating phash art match against reprints), and
the standalone border-attribute-vote side effect. No network calls; set-symbol rendering uses
the real vendored keyrune font (a local file, not a mock target) since it's pure local asset
loading, no different in kind from the raw Pillow calls elsewhere in this suite.
"""

import pytest
from PIL import Image, ImageDraw

from cardpicker.local_fallback import (
    BORDER_COLOR_TO_TAG,
    FALLBACK_ANONYMOUS_ID,
    cast_border_attribute_vote,
    cast_frame_style_vote,
    classify_border_color,
    classify_frame_style,
    extract_artist_name,
    filter_by_border_color,
    frame_style_is_consistent,
    match_artist,
    render_set_symbol,
    run_fallback_for_card,
)
from cardpicker.local_identify_printing_tags import CandidatePrinting, SelectedCard
from cardpicker.models import VotePolarity, VoteSource
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    SourceFactory,
    TagFactory,
)

_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


class TestExtractArtistName:
    def test_standard_illus_prefix(self):
        assert extract_artist_name("Sorcery\nIllus. Marie Magny") == "Marie Magny"

    def test_ocr_misread_prefix_still_matches_llus_anchor(self):
        # "1llus"/"illus" (leading I/l/1 confusion) is tolerated - the anchor is "llus" itself
        assert extract_artist_name("* Illus. Sebastian Giacobino *") == "Sebastian Giacobino"
        assert extract_artist_name("1llus. Some Artist") == "Some Artist"

    def test_no_illus_text_returns_none(self):
        assert extract_artist_name("Sorcery\nDeal 3 damage to any target.") is None

    def test_severely_garbled_prefix_is_not_recovered(self):
        # documents a real limitation found live (2026-07-15): "Illus." OCR'd as "Titus." isn't
        # recoverable by this regex - the vowel-collapse changes the anchor substring itself,
        # not just the leading character
        assert extract_artist_name("Titus. Marie Magny") is None


class TestMatchArtist:
    def test_exact_match(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mir", collector_number="1")]
        result = match_artist("Marie Magny", candidates, {1: "Marie Magny"})
        assert result == {1}

    def test_close_fuzzy_match_within_threshold(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mir", collector_number="1")]
        # a plausible OCR near-miss
        result = match_artist("Marie Magnv", candidates, {1: "Marie Magny"})
        assert result == {1}

    def test_unrelated_name_does_not_match(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mir", collector_number="1")]
        result = match_artist("Totally Different Person", candidates, {1: "Marie Magny"})
        assert result is None

    def test_narrows_to_the_one_candidate_with_matching_artist(self):
        candidates = [
            CandidatePrinting(pk=1, expansion_code="aaa", collector_number="1"),
            CandidatePrinting(pk=2, expansion_code="bbb", collector_number="2"),
        ]
        result = match_artist("Marie Magny", candidates, {1: "Marie Magny", 2: "Someone Else"})
        assert result == {1}

    def test_candidate_with_no_known_artist_is_skipped_not_errored(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mir", collector_number="1")]
        result = match_artist("Marie Magny", candidates, {})
        assert result is None


class TestClassifyBorderColor:
    @staticmethod
    def _uniform_bordered_image(border_rgb, art_rgb=(120, 80, 200)) -> Image.Image:
        img = Image.new("RGB", (750, 1050), border_rgb)
        draw = ImageDraw.Draw(img)
        draw.rectangle([60, 60, 690, 990], fill=art_rgb)
        return img

    def test_black_border(self):
        assert classify_border_color(self._uniform_bordered_image((5, 5, 5))) == "black"

    def test_white_border(self):
        assert classify_border_color(self._uniform_bordered_image((250, 250, 250))) == "white"

    def test_silver_border(self):
        assert classify_border_color(self._uniform_bordered_image((170, 170, 172))) == "silver"

    def test_borderless_when_edges_are_noisy_content(self):
        # simulate art bleeding to the edge: fill the whole image with high-variance noise-like
        # content instead of a uniform border band
        img = Image.new("RGB", (750, 1050))
        pixels = img.load()
        for x in range(0, 750, 3):
            for y in range(0, 1050, 3):
                pixels[x, y] = ((x * 7) % 255, (y * 13) % 255, ((x + y) * 5) % 255)
        assert classify_border_color(img) == "borderless"

    def test_mid_brightness_non_silver_color_is_ambiguous(self):
        # a mid-brightness, high-saturation color (e.g. a colored border) matches none of the
        # four taxonomy buckets - gold/yellow borders are explicitly out of scope for v1 (see
        # docs/features/printing-tags.md's chip taxonomy notes)
        assert classify_border_color(self._uniform_bordered_image((180, 140, 40))) is None


class TestFilterByBorderColor:
    def test_no_reading_filters_nothing(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="aaa", collector_number="1")]
        assert filter_by_border_color(None, candidates, {1: "black"}) is None

    def test_filters_to_matching_candidates(self):
        candidates = [
            CandidatePrinting(pk=1, expansion_code="aaa", collector_number="1"),
            CandidatePrinting(pk=2, expansion_code="bbb", collector_number="2"),
        ]
        result = filter_by_border_color("black", candidates, {1: "black", 2: "white"})
        assert result == {1}

    def test_no_candidates_match_the_sampled_color(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="aaa", collector_number="1")]
        result = filter_by_border_color("silver", candidates, {1: "black"})
        assert result is None


class TestCastBorderAttributeVote:
    def test_ambiguous_sample_casts_nothing(self, db):
        card = CardFactory()
        assert cast_border_attribute_vote(card, None) is None

    def test_seeded_tag_produces_an_unsaved_vote(self, db):
        TagFactory(name="Black Border")
        card = CardFactory()
        vote = cast_border_attribute_vote(card, "black")
        assert vote is not None
        assert vote.pk is None  # unsaved - caller batches via bulk_create
        assert vote.card_id == card.pk
        assert vote.tag.name == "Black Border"
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == FALLBACK_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == 0.75

    def test_unseeded_tag_degrades_to_no_vote(self, db):
        # seed_attribute_tags not run - matches post_report_card's identical graceful-
        # degradation contract for an unseeded sensitive tag
        card = CardFactory()
        assert cast_border_attribute_vote(card, "black") is None

    def test_every_taxonomy_color_maps_to_a_real_tag_name(self):
        assert set(BORDER_COLOR_TO_TAG.keys()) == {"black", "white", "silver", "borderless"}


class TestRenderSetSymbol:
    def test_known_set_code_renders_an_image(self):
        image = render_set_symbol("mir")
        assert image is not None
        assert image.mode == "L"

    def test_unknown_set_code_returns_none(self):
        assert render_set_symbol("zzzzz-not-a-real-set") is None


class TestRunFallbackForCard:
    def _make_selected(self, card_name="Forest"):
        printing_a = CanonicalCardFactory(
            name=card_name,
            expansion=CanonicalExpansionFactory(code="aaa"),
            artist=CanonicalArtistFactory(name="Marie Magny"),
        )
        printing_b = CanonicalCardFactory(
            name=card_name,
            expansion=CanonicalExpansionFactory(code="bbb"),
            artist=CanonicalArtistFactory(name="Zephyr Okonkwo"),
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, border_color="black")
        CanonicalPrintingMetadataFactory(canonical_card=printing_b, border_color="white")
        card = CardFactory(name=card_name)
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="aaa", collector_number=printing_a.collector_number),
            CandidatePrinting(pk=printing_b.pk, expansion_code="bbb", collector_number=printing_b.collector_number),
        ]
        return SelectedCard(card=card, candidates=candidates), printing_a, printing_b

    @staticmethod
    def _black_bordered_image_with_artist_text(artist_name: str) -> Image.Image:
        img = Image.new("RGB", (750, 1050), (5, 5, 5))
        draw = ImageDraw.Draw(img)
        draw.rectangle([60, 60, 690, 990], fill=(120, 80, 200))
        draw.text((150, 990), f"Illus. {artist_name}", fill=(255, 255, 255))
        return img

    def test_border_plus_artist_agree_narrows_to_one_candidate(self, db):
        selected, printing_a, printing_b = self._make_selected()
        image = self._black_bordered_image_with_artist_text("Marie Magny")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.printing_pk == printing_a.pk
        assert "border" in outcome.evidence_types_used
        assert outcome.skip_reason == ""

    def test_border_and_artist_contradict_eliminates_everything(self, db):
        selected, printing_a, printing_b = self._make_selected()
        # black border (matches printing_a) but artist text names printing_b's artist
        image = self._black_bordered_image_with_artist_text("Zephyr Okonkwo")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.printing_pk is None
        assert outcome.skip_reason == "eliminated"

    def test_no_evidence_at_all_is_a_distinct_skip_reason(self, db):
        selected, _, _ = self._make_selected()
        # mid-brightness colored border (ambiguous) + no artist text at all
        image = Image.new("RGB", (750, 1050), (180, 140, 40))

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.printing_pk is None
        assert outcome.skip_reason == "no-evidence"

    def test_ocr_raw_texts_shortcut_avoids_a_redundant_tesseract_call(self, db, monkeypatch):
        import cardpicker.local_ocr as local_ocr_module

        def fail_if_called(image):
            raise AssertionError("run_tesseract must not be called when ocr_raw_texts already had a match")

        monkeypatch.setattr(local_ocr_module, "run_tesseract", fail_if_called)

        selected, printing_a, printing_b = self._make_selected()
        image = self._black_bordered_image_with_artist_text("Marie Magny")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=["Illus. Marie Magny"])

        assert outcome.printing_pk == printing_a.pk

    def test_illus_anchor_fired_is_tracked_independent_of_artist_match_success(self, db):
        selected, printing_a, printing_b = self._make_selected()
        # "Illus." extracts fine, but the named artist matches neither candidate - the anchor
        # still fired even though artist evidence itself produced no usable reading
        image = self._black_bordered_image_with_artist_text("A Totally Unrelated Person")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.illus_anchor_fired is True
        assert "artist" not in outcome.evidence_types_used


class TestClassifyFrameStyle:
    def test_parsed_collector_number_is_modern(self):
        assert classify_frame_style(parsed_a_collector_number=True, illus_anchor_fired=False) == "modern"

    def test_illus_anchor_without_collector_number_is_old(self):
        assert classify_frame_style(parsed_a_collector_number=False, illus_anchor_fired=True) == "old"

    def test_collector_number_takes_priority_over_illus_anchor(self):
        # shouldn't both fire in practice (a modern frame has no "Illus." line), but if they
        # somehow do, the more specific/reliable signal (an actual parsed collector number)
        # wins
        assert classify_frame_style(parsed_a_collector_number=True, illus_anchor_fired=True) == "modern"

    def test_neither_signal_abstains(self):
        assert classify_frame_style(parsed_a_collector_number=False, illus_anchor_fired=False) is None


class TestCastFrameStyleVote:
    def test_no_reading_casts_nothing(self, db):
        card = CardFactory()
        assert cast_frame_style_vote(card, None) is None

    def test_seeded_tag_produces_an_unsaved_vote(self, db):
        TagFactory(name="Old Border")
        card = CardFactory()
        vote = cast_frame_style_vote(card, "old")
        assert vote is not None
        assert vote.pk is None
        assert vote.tag.name == "Old Border"
        assert vote.anonymous_id == FALLBACK_ANONYMOUS_ID
        assert vote.confidence == 0.7

    def test_unseeded_tag_degrades_to_no_vote(self, db):
        card = CardFactory()
        assert cast_frame_style_vote(card, "modern") is None


class TestFrameStyleIsConsistent:
    def test_no_frame_reading_is_always_consistent(self):
        assert frame_style_is_consistent(None, "1993") is True

    def test_no_printing_frame_value_is_always_consistent(self):
        assert frame_style_is_consistent("modern", None) is True
        assert frame_style_is_consistent("modern", "") is True

    def test_unmapped_printing_frame_value_is_treated_as_consistent(self):
        # "future" (Future Frame) has no reachable class from this classifier - an accepted
        # limitation, see module docstring, not a mismatch to flag
        assert frame_style_is_consistent("modern", "future") is True

    def test_agreement(self):
        assert frame_style_is_consistent("old", "1993") is True
        assert frame_style_is_consistent("old", "1997") is True
        assert frame_style_is_consistent("modern", "2003") is True
        assert frame_style_is_consistent("modern", "2015") is True

    def test_disagreement(self):
        assert frame_style_is_consistent("old", "2015") is False
        assert frame_style_is_consistent("modern", "1993") is False
