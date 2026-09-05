"""
Tests for the pass-2 fallback engine (docs/features/printing-tags.md's Stage 8) - old-border
frame handling (no collector line, no discriminating phash art match against reprints), and
the standalone border-attribute-vote side effect. No network calls, and no real tesseract
binary required - CI's environment doesn't have one installed, so every test that exercises
`detect_illus_anchor`'s crop/OCR fallback path mocks `local_ocr.run_tesseract` with the exact
text it would extract from the synthetic image being drawn, rather than trusting the real
binary to read rendered text accurately (that accuracy is what
`TestOcrLiveTesseractIntegration`-style skipif-guarded tests are for, not this module). Set-
symbol rendering uses the real vendored keyrune font (a local file, not a mock target) since
it's pure local asset loading, no different in kind from the raw Pillow calls elsewhere in
this suite.
"""

import pytest
from PIL import Image, ImageDraw

import cardpicker.local_ocr as local_ocr
from cardpicker.attribute_tags import seed_attribute_tags
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_fallback import (
    _BORDER_SAMPLE_BANDS_MM,
    BLEED_ASPECT_RATIO,
    BLEED_EDGE_TAG_NAME,
    BORDER_COLOR_TO_TAG,
    FALLBACK_ANONYMOUS_ID,
    MIN_USABLE_BAND_PX,
    TRIM_ASPECT_RATIO,
    cast_bleed_edge_vote,
    cast_border_attribute_vote,
    cast_frame_style_vote,
    classify_bleed_edge,
    classify_border_color,
    classify_frame_mismatch_direction,
    classify_frame_style,
    extract_artist_name,
    filter_by_border_color,
    frame_style_is_consistent,
    match_artist,
    project_mm_box_to_fractions,
    render_set_symbol,
    run_fallback_for_card,
)
from cardpicker.local_identify_printing_tags import CandidatePrinting, SelectedCard
from cardpicker.models import Tag, VotePolarity, VoteSource
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    TagFactory,
)


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

    @staticmethod
    def _image_with_sparse_text_bands(noisy_bands, base_rgb=(5, 5, 5), text_rgb=(250, 250, 250)) -> Image.Image:
        """A card whose border reads `base_rgb` everywhere except `noisy_bands` (a subset of
        {"left", "right", "top", "bottom"}), which carry a sparse (~1-in-7) `text_rgb` overlay -
        real-content-in-a-band, but weighted like actual text on a border (mean stays close to
        `base_rgb`; population std climbs well past `_BORDER_UNIFORMITY_STD_THRESHOLD`) rather
        than the full random noise `test_borderless_when_edges_are_noisy_content` uses, which
        would swing the pooled colour average unrecognisably far from `base_rgb` and so could
        not isolate "is this band judged uniform" from "what colour does this card read as"."""
        width, height = 750, 1050
        img = Image.new("RGB", (width, height), base_rgb)
        draw = ImageDraw.Draw(img)
        draw.rectangle([60, 60, 690, 990], fill=(120, 80, 200))
        pixels = img.load()
        for name in noisy_bands:
            box = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM[name], img)
            assert box is not None, f"{name} band did not project on the 750x1050 fixture"
            left, top, right, bottom = (
                int(box[0] * width),
                int(box[1] * height),
                int(box[2] * width),
                int(box[3] * height),
            )
            i = 0
            for y in range(top, bottom):
                for x in range(left, right):
                    if i % 7 == 0:
                        pixels[x, y] = text_rgb
                    i += 1
        return img

    def test_non_uniform_sides_with_uniform_top_still_names_a_colour(self):
        """issue #830 defect 2: an extended-art-shaped card - real content (not a painted
        border) at the left/right edges, but a genuine uniform border at the top - must still
        get a colour reading. The old pooled-uniformity test measured this exact shape
        misreading as 'borderless' on 20 of 30 confirmed extended-art images."""
        img = self._image_with_sparse_text_bands(noisy_bands=("left", "right"))
        assert classify_border_color(img) == "black"

    def test_non_uniform_sides_and_top_reads_borderless(self):
        img = self._image_with_sparse_text_bands(noisy_bands=("left", "right", "top"))
        assert classify_border_color(img) == "borderless"

    def test_bottom_band_variance_never_affects_the_uniformity_decision(self):
        """The bottom band is excluded from the per-band uniformity gate entirely (it carries
        the collector line on every real card, regardless of border colour) - real content
        there alone must not flip an otherwise clean border to 'borderless', nor visibly move
        the reported colour (its mean still folds into the colour average unchanged, matching
        the old pooled implementation's own behaviour on an ordinary framed card)."""
        img = self._image_with_sparse_text_bands(noisy_bands=("bottom",))
        assert classify_border_color(img) == "black"

    def test_asymmetric_padding_around_black_border_reads_black(self):
        """issue #735: a card image with ASYMMETRIC white canvas padding on a non-standard
        canvas (850x1000, aspect ratio 0.85 — far from trim 0.716 and bleed 0.735).  The
        non-standard aspect ratio causes _derive_bleed_mm to return None, which activates
        the card_rect gate in classify_border_color.  The card's own border is black.
        Without re-anchoring, band sampling would land in the white padding and return None
        (no bands sample successfully).  With the fix, bands are projected through the
        measured card rectangle and correctly read 'black'."""
        canvas_w, canvas_h = 850, 1000
        img = Image.new("RGB", (canvas_w, canvas_h), (250, 250, 250))
        card_l, card_t = 100, 50
        card_r, card_b = 750, 950
        draw = ImageDraw.Draw(img)
        draw.rectangle([card_l, card_t, card_r, card_b], fill=(5, 5, 5))
        border_px = 25
        draw.rectangle(
            [card_l + border_px, card_t + border_px, card_r - border_px, card_b - border_px],
            fill=(120, 80, 200),
        )
        assert classify_border_color(img) == "black"


