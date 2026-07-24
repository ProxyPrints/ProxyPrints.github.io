"""
Tests for cardpicker.local_lands_identify (docs/features/catalog-completion-plan.md's Part 4,
HOLD #B) - artist-decomposed identification for names whose candidate count blocks the normal
phash engine. No network calls: fetch_card_image/run_ocr_for_card/detect_illus_anchor are
mocked exactly like test_local_residual_classify.py mocks the same functions.

Evidence-first data source (issue #359): TestCurrentEvidenceForCard/TestOcrResultFromEvidence
cover the two new pure helpers directly; TestRunLandsIdentifyEvidenceFirst covers the orchestrator
branching (evidence-backed cards never call fetch_card_image/run_ocr_for_card/detect_illus_anchor
at all); TestEvidenceFirstAndFetchFallbackProduceIdenticalVerdicts is the explicit "same verdict
regardless of data source" fixture the issue asks for.
"""

import pytest

import cardpicker.local_lands_identify as module
from cardpicker import local_ocr
from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
    OCR_CONFIDENCE_BOTH,
    OCR_CONFIDENCE_COLLECTOR_ONLY,
    PHASH_MAX_CANDIDATES,
    CandidateNameIndex,
    EngineVote,
    OcrCardResult,
    SelectedCard,
)
from cardpicker.local_lands_identify import (
    BASIC_LAND_NAMES,
    LANDS_ANONYMOUS_ID,
    LANDS_SINGLETON_CONFIDENCE,
    LANDS_TIEBREAK_CONFIDENCE,
    identify_land_printing,
    is_lands_target,
    run_lands_identify,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    LandsAmbiguousResidue,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    ImageEvidenceFactory,
    SourceFactory,
)

# See test_local_identify_printing_tags.py's identical fixture for the full rationale -
# factory.Sequence counters are process-global across the whole pytest run.
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


class TestIsLandsTarget:
    def test_basic_land_name_is_a_target_regardless_of_candidate_count(self):
        assert is_lands_target("Plains", 1) is True
        assert is_lands_target("Snow-Covered Forest", 1) is True

    def test_over_cap_name_is_a_target_regardless_of_being_a_basic_land(self):
        assert is_lands_target("Lightning Bolt", PHASH_MAX_CANDIDATES + 1) is True

    def test_ordinary_under_cap_non_land_name_is_not_a_target(self):
        assert is_lands_target("Lightning Bolt", PHASH_MAX_CANDIDATES) is False

    def test_all_eleven_basic_land_names_present(self):
        assert BASIC_LAND_NAMES == {
            "Plains",
            "Island",
            "Swamp",
            "Mountain",
            "Forest",
            "Wastes",
            "Snow-Covered Plains",
            "Snow-Covered Island",
            "Snow-Covered Swamp",
            "Snow-Covered Mountain",
            "Snow-Covered Forest",
        }


