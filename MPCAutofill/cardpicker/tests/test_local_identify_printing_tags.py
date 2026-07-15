"""
Tests for the local OCR/phash printing-identification pilot (docs/features/printing-tags.md's
Stage 8). No network calls and no real tesseract binary in CI - both engines' raw outputs
(local_ocr.run_tesseract, local_phash's Scryfall/image fetches) are mocked throughout via
monkeypatch/requests_mock. The one test that exercises the real tesseract binary is guarded
with a skipif so the suite stays green in an environment without it installed (see
docs/features/printing-tags.md's Stage 8 environment section - CI's django image doesn't have
it, only the host venv used for the real pilot run does).
"""

import shutil

import pytest
from PIL import Image, ImageDraw

from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID
from cardpicker.local_identify_printing_tags import (
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    OCR_ANONYMOUS_ID,
    PHASH_ANONYMOUS_ID,
    CandidateNameIndex,
    CandidatePrinting,
    run_pilot,
    select_candidates,
    verify_zero_resolutions,
)
from cardpicker.local_ocr import (
    crop_collector_line,
    parse_collector_line,
    preprocess_variants,
    run_tesseract,
    validate_against_candidates,
)
from cardpicker.local_phash import find_best_match
from cardpicker.models import (
    CardPrintingTag,
    CardTagVote,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
    TagFactory,
)

# see test_deductive_backfill.py's identical fixture for the full rationale
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


