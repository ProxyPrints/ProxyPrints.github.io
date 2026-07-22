from unittest.mock import patch

from cardpicker.printing_consensus import ResolvedPrinting
from cardpicker.schema_types import (
    CardType,
    FilterSettings,
    SearchSettings,
    SearchTypeSettings,
    SourceSettings,
)
from cardpicker.search import search_functions
from cardpicker.search.search_functions import (
    _passes_resolved_attribute_filters,
    _resolved_printing_match_tier,
    retrieve_card_identifiers,
)


def make_search_settings(full_art_only: bool = False, borderless_only: bool = False) -> SearchSettings:
    return SearchSettings(
        filterSettings=FilterSettings(
            minimumDPI=0,
            maximumDPI=1500,
            maximumSize=30,
            languages=[],
            includesTags=[],
            excludesTags=[],
            fullArtOnly=full_art_only,
            borderlessOnly=borderless_only,
        ),
        searchTypeSettings=SearchTypeSettings(fuzzySearch=False, filterCardbacks=False),
        sourceSettings=SourceSettings(sources=[]),
    )


def make_resolved_printing(
    expansion_code: str = "ICE", collector_number: str = "61", full_art: bool = False, border_color: str = "black"
) -> ResolvedPrinting:
    return ResolvedPrinting(
        expansion_code=expansion_code, collector_number=collector_number, full_art=full_art, border_color=border_color
    )


class TestPassesResolvedAttributeFilters:
    """
    Hard-gate rule under test: these filters must only ever EXCLUDE a card whose resolved
    printing actively fails the check - a card absent from `resolved` (UNRESOLVED/NO_MATCH)
    must always pass, regardless of how many filters are active. This is the "unresolved
    cards are unknowns, not mismatches" requirement from the task spec.
    """

    def test_no_filters_active_everything_passes(self):
        settings = make_search_settings(full_art_only=False, borderless_only=False)
        resolved = {"card-1": make_resolved_printing(full_art=False, border_color="black")}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is True

    def test_unresolved_card_always_passes_even_with_filters_active(self):
        settings = make_search_settings(full_art_only=True, borderless_only=True)
        resolved: dict[str, ResolvedPrinting] = {}  # card-1 is UNRESOLVED/NO_MATCH - absent
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is True

    def test_full_art_only_excludes_resolved_non_full_art(self):
        settings = make_search_settings(full_art_only=True)
        resolved = {"card-1": make_resolved_printing(full_art=False)}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is False

    def test_full_art_only_passes_resolved_full_art(self):
        settings = make_search_settings(full_art_only=True)
        resolved = {"card-1": make_resolved_printing(full_art=True)}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is True

    def test_borderless_only_excludes_resolved_non_borderless(self):
        settings = make_search_settings(borderless_only=True)
        resolved = {"card-1": make_resolved_printing(border_color="black")}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is False

    def test_borderless_only_passes_resolved_borderless(self):
        settings = make_search_settings(borderless_only=True)
        resolved = {"card-1": make_resolved_printing(border_color="borderless")}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is True

    def test_both_filters_active_card_must_satisfy_both(self):
        settings = make_search_settings(full_art_only=True, borderless_only=True)
        resolved = {"card-1": make_resolved_printing(full_art=True, border_color="black")}
        # fails borderless despite passing full_art
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is False

        resolved = {"card-1": make_resolved_printing(full_art=True, border_color="borderless")}
        assert _passes_resolved_attribute_filters(resolved, settings, "card-1") is True


class TestResolvedPrintingMatchTier:
    """
    Tier 0 (exact set+collector) must sort before tier 1 (set-only), which must sort before
    tier 2 (no match, including all UNRESOLVED/NO_MATCH cards - "today's order, unchanged").
    """

    def test_exact_match_is_tier_0(self):
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, "ICE", "61", "card-1") == 0

    def test_exact_match_is_case_insensitive_on_expansion_code(self):
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, "ice", "61", "card-1") == 0

    def test_set_only_match_is_tier_1(self):
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, "ICE", "999", "card-1") == 1

    def test_set_only_match_with_no_collector_number_requested_is_tier_1(self):
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, "ICE", None, "card-1") == 1

    def test_expansion_mismatch_is_tier_2(self):
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, "ZZZ", "61", "card-1") == 2

    def test_unresolved_card_is_tier_2(self):
        resolved: dict[str, ResolvedPrinting] = {}
        assert _resolved_printing_match_tier(resolved, "ICE", "61", "card-1") == 2

    def test_no_expansion_code_requested_is_tier_2_regardless_of_collector_number(self):
        # decklist parsing never produces a collectorNumber without an expansionCode, but the
        # function's contract should still be well-defined for this input.
        resolved = {"card-1": make_resolved_printing(expansion_code="ICE", collector_number="61")}
        assert _resolved_printing_match_tier(resolved, None, "61", "card-1") == 2

    def test_stable_sort_preserves_order_within_a_tier(self):
        resolved = {
            "card-a": make_resolved_printing(expansion_code="ICE", collector_number="61"),
            "card-b": make_resolved_printing(expansion_code="ICE", collector_number="61"),
        }
        identifiers = ["card-b", "card-a", "unmatched-1", "unmatched-2"]
        result = sorted(
            identifiers, key=lambda identifier: _resolved_printing_match_tier(resolved, "ICE", "61", identifier)
        )
        # both tier-0 matches keep their relative order (card-b before card-a, as in the input),
        # and both tier-2 unmatched cards likewise keep theirs
        assert result == ["card-b", "card-a", "unmatched-1", "unmatched-2"]