class TestIdentifyLandPrinting:
    def test_no_artist_extracted_skips_before_any_query(self, db):
        card = CardFactory(name="Forest", content_phash=1)
        selected = SelectedCard(card=card, candidates=[])
        printing_pk, confidence, reason, matched, distances = identify_land_printing(selected, artist_name=None)
        assert (printing_pk, confidence, reason, matched, distances) == (None, None, "no-artist-extracted", None, None)

    def test_singleton_artist_match_with_confirming_phash_gets_singleton_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        printing = CanonicalCardFactory(name="Forest", artist=artist, image_hash=42)
        card = CardFactory(name="Forest", content_phash=42)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched, distances = identify_land_printing(
            selected, artist_name="Rebecca Guay"
        )

        assert printing_pk == printing.pk
        assert confidence == LANDS_SINGLETON_CONFIDENCE
        assert reason == ""
        assert matched == frozenset({printing.pk})
        assert distances == {printing.pk: 0}

    def test_singleton_artist_match_but_bad_phash_distance_does_not_get_singleton_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=1)
        card = CardFactory(name="Forest", content_phash=-1)  # maximally far, per local_phash's twos-complement range
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched, distances = identify_land_printing(
            selected, artist_name="Rebecca Guay"
        )

        assert printing_pk is None
        assert confidence is None
        assert reason.startswith("phash-")
        assert matched is not None  # artist match itself still succeeded and is reported
        assert distances is not None and len(distances) == 1  # ambiguous residue's own input

    def test_multi_candidate_artist_match_with_clear_phash_winner_gets_tiebreak_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        winner = CanonicalCardFactory(name="Forest", artist=artist, image_hash=100)
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=100_000_000)
        card = CardFactory(name="Forest", content_phash=100)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched, distances = identify_land_printing(
            selected, artist_name="Rebecca Guay"
        )

        assert printing_pk == winner.pk
        assert confidence == LANDS_TIEBREAK_CONFIDENCE
        assert len(matched) == 2
        assert distances is not None and len(distances) == 2

    def test_artist_name_matching_nothing_in_this_names_own_candidates_is_no_match(self, db):
        CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=CanonicalArtistFactory(name="Someone Else"))
        card = CardFactory(name="Forest", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched, distances = identify_land_printing(
            selected, artist_name="Rebecca Guay"
        )

        assert (printing_pk, confidence, reason, matched, distances) == (
            None,
            None,
            "artist-no-match",
            None,
            None,
        )

    def test_no_content_phash_still_reports_the_artist_match(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=1)
        card = CardFactory(name="Forest", content_phash=None)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched, distances = identify_land_printing(
            selected, artist_name="Rebecca Guay"
        )

        assert (printing_pk, confidence, reason) == (None, None, "no-content-phash")
        assert matched is not None
        assert distances is None  # no card hash to compare against yet


class TestSplitNewVotes:
    """Direct unit coverage for the issue #408 pre-write guard, independent of the full
    run_lands_identify orchestration."""

    def test_empty_batch_returns_empty(self, db):
        assert module._split_new_votes([]) == ([], 0)

    def test_no_pre_existing_votes_keeps_everything(self, db):
        card = CardFactory(name="Plains")
        printing = CanonicalCardFactory(name="Plains")
        vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing.pk, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )

        new_votes, already_voted = module._split_new_votes([vote])

        assert new_votes == [vote]
        assert already_voted == 0

    def test_identical_existing_triple_is_skipped(self, db):
        card = CardFactory(name="Plains")
        printing = CanonicalCardFactory(name="Plains")
        CardPrintingTag.objects.create(
            card=card, printing=printing, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )
        vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing.pk, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )

        new_votes, already_voted = module._split_new_votes([vote])

        assert new_votes == []
        assert already_voted == 1

    def test_a_vote_under_a_different_identity_for_the_same_card_and_printing_is_not_skipped(self, db):
        """A pre-existing vote from a DIFFERENT anonymous_id (e.g. LANDS_ANONYMOUS_ID) never
        collides with the uniqueness constraint (card, printing, anonymous_id) and must not be
        treated as a collision here."""
        card = CardFactory(name="Plains")
        printing = CanonicalCardFactory(name="Plains")
        CardPrintingTag.objects.create(
            card=card, printing=printing, anonymous_id=LANDS_ANONYMOUS_ID, source=VoteSource.OCR
        )
        vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing.pk, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )

        new_votes, already_voted = module._split_new_votes([vote])

        assert new_votes == [vote]
        assert already_voted == 0

    def test_mixed_batch_skips_only_the_colliding_vote(self, db):
        collided_card = CardFactory(name="Plains")
        clean_card = CardFactory(name="Plains")
        printing = CanonicalCardFactory(name="Plains")
        CardPrintingTag.objects.create(
            card=collided_card, printing=printing, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )
        colliding_vote = CardPrintingTag(
            card_id=collided_card.pk, printing_id=printing.pk, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )
        clean_vote = CardPrintingTag(
            card_id=clean_card.pk, printing_id=printing.pk, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )

        new_votes, already_voted = module._split_new_votes([colliding_vote, clean_vote])

        assert new_votes == [clean_vote]
        assert already_voted == 1


