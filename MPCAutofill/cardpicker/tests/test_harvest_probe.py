"""
Tests for cardpicker.harvest_probe (harvest-calculate pipeline Stage A, docs/features/
catalog-completion-plan.md) - no network calls: fetch_card_image is mocked exactly like
test_local_lands_identify.py mocks the same function. Asserts timing bookkeeping and the
rolled-back DB write, not real wall-clock values (those are meaningless under test).
"""

import pytest

import cardpicker.harvest_probe as module
from cardpicker.local_identify_printing_tags import EngineVote, OcrCardResult
from cardpicker.models import CardPrintingTag
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory


class FakeImage:
    """Stand-in for a PIL Image - real classify_bleed_edge/compute_card_art_hash calls need a
    real Image, so those are mocked too rather than fed this fake (see
    test_probe_runs_all_four_stages_and_rolls_back_the_db_write)."""


class TestRunStageAProbe:
    def test_no_cards_available_returns_empty_result(self, db):
        result = module.run_stage_a_probe(sample_size=5)
        assert result.attempted == 0
        assert result.fetched == 0
        assert result.per_card == []

    def test_unfetchable_image_records_fetch_time_only(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = module.run_stage_a_probe(sample_size=1)

        assert result.attempted == 1
        assert result.fetched == 0
        assert len(result.per_card) == 1
        assert result.per_card[0].fetched is False
        assert result.per_card[0].ocr_seconds == 0.0
        assert result.per_card[0].phash_seconds == 0.0
        assert result.per_card[0].db_seconds == 0.0

    def test_probe_runs_all_four_stages_and_rolls_back_the_db_write(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        fake_image = object()
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: fake_image)
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, **kw: OcrCardResult(
                vote=EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.95, detail="")
            ),
        )
        monkeypatch.setattr(module, "classify_bleed_edge", lambda image: None)

        class _FakeLocalPhash:
            @staticmethod
            def compute_card_art_hash(image, bleed_class=None):
                return 123

            @staticmethod
            def get_or_compute_canonical_hash(canonical):
                return 456

        monkeypatch.setattr(module, "local_phash", _FakeLocalPhash())

        result = module.run_stage_a_probe(sample_size=1)

        assert result.attempted == 1
        assert result.fetched == 1
        timing = result.per_card[0]
        assert timing.fetched is True
        # Real wall-clock values are non-negative, not asserted against a specific magnitude -
        # this test is about which stages ran, not how long they took.
        assert timing.ocr_seconds >= 0.0
        assert timing.phash_seconds >= 0.0
        assert timing.db_seconds >= 0.0

        # The DB write timing sample must never persist - the whole point of the savepoint
        # rollback.
        assert CardPrintingTag.objects.count() == 0

    def test_totals_and_percentages_sum_correctly(self, db):
        result = module.ProbeResult(sample_size=2)
        result.per_card = [
            module.StageTimings(card_id=1, fetch_seconds=1.0, ocr_seconds=1.0, phash_seconds=1.0, db_seconds=1.0),
            module.StageTimings(card_id=2, fetch_seconds=1.0, ocr_seconds=1.0, phash_seconds=1.0, db_seconds=1.0),
        ]
        totals = result.totals
        assert totals == {"fetch": 2.0, "ocr": 2.0, "phash": 2.0, "db": 2.0}
        percentages = result.percentages
        assert sum(percentages.values()) == pytest.approx(100.0)
        assert all(pytest.approx(p) == 25.0 for p in percentages.values())

    def test_percentages_are_zero_not_a_division_error_when_nothing_ran(self, db):
        result = module.ProbeResult(sample_size=1)
        assert result.percentages == {"fetch": 0.0, "ocr": 0.0, "phash": 0.0, "db": 0.0}
