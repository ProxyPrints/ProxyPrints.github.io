"""
Tests for cardpicker.local_lands_identify (docs/features/catalog-completion-plan.md's Part 4,
HOLD #B) - artist-decomposed identification for names whose candidate count blocks the normal
phash engine. No network calls: fetch_card_image/run_ocr_for_card/detect_illus_anchor are
mocked exactly like test_local_residual_classify.py mocks the same functions.
"""

import pytest

import cardpicker.local_lands_identify as module
from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
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
from cardpicker.models import CardPrintingTag, CardScanLog
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
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
        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name=None)
        assert (printing_pk, confidence, reason, matched) == (None, None, "no-artist-extracted", None)

    def test_singleton_artist_match_with_confirming_phash_gets_singleton_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        printing = CanonicalCardFactory(name="Forest", artist=artist, image_hash=42)
        card = CardFactory(name="Forest", content_phash=42)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name="Rebecca Guay")

        assert printing_pk == printing.pk
        assert confidence == LANDS_SINGLETON_CONFIDENCE
        assert reason == ""
        assert matched == frozenset({printing.pk})

    def test_singleton_artist_match_but_bad_phash_distance_does_not_get_singleton_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=1)
        card = CardFactory(name="Forest", content_phash=-1)  # maximally far, per local_phash's twos-complement range
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name="Rebecca Guay")

        assert printing_pk is None
        assert confidence is None
        assert reason.startswith("phash-")
        assert matched is not None  # artist match itself still succeeded and is reported

    def test_multi_candidate_artist_match_with_clear_phash_winner_gets_tiebreak_confidence(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        winner = CanonicalCardFactory(name="Forest", artist=artist, image_hash=100)
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=100_000_000)
        card = CardFactory(name="Forest", content_phash=100)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name="Rebecca Guay")

        assert printing_pk == winner.pk
        assert confidence == LANDS_TIEBREAK_CONFIDENCE
        assert len(matched) == 2

    def test_artist_name_matching_nothing_in_this_names_own_candidates_is_no_match(self, db):
        CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=CanonicalArtistFactory(name="Someone Else"))
        card = CardFactory(name="Forest", content_phash=1)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name="Rebecca Guay")

        assert (printing_pk, confidence, reason, matched) == (None, None, "artist-no-match", None)

    def test_no_content_phash_still_reports_the_artist_match(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalCardFactory(name="Forest", artist=artist, image_hash=1)
        card = CardFactory(name="Forest", content_phash=None)
        index = CandidateNameIndex()
        selected = SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        printing_pk, confidence, reason, matched = identify_land_printing(selected, artist_name="Rebecca Guay")

        assert (printing_pk, confidence, reason) == (None, None, "no-content-phash")
        assert matched is not None


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