class TestRunLandsIdentify:
    def test_fetch_budget_zero_still_reports_pool_size_and_candidate_counts_with_no_fetches(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        def _unexpected_fetch(card, dpi=None):
            raise AssertionError("fetch_card_image should never be called at fetch_budget=0")

        monkeypatch.setattr(module, "fetch_card_image", _unexpected_fetch)

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=0)

        assert result.land_pool_size == 1
        assert result.per_name_candidate_counts["Plains"] == 1
        # fetch_attempted (real network calls made) is 0, distinct from sampled (how many cards
        # were selected into the sample slice before hitting the budget wall) - the latter is 1
        # here since sample_size=300 comfortably covers the single-card pool.
        assert result.fetch_attempted == 0
        assert result.sampled == 1

    def test_ocr_resolving_a_land_card_casts_a_normal_ocr_vote_not_a_lands_vote(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, **kw: OcrCardResult(
                vote=EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.95, detail="")
            ),
        )

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        assert result.ocr_resolved == 1
        assert result.votes_written == 1
        assert CardPrintingTag.objects.get().anonymous_id == OCR_ANONYMOUS_ID

    def test_ocr_resolved_vote_colliding_with_an_existing_identical_vote_is_skipped_not_crashed(self, db, monkeypatch):
        """Regression for issue #408 (run 20260724T021229-15c88eba): the OCR-resolved branch casts
        votes under OCR_ANONYMOUS_ID, an identity `_land_pool_selected_cards`'s own eligibility
        query never checks (it's scoped to LANDS_ANONYMOUS_ID) - so a card can legitimately still
        be selected into this pool while an earlier pass/pilot run already cast an identical
        (card, printing, OCR_ANONYMOUS_ID) vote. That agreement must be a no-op, not an
        IntegrityError that aborts the whole batch: the pre-existing vote is skipped and counted
        in `already_voted`, and every OTHER vote computed in the same run still commits."""
        printing = CanonicalCardFactory(name="Plains")
        collided_card = CardFactory(name="Plains")
        CardPrintingTag.objects.create(
            card=collided_card,
            printing=printing,
            anonymous_id=OCR_ANONYMOUS_ID,
            source=VoteSource.OCR,
            confidence=0.9,
        )
        clean_card = CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, **kw: OcrCardResult(
                vote=EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.95, detail="")
            ),
        )

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        # the computation itself is unaffected by the collision - both cards genuinely resolved.
        assert result.ocr_resolved == 2
        assert result.already_voted == 1
        assert result.votes_written == 1
        # no duplicate landed, no IntegrityError raised, and the pre-existing row is untouched.
        assert CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID).count() == 2
        assert CardPrintingTag.objects.get(card=clean_card).printing_id == printing.pk

    def test_fetch_budget_exhaustion_stops_the_pipeline_not_the_pool_count(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")
        CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (False, None))

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=1)

        assert result.land_pool_size == 2
        assert result.fetch_attempted == 1
        assert any(o.skip_reason == "fetch-budget-exhausted" for o in result.outcomes)

    def test_singleton_lands_vote_written_under_write_mode(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        printing = CanonicalCardFactory(name="Plains", artist=artist, image_hash=7)
        card = CardFactory(name="Plains", content_phash=7)

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (True, "Rebecca Guay"))

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        assert result.singleton_votes == 1
        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get()
        assert vote.card_id == card.pk
        assert vote.printing_id == printing.pk
        assert vote.anonymous_id == LANDS_ANONYMOUS_ID
        assert vote.confidence == LANDS_SINGLETON_CONFIDENCE

    def test_ambiguous_phash_persists_residue_row_under_write_mode(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        far = CanonicalCardFactory(name="Plains", artist=artist, image_hash=1)
        card = CardFactory(name="Plains", content_phash=-1)  # maximally far, per local_phash's twos-complement range

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (True, "Rebecca Guay"))

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        assert result.ambiguous_phash == 1
        assert result.votes_written == 0  # no vote - this is routing data, not a vote
        assert result.residue_written == 1
        residue = LandsAmbiguousResidue.objects.get()
        assert residue.card_id == card.pk
        assert residue.artist_name == "Rebecca Guay"
        assert residue.candidate_pks == [far.pk]
        assert str(far.pk) in residue.phash_distances

    def test_ambiguous_phash_writes_no_residue_row_under_dry_run(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Plains", artist=artist, image_hash=1)
        CardFactory(name="Plains", content_phash=-1)  # maximally far, per local_phash's twos-complement range

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (True, "Rebecca Guay"))

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=10)

        assert result.ambiguous_phash == 1
        assert result.residue_written == 0
        assert LandsAmbiguousResidue.objects.count() == 0

    def test_fetch_uses_the_s800_ocr_tier_not_the_full_dpi_default(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")
        captured_dpi = []

        def _capture_dpi(card, dpi=None):
            captured_dpi.append(dpi)
            return object()

        monkeypatch.setattr(module, "fetch_card_image", _capture_dpi)
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (False, None))

        run_lands_identify(dry_run=True, sample_size=300, fetch_budget=10)

        assert captured_dpi == [module.OCR_FETCH_DPI]
        assert module.OCR_FETCH_DPI != 250  # not the print-quality DEFAULT_FETCH_DPI

    def test_dry_run_writes_nothing(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Plains", artist=artist, image_hash=7)
        CardFactory(name="Plains", content_phash=7)

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (True, "Rebecca Guay"))

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=10)

        assert result.singleton_votes == 1
        assert result.votes_written == 0
        assert CardPrintingTag.objects.count() == 0

    def test_idempotent_via_scan_log_row(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        card = CardFactory(name="Plains")
        CardScanLog.objects.create(card=card, anonymous_id=LANDS_ANONYMOUS_ID, skip_reason="artist-no-match")

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=0)

        assert result.land_pool_size == 0