class TestProjectMmBoxToFractions:
    """issue #830 defect 1: the mm-relative band projection. `_BORDER_SAMPLE_BANDS_MM`'s own
    bands, converted, must not collapse below `MIN_USABLE_BAND_PX` on a trim-exact image at
    production resolutions - the regression this whole mechanism exists to prevent (see
    `project_mm_box_to_fractions`'s own docstring)."""

    @staticmethod
    def _trim_exact_image(dpi: int) -> Image.Image:
        # 63mm x 88mm at `dpi` - a genuinely trim-exact (no bleed margin) synthetic image,
        # the worst case for band collapse (see this PR's own report for the bleed-inclusive
        # numbers at the same two DPIs).
        width = round(63.0 / 25.4 * dpi)
        height = round(88.0 / 25.4 * dpi)
        return Image.new("RGB", (width, height), (5, 5, 5))

    @pytest.mark.parametrize("dpi", [250, 460])
    @pytest.mark.parametrize("band_name", ["left", "right", "top", "bottom"])
    def test_band_does_not_collapse_on_a_trim_exact_image(self, dpi, band_name):
        img = self._trim_exact_image(dpi)
        width, height = img.size
        box = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM[band_name], img)
        assert box is not None, f"{band_name} band refused to project at {dpi} DPI trim-exact"
        left, top, right, bottom = box
        assert int(right * width) - int(left * width) >= MIN_USABLE_BAND_PX
        assert int(bottom * height) - int(top * height) >= MIN_USABLE_BAND_PX

    def test_refuses_a_box_thinner_than_the_usable_floor(self):
        """A degenerate mm box (both edges effectively the same coordinate) must refuse rather
        than silently return a sub-pixel band - the exact failure this mechanism exists to
        prevent, proven directly rather than only via the non-collapse cases above."""
        img = self._trim_exact_image(250)
        degenerate_top_band = (7.2275, 0.0, 55.7725, 0.001)
        assert project_mm_box_to_fractions(degenerate_top_band, img) is None

    def test_card_rect_maps_band_through_measured_rectangle(self):
        """issue #735: when card_rect is provided, mm coordinates map linearly through the
        measured card rectangle rather than through an aspect-ratio derivation. A 750x1050
        image with card_rect=(0.10, 0.08, 0.90, 0.92) should place the left band at 10%
        + left_mm/63*80% of the width."""
        img = Image.new("RGB", (750, 1050), (5, 5, 5))
        card_rect = (0.10, 0.08, 0.90, 0.92)
        mm_box = _BORDER_SAMPLE_BANDS_MM["left"]
        box = project_mm_box_to_fractions(mm_box, img, card_rect=card_rect)
        assert box is not None
        cr_left, cr_top, cr_right, cr_bottom = card_rect
        expected_left = cr_left + (mm_box[0] / 63.0) * (cr_right - cr_left)
        expected_right = cr_left + (mm_box[2] / 63.0) * (cr_right - cr_left)
        assert abs(box[0] - expected_left) < 1e-9
        assert abs(box[2] - expected_right) < 1e-9

    def test_card_rect_none_falls_back_to_bleed_derivation(self):
        img = self._trim_exact_image(250)
        box_with_rect = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM["top"], img, card_rect=None)
        assert box_with_rect is not None

    def test_card_rect_degenerate_returns_none(self):
        img = Image.new("RGB", (750, 1050), (5, 5, 5))
        degenerate_rect = (0.5, 0.5, 0.3, 0.9)
        assert project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM["top"], img, card_rect=degenerate_rect) is None


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

    def test_taxonomy_key_set_is_exactly_the_v1_border_classes(self):
        """KEYS ONLY - this asserts nothing about which tag each colour maps TO. Despite its
        previous name (`test_every_taxonomy_color_maps_to_a_real_tag_name`) it never checked
        that the values were real tag names, let alone the right ones; the two tests below are
        what do that. Kept as its own case because the key set is `classify_border_color`'s
        closed output space and several call sites branch on membership in it."""
        assert set(BORDER_COLOR_TO_TAG.keys()) == {"black", "white", "silver", "borderless"}

    def test_each_taxonomy_color_maps_to_its_own_correct_tag(self):
        """THE MAPPING ITSELF, pinned to literals - the only assertion in the repo that a
        black-bordered card is voted "Black Border" and not something else.

        Written out rather than derived on purpose: every other test of this table either
        iterates it to build its own fixture and then compares the verdict against that same
        table (`test_local_layout_class_cast.py`'s two round-trip cases), or happens to pin one
        pair incidentally. Swapping two values here is a silent, catalogue-wide mislabelling -
        ~139k black-bordered rows would be voted "White Border" - and before this test the
        `white` and `silver` entries had no assertion anywhere in the suite at all.
        """
        assert BORDER_COLOR_TO_TAG == {
            "black": "Black Border",
            "white": "White Border",
            "silver": "Silver Border",
            "borderless": "Borderless",
        }

    def test_every_taxonomy_tag_name_exists_after_the_real_seed_commands_run(self, db):
        """The "is a REAL Tag name" half: each value must be a row one of the two seed commands
        this project actually ships creates. `run_layout_class_cast` hard-raises on a missing
        tag and `cast_border_attribute_vote` degrades to casting nothing, so a value that no
        seeder produces silently disables border voting rather than failing loudly at deploy."""
        seed_default_tags()
        seed_attribute_tags()
        seeded = set(Tag.objects.values_list("name", flat=True))
        missing = sorted(set(BORDER_COLOR_TO_TAG.values()) - seeded)
        assert not missing, f"BORDER_COLOR_TO_TAG values with no seeder: {missing}"


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

    def test_border_plus_artist_agree_narrows_to_one_candidate(self, db, monkeypatch):
        monkeypatch.setattr(local_ocr, "run_tesseract", lambda image: "Illus. Marie Magny")
        selected, printing_a, printing_b = self._make_selected()
        image = self._black_bordered_image_with_artist_text("Marie Magny")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.printing_pk == printing_a.pk
        assert "border" in outcome.evidence_types_used
        assert outcome.skip_reason == ""

    def test_border_and_artist_contradict_eliminates_everything(self, db, monkeypatch):
        monkeypatch.setattr(local_ocr, "run_tesseract", lambda image: "Illus. Zephyr Okonkwo")
        selected, printing_a, printing_b = self._make_selected()
        # black border (matches printing_a) but artist text names printing_b's artist
        image = self._black_bordered_image_with_artist_text("Zephyr Okonkwo")

        outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])

        assert outcome.printing_pk is None
        assert outcome.skip_reason == "eliminated"

    def test_no_evidence_at_all_is_a_distinct_skip_reason(self, db, monkeypatch):
        monkeypatch.setattr(local_ocr, "run_tesseract", lambda image: "")
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

    def test_illus_anchor_fired_is_tracked_independent_of_artist_match_success(self, db, monkeypatch):
        monkeypatch.setattr(local_ocr, "run_tesseract", lambda image: "Illus. A Totally Unrelated Person")
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


