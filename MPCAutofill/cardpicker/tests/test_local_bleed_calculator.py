"""
Tests for cardpicker.local_bleed_calculator: Method A (closed-form aspect ratio) recovery from
stored `bleed_diff_mm`, Method B (pinline ruler) per-edge derivation and its abstain-flag
honouring, the cross-method disagreement gate, and the batch runner's negative-only
`appropriate-bleed` casting. No network calls, no live image fetch - consumes stored
`ImageEvidence`/`CanonicalPrintingMetadata` rows only, same "host venv, no network" precedent
`test_local_layout_class_cast.py` already establishes for this pipeline family.
"""

import pytest

from cardpicker.attribute_tags import seed_attribute_tags
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_bleed_calculator import (
    BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON,
    BLEED_CALC_NOT_TRIMMED_SKIP_REASON,
    BLEED_CALCULATOR_CAST_ANONYMOUS_ID,
    BLEED_MARGIN_MM,
    METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM,
    calculate_bleed_verdict,
    run_bleed_calculator_cast,
)
from cardpicker.local_fallback import (
    BLEED_ASPECT_RATIO,
    BLEED_EDGE_TAG_NAME,
    FALLBACK_CONFIDENCE_MULTI_EVIDENCE,
    FALLBACK_CONFIDENCE_SINGLE_EVIDENCE,
    TRIM_ASPECT_RATIO,
    compute_bleed_diff_mm,
)
from cardpicker.local_pinline_inset import CALL_MEASURED
from cardpicker.models import CardTagVote, VotePolarity
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    ImageEvidenceFactory,
)

_COMPLETE_EXTRACTOR_VERSIONS = {"geometry_bleed": "geometry-bleed-v1"}
_WITH_PINLINE_EXTRACTOR_VERSIONS = {**_COMPLETE_EXTRACTOR_VERSIONS, "pinline_inset": "pinline-inset-v1"}


class _FakeImage:
    def __init__(self, width: int, height: int):
        self.size = (width, height)


def _bleed_diff_mm_for_aspect(aspect_ratio: float, height: int = 1040) -> float:
    width = round(height * aspect_ratio)
    return compute_bleed_diff_mm(_FakeImage(width, height))


def _trim_exact_evidence(card, **overrides):
    """A synthetic upload whose own pixel aspect ratio is exactly the trim ratio (0mm bleed)."""
    height = 1040
    width = round(height * TRIM_ASPECT_RATIO)
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        width=width,
        height=height,
        bleed_class="trimmed",
        bleed_diff_mm=_bleed_diff_mm_for_aspect(TRIM_ASPECT_RATIO, height),
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def _standard_bleed_evidence(card, **overrides):
    """A synthetic upload at the standard ~3.175mm MPC bleed aspect ratio."""
    height = 1040
    width = round(height * BLEED_ASPECT_RATIO)
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        width=width,
        height=height,
        bleed_class="bleed",
        bleed_diff_mm=_bleed_diff_mm_for_aspect(BLEED_ASPECT_RATIO, height),
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestCalculateBleedVerdictMethodA:
    def test_trim_exact_card_yields_near_zero_bleed_and_casts_a_vote(self, db):
        card = CardFactory(name="Trimmed Upload")
        evidence = _trim_exact_evidence(card)

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_a_mm is not None
        assert abs(verdict.method_a_mm) < 0.1
        assert verdict.is_hit is True
        assert verdict.tag_name == BLEED_EDGE_TAG_NAME
        assert verdict.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE  # Method A alone here

    def test_standard_bleed_card_yields_near_3175mm_but_is_not_trimmed(self, db):
        card = CardFactory(name="Standard Bleed Upload")
        evidence = _standard_bleed_evidence(card)

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_a_mm is not None
        assert abs(verdict.method_a_mm - 3.175) < 0.1
        assert verdict.is_hit is False
        assert verdict.skip_reason == BLEED_CALC_NOT_TRIMMED_SKIP_REASON