class TestSelection:
    def test_excludes_resolved_cards(self, db):
        CardFactory(name="Forest", printing_tag_status=PrintingTagStatus.RESOLVED)
        CanonicalCardFactory(name="Forest")
        assert select_candidates("ocr") == []

    def test_excludes_cards_with_confirmed_indexing_match(self, db):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", canonical_card=printing)
        assert select_candidates("ocr") == []

    def test_excludes_cards_with_no_name_candidate(self, db):
        CardFactory(name="Totally Unmatched Name")
        assert select_candidates("ocr") == []

    def test_includes_card_with_a_name_candidate(self, db):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [card.pk]

    def test_excludes_card_with_existing_vote_from_this_engines_own_anonymous_id(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=OCR_ANONYMOUS_ID)
        assert select_candidates("ocr") == []
        # a different engine's own anonymous_id is unaffected by an OCR vote
        assert [s.card.pk for s in select_candidates("phash")] == [card.pk]

    def test_excludes_card_already_covered_by_deductive_backfill(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
        assert select_candidates("ocr") == []

    def test_excludes_resolved_custom_art_tag(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", tags=["custom-art"])
        assert select_candidates("ocr") == []

    def test_excludes_resolved_non_english_tag(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", tags=["non-english"])
        assert select_candidates("ocr") == []

    def test_multi_candidate_names_come_before_single_candidate_names(self, db):
        CanonicalCardFactory(name="Single Match")
        single = CardFactory(name="Single Match")
        CanonicalCardFactory(name="Multi Match", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Multi Match", expansion=CanonicalExpansionFactory(code="bbb"))
        multi = CardFactory(name="Multi Match")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [multi.pk, single.pk]


class TestCandidateNameIndex:
    def test_groups_by_normalised_name(self, db):
        CanonicalCardFactory(name="Kusari-Gama")
        index = CandidateNameIndex()
        assert len(index.candidates_for("Kusari-Gama (Modern Tomas Giorello)")) == 1


class TestOcrParsing:
    def test_standard_modern_collector_line(self):
        parsed = parse_collector_line("158/287 R MOM EN Some Artist")
        assert parsed.set_code == "mom"
        assert parsed.collector_number == "158"

    def test_pre_m15_has_no_set_code(self):
        # older frames print just the collector number, no set code on the line at all
        parsed = parse_collector_line("158")
        assert parsed.set_code is None
        assert parsed.collector_number == "158"

    def test_letter_suffix_collector_number(self):
        parsed = parse_collector_line("123a/281 M MID EN")
        assert parsed.collector_number == "123a"

    def test_junk_input_parses_to_nothing(self):
        parsed = parse_collector_line("asdf jkl qwerty !!@#")
        assert parsed.set_code is None
        assert parsed.collector_number is None

    def test_empty_string(self):
        parsed = parse_collector_line("")
        assert parsed.set_code is None
        assert parsed.collector_number is None


class TestOcrValidationRail:
    CANDIDATES = [
        CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
        CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
    ]

    def test_no_text_extracted(self):
        parsed = parse_collector_line("")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "no-text"

    def test_set_and_collector_match_exactly_one_candidate(self):
        parsed = parse_collector_line("158/287 R MOM EN")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""

    def test_parsed_but_no_matching_candidate(self):
        parsed = parse_collector_line("999/287 R MOM EN")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "parsed-but-no-match"

    def test_collector_only_ambiguous_across_two_candidates(self):
        # no set code parsed - collector number "158" alone matches both candidates above
        parsed = parse_collector_line("158")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "ambiguous"

    def test_collector_only_matches_when_unambiguous(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        parsed = parse_collector_line("158")
        matched, reason = validate_against_candidates(parsed, candidates)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""


class TestPhashThresholdAndMargin:
    def test_clear_winner_within_threshold_and_margin(self):
        candidate_a = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        candidate_b = CandidatePrinting(pk=2, expansion_code="mom", collector_number="2")
        match, reason = find_best_match(
            card_hash=0,
            candidates_with_hashes=[(candidate_a, 0), (candidate_b, (1 << 40) - 1)],
            distance_threshold=10,
            margin=6,
        )
        assert reason == ""
        assert match is not None
        assert match.candidate.pk == 1

    def test_over_distance_threshold_is_no_clear_winner(self):
        candidate = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        match, reason = find_best_match(
            card_hash=0, candidates_with_hashes=[(candidate, (1 << 20) - 1)], distance_threshold=10, margin=6
        )
        assert match is None
        assert reason == "no-clear-winner"

    def test_runner_up_too_close_is_no_clear_winner(self):
        # best distance 2 (within threshold), but runner-up at distance 4 is only 2 apart -
        # below the margin of 6, so the match isn't clear enough to trust
        candidate_a = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        candidate_b = CandidatePrinting(pk=2, expansion_code="mom", collector_number="2")
        match, reason = find_best_match(
            card_hash=0b11,
            candidates_with_hashes=[(candidate_a, 0), (candidate_b, 0b1111)],
            distance_threshold=10,
            margin=6,
        )
        assert match is None
        assert reason == "no-clear-winner"

    def test_no_hashable_candidates(self):
        match, reason = find_best_match(card_hash=0, candidates_with_hashes=[], distance_threshold=10, margin=6)
        assert match is None
        assert reason == "no-hashable-candidates"


class TestPhashCandidateCap:
    """A name with more candidates than the cap (basic lands/staple commons - 944 candidates
    for Forest alone in the live pilot pool, confirmed 2026-07-15) must never fetch or hash
    anything - the cap is checked before any network call, not just before voting."""

    def test_over_the_cap_skips_without_fetching_anything(self, db, monkeypatch):
        import cardpicker.local_identify_printing_tags as module

        card = CardFactory(name="Forest")
        candidates = [CandidatePrinting(pk=i, expansion_code="aaa", collector_number=str(i)) for i in range(13)]
        selected = module.SelectedCard(card=card, candidates=candidates)

        # passing image=None (rather than a real fetch) doubles as proof the cap is checked
        # before any image is needed at all - if the cap check didn't short-circuit first,
        # this would instead fail differently (compute_card_art_hash on a None image)
        vote, reason = module.run_phash_for_card(selected, None, max_candidates=12)
        assert vote is None
        assert reason == "too-many-candidates"

    def test_at_or_under_the_cap_is_unaffected(self, db, monkeypatch):
        import cardpicker.local_identify_printing_tags as module

        card = CardFactory(name="Forest")
        candidates = [CandidatePrinting(pk=i, expansion_code="aaa", collector_number=str(i)) for i in range(12)]
        selected = module.SelectedCard(card=card, candidates=candidates)

        vote, reason = module.run_phash_for_card(selected, None, max_candidates=12)
        assert vote is None
        assert reason == "unfetchable-image"  # got past the cap check, failed later for an unrelated reason


class TestOcrLiveTesseractIntegration:
    """The one test that exercises the real tesseract binary (see this module's docstring) -
    everything else in this file mocks run_tesseract, since CI's django image doesn't have the
    binary installed (see docs/features/printing-tags.md's Stage 8 environment section)."""

    @pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract-ocr binary not installed")
    def test_crop_preprocess_and_ocr_a_synthetic_collector_line(self):
        # positioned within DEFAULT_CROP_BOX's bottom 90-100% band (945-1050px of a 1050px-tall
        # image) - tuned against a real production card image, see DEFAULT_CROP_BOX's comment
        img = Image.new("RGB", (750, 1050), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 945, 262, 1050], fill="black")
        draw.text((10, 975), "158/287 R MOM EN", fill="white")

        cropped = crop_collector_line(img)
        variants = preprocess_variants(cropped)
        texts = [run_tesseract(v) for v in variants]
        parsed_results = [parse_collector_line(t) for t in texts]
        assert any(p.set_code == "mom" and p.collector_number == "158" for p in parsed_results)


class TestRunPilotAgreementAndDisagreement:
    def test_both_engines_agree_keeps_both_votes(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        def fake_phash(selected, image, threshold, margin, max_candidates):
            return module.EngineVote(engine="phash", printing_pk=printing.pk, confidence=0.8, detail="d=0"), ""

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "run_phash_for_card", fake_phash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card: None)

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert results["phash"].votes_written == 1
        assert results["ocr"].disagreements == []
        from cardpicker.models import CardPrintingTag

        assert CardPrintingTag.objects.filter(card=card, anonymous_id=OCR_ANONYMOUS_ID).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=PHASH_ANONYMOUS_ID).exists()

    def test_both_engines_disagree_writes_neither(self, db, monkeypatch):
        printing_a = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        printing_b = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing_a.pk, confidence=0.85, detail="raw")
            )

        def fake_phash(selected, image, threshold, margin, max_candidates):
            return module.EngineVote(engine="phash", printing_pk=printing_b.pk, confidence=0.8, detail="d=0"), ""

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "run_phash_for_card", fake_phash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card: None)

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 0
        assert results["phash"].votes_written == 0
        assert len(results["ocr"].disagreements) == 1
        assert results["ocr"].disagreements[0]["card_id"] == card.pk
        from cardpicker.models import CardPrintingTag

        assert not CardPrintingTag.objects.filter(card=card).exists()

    def test_dry_run_writes_nothing(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card: None)

        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=True, nice=False)

        assert results["ocr"].votes_written == 1  # counted, even though nothing is persisted
        from cardpicker.models import CardPrintingTag

        assert not CardPrintingTag.objects.exists()

    def test_only_requested_engine_appears_in_results(self, db, monkeypatch):
        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=True, nice=False)
        # "fallback" (pass 2) always gets a result entry - it isn't a selectable --engine, it
        # fires automatically whenever pass 1 (whichever engines were requested) misses
        assert set(results.keys()) == {"ocr", "fallback"}