class TestClassifyFrameMismatchDirection:
    def test_agrees_with_frame_style_is_consistent_on_every_consistent_case(self):
        for frame_class, printing_frame_value in [
            (None, "1993"),
            ("modern", None),
            ("modern", ""),
            ("modern", "future"),
            ("old", "1993"),
            ("old", "1997"),
            ("modern", "2003"),
            ("modern", "2015"),
        ]:
            assert classify_frame_mismatch_direction(frame_class, printing_frame_value) is None
            assert frame_style_is_consistent(frame_class, printing_frame_value) is True

    def test_pre_2003_printing_rendered_in_a_modern_template(self):
        assert classify_frame_mismatch_direction("modern", "1993") == ("modern", "old")

    def test_modern_printing_rendered_in_a_retro_template(self):
        assert classify_frame_mismatch_direction("old", "2015") == ("old", "modern")


class TestClassifyBleedEdge:
    def test_trim_ratio_classifies_as_trimmed(self):
        image = Image.new("RGB", (716, 1000), "white")  # 716/1000 ~= 63/88
        assert classify_bleed_edge(image) == "trimmed"

    def test_bleed_ratio_classifies_as_bleed(self):
        image = Image.new("RGB", (735, 1000), "white")  # 735/1000 ~= BLEED_ASPECT_RATIO
        assert classify_bleed_edge(image) == "bleed"

    def test_far_from_both_references_is_ambiguous(self):
        image = Image.new("RGB", (1000, 1000), "white")  # square - nowhere near either ratio
        assert classify_bleed_edge(image) is None

    def test_exact_reference_ratios_round_trip(self):
        # exact float ratios (not the rounded pixel approximations above) must still classify
        # correctly - guards against an off-by-epsilon tolerance bug
        trim_image = Image.new("RGB", (int(TRIM_ASPECT_RATIO * 10000), 10000), "white")
        bleed_image = Image.new("RGB", (int(BLEED_ASPECT_RATIO * 10000), 10000), "white")
        assert classify_bleed_edge(trim_image) == "trimmed"
        assert classify_bleed_edge(bleed_image) == "bleed"


