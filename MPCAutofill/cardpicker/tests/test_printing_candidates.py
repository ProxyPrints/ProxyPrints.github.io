import datetime as dt

from cardpicker.printing_candidates import (
    find_candidates_by_name,
    get_ranked_printing_candidates,
    rank_candidates_by_confidence,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
)


class TestFindCandidatesByName:
    def test_matches_regardless_of_punctuation(self, db):
        printing = CanonicalCardFactory(name="Zirda, the Dawnwaker")
        results = list(find_candidates_by_name("zirda the dawnwaker"))
        assert results == [printing]

    def test_matches_regardless_of_hyphenation(self, db):
        printing = CanonicalCardFactory(name="Snow-Covered Forest")
        results = list(find_candidates_by_name("snow covered forest"))
        assert results == [printing]

    def test_requires_every_word(self, db):
        CanonicalCardFactory(name="Lightning Bolt")
        results = list(find_candidates_by_name("lightning strike"))
        assert results == []

    def test_empty_query_returns_no_candidates(self, db):
        CanonicalCardFactory(name="Lightning Bolt")
        assert list(find_candidates_by_name("   ")) == []


class TestRankCandidatesByConfidence:
    def test_closer_match_ranks_first(self, db):
        # deliberately not a bracketed/parenthetical difference (e.g. "(Extended Art)") -
        # to_searchable() strips bracketed text entirely, so two names differing only in
        # a parenthetical normalise to the exact same string and can't be told apart here
        close = CanonicalCardFactory(name="Lightning Bolt")
        far = CanonicalCardFactory(name="Lightning Storm")
        ranked = rank_candidates_by_confidence([far, close], "Lightning Bolt")
        assert ranked == [close, far]


class TestGetRankedPrintingCandidates:
    def test_unresolved_card_falls_back_to_searchq(self, db):
        card = CardFactory(name="Mountain 4", searchq="mountain")
        exact = CanonicalCardFactory(name="Mountain")
        CanonicalCardFactory(name="Fire Elemental")  # shouldn't match
        results = get_ranked_printing_candidates(card, None)
        assert results == [exact]

    def test_explicit_query_overrides_searchq(self, db):
        card = CardFactory(name="Mountain 4", searchq="mountain")
        forest = CanonicalCardFactory(name="Forest")
        CanonicalCardFactory(name="Mountain")  # shouldn't match - explicit query wins
        results = get_ranked_printing_candidates(card, "forest")
        assert results == [forest]

    def test_expansion_hint_moves_matching_expansion_candidates_first(self, db):
        card = CardFactory(name="Mountain 4", searchq="mountain", expansion_hint="mh3")
        hinted_expansion = CanonicalExpansionFactory(code="mh3")
        other_expansion = CanonicalExpansionFactory(code="woe")
        hinted = CanonicalCardFactory(name="Mountain", expansion=hinted_expansion)
        other = CanonicalCardFactory(name="Mountain", expansion=other_expansion)

        results = get_ranked_printing_candidates(card, None)

        assert results[0] == hinted
        assert set(results) == {hinted, other}

    def test_linked_card_lists_all_printings_of_same_oracle_card_by_recency(self, db):
        card = CardFactory()
        older = CanonicalCardFactory(canonical_id="11111111-1111-1111-1111-111111111111")
        newer = CanonicalCardFactory(canonical_id=older.canonical_id)
        CanonicalPrintingMetadataFactory(canonical_card=older, released_at=dt.date(2010, 1, 1))
        CanonicalPrintingMetadataFactory(canonical_card=newer, released_at=dt.date(2020, 1, 1))
        card.inferred_canonical_card = older
        card.save(update_fields=["inferred_canonical_card"])

        results = get_ranked_printing_candidates(card, None)

        assert results == [newer, older]

    def test_linked_card_puts_printings_missing_release_date_last(self, db):
        card = CardFactory()
        dated = CanonicalCardFactory(canonical_id="22222222-2222-2222-2222-222222222222")
        undated = CanonicalCardFactory(canonical_id=dated.canonical_id)
        CanonicalPrintingMetadataFactory(canonical_card=dated, released_at=dt.date(2015, 6, 1))
        # `undated` deliberately has no `CanonicalPrintingMetadata` row at all
        card.inferred_canonical_card = dated
        card.save(update_fields=["inferred_canonical_card"])

        results = get_ranked_printing_candidates(card, None)

        assert results == [dated, undated]

    def test_explicit_query_overrides_linked_card_browse_mode(self, db):
        card = CardFactory()
        linked = CanonicalCardFactory(canonical_id="33333333-3333-3333-3333-333333333333")
        card.inferred_canonical_card = linked
        card.save(update_fields=["inferred_canonical_card"])
        other = CanonicalCardFactory(name="Something Else Entirely")

        results = get_ranked_printing_candidates(card, "Something Else Entirely")

        assert results == [other]
