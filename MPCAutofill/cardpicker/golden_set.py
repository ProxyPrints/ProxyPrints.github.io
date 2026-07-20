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
    # geometry_bleed (task #147, recorded 2026-07-19 against a real extract_card_evidence() run
    # over all 30 golden cards at DEFAULT_FETCH_DPI - no persistence, see the task's own
    # VERIFICATION notes for how this was gathered). `value` is only `bleed_class` - the single
    # discrete, stable-under-re-fetch signal worth pinning as a hard gate; `width`/`height`/
    # `aspect_ratio` are real but continuous/DPI-derived and would make this set brittle to pin
    # exactly, so they're intentionally not part of the golden assertion. 27/30 bleed, 3/30
    # trimmed (90%/10%) - a higher trimmed share than the 40-source validation's ~2.5% baseline
    # (local_fallback.py's own bleed-classification section), but this is a small n=30
    # stratified-by-source sample, not a re-measurement of that baseline.
    "geometry_bleed": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: "bleed",
            37: "bleed",
            40: "bleed",
            37962: "bleed",
            39520: "bleed",
            41039: "bleed",
            102138: "bleed",
            128981: "bleed",
            144933: "bleed",
            145081: "bleed",
            145532: "trimmed",
            147855: "bleed",
            150472: "trimmed",
            159175: "bleed",
            161020: "bleed",
            175889: "bleed",
            189166: "trimmed",
            189921: "bleed",
            190895: "bleed",
            193523: "bleed",
            194684: "bleed",
            199986: "bleed",
            200330: "bleed",
            200668: "bleed",
            204427: "bleed",
            207913: "bleed",
            208337: "bleed",
            208569: "bleed",
            214113: "bleed",
            217783: "bleed",
        }.items()
    ],
    # layout_class (issue #148, geometry-group, recorded 2026-07-19 the same way geometry_bleed
    # was - a real no-persistence extract_card_evidence() run over all 30 golden cards). `value`
    # is `classify_border_color`'s own output (see image_evidence.py's module docstring for why
    # this classifier backs the `layout_class` field). Card 207913 genuinely came back "" with
    # an "ambiguous" skip_reason in the real run (a border sample outside the v1 taxonomy) - kept
    # as-is rather than discarded, since a golden set that only ever pins clean-positive outcomes
    # would never catch a regression in the ambiguous path.
    "layout_class": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: "borderless",
            37: "black",
            40: "black",
            37962: "black",
            39520: "black",
            41039: "borderless",
            102138: "black",
            128981: "black",
            144933: "borderless",
            145081: "borderless",
            145532: "black",
            147855: "borderless",
            150472: "black",
            159175: "black",
            161020: "white",
            175889: "borderless",
            189166: "black",
            189921: "black",
            190895: "borderless",
            193523: "borderless",
            194684: "black",
            199986: "black",
            200330: "black",
            200668: "borderless",
            204427: "borderless",
            207913: "",
            208337: "borderless",
            208569: "borderless",
            214113: "borderless",
            217783: "borderless",
        }.items()
    ],
    # crop_coordinates (issue #148, geometry-group, recorded the same run as layout_class above).
    # `value` is a dict of the three pixel-coordinate boxes this extractor writes
    # (`collector_line_crop_px`/`artist_crop_px`/`art_crop_px`) - kept together per card rather
    # than as three separate GOLDEN_EXPECTATIONS keys, since they're one extractor's one pass
    # (see image_evidence.py's `crop_coordinates` extractor_versions key). The three
    # 'trimmed'-classified cards (145532/150472/189166) show visibly different numbers than the
    # 'bleed' majority - real evidence that normalize_crop_box's remap is actually engaged for
    # those rows, not a no-op silently passing through everywhere.
    "crop_coordinates": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            37: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            40: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            37962: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 681, 925],
                "art_crop_px": [48, 92, 633, 536],
            },
            39520: {
                "collector_line_crop_px": [41, 832, 237, 893],
                "artist_crop_px": [0, 758, 678, 925],
                "art_crop_px": [47, 92, 631, 536],
            },
            41039: {
                "collector_line_crop_px": [41, 832, 237, 893],
                "artist_crop_px": [0, 758, 678, 925],
                "art_crop_px": [47, 92, 631, 536],
            },
            102138: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            128981: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            144933: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            145081: {
                "collector_line_crop_px": [41, 832, 237, 893],
                "artist_crop_px": [0, 758, 678, 925],
                "art_crop_px": [47, 92, 631, 536],
            },
            145532: {
                "collector_line_crop_px": [10, 859, 222, 924],
                "artist_crop_px": [0, 780, 662, 925],
                "art_crop_px": [18, 66, 644, 542],
            },
            147855: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            150472: {
                "collector_line_crop_px": [10, 859, 219, 924],
                "artist_crop_px": [0, 780, 654, 925],
                "art_crop_px": [17, 66, 637, 542],
            },
            159175: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            161020: {
                "collector_line_crop_px": [41, 832, 237, 893],
                "artist_crop_px": [0, 758, 678, 925],
                "art_crop_px": [47, 92, 631, 536],
            },
            175889: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            189166: {
                "collector_line_crop_px": [10, 859, 222, 924],
                "artist_crop_px": [0, 780, 664, 925],
                "art_crop_px": [18, 66, 646, 542],
            },
            189921: {
                "collector_line_crop_px": [41, 832, 237, 893],
                "artist_crop_px": [0, 758, 678, 925],
                "art_crop_px": [47, 92, 631, 536],
            },
            190895: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            193523: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            194684: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            199986: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            200330: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            200668: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            204427: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            207913: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            208337: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            208569: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            214113: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
            217783: {
                "collector_line_crop_px": [41, 832, 238, 893],
                "artist_crop_px": [0, 758, 680, 925],
                "art_crop_px": [48, 92, 632, 536],
            },
        }.items()
    ],
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
