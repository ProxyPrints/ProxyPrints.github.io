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

    def test_fetch_health_expects_true_for_every_card(self):
        assert all(e.value is True for e in GOLDEN_EXPECTATIONS["fetch_health"])

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


class TestGetGoldenCards:
    def test_raises_when_pinned_ids_are_missing_from_the_db(self, db):
        # the test DB never contains these production pks - this is exercising the "raise
        # rather than silently shrink" behaviour, not a real-catalog integration check.
        try:
            get_golden_cards()
            assert False, "expected ValueError for missing golden-set ids"
        except ValueError as exc:
            assert "no longer exist" in str(exc)