class TestRetrieveCardIdentifiersDegradation:
    """
    E-2: a printing-specific search (expansion_code and/or collector_number supplied) that
    finds zero hits under that hard filter retries once without it, flagging the response
    `degraded` so the caller (and eventually the frontend) can say so honestly instead of
    reporting an empty result for a card that exists under other printings. Exact-match
    behaviour when hits DO exist under the filter must stay completely untouched by this -
    `_retrieve_card_identifiers_once` is mocked directly (rather than hitting a real
    Elasticsearch index) precisely so these tests assert only the retry/degrade decision,
    never the underlying search/rerank logic those other test classes already cover.
    """

    def test_hits_found_under_the_filter_no_retry_no_degradation(self):
        with patch.object(search_functions, "_retrieve_card_identifiers_once", return_value=["abc"]) as mock_once:
            identifiers, degraded = retrieve_card_identifiers(
                search_settings=make_search_settings(),
                query="lightning bolt",
                card_type=CardType.CARD,
                expansion_code="2ED",
                collector_number="162",
            )
        assert identifiers == ["abc"]
        assert degraded is False
        mock_once.assert_called_once()

    def test_zero_hits_under_the_filter_retries_without_it_and_flags_degraded(self):
        calls: list[tuple[str | None, str | None]] = []

        def fake_once(
            search_settings: SearchSettings,
            query: str,
            card_type: CardType,
            expansion_code: str | None,
            collector_number: str | None,
            operator_filters: list | None = None,
        ) -> list[str]:
            calls.append((expansion_code, collector_number))
            return [] if expansion_code else ["fallback-id"]

        with patch.object(search_functions, "_retrieve_card_identifiers_once", side_effect=fake_once):
            identifiers, degraded = retrieve_card_identifiers(
                search_settings=make_search_settings(),
                query="lightning bolt",
                card_type=CardType.CARD,
                expansion_code="2ED",
                collector_number="162",
            )
        assert identifiers == ["fallback-id"]
        assert degraded is True
        # exactly one filtered attempt, then exactly one unfiltered retry - never more
        assert calls == [("2ED", "162"), (None, None)]

    def test_zero_hits_with_no_printing_filter_supplied_never_retries(self):
        # nothing to degrade from - a plain name search finding nothing is just "no results",
        # not a printing-specific miss, so there must be no spurious second Elasticsearch hit.
        with patch.object(search_functions, "_retrieve_card_identifiers_once", return_value=[]) as mock_once:
            identifiers, degraded = retrieve_card_identifiers(
                search_settings=make_search_settings(),
                query="a card that does not exist",
                card_type=CardType.CARD,
                expansion_code=None,
                collector_number=None,
            )
        assert identifiers == []
        assert degraded is False
        mock_once.assert_called_once()

    def test_zero_hits_with_only_expansion_code_still_retries(self):
        # collector_number alone can also be omitted while expansion_code is set (a decklist
        # line naming just a set, no number) - either field alone must still trigger the retry.
        calls: list[tuple[str | None, str | None]] = []

        def fake_once(
            search_settings: SearchSettings,
            query: str,
            card_type: CardType,
            expansion_code: str | None,
            collector_number: str | None,
            operator_filters: list | None = None,
        ) -> list[str]:
            calls.append((expansion_code, collector_number))
            return [] if expansion_code else ["fallback-id"]

        with patch.object(search_functions, "_retrieve_card_identifiers_once", side_effect=fake_once):
            identifiers, degraded = retrieve_card_identifiers(
                search_settings=make_search_settings(),
                query="lightning bolt",
                card_type=CardType.CARD,
                expansion_code="2ED",
                collector_number=None,
            )
        assert identifiers == ["fallback-id"]
        assert degraded is True
        assert calls == [("2ED", None), (None, None)]
