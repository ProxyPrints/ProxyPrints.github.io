"""
Golden-set fixture tests (docs/features/catalog-completion-plan.md, task #145).

WHAT THIS FILE DOES NOT DO - read before trusting it as the "hard gate" task #145 names.
NO EXTRACTOR RUNS HERE. Not one test in this module calls `fetch_and_compute_card_evidence_for_tests`,
`compute_card_art_hash`, `classify_border_color`, `classify_bleed_edge` or any other
extractor, and none can: `golden_set.py` imports no extractor code, the 30 pinned ids are
real PRODUCTION pks that never exist in pytest's isolated DB, and the expectations are
values transcribed from manual host-venv runs on dates recorded in `golden_set.py`'s own
comments. Stubbing `fetch_and_compute_card_evidence_for_tests` to return None, or forcing `classify_bleed_edge`
to return a constant, leaves every assertion in this file green (verified by mutation,
2026-07-29). The gate that task #145 describes is the MANUAL re-run of those extractions
against these ids, not this suite.

What the tests below therefore are, named accordingly:

* `TestGoldenCardIds` - properties of the pinned id list itself.
* `TestGoldenExpectationsShapeAndCoverage` - that each recorded expectation covers all 30
  cards and has the SHAPE (keys, python types, enumerated value spaces) its extractor's
  reader expects. These are type/coverage checks over hand-transcribed literals, not
  behavioural assertions, and they are worth having on exactly that footing: a
  transcription typo or a half-populated extractor key is a real thing they catch.
* `TestGoldenSetIsCoupledToTheExtractorsItGates` - the only cells here that a change to
  production code can break. They tie the recorded roster to `image_evidence.py`'s own
  extractor registry and to `local_fallback.BORDER_COLOR_TO_TAG`'s real output space.
* `TestGetGoldenCards` - see that class's own docstring; its single test asserts the gate
  is INOPERABLE in the test DB, which is a deliberate and clearly-marked non-check.

Whether to relabel this fixture or rebuild it against external labels is an open owner
ruling; this module's job is only to stop describing itself as more than it is.
"""

import re
from pathlib import Path

from cardpicker.golden_set import GOLDEN_CARD_IDS, GOLDEN_EXPECTATIONS, get_golden_cards
from cardpicker.local_fallback import BORDER_COLOR_TO_TAG

CARDPICKER_DIR = Path(__file__).resolve().parents[1]

# Extractors that deliberately carry no golden expectation. Each entry is a waiver that has to
# be argued for, not a to-do list: task #145 allows waiving a card per extractor, and by the
# same reasoning an extractor whose only output is unstable under re-fetch. Adding a key here
# is the deliberate act that `test_every_extractor_has_a_golden_expectation_or_a_waiver`
# forces; a NEW extractor shipping with neither an expectation nor a waiver fails that test.
EXTRACTORS_WITHOUT_GOLDEN_EXPECTATIONS = {
    # PROVISIONAL, and recorded as such rather than dressed up as a principled exclusion.
    # artbox_phash writes two fields: `artbox_phash` (a raw 64-bit perceptual hash int, which
    # golden_set.py excludes on the same "continuous/brittle to pin exactly" grounds it gives
    # for width/height/aspect_ratio and raw OCR text - a sound exclusion) and `artbox_crop_px`,
    # which is a discrete pixel box no different in kind from the three boxes `crop_coordinates`
    # DOES pin. So this extractor is pinnable in part and simply has not been pinned; the waiver
    # inherits the status quo so this test can land without a fresh 30-card host-venv run, which
    # needs prod credentials. Closing it is a follow-up, not a design decision.
    "artbox_phash",
    # PROVISIONAL, same reasoning as artbox_phash above. pinline_inset writes one pinnable
    # discrete value (`pinline_inset_verdict`: measured/ambiguous/indeterminate - no different in
    # kind from `geometry_bleed`'s `bleed_class` or `layout_class`'s own output, both of which ARE
    # pinned) alongside four continuous per-edge fractions and four discrete per-edge calls that
    # golden_set.py would exclude on the same "continuous/brittle" grounds `fetch_latency_ms`/
    # width/height already are. It is pinnable and simply has not been pinned; closing it needs
    # the same real 30-card host-venv run with prod credentials artbox_phash's waiver defers.
    "pinline_inset",
}

