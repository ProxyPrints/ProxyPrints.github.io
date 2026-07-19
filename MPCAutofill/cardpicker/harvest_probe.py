"""
Stage A instrumented probe (harvest-calculate pipeline commission, 2026-07-19 - see
docs/features/catalog-completion-plan.md). Wall-clock split for fetch/OCR/phash/DB across a
small real sample - the baseline every later Stage B fetch-economics/topology claim must be
checked against, not assumed (the commission's own R2/Google/Scryfall rate figures are starting
values to confirm or adjust, not gospel).

Read-only against votes: the DB-write timing sample is a real `bulk_create()` wrapped in a
savepoint that is always rolled back, matching Stage D's own eventual writer shape (a batched
INSERT) without ever persisting anything from a mere measurement run.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from django.db import transaction

from cardpicker import local_phash
from cardpicker.image_cdn_fetch import fetch_card_image
from cardpicker.local_fallback import classify_bleed_edge
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    SelectedCard,
    run_ocr_for_card,
)
from cardpicker.models import CanonicalCard, Card, CardPrintingTag, CardTypes


@dataclass
class StageTimings:
    card_id: int
    fetch_seconds: float = 0.0
    ocr_seconds: float = 0.0
    phash_seconds: float = 0.0
    db_seconds: float = 0.0
    fetched: bool = False


@dataclass
class ProbeResult:
    sample_size: int = 0
    attempted: int = 0
    fetched: int = 0
    per_card: list[StageTimings] = field(default_factory=list)

    def _stage_total(self, attr: str) -> float:
        return sum(getattr(t, attr) for t in self.per_card)

    @property
    def totals(self) -> dict[str, float]:
        return {
            "fetch": self._stage_total("fetch_seconds"),
            "ocr": self._stage_total("ocr_seconds"),
            "phash": self._stage_total("phash_seconds"),
            "db": self._stage_total("db_seconds"),
        }

    @property
    def percentages(self) -> dict[str, float]:
        totals = self.totals
        grand_total = sum(totals.values())
        if grand_total == 0:
            return {stage: 0.0 for stage in totals}
        return {stage: (value / grand_total) * 100 for stage, value in totals.items()}


def _select_probe_sample(sample_size: int) -> list[SelectedCard]:
    """No idempotence/exclusion semantics needed for a one-off measurement probe (unlike
    _eligible_base_queryset, which exists for resumable-engine bookkeeping this doesn't need) -
    a plain random sample of resolvable-name cards is representative enough for a wall-clock
    baseline. Oversamples 3x since not every name has real candidates."""
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


def _time_db_write_probe(card: Card, printing_pk: Optional[int]) -> float:
    """Real INSERT timing via bulk_create, inside a savepoint that is always rolled back - never
    persists anything. Representative of Stage D/E's eventual batched writer, not a live vote."""
    start = time.monotonic()
    with transaction.atomic():
        sid = transaction.savepoint()
        CardPrintingTag.objects.bulk_create(
            [
                CardPrintingTag(
                    card=card,
                    printing_id=printing_pk,
                    is_no_match=printing_pk is None,
                    anonymous_id="harvest-probe-v1",
                    run_id="stage-a-probe",
                )
            ]
        )
        transaction.savepoint_rollback(sid)
    return time.monotonic() - start


def run_stage_a_probe(sample_size: int = 30) -> ProbeResult:
    """Pure measurement: fetches real images (real network cost against the shared image-cdn
    limiter - the commission itself accepts this fetch cost for Stage A), runs OCR and the full
    phash prep (card hash + every candidate's cached/computed hash) exactly as the real pipeline
    would, and times a representative (rolled-back) DB write. No votes/residue are ever
    persisted."""
    result = ProbeResult(sample_size=sample_size)
    selected_cards = _select_probe_sample(sample_size)
    result.attempted = len(selected_cards)

    for selected in selected_cards:
        card = selected.card
        timing = StageTimings(card_id=card.pk)

        t0 = time.monotonic()
        image = fetch_card_image(card)
        timing.fetch_seconds = time.monotonic() - t0
        timing.fetched = image is not None

        if image is not None:
            result.fetched += 1

            t0 = time.monotonic()
            run_ocr_for_card(selected, image)
            timing.ocr_seconds = time.monotonic() - t0

            t0 = time.monotonic()
            bleed_class = classify_bleed_edge(image)
            local_phash.compute_card_art_hash(image, bleed_class)
            canonicals_by_pk = {
                c.pk: c for c in CanonicalCard.objects.filter(pk__in=[c.pk for c in selected.candidates])
            }
            for candidate in selected.candidates:
                canonical = canonicals_by_pk.get(candidate.pk)
                if canonical is not None:
                    local_phash.get_or_compute_canonical_hash(canonical)
            timing.phash_seconds = time.monotonic() - t0

            probe_printing_pk = selected.candidates[0].pk if selected.candidates else None
            timing.db_seconds = _time_db_write_probe(card, probe_printing_pk)

        result.per_card.append(timing)

    return result
