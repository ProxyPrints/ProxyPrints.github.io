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
    # collector_line_ocr (issue #149, OCR-group, recorded 2026-07-19 the same way as the
    # geometry-group extractors above - a real, no-persistence extract_card_evidence() run over
    # all 30 golden cards). `value` is {"set_code", "collector_number"} - local_ocr.
    # parse_collector_line's own discrete, tolerant parse of the raw OCR text (the raw text
    # itself is NOT pinned, same "brittle/continuous values excluded" rationale geometry_bleed's
    # own comment gives for omitting width/height/aspect_ratio). No candidate matching happens
    # here (Stage D's job, see image_evidence.py's module docstring) - most of these are blank
    # (real tesseract found nothing plausible on this sample), which is an honest outcome, not a
    # placeholder: only 10/30 produced a parseable collector number on this real run, several of
    # those a 4-digit "year" collector number (mtg/proxy sets) rather than a classic 3-digit one.
    "collector_line_ocr": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: {"set_code": "", "collector_number": "0013"},
            37: {"set_code": "j25", "collector_number": "0002"},
            40: {"set_code": "", "collector_number": "3"},
            37962: {"set_code": "sld", "collector_number": "142"},
            39520: {"set_code": "", "collector_number": ""},
            41039: {"set_code": "", "collector_number": ""},
            102138: {"set_code": "", "collector_number": ""},
            128981: {"set_code": "", "collector_number": ""},
            144933: {"set_code": "", "collector_number": ""},
            145081: {"set_code": "", "collector_number": ""},
            145532: {"set_code": "", "collector_number": ""},
            147855: {"set_code": "foe", "collector_number": "0"},
            150472: {"set_code": "", "collector_number": ""},
            159175: {"set_code": "", "collector_number": ""},
            161020: {"set_code": "", "collector_number": ""},
            175889: {"set_code": "", "collector_number": ""},
            189166: {"set_code": "", "collector_number": ""},
            189921: {"set_code": "", "collector_number": ""},
            190895: {"set_code": "mtg", "collector_number": "2024"},
            193523: {"set_code": "oey", "collector_number": "0055"},
            194684: {"set_code": "", "collector_number": ""},
            199986: {"set_code": "", "collector_number": "4"},
            200330: {"set_code": "mtg", "collector_number": "2024"},
            200668: {"set_code": "dmr", "collector_number": "421r"},
            204427: {"set_code": "mtg", "collector_number": "2024"},
            207913: {"set_code": "thato", "collector_number": "267"},
            208337: {"set_code": "ahr", "collector_number": "7"},
            208569: {"set_code": "proxy", "collector_number": "2025"},
            214113: {"set_code": "cls", "collector_number": "0228"},
            217783: {"set_code": "msh", "collector_number": "570"},
        }.items()
    ],
    # artist_ocr (issue #149, OCR-group, recorded the same run as collector_line_ocr above).
    # `illus_anchor_fired` is False for all 30 golden cards on this real run - genuine, not a
    # placeholder: the "Illus. <artist>" credit is an OLD-BORDER-ONLY convention (pre-2003, see
    # local_fallback.py's frame-style section), and this sample - stratified by SOURCE, not by
    # frame era - happened to draw zero old-border cards (consistent with issue #148's own
    # layout_class results: 14 black/13 borderless/1 white/1 ambiguous, no frame-era signal
    # pointing old-border either). Kept as-is per the same "don't discard a real all-negative
    # outcome" rationale layout_class's own comment gives for card 207913's ambiguous read - a
    # golden set that only ever pins positive matches would never catch a regression in the
    # "correctly found nothing" path.
    "artist_ocr": [
        GoldenExpectation(card_id=cid, value={"name": "", "illus_anchor_fired": False}) for cid in GOLDEN_CARD_IDS
    ],
    # collector_line_tsv (issue #149, OCR-group, recorded the same run as collector_line_ocr
    # above). `value` is a bool - whether tesseract's TSV output found ANY non-blank word in the
    # collector-line crop, not the exact word-box list itself (too brittle to pin exactly across
    # a tesseract version bump - same "exclude the continuous/brittle, pin the discrete" call
    # geometry_bleed's own comment makes for width/height/aspect_ratio). 25/30 found at least one
    # word (including several cards where collector_line_ocr itself found no PARSEABLE collector
    # number - tesseract read something, it just didn't fit the collector-number regex, a
    # genuinely different, weaker outcome than a fully blank crop).
    "collector_line_tsv": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: True,
            37: True,
            40: True,
            37962: True,
            39520: False,
            41039: True,
            102138: False,
            128981: True,
            144933: True,
            145081: True,
            145532: False,
            147855: True,
            150472: False,
            159175: True,
            161020: True,
            175889: True,
            189166: False,
            189921: True,
            190895: True,
            193523: True,
            194684: True,
            199986: True,
            200330: True,
            200668: True,
            204427: True,
            207913: True,
            208337: True,
            208569: True,
            214113: True,
            217783: True,
        }.items()
    ],
    # symbol_region (issue #160, "Part 4b: symbol harness", recorded 2026-07-20 against a real,
    # no-persistence extract_card_evidence() run over all 30 golden cards - same host-venv/real-
    # network-fetch method as every extractor above). `value` is {"symbol_crop_px", "phash_present"}
    # - `symbol_crop_px` is deterministic from width/height/bleed_class alone (same as
    # crop_coordinates's own three boxes), pinned exactly; the raw phash int itself is NOT pinned
    # (library-version-dependent, same "exclude the continuous/brittle" rationale geometry_bleed's
    # own comment gives for width/height/aspect_ratio) - only whether a real (non-degenerate) hash
    # was produced at all. 30/30 produced one on this real run, zero "ambiguous" (degenerate-crop)
    # skips - genuinely unsurprising for a source-stratified sample of real fetched images (the
    # degenerate-box guard is a mechanical crash-prevention measure for a sub-floor-resolution
    # input, not a classification threshold expected to fire on a normal fetch - see
    # image_evidence.py's own module docstring), not a placeholder result. The three
    # 'trimmed'-classified cards (145532/150472/189166) show visibly different crop-coordinate
    # numbers than the majority, same real evidence of normalize_crop_box's remap being engaged
    # that issue #148's own crop_coordinates expectation notes.
    "symbol_region": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            37: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            40: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            37962: {"symbol_crop_px": [531, 509, 681, 740], "phash_present": True},
            39520: {"symbol_crop_px": [529, 509, 678, 740], "phash_present": True},
            41039: {"symbol_crop_px": [529, 509, 678, 740], "phash_present": True},
            102138: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            128981: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            144933: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            145081: {"symbol_crop_px": [529, 509, 678, 740], "phash_present": True},
            145532: {"symbol_crop_px": [535, 512, 662, 760], "phash_present": True},
            147855: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            150472: {"symbol_crop_px": [529, 512, 654, 760], "phash_present": True},
            159175: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            161020: {"symbol_crop_px": [529, 509, 678, 740], "phash_present": True},
            175889: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            189166: {"symbol_crop_px": [537, 512, 664, 760], "phash_present": True},
            189921: {"symbol_crop_px": [529, 509, 678, 740], "phash_present": True},
            190895: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            193523: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            194684: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            199986: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            200330: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            200668: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            204427: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            207913: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            208337: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            208569: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            214113: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
            217783: {"symbol_crop_px": [530, 509, 680, 740], "phash_present": True},
        }.items()
    ],
    # legal_line (public issue #151, "Legal-line extractor + moderator flag + volume report
    # (task #159)" - this PR builds the extractor + moderator-flag signal only, recorded
    # 2026-07-20 against a real, no-persistence extract_card_evidence() run over all 30 golden
    # cards - same host-venv/real-network-fetch method as every extractor above). `value` is
    # {"legal_line_copyright_year", "legal_line_proxy_marker_detected"} - the raw text itself is
    # NOT pinned (same "exclude the continuous/brittle" rationale collector_line_ocr's own
    # comment gives). Only 10/30 produced a plausible copyright year on this real run (a lower
    # yield than collector_line_ocr's own 10/30, but genuinely different cards fired - this crop
    # region is a NEW, dedicated area, not a reuse), and this catalog being specifically an
    # MTG-proxy print catalog (not a scan archive) means the proxy/not-for-sale marker fires far
    # more often than a random sample of authentic scans would (10/30, not a rare edge case) -
    # confirmed genuine on inspection, not a detector bug: real hits include "NOT FOR SALE"
    # (145081), "Custom Proxy *NOTFORSALE" (161020), "MTG PROXY" (190895), "Proxy - <username>"
    # community-credit watermarks baked into the source image (37962), and combined "Proxy / Not
    # for Sale" legends with a real year (128981: 1998). Kept as-is per the same "don't discard a
    # real all-negative OR all-positive outcome" rationale every prior extractor's own golden-set
    # comment gives.
    "legal_line": [
        GoldenExpectation(card_id=cid, value=value)
        for cid, value in {
            35: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            37: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            40: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            37962: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
            39520: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            41039: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            102138: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            128981: {"legal_line_copyright_year": "1998", "legal_line_proxy_marker_detected": True},
            144933: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            145081: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
            145532: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            147855: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            150472: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            159175: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            161020: {"legal_line_copyright_year": "2020", "legal_line_proxy_marker_detected": True},
            175889: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            189166: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            189921: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            190895: {"legal_line_copyright_year": "2024", "legal_line_proxy_marker_detected": True},
            193523: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
            194684: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            199986: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            200330: {"legal_line_copyright_year": "2024", "legal_line_proxy_marker_detected": False},
            200668: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            204427: {"legal_line_copyright_year": "2024", "legal_line_proxy_marker_detected": False},
            207913: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
            208337: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": False},
            208569: {"legal_line_copyright_year": "2025", "legal_line_proxy_marker_detected": True},
            214113: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
            217783: {"legal_line_copyright_year": "", "legal_line_proxy_marker_detected": True},
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
