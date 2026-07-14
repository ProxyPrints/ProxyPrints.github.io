"""
End-to-end tests for vote-system Stage 3 ("consumption"): printing-preferred search re-rank
and resolved-attribute filters, exercised through the real `post_editor_search` endpoint and a
real (testcontainers) Elasticsearch index - proving the whole pipeline (widened
get_expansion_code/get_collector_number indexing -> the pre-existing hard ES filter -> the new
post-fetch re-rank/filter step in `retrieve_card_identifiers`) works together, not just its
individual pieces in isolation (see test_printing_consensus.py::TestGetResolvedPrintings and
test_search_functions.py for those).
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
    SourceFactory,
)

# `factory.Sequence` counters are process-global across the whole pytest session - a fresh
# test file using these shared factories shifts sequence-derived values (e.g. "Artist 0")
# that other test files' snapshots hardcode, purely based on collection order. See
# test_printing_consensus.py's identical fixture and docs/lessons.md for the full story.
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


BASE_SEARCH_SETTINGS = {
    "searchTypeSettings": {"fuzzySearch": False, "filterCardbacks": False},
    "sourceSettings": {"sources": []},  # populated per-test with the actual source pk
    "filterSettings": {
        "minimumDPI": 0,
        "maximumDPI": 1500,
        "maximumSize": 30,
        "languages": [],
        "includesTags": [],
        "excludesTags": [],
        "fullArtOnly": False,
        "borderlessOnly": False,
    },
}


def search_settings_for(source_pk: int, **filter_overrides) -> dict:
    settings = {
        "searchTypeSettings": {"fuzzySearch": False, "filterCardbacks": False},
        "sourceSettings": {"sources": [[source_pk, True]]},
        "filterSettings": {**BASE_SEARCH_SETTINGS["filterSettings"], **filter_overrides},
    }
    return settings


@pytest.fixture()
def resolved_and_unresolved_cards(django_settings, elasticsearch, example_drive_1):
    """
    A minimal, self-contained card set (deliberately not reusing conftest's `all_cards`, to
    avoid interaction with its pre-existing canonical_card/name fixtures) - two cards sharing
    the same searchable name and the same underlying printing.

    `unresolved_card` has `canonical_card` set (the pre-existing, deterministic "confirmed
    indexing match" mechanism, unrelated to voting - e.g. set from the source file's own
    tags at ingestion time) but has never been community-vote-resolved (UNRESOLVED, the
    default - nobody needed to vote on it, since its printing was already confidently known).
    `resolved_card` has NO `canonical_card` (nothing to key off deterministically) but HAS
    been community-vote-resolved to the exact same printing.

    This is the realistic scenario the re-rank boost targets: both cards survive the
    pre-existing ES hard filter (one via `canonical_card` directly, one only via the widened
    get_expansion_code/get_collector_number fallback for RESOLVED cards) - and among those
    survivors, the vote-confirmed one should be preferred.
    """
    expansion = CanonicalExpansionFactory(code="ice")
    printing = CanonicalCardFactory(expansion=expansion, collector_number="61")
    CanonicalPrintingMetadataFactory(canonical_card=printing, full_art=True, border_color="borderless")

    resolved_card = CardFactory(
        identifier="consumption-resolved",
        name="Consumption Test Card",
        source=example_drive_1,
        priority=1,
        printing_tag_status=PrintingTagStatus.RESOLVED,
        inferred_canonical_card=printing,
    )
    unresolved_card = CardFactory(
        identifier="consumption-unresolved",
        name="Consumption Test Card",
        source=example_drive_1,
        priority=5,  # higher priority - would rank first under today's (pre-re-rank) order
        canonical_card=printing,
        printing_tag_status=PrintingTagStatus.UNRESOLVED,
    )
    call_command("search_index", "--rebuild", "-f")
    return resolved_card, unresolved_card, example_drive_1, printing


class TestPrintingPreferredReRank:
    def test_resolved_exact_match_ranks_above_higher_priority_unresolved_card(
        self, client, resolved_and_unresolved_cards
    ):
        resolved_card, unresolved_card, source, printing = resolved_and_unresolved_cards
        response = client.post(
            reverse(views.post_editor_search),
            {
                "searchSettings": search_settings_for(source.pk),
                "queries": {
                    "key1": {
                        "query": "Consumption Test Card",
                        "cardType": "CARD",
                        "expansionCode": "ICE",
                        "collectorNumber": "61",
                    }
                },
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        results = response.json()["results"]["key1"]
        # both survive the (widened) hard ES filter, but the RESOLVED exact match is boosted
        # above the UNRESOLVED card despite the latter's higher `priority` - this is the "today's
        # name-rank order is only the fallback, not the ceiling" behavior item 2 asked for.
        assert results == [resolved_card.identifier, unresolved_card.identifier]

    def test_no_set_data_in_query_leaves_todays_order_unchanged(self, client, resolved_and_unresolved_cards):
        resolved_card, unresolved_card, source, printing = resolved_and_unresolved_cards
        response = client.post(
            reverse(views.post_editor_search),
            {
                "searchSettings": search_settings_for(source.pk),
                "queries": {"key1": {"query": "Consumption Test Card", "cardType": "CARD"}},
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        results = response.json()["results"]["key1"]
        # hard gate: with no set/collector in the query, the re-rank step never activates -
        # today's priority-based order (unresolved_card has higher priority) is unchanged.
        assert results == [unresolved_card.identifier, resolved_card.identifier]


class TestResolvedAttributeFilters:
    def test_full_art_only_excludes_resolved_non_matching_card_but_keeps_unresolved_visible(
        self, client, resolved_and_unresolved_cards
    ):
        resolved_card, unresolved_card, source, printing = resolved_and_unresolved_cards
        # flip the resolved printing to NOT full art for this test
        printing.printing_metadata.full_art = False
        printing.printing_metadata.save()

        response = client.post(
            reverse(views.post_editor_search),
            {
                "searchSettings": search_settings_for(source.pk, fullArtOnly=True),
                "queries": {"key1": {"query": "Consumption Test Card", "cardType": "CARD"}},
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        results = response.json()["results"]["key1"]
        # the RESOLVED-but-not-full-art card is excluded; the UNRESOLVED card is an unknown,
        # not a mismatch, and must remain visible even with the filter active.
        assert results == [unresolved_card.identifier]

    def test_full_art_only_includes_resolved_matching_card(self, client, resolved_and_unresolved_cards):
        resolved_card, unresolved_card, source, printing = resolved_and_unresolved_cards
        # printing_metadata.full_art is True per the fixture setup
        response = client.post(
            reverse(views.post_editor_search),
            {
                "searchSettings": search_settings_for(source.pk, fullArtOnly=True),
                "queries": {"key1": {"query": "Consumption Test Card", "cardType": "CARD"}},
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        results = response.json()["results"]["key1"]
        assert set(results) == {resolved_card.identifier, unresolved_card.identifier}

    def test_filter_off_by_default_shows_everything(self, client, resolved_and_unresolved_cards):
        resolved_card, unresolved_card, source, printing = resolved_and_unresolved_cards
        response = client.post(
            reverse(views.post_editor_search),
            {
                "searchSettings": search_settings_for(source.pk),  # fullArtOnly/borderlessOnly default False
                "queries": {"key1": {"query": "Consumption Test Card", "cardType": "CARD"}},
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        results = response.json()["results"]["key1"]
        assert set(results) == {resolved_card.identifier, unresolved_card.identifier}