class TestCastBleedEdgeVote:
    """Negative-only (2026-07-16, consolidated respec item 4b, supersedes the original
    both-directions design): a vote is cast ONLY for 'trimmed' - 'bleed' casts nothing at all,
    regardless of whether the tag exists, since absence of a vote IS the "normal bleed" signal."""

    def test_no_reading_casts_nothing(self, db):
        card = CardFactory()
        assert cast_bleed_edge_vote(card, None) is None

    def test_bleed_reading_casts_nothing_even_with_the_tag_seeded(self, db):
        TagFactory(name=BLEED_EDGE_TAG_NAME)
        card = CardFactory()
        assert cast_bleed_edge_vote(card, "bleed") is None

    def test_unseeded_tag_degrades_trimmed_to_no_vote(self, db):
        card = CardFactory()
        assert cast_bleed_edge_vote(card, "trimmed") is None

    def test_trimmed_casts_a_negative_vote_on_the_existing_tag(self, db):
        TagFactory(name=BLEED_EDGE_TAG_NAME)
        card = CardFactory()
        vote = cast_bleed_edge_vote(card, "trimmed")
        assert vote is not None
        assert vote.pk is None
        assert vote.tag.name == BLEED_EDGE_TAG_NAME
        assert vote.polarity == VotePolarity.NOT_APPLICABLE
        assert vote.anonymous_id == FALLBACK_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == 0.7