# GOLDEN_EXPECTATIONS keys that are not themselves `extractor_versions` keys. `bleed_diff_mm` is
# a FIELD of the geometry_bleed pass (image_evidence.py:955, immediately before that pass stamps
# its own extractor version at :961) that golden_set.py happens to pin under its own top-level
# key rather than folding into the `geometry_bleed` entry - a layout choice in the fixture, not a
# separate extractor.
NON_EXTRACTOR_GOLDEN_KEYS = {"bleed_diff_mm"}


def _extractor_versions_keys() -> set[str]:
    """The extractor names `image_evidence.py` actually stamps into
    `ImageEvidence.extractor_versions`, read out of that module's source.

    Derived rather than hand-listed on purpose: a hand-listed copy would drift with the
    thing it is supposed to be tracking, which is the whole failure mode this module is
    being fixed for. Same source-derivation technique `test_skip_reason_roster.py` uses.
    """
    source = (CARDPICKER_DIR / "image_evidence.py").read_text()
    keys = set(re.findall(r'extractor_versions\[\s*"([a-z0-9_]+)"\s*\]\s*=', source))
    # A silently-empty derivation would make both coupling tests below pass vacuously; the
    # registry has had ten-plus entries since #216.
    assert len(keys) >= 8, f"extractor_versions derivation found only {len(keys)} keys - it is probably broken"
    return keys


class TestGoldenCardIds:
    def test_pinned_set_has_no_duplicates(self):
        assert len(GOLDEN_CARD_IDS) == len(set(GOLDEN_CARD_IDS))

    def test_pinned_set_is_roughly_thirty_cards(self):
        # task #145: "~30 known cards" - not a hard-coded exact count, but this should never
        # silently drift to e.g. 3 or 300.
        assert 25 <= len(GOLDEN_CARD_IDS) <= 35


