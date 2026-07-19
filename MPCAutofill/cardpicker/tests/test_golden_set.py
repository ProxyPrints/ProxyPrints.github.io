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


class TestGetGoldenCards:
    def test_raises_when_pinned_ids_are_missing_from_the_db(self, db):
        # the test DB never contains these production pks - this is exercising the "raise
        # rather than silently shrink" behaviour, not a real-catalog integration check.
        try:
            get_golden_cards()
            assert False, "expected ValueError for missing golden-set ids"
        except ValueError as exc:
            assert "no longer exist" in str(exc)