class TestIdempotence:
    def test_a_card_voted_on_is_excluded_from_the_next_selection(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card: None)
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        # re-running the exact same selection now excludes this card - it already has a vote
        # under OCR_ANONYMOUS_ID
        assert select_candidates("ocr") == []


class TestVerifyZeroResolutions:
    def test_no_violations_when_nothing_resolves(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, anonymous_id=OCR_ANONYMOUS_ID, printing=printing, source=VoteSource.OCR)
        assert verify_zero_resolutions([card.pk]) == []

    def test_detects_a_violation(self, db, monkeypatch):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        # verify_zero_resolutions imports resolve_printing locally inside the function body,
        # so patching cardpicker.printing_consensus.resolve_printing (the module it imports
        # from) before calling it is what a fresh local import picks up.
        import cardpicker.printing_consensus as consensus_module

        monkeypatch.setattr(consensus_module, "resolve_printing", lambda c: "NO_MATCH")
        assert verify_zero_resolutions([card.pk]) == [card.pk]


def _black_bordered_image_with_artist_text(artist_name: str) -> Image:
    img = Image.new("RGB", (750, 1050), (5, 5, 5))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 690, 990], fill=(120, 80, 200))
    draw.text((150, 990), f"Illus. {artist_name}", fill=(255, 255, 255))
    return img