def _evidence(card, **overrides):
    """Same shape as test_local_calculate_verdicts.py's own `_evidence` helper - a CURRENT
    ImageEvidence row (content_hash matching the card's own content_phash) carrying both
    extractor groups `_current_evidence_for_card` requires by default."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1", "artist_ocr": "artist-ocr-v1"},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        artist_ocr_raw_text="",
        artist_ocr_name="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestCurrentEvidenceForCard:
    """Unit tests for the module docstring's CURRENCY check (issue #359)."""

    def test_no_content_phash_never_matches(self, db):
        card = CardFactory(name="Plains", content_phash=None)
        _evidence(card, content_hash=0)

        assert module._current_evidence_for_card(card) is None

    def test_mismatched_content_hash_is_not_current(self, db):
        card = CardFactory(name="Plains", content_phash=5)
        _evidence(card, content_hash=999)  # a prior image version, since superseded

        assert module._current_evidence_for_card(card) is None

    def test_missing_artist_ocr_extractor_key_is_not_current(self, db):
        card = CardFactory(name="Plains", content_phash=5)
        _evidence(card, content_hash=5, extractor_versions={"collector_line_ocr": "v1"})

        assert module._current_evidence_for_card(card) is None

    def test_missing_collector_line_ocr_extractor_key_is_not_current(self, db):
        card = CardFactory(name="Plains", content_phash=5)
        _evidence(card, content_hash=5, extractor_versions={"artist_ocr": "v1"})

        assert module._current_evidence_for_card(card) is None

    def test_matching_hash_with_both_extractor_keys_is_current(self, db):
        card = CardFactory(name="Plains", content_phash=5)
        evidence = _evidence(card, content_hash=5)

        assert module._current_evidence_for_card(card) == evidence