class TestCalculateBleedVerdictMethodBAndGate:
    def _black_2003_card_with_pinline(self, db, top_extra_mm: float = 0.0):
        """A trim-exact card whose pinline sits exactly `top_extra_mm` beyond where the
        black_2003 calibration constants predict on every edge - `top_extra_mm=0` reproduces
        the true zero-bleed geometry exactly (agrees with Method A); a positive value simulates
        a thicker-than-calibrated printed border (Method B overestimates bleed, Method A does
        not - the module docstring's own disagreement mechanism)."""
        scale_px_per_mm = 10.0
        width, height = 630, 880  # exactly 63mm x 88mm at 10px/mm - trim-exact aspect ratio
        top_const, bottom_const, left_const, right_const = 2.962, 2.962, 2.960, 2.960

        def _frac(const: float, dim_mm: float, dim_px: int) -> float:
            return (const + top_extra_mm) * scale_px_per_mm / dim_px if dim_mm else 0.0

        left_frac = _frac(left_const, 63, width)
        right_frac = _frac(right_const, 63, width)
        top_frac = _frac(top_const, 88, height)
        bottom_frac = _frac(bottom_const, 88, height)

        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card, border_color="black", frame="2003")
        card = CardFactory(name="Pinline Card", canonical_card=canonical_card)
        evidence = ImageEvidenceFactory(
            card=card,
            content_hash=card.content_phash or 0,
            extractor_versions=dict(_WITH_PINLINE_EXTRACTOR_VERSIONS),
            width=width,
            height=height,
            bleed_class="trimmed",
            bleed_diff_mm=_bleed_diff_mm_for_aspect(TRIM_ASPECT_RATIO, height),
            pinline_inset_frac_top=top_frac,
            pinline_inset_frac_bottom=bottom_frac,
            pinline_inset_frac_left=left_frac,
            pinline_inset_frac_right=right_frac,
            pinline_inset_call_top=CALL_MEASURED,
            pinline_inset_call_bottom=CALL_MEASURED,
            pinline_inset_call_left=CALL_MEASURED,
            pinline_inset_call_right=CALL_MEASURED,
        )
        return card, evidence

    def test_both_methods_agree_on_zero_bleed_casts_with_multi_evidence_confidence(self, db):
        card, evidence = self._black_2003_card_with_pinline(db, top_extra_mm=0.0)

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_a_mm is not None and abs(verdict.method_a_mm) < 0.1
        assert verdict.method_b_mean_mm is not None and abs(verdict.method_b_mean_mm) < 0.1
        assert verdict.is_hit is True
        assert verdict.confidence == FALLBACK_CONFIDENCE_MULTI_EVIDENCE

    def test_thick_border_disagreement_past_the_gate_abstains(self, db):
        # A border ~4mm thicker than calibration expects pushes Method B's reading well past
        # METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM away from Method A's aspect-ratio-only zero.
        card, evidence = self._black_2003_card_with_pinline(db, top_extra_mm=4.0)

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_a_mm is not None
        assert verdict.method_b_mean_mm is not None
        assert abs(verdict.method_a_mm - verdict.method_b_mean_mm) > METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM
        assert verdict.is_hit is False
        assert verdict.skip_reason == BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON


class TestCalculateBleedVerdictAbstainFlaggedClass:
    def test_white_2015_is_fully_abstained_and_falls_back_to_method_a_alone(self, db):
        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card, border_color="white", frame="2015")
        card = CardFactory(name="White 2015 Card", canonical_card=canonical_card)
        evidence = _trim_exact_evidence(
            card,
            extractor_versions=dict(_WITH_PINLINE_EXTRACTOR_VERSIONS),
            pinline_inset_frac_top=0.05,
            pinline_inset_frac_bottom=0.05,
            pinline_inset_frac_left=0.05,
            pinline_inset_frac_right=0.05,
            pinline_inset_call_top=CALL_MEASURED,
            pinline_inset_call_bottom=CALL_MEASURED,
            pinline_inset_call_left=CALL_MEASURED,
            pinline_inset_call_right=CALL_MEASURED,
        )

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_b_mean_mm is None
        assert all(v is None for v in verdict.method_b_edges_mm.values())
        assert verdict.is_hit is True
        assert verdict.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE

    def test_borderless_is_structurally_abstained_regardless_of_frame(self, db):
        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card, border_color="borderless", frame="2015")
        card = CardFactory(name="Borderless Card", canonical_card=canonical_card)
        evidence = _trim_exact_evidence(card, extractor_versions=dict(_WITH_PINLINE_EXTRACTOR_VERSIONS))

        verdict = calculate_bleed_verdict(card, evidence)

        assert verdict.method_b_mean_mm is None
        assert verdict.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE


class TestRunBleedCalculatorCast:
    def test_dry_run_counts_without_writing(self, db):
        seed_default_tags()
        seed_attribute_tags()
        seed_sensitive_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _trim_exact_evidence(card)

        result = run_bleed_calculator_cast(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert result.votes_written == 0
        assert CardTagVote.objects.count() == 0

    def test_write_casts_negative_only_vote(self, db):
        seed_default_tags()
        seed_attribute_tags()
        seed_sensitive_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _trim_exact_evidence(card)

        result = run_bleed_calculator_cast(dry_run=False)

        assert result.votes_written == 1
        vote = CardTagVote.objects.get(card=card, anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID)
        assert vote.tag.name == BLEED_EDGE_TAG_NAME
        assert vote.polarity == VotePolarity.NOT_APPLICABLE
        assert vote.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE

    def test_ordinary_bleed_card_casts_no_vote(self, db):
        seed_default_tags()
        seed_attribute_tags()
        seed_sensitive_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _standard_bleed_evidence(card)

        result = run_bleed_calculator_cast(dry_run=False)

        assert result.votes_would_cast == 0
        assert CardTagVote.objects.filter(anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID).count() == 0


class TestCardMeasuredBleedMm:
    """Card.measured_bleed_mm() - the WTC reference-image crop's own read of Method A, via the
    same `_trim_exact_evidence`/`_standard_bleed_evidence` fixtures the verdict tests above use,
    so this can't silently drift from what `calculate_bleed_verdict`'s own method_a_mm reads."""

    def test_trim_exact_card_reads_near_zero_bleed(self, db):
        card = CardFactory(name="Trimmed Upload", content_phash=1)
        _trim_exact_evidence(card)

        assert card.measured_bleed_mm() == pytest.approx(0.0, abs=0.1)

    def test_standard_bleed_card_reads_the_standard_margin(self, db):
        card = CardFactory(name="Standard Upload", content_phash=2)
        _standard_bleed_evidence(card)

        assert card.measured_bleed_mm() == pytest.approx(BLEED_MARGIN_MM, abs=0.1)

    def test_no_current_evidence_reads_none(self, db):
        card = CardFactory(name="No Evidence", content_phash=3)

        assert card.measured_bleed_mm() is None
