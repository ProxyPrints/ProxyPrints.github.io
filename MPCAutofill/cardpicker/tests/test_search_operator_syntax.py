"""
End-to-end tests for Scryfall-style search-operator syntax (2026-07-22) - exercised through the
real `post_editor_search` endpoint and a real (testcontainers) Elasticsearch index, proving the
whole pipeline (`cardpicker.search.operator_parser.parse_query` -> the operator-filter wiring in
`cardpicker.search.search_functions.get_search` -> the new `documents.py` mapping fields) works
together. Parser-only behaviour (quoting, negation syntax, unknown-operator detection in
isolation) is covered by `test_operator_parser.py`; this file is about what each operator
actually MATCHES once it reaches a real index, including the artist fallback-chain precedence
and case-insensitivity, which only exist at the Django-model/ES-mapping layer this file exercises.
"""

import pytest

from django.core.management import call_command
from django.urls import reverse

from cardpicker import views
from cardpicker.models import PrintingTagStatus
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
)


def search_settings_for(source_pk: int, **filter_overrides) -> dict:
    return {
        "searchTypeSettings": {"fuzzySearch": False, "filterCardbacks": False},
        "sourceSettings": {"sources": [[source_pk, True]]},
        "filterSettings": {
            "minimumDPI": 0,
            "maximumDPI": 1500,
            "maximumSize": 30,
            "languages": [],
            "includesTags": [],
            "excludesTags": [],
            "fullArtOnly": False,
            "borderlessOnly": False,
            **filter_overrides,
        },
    }


