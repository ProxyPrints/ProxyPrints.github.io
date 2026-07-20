"""
Golden-set fixture tests (docs/features/catalog-completion-plan.md, task #145). Real DB rows
are not created here - `get_golden_cards()`'s missing-id behaviour is exercised against
whatever pinned ids do/don't exist in the test DB, which is always empty of them.
"""

from cardpicker.golden_set import GOLDEN_CARD_IDS, GOLDEN_EXPECTATIONS, get_golden_cards


class TestGoldenCardIds:
    def test_pinned_set_has_no_duplicates(self):
        assert len(GOLDEN_CARD_IDS) == len(set(GOLDEN_CARD_IDS))

    def test_pinned_set_is_roughly_thirty_cards(self):
        # task #145: "~30 known cards" - not a hard-coded exact count, but this should never
        # silently drift to e.g. 3 or 300.
        assert 25 <= len(GOLDEN_CARD_IDS) <= 35


class TestGoldenExpectations:
    def test_fetch_health_expectation_covers_every_golden_card(self):
        fetch_health_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["fetch_health"]}
        assert fetch_health_card_ids == set(GOLDEN_CARD_IDS)

    def test_fetch_health_expects_ok_for_every_card(self):
        # Completed by issue #150's re-spec (#215/#216) - value is now a dict (fetch_ok +
        # fetch_image_format), not a bare bool - see golden_set.py's own comment.
        assert all(e.value["fetch_ok"] is True for e in GOLDEN_EXPECTATIONS["fetch_health"])

    def test_fetch_health_image_format_is_a_known_format(self):
        # Recorded 2026-07-20 against a real extract_card_evidence() run over all 30 golden cards
        # (issue #216) - see TestGeometryBleed's own note above for why this isn't re-verified
        # live in CI. Only PNG/JPEG appeared on this real run.
        assert all(e.value["fetch_image_format"] in ("PNG", "JPEG") for e in GOLDEN_EXPECTATIONS["fetch_health"])

    def test_geometry_bleed_expectation_covers_every_golden_card(self):
        geometry_bleed_card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["geometry_bleed"]}
        assert geometry_bleed_card_ids == set(GOLDEN_CARD_IDS)

    def test_geometry_bleed_values_are_a_known_bleed_class(self):
        # Recorded 2026-07-19 against a real extract_card_evidence() run over all 30 golden
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
        # Recorded 2026-07-19 against a real extract_card_evidence() run over all 30 golden
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
        # Recorded 2026-07-19 against a real extract_card_evidence() run over all 30 golden
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
        # Recorded 2026-07-20 against a real extract_card_evidence() run over all 30 golden cards
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
        # Recorded 2026-07-20 against a real extract_card_evidence() run over all 30 golden cards
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
        # Recorded 2026-07-20 against a real extract_card_evidence() run over all 30 golden cards
        # (issue #216, closing the golden-gate gap #215 shipped without) - see TestGeometryBleed's
        # own note above for why this isn't re-verified live in CI. False (not truncated) for
        # every card on this real run - a genuine all-negative outcome (see golden_set.py's own
        # comment), not a placeholder.
        assert all(isinstance(e.value, bool) for e in GOLDEN_EXPECTATIONS["quality_signals"])

    def test_color_profile_expectation_covers_every_golden_card(self):
        card_ids = {e.card_id for e in GOLDEN_EXPECTATIONS["color_profile"]}
        assert card_ids == set(GOLDEN_CARD_IDS)

    def test_color_profile_values_have_mean_and_stddev_rgb_keys(self):
        # Recorded the same run as quality_signals above. No exact-value comparison here -
        # color_profile has no discrete signal at all (see golden_set.py's own comment for why
        # the real recorded numbers are kept as a documentation artifact, not a hard-pinned
        # assertion) - only structure/type/range are checked, the same bar
        # test_crop_coordinates_values_have_all_three_boxes_as_four_int_lists applies to its own
        # pixel-coordinate lists above.
        for expectation in GOLDEN_EXPECTATIONS["color_profile"]:
            assert set(expectation.value) == {"color_mean_rgb", "color_stddev_rgb"}
            for key in ("color_mean_rgb", "color_stddev_rgb"):
                channel_values = expectation.value[key]
                assert len(channel_values) == 3
                for channel_value in channel_values:
                    assert isinstance(channel_value, float)
                    assert 0.0 <= channel_value <= 255.0


class TestGetGoldenCards:
    def test_raises_when_pinned_ids_are_missing_from_the_db(self, db):
        # the test DB never contains these production pks - this is exercising the "raise
        # rather than silently shrink" behaviour, not a real-catalog integration check.
        try:
            get_golden_cards()
            assert False, "expected ValueError for missing golden-set ids"
        except ValueError as exc:
            assert "no longer exist" in str(exc)
