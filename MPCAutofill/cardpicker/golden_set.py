"""
Stage C's golden-set fixture (docs/features/catalog-completion-plan.md, task #145): a fixed,
stratified sample of real card ids that every extractor PR's own tests assert against before
merging - the literal hard gate task #145 requires ("golden-set (~30 known cards, stratified)
passes BEFORE that PR merges").

This module holds ONLY the card-id selection plus a home for each extractor's expected-value
assertions (`GOLDEN_EXPECTATIONS`) - it does not itself assert anything; each extractor's own
test file imports `get_golden_cards()` (or `GOLDEN_CARD_IDS` directly), runs its own extractor
against them, and checks against whatever key it owns in `GOLDEN_EXPECTATIONS`.

Selection is INTENTIONALLY NOT re-randomized per test run - a golden set only works as a
"literal hard gate" if the same 30 cards are checked every time, so a new extractor's PR can
compare its own real-world behaviour against previously-recorded expectations rather than a
different sample each CI run. If a pinned id is ever deleted from the catalog, re-draw a
replacement deliberately (same stratified-by-source method below) rather than silently letting
the set shrink - `get_golden_cards()` raises if any id is missing, specifically so this can't
happen unnoticed.

Per-card ground truth (expected border color, expected OCR text, etc.) is filled in
INCREMENTALLY, one extractor at a time, by whichever PR builds that extractor - this file does
not (and structurally cannot) pre-populate expectations for extractors that don't exist yet.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cardpicker.models import Card

# Pinned 2026-07-19 (task #145's substrate PR), drawn from production via a seeded (20260719),
# stratified-by-Source sample: one card per distinct GOOGLE_DRIVE Source (28 distinct sources,
# explicitly excluding the project's own "WilfordGrimley" source for most of the draw, matching
# the same community-drive-coverage convention the Drive API verification test used), plus 3
# cards from the project's own source for coverage, all filtered to `content_phash__isnull=False`
# (already hashed at ingest - ImageEvidence keys on this hash, see models.py's own docstring).
GOLDEN_CARD_IDS: list[int] = [
    35,
    37,
    40,
    37962,
    39520,
    41039,
    102138,
    128981,
    144933,
    145081,
    145532,
    147855,
    150472,
    159175,
    161020,
    175889,
    189166,
    189921,
    190895,
    193523,
    194684,
    199986,
    200330,
    200668,
    204427,
    207913,
    208337,
    208569,
    214113,
    217783,
]


@dataclass(frozen=True)
class GoldenExpectation:
    """
    One extractor's expected value for one golden card. `value` is deliberately typed loose
    (Any) - each extractor's own test decides how to compare it (exact match, within a
    Hamming-distance margin, membership in a set, etc.).
    """

    card_id: int
    value: Any


# Populated incrementally, one extractor at a time. Key = extractor name (matches
# ImageEvidence.extractor_versions' own keys), value = list of per-card expectations for cards
# in GOLDEN_CARD_IDS that extractor's test actually asserts against - not required to cover all
# 30 (task #145 allows waiving cards per extractor, e.g. a pre-M15-frame case a not-yet-built
# frame-aware extractor doesn't apply to yet).
GOLDEN_EXPECTATIONS: dict[str, list[GoldenExpectation]] = {
    # fetch_health's only real expectation is "the fetch succeeds" - a golden card that starts
    # 404ing would mean the set itself has gone stale (see get_golden_cards()'s own docstring
    # about deliberate replacement), not a fetch_health regression, so this list exists mostly
    # to establish the convention other extractors will follow, not because fetch_health has
    # anything subtle to assert.
    "fetch_health": [GoldenExpectation(card_id=cid, value=True) for cid in GOLDEN_CARD_IDS],
}


def get_golden_cards() -> list["Card"]:
    """
    Returns the golden set's real Card rows, in GOLDEN_CARD_IDS order. Raises if any pinned id
    no longer exists - a silently-shrinking golden set defeats its own purpose as a hard gate.
    """

    from cardpicker.models import Card

    cards = list(Card.objects.filter(pk__in=GOLDEN_CARD_IDS))
    found_ids = {c.pk for c in cards}
    missing = [cid for cid in GOLDEN_CARD_IDS if cid not in found_ids]
    if missing:
        raise ValueError(f"Golden set card ids no longer exist: {missing} - draw a deliberate replacement")
    by_id = {c.pk: c for c in cards}
    return [by_id[cid] for cid in GOLDEN_CARD_IDS]


__all__ = ["GOLDEN_CARD_IDS", "GoldenExpectation", "GOLDEN_EXPECTATIONS", "get_golden_cards"]