def do_search(client, source_pk: int, query: str, **filter_overrides) -> dict:
    response = client.post(
        reverse(views.post_editor_search),
        {
            "searchSettings": search_settings_for(source_pk, **filter_overrides),
            "queries": {"key1": {"query": query, "cardType": "CARD"}},
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture()
def operator_card_set(django_settings, elasticsearch, example_drive_1):
    """
    A card set exercising every rung of the artist fallback chain plus border/frame/tag/set/lang,
    all sharing one source and one searchable name so free-text alone never distinguishes them -
    only the operator under test should.
    """
    guay = CanonicalArtistFactory(name="Rebecca Guay")
    other_artist = CanonicalArtistFactory(name="Someone Else")
    override_only_artist = CanonicalArtistFactory(name="Override Only Artist")
    vote_only_artist = CanonicalArtistFactory(name="Vote Only Artist")
    inferred_artist = CanonicalArtistFactory(name="Inferred Chain Artist")

    ice = CanonicalExpansionFactory(code="ice")
    xln = CanonicalExpansionFactory(code="xln")

    guay_printing = CanonicalCardFactory(expansion=ice, collector_number="61", artist=guay)
    CanonicalPrintingMetadataFactory(
        canonical_card=guay_printing, full_art=True, border_color="Borderless", frame="2015"
    )
    other_printing = CanonicalCardFactory(expansion=xln, collector_number="10", artist=other_artist)
    inferred_printing = CanonicalCardFactory(artist=inferred_artist)

    # rung 1: `canonical_card.artist` (a confirmed indexing match) - also carries border/frame.
    canonical_card_match = CardFactory(
        identifier="op-canonical-card",
        name="Operator Test Card",
        source=example_drive_1,
        canonical_card=guay_printing,
        tags=["foil", "common"],
        language="en",
    )
    # a card with a DIFFERENT artist/printing, to prove the artist/border/frame/set filters
    # actually exclude a non-matching card, not just fail to exclude anything.
    non_matching_card = CardFactory(
        identifier="op-non-matching",
        name="Operator Test Card",
        source=example_drive_1,
        canonical_card=other_printing,
        tags=["extended-art"],
        language="ja",
    )
    # rung 0: explicit `canonical_artist` override wins even over a (deliberately different)
    # `canonical_card.artist`.
    explicit_artist_override = CardFactory(
        identifier="op-explicit-override",
        name="Operator Test Card",
        source=example_drive_1,
        canonical_card=other_printing,
        canonical_artist=override_only_artist,
        tags=["common"],
    )
    # rung 2: RESOLVED-gated `inferred_canonical_card.artist` - only takes effect because
    # printing_tag_status is RESOLVED.
    resolved_inferred = CardFactory(
        identifier="op-resolved-inferred",
        name="Operator Test Card",
        source=example_drive_1,
        printing_tag_status=PrintingTagStatus.RESOLVED,
        inferred_canonical_card=inferred_printing,
    )
    # same inferred_canonical_card, but UNRESOLVED - the artist fallback must NOT fire here.
    unresolved_inferred = CardFactory(
        identifier="op-unresolved-inferred",
        name="Operator Test Card",
        source=example_drive_1,
        printing_tag_status=PrintingTagStatus.UNRESOLVED,
        inferred_canonical_card=inferred_printing,
    )
    # rung 3: `inferred_canonical_artist` (artist-vote consensus only, no printing at all).
    vote_only = CardFactory(
        identifier="op-vote-only",
        name="Operator Test Card",
        source=example_drive_1,
        inferred_canonical_artist=vote_only_artist,
    )
    # no artist signal anywhere - must never match any artist: filter.
    no_artist_signal = CardFactory(
        identifier="op-no-artist",
        name="Operator Test Card",
        source=example_drive_1,
    )

    call_command("search_index", "--rebuild", "-f")
    return {
        "source": example_drive_1,
        "canonical_card_match": canonical_card_match,
        "non_matching_card": non_matching_card,
        "explicit_artist_override": explicit_artist_override,
        "resolved_inferred": resolved_inferred,
        "unresolved_inferred": unresolved_inferred,
        "vote_only": vote_only,
        "no_artist_signal": no_artist_signal,
    }


class TestArtistOperator:
    def test_matches_canonical_card_artist_case_insensitively(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card artist:guay")
        assert result["results"]["key1"] == [operator_card_set["canonical_card_match"].identifier]

    def test_matches_quoted_full_name(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, 'Operator Test Card artist:"Rebecca Guay"')
        assert result["results"]["key1"] == [operator_card_set["canonical_card_match"].identifier]

    def test_explicit_canonical_artist_overrides_canonical_card_artist(self, client, operator_card_set):
        # `explicit_artist_override` has canonical_card=other_printing (artist "Someone Else")
        # but canonical_artist="Override Only Artist" set directly - the explicit override must
        # win, so it must match THIS artist filter and NOT the "Someone Else" one its
        # `canonical_card` would otherwise resolve to.
        result = do_search(client, operator_card_set["source"].pk, 'Operator Test Card artist:"Override Only"')
        assert result["results"]["key1"] == [operator_card_set["explicit_artist_override"].identifier]

        someone_else_search = do_search(
            client, operator_card_set["source"].pk, 'Operator Test Card artist:"Someone Else"'
        )
        assert operator_card_set["explicit_artist_override"].identifier not in someone_else_search["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier in someone_else_search["results"]["key1"]

    def test_resolved_inferred_card_artist_matches(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card artist:Inferred")
        assert result["results"]["key1"] == [operator_card_set["resolved_inferred"].identifier]

    def test_unresolved_inferred_card_artist_does_not_match(self, client, operator_card_set):
        # same inferred_canonical_card as the RESOLVED case, but printing_tag_status is
        # UNRESOLVED - the fallback must not fire, so this card is absent from the artist match.
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card artist:Inferred")
        assert operator_card_set["unresolved_inferred"].identifier not in result["results"]["key1"]

    def test_vote_only_artist_matches_via_last_fallback_rung(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, 'Operator Test Card artist:"Vote Only"')
        assert result["results"]["key1"] == [operator_card_set["vote_only"].identifier]

    def test_no_artist_signal_never_matches(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card artist:guay")
        assert operator_card_set["no_artist_signal"].identifier not in result["results"]["key1"]

    def test_negated_artist_excludes_matching_card(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card -artist:guay")
        assert operator_card_set["canonical_card_match"].identifier not in result["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier in result["results"]["key1"]


class TestBorderAndFrameOperators:
    def test_border_matches_case_insensitively(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card border:borderless")
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier not in result["results"]["key1"]

    def test_border_uppercase_query_still_matches(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card border:BORDERLESS")
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]

    def test_frame_matches(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card frame:2015")
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier not in result["results"]["key1"]

    def test_negated_border(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card -border:borderless")
        assert operator_card_set["canonical_card_match"].identifier not in result["results"]["key1"]


class TestTagSetLangOperators:
    def test_tag_operator_compiles_to_existing_tags_field(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card tag:foil")
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier not in result["results"]["key1"]

    def test_negated_tag(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card -tag:foil")
        assert operator_card_set["canonical_card_match"].identifier not in result["results"]["key1"]

    def test_set_operator_compiles_to_expansion_code(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card set:ice")
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]
        assert operator_card_set["non_matching_card"].identifier not in result["results"]["key1"]

    def test_lang_operator_compiles_to_language(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card lang:ja")
        assert result["results"]["key1"] == [operator_card_set["non_matching_card"].identifier]

    def test_lang_operator_is_case_insensitive(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card lang:JA")
        assert result["results"]["key1"] == [operator_card_set["non_matching_card"].identifier]

    def test_combining_two_operators_ands_them_together(self, client, operator_card_set):
        # `tag:common` alone matches BOTH canonical_card_match and explicit_artist_override (both
        # carry that tag) - adding `set:ice` narrows to just canonical_card_match, since
        # explicit_artist_override's own `canonical_card` (other_printing) sits on `xln`, not
        # `ice`. This is the proof that two operators in one query AND together rather than
        # each independently loosening the result set.
        both_tagged = do_search(client, operator_card_set["source"].pk, "Operator Test Card tag:common")
        assert set(both_tagged["results"]["key1"]) == {
            operator_card_set["canonical_card_match"].identifier,
            operator_card_set["explicit_artist_override"].identifier,
        }

        narrowed = do_search(client, operator_card_set["source"].pk, "Operator Test Card tag:common set:ice")
        assert narrowed["results"]["key1"] == [operator_card_set["canonical_card_match"].identifier]


class TestUnknownOperatorResponse:
    def test_unknown_operator_is_reported_and_does_not_become_literal_text(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card power:4")
        assert result["operatorErrors"]["key1"] == ["unsupported operator: power"]
        # "power:4" was consumed as an error, not appended to the free-text match - the
        # remaining "Operator Test Card" text still matches every card sharing that name.
        assert operator_card_set["canonical_card_match"].identifier in result["results"]["key1"]

    def test_clean_query_has_no_operator_errors_key_populated(self, client, operator_card_set):
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card artist:guay")
        assert result.get("operatorErrors", {}) == {}


class TestPlainTextRegression:
    def test_plain_text_query_unaffected_by_operator_parsing(self, client, operator_card_set):
        """
        The regression this whole feature must never cause: a query with no `operator:` tokens
        at all returns EXACTLY what it did before this feature existed - every card sharing the
        searchable name, in the same (priority-then-source-order) order, nothing dropped, nothing
        added, no operatorErrors populated.
        """
        result = do_search(client, operator_card_set["source"].pk, "Operator Test Card")
        assert set(result["results"]["key1"]) == {
            operator_card_set["canonical_card_match"].identifier,
            operator_card_set["non_matching_card"].identifier,
            operator_card_set["explicit_artist_override"].identifier,
            operator_card_set["resolved_inferred"].identifier,
            operator_card_set["unresolved_inferred"].identifier,
            operator_card_set["vote_only"].identifier,
            operator_card_set["no_artist_signal"].identifier,
        }
        assert result.get("operatorErrors", {}) == {}