class TestGoldenExpectationsShapeAndCoverage:
    """SHAPE AND COVERAGE ONLY - see this module's docstring. Every assertion in this class
    reads hand-transcribed literals out of `GOLDEN_EXPECTATIONS` and checks their keys, python
    types, enumerated value spaces and per-card coverage. None of them runs an extractor, so
    none of them can fail because an extractor's behaviour changed. They exist to catch
    transcription errors and half-populated expectation tables, and that is all they claim."""

    def test_fetch_health_expectation_covers_every_golden_card(self):
        fetch_health_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["fetch_health"]}
        assert fetch_health_card_ids == set(GOLDEN_CARD_IDS)

    def test_fetch_health_expects_ok_for_every_card(self):
        # Completed by issue #150's re-spec (#215/#216) - value is now a dict (fetch_ok +
        # fetch_image_format), not a bare bool - see golden_set.py's own comment.
        assert all(e.value["fetch_ok"] is True for e in GOLDEN_EXPECTATIONS["fetch_health"])

    def test_fetch_health_image_format_is_a_known_format(self):
        # Recorded 2026-07-20 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden cards
        # (issue #216) - see TestGeometryBleed's own note above for why this isn't re-verified
        # live in CI. Only PNG/JPEG appeared on this real run.
        assert all(e.value["fetch_image_format"] in ("PNG", "JPEG") for e in GOLDEN_EXPECTATIONS["fetch_health"])

    def test_geometry_bleed_expectation_covers_every_golden_card(self):
        geometry_bleed_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["geometry_bleed"]}
        assert geometry_bleed_card_ids == set(GOLDEN_CARD_IDS)

    def test_geometry_bleed_values_are_a_known_bleed_class(self):
        # Recorded 2026-07-19 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden
        # cards (see golden_set.py's own comment for the real fetched dims/counts) - NOT
        # re-verified live here, matching this file's own documented scope (real production Card
        # rows don't exist in pytest's isolated testcontainers DB, so get_golden_cards() can't
        # run against real network/data inside this test suite; re-running the real extraction
        # against these pinned ids is a host-venv/manual check, done when this expectation was
        # populated and whenever it's next revisited, not a per-CI-run network call).
        assert all(e.value in ("bleed", "trimmed") for e in GOLDEN_EXPECTATIONS["geometry_bleed"])

    def test_layout_class_expectation_covers_every_golden_card(self):
        layout_class_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["layout_class"]}
        assert layout_class_card_ids == set(GOLDEN_CARD_IDS)

    def test_layout_class_values_are_a_known_border_class_or_ambiguous(self):
        # Recorded 2026-07-19 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden
        # cards (issue #148) - see this file's own note on TestGeometryBleed above for why this
        # isn't re-verified live in CI. "" (ambiguous) is a genuine real outcome for one golden
        # card (207913), not a placeholder - see golden_set.py's own comment.
        assert all(
            e.value in ("black", "white", "silver", "borderless", "") for e in GOLDEN_EXPECTATIONS["layout_class"]
        )

    def test_crop_coordinates_expectation_covers_every_golden_card(self):
        crop_coordinates_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["crop_coordinates"]}
        assert crop_coordinates_card_ids == set(GOLDEN_CARD_IDS)

    def test_crop_coordinates_values_have_all_three_boxes_as_four_int_lists(self):
        for expectation in GOLDEN_EXPECTATIONS["crop_coordinates"]:
            for key in ("collector_line_crop_px", "artist_crop_px", "art_crop_px"):
                box = expectation.value[key]
                assert len(box) == 4
                assert all(isinstance(coord, int) for coord in box)

    def test_collector_line_ocr_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["collector_line_ocr"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_collector_line_ocr_values_have_set_code_and_collector_number_keys(self):
        # Recorded 2026-07-19 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden
        # cards (issue #149) - see TestGeometryBleed's own note above for why this isn't
        # re-verified live in CI. "" is a genuine real outcome for most of this sample (only
        # 10/30 produced a parseable collector number), not a placeholder - see golden_set.py's
        # own comment.
        for expectation in GOLDEN_EXPECTATIONS["collector_line_ocr"]:
            assert set(expectation.value) == {"set_code", "collector_number"}
            assert isinstance(expectation.value["set_code"], str)
            assert isinstance(expectation.value["collector_number"], str)

    def test_artist_ocr_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["artist_ocr"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_artist_ocr_values_have_name_and_illus_anchor_fired_keys(self):
        # Recorded the same run as collector_line_ocr above - illus_anchor_fired is False for
        # every card on this real sample (a genuine "Illus." old-border-only convention this
        # source-stratified draw happened not to include - see golden_set.py's own comment), not
        # a placeholder.
        for expectation in GOLDEN_EXPECTATIONS["artist_ocr"]:
            assert set(expectation.value) == {"name", "illus_anchor_fired"}
            assert isinstance(expectation.value["name"], str)
            assert isinstance(expectation.value["illus_anchor_fired"], bool)

    def test_collector_line_tsv_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["collector_line_tsv"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_collector_line_tsv_values_are_bool(self):
        # Recorded the same run as collector_line_ocr above - 25/30 found at least one non-blank
        # tesseract word in the collector-line crop (see golden_set.py's own comment for why the
        # exact word-box list itself isn't pinned here).
        assert all(isinstance(e.value, bool) for e in GOLDEN_EXPECTATIONS["collector_line_tsv"])

    def test_symbol_region_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["symbol_region"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_symbol_region_values_have_crop_px_and_phash_present_keys(self):
        # Recorded 2026-07-20 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden cards
        # (issue #160) - see TestGeometryBleed's own note above for why this isn't re-verified
        # live in CI. 30/30 produced a real (non-degenerate) hash on this run, zero "ambiguous"
        # skips - a genuine outcome, not a placeholder (see golden_set.py's own comment).
        for expectation in GOLDEN_EXPECTATIONS["symbol_region"]:
            assert set(expectation.value) == {"symbol_crop_px", "phash_present"}
            box = expectation.value["symbol_crop_px"]
            assert len(box) == 4
            assert all(isinstance(coord, int) for coord in box)
            assert isinstance(expectation.value["phash_present"], bool)

    def test_legal_line_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["legal_line"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_legal_line_values_have_copyright_year_and_proxy_marker_keys(self):
        # Recorded 2026-07-20 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden cards
        # (issue #151) - see TestGeometryBleed's own note above for why this isn't re-verified
        # live in CI. 10/30 detected a proxy/not-for-sale marker on this real run (this catalog is
        # specifically an MTG-proxy print catalog, so this is a genuinely common real outcome, not
        # a rare edge case) - see golden_set.py's own comment for the real per-card breakdown.
        for expectation in GOLDEN_EXPECTATIONS["legal_line"]:
            assert set(expectation.value) == {"legal_line_copyright_year", "legal_line_proxy_marker_detected"}
            assert isinstance(expectation.value["legal_line_copyright_year"], str)
            assert isinstance(expectation.value["legal_line_proxy_marker_detected"], bool)

    def test_quality_signals_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["quality_signals"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_quality_signals_values_are_bool(self):
        # Recorded 2026-07-20 against a real fetch_and_compute_card_evidence_for_tests() run over all 30 golden cards
        # (issue #216, closing the golden-gate gap #215 shipped without) - see TestGeometryBleed's
        # own note above for why this isn't re-verified live in CI. False (not truncated) for
        # every card on this real run - a genuine all-negative outcome (see golden_set.py's own
        # comment), not a placeholder.
        assert all(isinstance(e.value, bool) for e in GOLDEN_EXPECTATIONS["quality_signals"])

    def test_bleed_diff_mm_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["bleed_diff_mm"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_bleed_diff_mm_values_are_float(self):
        assert all(isinstance(e.value, float) for e in GOLDEN_EXPECTATIONS["bleed_diff_mm"])


class TestGoldenSetIsCoupledToTheExtractorsItGates:
    """The only tests in this module a production-code change can break.

    They do not check any extractor's OUTPUT - that requires the real card images and is the
    manual host-venv run this suite structurally cannot do. What they check is that the
    recorded roster has not silently detached from the code it is supposed to gate: an
    extractor added or renamed in `image_evidence.py` without a corresponding golden
    expectation, or a recorded `layout_class` value that `classify_border_color` can no
    longer produce. Both are how a golden set rots into decoration without anyone noticing.
    """

    def test_every_extractor_has_a_golden_expectation_or_a_waiver(self):
        """A new extractor must ship with golden coverage or an argued waiver.

        This is the "hard gate" half of task #145 that IS mechanisable here: the gate cannot
        be a gate if an extractor can be added without ever entering the golden set. The
        extractor names come from `image_evidence.py`'s own `extractor_versions[...]`
        assignments, so renaming one there without updating `GOLDEN_EXPECTATIONS` fails here.

        THIS HAS ALREADY HAPPENED ONCE. golden_set.py's own `quality_signals` comment records
        that "#215 shipped this extractor without golden expectations since the isolated
        worktree it built in had no route to prod credentials", and issue #216 had to be opened
        to close the gap afterwards. Nothing in the suite noticed at the time; this test is
        what notices next time.
        """
        uncovered = _extractor_versions_keys() - set(GOLDEN_EXPECTATIONS) - EXTRACTORS_WITHOUT_GOLDEN_EXPECTATIONS
        assert not uncovered, (
            f"extractors with no golden expectation and no waiver: {sorted(uncovered)} - either "
            f"record expectations for the 30 golden cards, or add the name to "
            f"EXTRACTORS_WITHOUT_GOLDEN_EXPECTATIONS with the reason."
        )

    def test_no_golden_expectation_names_an_extractor_that_no_longer_exists(self):
        """The other direction: an expectation key that is neither a live extractor nor a
        declared non-extractor measurement is a stale block of literals nothing reads."""
        orphaned = set(GOLDEN_EXPECTATIONS) - _extractor_versions_keys() - NON_EXTRACTOR_GOLDEN_KEYS
        assert not orphaned, (
            f"golden expectations for names image_evidence.py does not stamp into "
            f"extractor_versions: {sorted(orphaned)}"
        )

    def test_recorded_layout_class_values_stay_inside_the_live_border_taxonomy(self):
        """Every recorded `layout_class` must still be a value `classify_border_color` can
        return - i.e. a `BORDER_COLOR_TO_TAG` key, or "" for its ambiguous outcome.

        Derived from the production constant, not from a copy of it, so narrowing the
        taxonomy (dropping "white", say - card 161020 is recorded as white) invalidates the
        golden set loudly instead of leaving expectations that describe a classifier that no
        longer exists."""
        recorded = {e.value for e in GOLDEN_EXPECTATIONS["layout_class"]}
        unreachable = recorded - set(BORDER_COLOR_TO_TAG) - {""}
        assert not unreachable, (
            f"golden layout_class values classify_border_color can no longer produce: "
            f"{sorted(unreachable)} - BORDER_COLOR_TO_TAG's key set changed under the fixture."
        )


class TestGetGoldenCards:
    """NOT A GATE CHECK. The one test here asserts `get_golden_cards()` RAISES, because the
    30 pinned production pks never exist in pytest's isolated DB. Read literally: the only
    DB-touching test of the golden set asserts that the golden set is inoperable under test.
    That is a real property of the fixture worth stating out loud rather than a bug in the
    test - but it means nothing here ever loads a golden card, and no amount of passing in
    this class indicates the gate works."""

    def test_missing_pinned_ids_raise_rather_than_silently_shrinking_the_set(self, db):
        # the test DB never contains these production pks, so this exercises exactly one
        # thing: the "raise rather than silently shrink" branch. It is not, and cannot be, a
        # real-catalog integration check - see this class's docstring.
        try:
            get_golden_cards()
            assert False, "expected ValueError for missing golden-set ids"
        except ValueError as exc:
            assert "no longer exist" in str(exc)
