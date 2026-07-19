"""
T1/T2 resolution-tier probe (owner directive 2026-07-19, "STAGE B RESOLUTION DECISION" -
docs/features/catalog-completion-plan.md's "Harvest-calculate pipeline" section). Gates any
change to the fetch tier a future R2-cached harvest tier would use: T1 measures real OCR
accuracy at each candidate resolution (not interpolated from the RESOLUTION_FLOOR_DPI sweep), T2
measures phash Hamming-distance drift against the SAME "full resolution" baseline every existing
phash calibration in this project actually used - confirmed directly against
docs/features/printing-tags.md's "Phash accuracy at small CDN sizes" section ("hashed at full
res (250dpi/~925px)"), NOT literal native resolution, which is a distinct, higher baseline
(dpi=None -> no h= param sent to Google's lh4 endpoint at all, confirmed against
image-cdn/src/url.ts + GoogleDriveService.ts). Both baselines are probed here so the report can
state plainly which one the harvest-tier candidate should be compared against, rather than
assuming the two coincide.

DPI tiers (height = dpi * 1110 / 300, image-cdn/src/url.ts):
- "native": dpi=None, Google's own stored original - no resize directive sent at all.
- "1200px": dpi=320 -> 1184px (nearest-10 dpi at/above the literal ~1200px target the owner
  named for a prospective harvest tier).
- "925px": dpi=250 (image_cdn_fetch.DEFAULT_FETCH_DPI) - the resolution every phash calibration
  doc in this project actually means by "full resolution", not a new value invented here.
- "800px": dpi=220 (local_lands_identify.OCR_FETCH_DPI) - already shipped, already used in
  production for Part 4's LANDS OCR pass.
"""

from dataclasses import dataclass, field
from typing import Optional

from cardpicker import local_phash
from cardpicker.image_cdn_fetch import fetch_card_image
from cardpicker.local_fallback import classify_bleed_edge
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    SelectedCard,
    run_ocr_for_card,
)
from cardpicker.local_phash import _int_to_hash
from cardpicker.models import Card, CardTypes

RESOLUTION_TIERS: dict[str, Optional[int]] = {
    "native": None,
    "1200px": 320,
    "925px": 250,
    "800px": 220,
}

# The literal native fetch - the highest-resolution reference available, used for T1's own
# "how far down can we go" framing.
NATIVE_TIER = "native"

# What every existing phash calibration doc in this project actually means by "full resolution"
# (see module docstring) - T2's real comparison baseline, distinct from NATIVE_TIER.
CALIBRATION_BASELINE_TIER = "925px"


@dataclass
class TierOutcome:
    fetched: bool = False
    ocr_matched: bool = False
    ocr_skip_reason: str = ""
    phash: Optional[int] = None


@dataclass
class CardTierProbe:
    card_id: int
    outcomes: dict[str, TierOutcome] = field(default_factory=dict)


@dataclass
class ResolutionTierProbeResult:
    sample_size: int = 0
    attempted: int = 0
    per_card: list[CardTierProbe] = field(default_factory=list)

    def ocr_match_rate(self, tier: str) -> float:
        fetched = [c for c in self.per_card if c.outcomes.get(tier, TierOutcome()).fetched]
        if not fetched:
            return 0.0
        matched = sum(1 for c in fetched if c.outcomes[tier].ocr_matched)
        return matched / len(fetched)

    def hamming_distances_vs(self, tier: str, reference_tier: str) -> list[int]:
        """Per-card Hamming distance between `tier`'s phash and `reference_tier`'s phash for the
        same card - only over cards where both tiers produced a hash. Empty list is a legitimate
        result (e.g. reference_tier == tier, or nothing fetched at either tier)."""
        distances = []
        for card in self.per_card:
            tier_outcome = card.outcomes.get(tier)
            ref_outcome = card.outcomes.get(reference_tier)
            if (
                tier_outcome is not None
                and ref_outcome is not None
                and tier_outcome.phash is not None
                and ref_outcome.phash is not None
            ):
                distances.append(_int_to_hash(tier_outcome.phash) - _int_to_hash(ref_outcome.phash))
        return distances


def _select_probe_sample(sample_size: int) -> list[SelectedCard]:
    # Same selection shape as harvest_probe._select_probe_sample - duplicated rather than
    # imported since that function is private to Stage A's own wall-clock probe, and this
    # probe's purpose (resolution-tier comparison, not timing) is distinct enough to warrant its
    # own copy rather than an oddly-named cross-module dependency.
    index = CandidateNameIndex()
    selected: list[SelectedCard] = []
    candidate_cards = Card.objects.filter(card_type=CardTypes.CARD).order_by("?")[: sample_size * 3]
    for card in candidate_cards:
        candidates = index.candidates_for(card.name)
        if not candidates:
            continue
        selected.append(SelectedCard(card=card, candidates=candidates))
        if len(selected) >= sample_size:
            break
    return selected


def run_resolution_tier_probe(sample_size: int = 50) -> ResolutionTierProbeResult:
    """T1+T2 combined: for each sampled card, fetches at every configured resolution tier
    (RESOLUTION_TIERS) and, per tier, runs the real OCR validation path (T1) and computes the
    real art-crop phash (T2) - the exact same functions the live pipeline uses, just re-run at
    each tier's resolution. No votes are ever persisted (OCR's own validation path here never
    writes anything; the phash computed is the CARD's own art-crop hash, never saved anywhere -
    distinct from get_or_compute_canonical_hash's CanonicalCard-side persistence, which this
    probe does not call)."""
    result = ResolutionTierProbeResult(sample_size=sample_size)
    selected_cards = _select_probe_sample(sample_size)
    result.attempted = len(selected_cards)

    for selected in selected_cards:
        card = selected.card
        card_probe = CardTierProbe(card_id=card.pk)

        for tier_name, dpi in RESOLUTION_TIERS.items():
            outcome = TierOutcome()
            image = fetch_card_image(card, dpi=dpi)
            outcome.fetched = image is not None

            if image is not None:
                ocr_result = run_ocr_for_card(selected, image)
                outcome.ocr_matched = ocr_result.vote is not None
                outcome.ocr_skip_reason = ocr_result.skip_reason

                bleed_class = classify_bleed_edge(image)
                outcome.phash = local_phash.compute_card_art_hash(image, bleed_class)

            card_probe.outcomes[tier_name] = outcome

        result.per_card.append(card_probe)

    return result


__all__ = [
    "RESOLUTION_TIERS",
    "NATIVE_TIER",
    "CALIBRATION_BASELINE_TIER",
    "TierOutcome",
    "CardTierProbe",
    "ResolutionTierProbeResult",
    "run_resolution_tier_probe",
]