class TestPass2Wiring:
    """Integration coverage for the pass-2 fallback wiring inside run_pilot itself (not just
    local_fallback's own unit tests) - pass 1 mocked to always miss, local_fallback's real
    logic runs against a real (synthetic) image."""

    def test_fallback_fires_and_votes_when_pass_1_misses_entirely(self, db, monkeypatch):
        printing = CanonicalCardFactory(
            name="Forest",
            expansion=CanonicalExpansionFactory(code="aaa"),
            artist=CanonicalArtistFactory(name="Marie Magny"),
        )
        # frame="1993" (old-border class) - the fake image below carries an "Illus. <artist>"
        # credit, which the frame classifier reads as old-border; the printing's own frame must
        # agree, or the CONSISTENCY CHECK correctly withholds the vote as a frame-mismatch (see
        # TestPass2Wiring::test_frame_mismatch_withholds_the_printing_vote below for that path).
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black", frame="1993")
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fake image below has "Illus. Marie Magny" drawn
        # on it, but the crop/OCR fallback inside detect_illus_anchor() must not depend on the
        # real binary reading it accurately; this mirrors what it would extract.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "Illus. Marie Magny")
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, crop_box: module.OcrCardResult())
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(
            module, "fetch_card_image", lambda card: _black_bordered_image_with_artist_text("Marie Magny")
        )

        results, attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["fallback"].votes_written == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, printing=printing).exists()
        assert attributes.border_votes_by_class["black"] == 1
        assert CardTagVote.objects.filter(
            card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, tag__name="Black Border"
        ).exists()

    def test_frame_mismatch_withholds_the_printing_vote(self, db, monkeypatch):
        # OCR "succeeds" (a modern-frame signal: a collector number was parsed), but the
        # matched printing's own frame is old-border (1993) - contradiction, so the vote must
        # be withheld even though pass 1 nominally produced one.
        printing = CanonicalCardFactory(name="Forest")
        CanonicalPrintingMetadataFactory(canonical_card=printing, frame="1993")
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fetched image is blank (no text at all), so a
        # real tesseract read would also find nothing, but the frame classifier's unconditional
        # detect_illus_anchor() call must not depend on the real binary being present to do so.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 0
        assert results["ocr"].skip_counts["frame-mismatch"] == 1
        assert not CardPrintingTag.objects.filter(card=card).exists()
        assert len(attributes.frame_mismatches) == 1
        assert attributes.frame_mismatches[0]["card_id"] == card.pk

    def test_already_fallback_covered_card_is_not_reattempted(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=FALLBACK_ANONYMOUS_ID)

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fail_if_called(selected, image, ocr_raw_texts):
            raise AssertionError("run_fallback_for_card must not run again for an already-covered card")

        monkeypatch.setattr(module.local_fallback, "run_fallback_for_card", fail_if_called)
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, crop_box: module.OcrCardResult())
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card: Image.new("RGB", (750, 1050), (5, 5, 5)))

        # if the assertion inside fail_if_called had fired, this call itself would raise
        run_pilot(engine="both", limit=10, dry_run=False, nice=False)


class TestGroundTruthAttributeVotes:
    """When a printing is confirmed for a card this run, border/frame attribute votes prefer
    ground truth from that printing's own CanonicalPrintingMetadata over the pixel/OCR
    heuristic estimate - see run_pilot's ground-truth-preferred wiring, docs/features/
    printing-tags.md's Stage 8 section."""

    def test_ground_truth_overrides_heuristic_when_printing_confirmed(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="white", frame="2015")
        card = CardFactory(name="Forest")
        TagFactory(name="White Border")
        TagFactory(name="Black Border")
        TagFactory(name="Modern Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fetched image is blank, so this matches what a
        # real read would find anyway; see the identical note on TestPass2Wiring above.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        # a uniform near-black image - the pixel-sample heuristic would read "black" here, but
        # the matched printing's own metadata says "white" and must win instead.
        monkeypatch.setattr(module, "fetch_card_image", lambda card: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert attributes.border_votes_by_class == {"white": 1}
        assert attributes.border_ground_truth_count == 1
        assert CardTagVote.objects.filter(card=card, tag__name="White Border").exists()
        assert not CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()

        # frame: the heuristic (parsed_a_collector_number=True) already reads "modern", which
        # happens to agree with the printing's own frame="2015" -> "modern" - still sourced
        # from (and counted as) ground truth, since that's genuinely where the cast value came
        # from this run.
        assert attributes.frame_votes_by_class == {"modern": 1}
        assert attributes.frame_ground_truth_count == 1
        assert CardTagVote.objects.filter(card=card, tag__name="Modern Border").exists()

    def test_heuristic_used_when_no_printing_confirmed_this_run(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, crop_box: module.OcrCardResult())
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert attributes.border_votes_by_class == {"black": 1}
        assert attributes.border_ground_truth_count == 0
        assert CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()

    def test_heuristic_used_when_confirmed_printing_has_no_usable_metadata(self, db, monkeypatch):
        # a printing that matches but has no CanonicalPrintingMetadata row at all (predates the
        # metadata import - see cardpicker.local_identify_printing_tags module docstring's
        # sibling deductive_backfill's identical nullable-metadata handling)
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert attributes.border_votes_by_class == {"black": 1}
        assert attributes.border_ground_truth_count == 0
        assert CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()