class TestOcrResultFromEvidence:
    """Unit tests for `_ocr_result_from_evidence` - the evidence-first replacement for step 1
    (`run_ocr_for_card`), reusing `local_ocr.validate_against_candidates` unmodified."""

    def test_direct_set_and_number_match_casts_the_both_confidence_tier(self, db):
        expansion = CanonicalExpansionFactory(code="lea")
        printing = CanonicalCardFactory(name="Plains", expansion=expansion, collector_number="288")
        card = CardFactory(name="Plains", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Plains"))
        evidence = _evidence(
            card,
            content_hash=1,
            collector_line_raw_text="288/264 LEA EN",
            collector_line_set_code="lea",
            collector_line_collector_number="288",
        )

        result = module._ocr_result_from_evidence(evidence, selected)

        assert result.vote is not None
        assert result.vote.printing_pk == printing.pk
        assert result.vote.confidence == OCR_CONFIDENCE_BOTH

    def test_collector_number_only_match_casts_the_collector_only_confidence_tier(self, db):
        printing = CanonicalCardFactory(name="Plains", collector_number="288")
        card = CardFactory(name="Plains", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Plains"))
        evidence = _evidence(
            card,
            content_hash=1,
            collector_line_raw_text="288",
            collector_line_set_code="",
            collector_line_collector_number="288",
        )

        result = module._ocr_result_from_evidence(evidence, selected)

        assert result.vote is not None
        assert result.vote.printing_pk == printing.pk
        assert result.vote.confidence == OCR_CONFIDENCE_COLLECTOR_ONLY

    def test_ambiguous_collector_number_yields_ambiguous_skip_reason_not_a_vote(self, db):
        CanonicalCardFactory(name="Plains", collector_number="288")
        CanonicalCardFactory(name="Plains", collector_number="288")
        card = CardFactory(name="Plains", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Plains"))
        evidence = _evidence(card, content_hash=1, collector_line_set_code="", collector_line_collector_number="288")

        result = module._ocr_result_from_evidence(evidence, selected)

        assert result.vote is None
        assert result.skip_reason == "ambiguous"

    def test_parsed_but_no_match_is_reported_as_such(self, db):
        CanonicalCardFactory(name="Plains", collector_number="1")
        card = CardFactory(name="Plains", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Plains"))
        evidence = _evidence(card, content_hash=1, collector_line_set_code="", collector_line_collector_number="999")

        result = module._ocr_result_from_evidence(evidence, selected)

        assert result.vote is None
        assert result.skip_reason == "parsed-but-no-match"

    def test_no_stored_collector_number_is_no_text(self, db):
        CanonicalCardFactory(name="Plains")
        card = CardFactory(name="Plains", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Plains"))
        evidence = _evidence(card, content_hash=1)  # collector_line_collector_number left blank

        result = module._ocr_result_from_evidence(evidence, selected)

        assert result.vote is None
        assert result.skip_reason == "no-text"


class TestRunLandsIdentifyEvidenceFirst:
    """Orchestrator-level coverage for the evidence-first branch (issue #359) - an evidence-
    backed card must never touch fetch_card_image/run_ocr_for_card/detect_illus_anchor, and must
    never count against fetch_attempted/fetch_budget."""

    def test_evidence_backed_ocr_resolve_never_fetches(self, db, monkeypatch):
        expansion = CanonicalExpansionFactory(code="lea")
        printing = CanonicalCardFactory(name="Plains", expansion=expansion, collector_number="288")
        card = CardFactory(name="Plains", content_phash=1)
        _evidence(
            card,
            content_hash=1,
            collector_line_raw_text="288/264 LEA EN",
            collector_line_set_code="lea",
            collector_line_collector_number="288",
        )

        def _unexpected_fetch(c, dpi=None):
            raise AssertionError("evidence-backed card should never call fetch_card_image")

        def _unexpected_ocr(selected, image, **kw):
            raise AssertionError("evidence-backed card should never call run_ocr_for_card")

        def _unexpected_artist(image, raw_texts):
            raise AssertionError("evidence-backed card should never call detect_illus_anchor")

        monkeypatch.setattr(module, "fetch_card_image", _unexpected_fetch)
        monkeypatch.setattr(module, "run_ocr_for_card", _unexpected_ocr)
        monkeypatch.setattr(module, "detect_illus_anchor", _unexpected_artist)

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=0)

        assert result.evidence_backed == 1
        assert result.fetch_attempted == 0
        assert result.ocr_resolved == 1
        vote = CardPrintingTag.objects.get()
        assert vote.printing_id == printing.pk
        assert vote.anonymous_id == OCR_ANONYMOUS_ID
        outcome = result.outcomes[0]
        assert outcome.evidence_backed is True
        assert outcome.fetched is False

    def test_evidence_backed_artist_singleton_never_fetches(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        printing = CanonicalCardFactory(name="Plains", artist=artist, image_hash=7)
        card = CardFactory(name="Plains", content_phash=7)
        _evidence(card, content_hash=7, artist_ocr_name="Rebecca Guay")

        def _unexpected_fetch(c, dpi=None):
            raise AssertionError("evidence-backed card should never call fetch_card_image")

        monkeypatch.setattr(module, "fetch_card_image", _unexpected_fetch)

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=0)

        assert result.evidence_backed == 1
        assert result.fetch_attempted == 0
        assert result.singleton_votes == 1
        vote = CardPrintingTag.objects.get()
        assert vote.printing_id == printing.pk
        assert vote.anonymous_id == LANDS_ANONYMOUS_ID
        assert vote.confidence == LANDS_SINGLETON_CONFIDENCE

    def test_evidence_backed_cards_do_not_count_against_fetch_budget(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Plains", artist=artist, image_hash=7)
        evidence_card = CardFactory(name="Plains", content_phash=7)
        _evidence(evidence_card, content_hash=7, artist_ocr_name="Rebecca Guay")
        fetch_card = CardFactory(name="Plains", content_phash=None)

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (False, None))

        # fetch_budget=0: the evidence-backed card still resolves fully (free), the non-evidence
        # card hits the budget wall - proves the two populations are counted independently.
        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=0)

        assert result.evidence_backed == 1
        assert result.fetch_attempted == 0
        outcomes_by_card = {o.card_id: o for o in result.outcomes}
        assert outcomes_by_card[evidence_card.pk].skip_reason != "fetch-budget-exhausted"
        assert outcomes_by_card[fetch_card.pk].skip_reason == "fetch-budget-exhausted"

    def test_stale_evidence_content_hash_falls_back_to_live_fetch(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        card = CardFactory(name="Plains", content_phash=1)
        _evidence(card, content_hash=999)  # a prior image version, since superseded

        fetched = []
        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: fetched.append(c.pk) or object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (False, None))

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=10)

        assert result.evidence_backed == 0
        assert result.fetch_attempted == 1
        assert fetched == [card.pk]

    def test_evidence_missing_a_required_extractor_key_falls_back_to_live_fetch(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        card = CardFactory(name="Plains", content_phash=1)
        _evidence(card, content_hash=1, extractor_versions={"collector_line_ocr": "v1"})  # no artist_ocr

        fetched = []
        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: fetched.append(c.pk) or object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (False, None))

        result = run_lands_identify(dry_run=True, sample_size=300, fetch_budget=10)

        assert result.evidence_backed == 0
        assert result.fetch_attempted == 1
        assert fetched == [card.pk]


class TestEvidenceFirstAndFetchFallbackProduceIdenticalVerdicts:
    """issue #359's explicit ask: the SAME underlying signal (a collector-line read, or an artist
    credit), fed through the evidence-first path vs the live-fetch fallback path, must produce
    byte-identical outcomes - proving the data-source swap is behavior-neutral, not just that each
    path works in isolation."""

    def test_ocr_direct_match_is_identical_via_both_paths(self, db, monkeypatch):
        expansion = CanonicalExpansionFactory(code="lea")
        printing = CanonicalCardFactory(name="Plains", expansion=expansion, collector_number="288")
        evidence_card = CardFactory(name="Plains", content_phash=1)
        fetch_card = CardFactory(name="Plains", content_phash=None)
        _evidence(
            evidence_card,
            content_hash=1,
            collector_line_raw_text="288/264 LEA EN",
            collector_line_set_code="lea",
            collector_line_collector_number="288",
        )

        def fake_run_ocr_for_card(selected, image, **kw):
            # A real live OCR pass that happens to read the IDENTICAL text the stored evidence
            # above already carries - same input, live channel instead of stored, run through the
            # same validate_against_candidates the evidence-first path itself uses internally.
            parsed = local_ocr.OcrParseResult(raw_text="288/264 LEA EN", set_code="lea", collector_number="288")
            matched, _reason = local_ocr.validate_against_candidates(parsed, selected.candidates)
            assert matched is not None
            return OcrCardResult(
                vote=EngineVote(engine="ocr", printing_pk=matched.pk, confidence=OCR_CONFIDENCE_BOTH, detail="")
            )

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", fake_run_ocr_for_card)

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        votes = {v.card_id: v for v in CardPrintingTag.objects.all()}
        assert votes[evidence_card.pk].printing_id == votes[fetch_card.pk].printing_id == printing.pk
        assert votes[evidence_card.pk].confidence == votes[fetch_card.pk].confidence == OCR_CONFIDENCE_BOTH
        assert votes[evidence_card.pk].anonymous_id == votes[fetch_card.pk].anonymous_id == OCR_ANONYMOUS_ID

        outcomes_by_card = {o.card_id: o for o in result.outcomes}
        assert outcomes_by_card[evidence_card.pk].evidence_backed is True
        assert outcomes_by_card[evidence_card.pk].fetched is False
        assert outcomes_by_card[fetch_card.pk].evidence_backed is False
        assert outcomes_by_card[fetch_card.pk].fetched is True
        assert (
            outcomes_by_card[evidence_card.pk].ocr_resolved_pk
            == outcomes_by_card[fetch_card.pk].ocr_resolved_pk
            == printing.pk
        )

    def test_artist_singleton_match_is_identical_via_both_paths(self, db, monkeypatch):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        printing = CanonicalCardFactory(name="Plains", artist=artist, image_hash=7)
        evidence_card = CardFactory(name="Plains", content_phash=7)
        fetch_card = CardFactory(name="Plains", content_phash=7)
        _evidence(evidence_card, content_hash=7, artist_ocr_name="Rebecca Guay")

        monkeypatch.setattr(module, "fetch_card_image", lambda c, dpi=None: object())
        monkeypatch.setattr(module, "run_ocr_for_card", lambda selected, image, **kw: OcrCardResult())
        monkeypatch.setattr(module, "detect_illus_anchor", lambda image, raw_texts: (True, "Rebecca Guay"))

        result = run_lands_identify(dry_run=False, sample_size=300, fetch_budget=10)

        votes = {v.card_id: v for v in CardPrintingTag.objects.all()}
        assert votes[evidence_card.pk].printing_id == votes[fetch_card.pk].printing_id == printing.pk
        assert votes[evidence_card.pk].confidence == votes[fetch_card.pk].confidence == LANDS_SINGLETON_CONFIDENCE
        assert votes[evidence_card.pk].anonymous_id == votes[fetch_card.pk].anonymous_id == LANDS_ANONYMOUS_ID

        outcomes_by_card = {o.card_id: o for o in result.outcomes}
        assert outcomes_by_card[evidence_card.pk].evidence_backed is True
        assert outcomes_by_card[fetch_card.pk].evidence_backed is False
