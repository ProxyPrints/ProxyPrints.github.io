"""
Tests for cardpicker.resolution_tier_probe (T1/T2, docs/features/catalog-completion-plan.md's
"STAGE B RESOLUTION DECISION") - no network calls: fetch_card_image is mocked exactly like
test_harvest_probe.py mocks the same function. Asserts per-tier bookkeeping, OCR match-rate
aggregation, and Hamming-distance computation - not real network/OCR/phash values.
"""

import pytest

import cardpicker.resolution_tier_probe as module
from cardpicker.local_identify_printing_tags import EngineVote, OcrCardResult
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory


class TestRunResolutionTierProbe:
    def test_no_cards_available_returns_empty_result(self, db):
        result = module.run_resolution_tier_probe(sample_size=5)
        assert result.attempted == 0
        assert result.per_card == []

    def test_unfetchable_at_every_tier_records_no_outcomes_fetched(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = module.run_resolution_tier_probe(sample_size=1)

        assert result.attempted == 1
        card_probe = result.per_card[0]
        assert set(card_probe.outcomes.keys()) == set(module.RESOLUTION_TIERS.keys())
        assert all(not outcome.fetched for outcome in card_probe.outcomes.values())

    def test_fetches_and_probes_every_configured_tier(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        requested_dpis: list[object] = []

        def fake_fetch(card, dpi=None):
            requested_dpis.append(dpi)
            return object()

        monkeypatch.setattr(module, "fetch_card_image", fake_fetch)
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

        monkeypatch.setattr(module, "local_phash", _FakeLocalPhash())

        result = module.run_resolution_tier_probe(sample_size=1)

        assert requested_dpis == list(module.RESOLUTION_TIERS.values())
        card_probe = result.per_card[0]
        assert set(card_probe.outcomes.keys()) == set(module.RESOLUTION_TIERS.keys())
        for outcome in card_probe.outcomes.values():
            assert outcome.fetched is True
            assert outcome.ocr_matched is True
            assert outcome.phash == 123

    def test_ocr_skip_reason_recorded_on_no_match(self, db, monkeypatch):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, **kw: OcrCardResult(skip_reason="no-text"),
        )
        monkeypatch.setattr(module, "classify_bleed_edge", lambda image: None)

        class _FakeLocalPhash:
            @staticmethod
            def compute_card_art_hash(image, bleed_class=None):
                return 1

        monkeypatch.setattr(module, "local_phash", _FakeLocalPhash())

        result = module.run_resolution_tier_probe(sample_size=1)

        outcome = result.per_card[0].outcomes[module.NATIVE_TIER]
        assert outcome.ocr_matched is False
        assert outcome.ocr_skip_reason == "no-text"


class TestOcrMatchRate:
    def test_match_rate_only_counts_fetched_outcomes(self, db):
        result = module.ResolutionTierProbeResult(sample_size=2)
        result.per_card = [
            module.CardTierProbe(card_id=1, outcomes={"native": module.TierOutcome(fetched=True, ocr_matched=True)}),
            module.CardTierProbe(card_id=2, outcomes={"native": module.TierOutcome(fetched=True, ocr_matched=False)}),
        ]
        assert result.ocr_match_rate("native") == pytest.approx(0.5)

    def test_match_rate_ignores_unfetched_cards(self, db):
        result = module.ResolutionTierProbeResult(sample_size=2)
        result.per_card = [
            module.CardTierProbe(card_id=1, outcomes={"native": module.TierOutcome(fetched=True, ocr_matched=True)}),
            module.CardTierProbe(card_id=2, outcomes={"native": module.TierOutcome(fetched=False)}),
        ]
        assert result.ocr_match_rate("native") == pytest.approx(1.0)

    def test_zero_fetched_returns_zero_not_a_division_error(self, db):
        result = module.ResolutionTierProbeResult(sample_size=1)
        result.per_card = [module.CardTierProbe(card_id=1, outcomes={"native": module.TierOutcome(fetched=False)})]
        assert result.ocr_match_rate("native") == 0.0


class TestHammingDistancesVs:
    def test_computes_distance_between_two_tiers(self, db):
        # 0b...0000 vs 0b...0011 differ in 2 bits.
        result = module.ResolutionTierProbeResult(sample_size=1)
        result.per_card = [
            module.CardTierProbe(
                card_id=1,
                outcomes={
                    "native": module.TierOutcome(fetched=True, phash=0),
                    "800px": module.TierOutcome(fetched=True, phash=3),
                },
            )
        ]
        distances = result.hamming_distances_vs("800px", "native")
        assert distances == [2]

    def test_skips_cards_missing_either_tier(self, db):
        result = module.ResolutionTierProbeResult(sample_size=2)
        result.per_card = [
            module.CardTierProbe(
                card_id=1,
                outcomes={
                    "native": module.TierOutcome(fetched=True, phash=0),
                    "800px": module.TierOutcome(fetched=True, phash=0),
                },
            ),
            module.CardTierProbe(card_id=2, outcomes={"native": module.TierOutcome(fetched=False, phash=None)}),
        ]
        distances = result.hamming_distances_vs("800px", "native")
        assert distances == [0]

    def test_empty_when_no_comparable_pairs(self, db):
        result = module.ResolutionTierProbeResult(sample_size=1)
        result.per_card = [module.CardTierProbe(card_id=1, outcomes={})]
        assert result.hamming_distances_vs("800px", "native") == []


class TestConfiguredTiers:
    def test_native_tier_requests_no_dpi_param(self):
        assert module.RESOLUTION_TIERS[module.NATIVE_TIER] is None

    def test_calibration_baseline_matches_default_fetch_dpi(self):
        from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI

        assert module.RESOLUTION_TIERS[module.CALIBRATION_BASELINE_TIER] == DEFAULT_FETCH_DPI

    def test_800px_tier_matches_shipped_ocr_fetch_dpi(self):
        from cardpicker.local_lands_identify import OCR_FETCH_DPI

        assert module.RESOLUTION_TIERS["800px"] == OCR_FETCH_DPI
