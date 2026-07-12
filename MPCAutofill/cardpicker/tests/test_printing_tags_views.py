import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import CardPrintingTag, CardPrintingTagSource, PrintingTagStatus
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
)

# see test_printing_consensus.py for why this capture-and-restore fixture exists
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


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    # django-ratelimit's counters live in Django's cache, which isn't reset between tests
    # by default - clear it so one test's submissions can't affect another's rate limit.
    cache.clear()
    yield
    cache.clear()


class TestPostPrintingCandidates:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_defaults_to_same_oracle_id_when_card_has_a_canonical_card(self, client, django_settings):
        canonical_id = "11111111-1111-1111-1111-111111111111"
        printing_a = CanonicalCardFactory(canonical_id=canonical_id, name="Lightning Bolt")
        printing_b = CanonicalCardFactory(canonical_id=canonical_id, name="Lightning Bolt")
        unrelated = CanonicalCardFactory(name="Lightning Bolt")  # different (random) canonical_id
        card = CardFactory(canonical_card=printing_a)

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        assert response.status_code == 200
        result_identifiers = {result["identifier"] for result in response.json()["results"]}
        assert result_identifiers == {str(printing_a.identifier), str(printing_b.identifier)}
        assert str(unrelated.identifier) not in result_identifiers

    def test_defaults_to_same_oracle_id_when_card_has_an_inferred_canonical_card(self, client, django_settings):
        canonical_id = "22222222-2222-2222-2222-222222222222"
        printing_a = CanonicalCardFactory(canonical_id=canonical_id)
        printing_b = CanonicalCardFactory(canonical_id=canonical_id)
        card = CardFactory(inferred_canonical_card=printing_a)

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        result_identifiers = {result["identifier"] for result in response.json()["results"]}
        assert result_identifiers == {str(printing_a.identifier), str(printing_b.identifier)}

    def test_falls_back_to_name_search_when_no_link_exists(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        matching = CanonicalCardFactory(name="Brainstorm")
        CanonicalCardFactory(name="Opt")  # shouldn't match

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        result_identifiers = {result["identifier"] for result in response.json()["results"]}
        assert result_identifiers == {str(matching.identifier)}

    def test_explicit_query_searches_by_name_even_when_a_link_exists(self, client, django_settings):
        linked = CanonicalCardFactory(name="Lightning Bolt")
        card = CardFactory(canonical_card=linked)
        searched = CanonicalCardFactory(name="Opt")

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier, "query": "Opt"},
            content_type="application/json",
        )

        result_identifiers = {result["identifier"] for result in response.json()["results"]}
        assert result_identifiers == {str(searched.identifier)}
        assert str(linked.identifier) not in result_identifiers

    def test_candidate_shape_includes_printing_metadata_fields(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        printing = CanonicalCardFactory(name="Brainstorm")
        CanonicalPrintingMetadataFactory(canonical_card=printing, full_art=True, frame="1997")

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        [result] = response.json()["results"]
        assert result["fullArt"] is True
        assert result["frame"] == "1997"
        assert result["artist"] == printing.artist.name

    def test_candidate_without_printing_metadata_uses_defaults(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        CanonicalCardFactory(name="Brainstorm")  # no CanonicalPrintingMetadataFactory for this one

        response = client.post(
            reverse(views.post_printing_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        [result] = response.json()["results"]
        assert result["fullArt"] is False
        assert result["frame"] == ""
        assert result["releasedAt"] is None


class TestPostPrintingConsensus:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_printing_consensus),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_no_votes_yet(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_printing_consensus),
            {"identifier": card.identifier},
            content_type="application/json",
        )
        body = response.json()
        assert body["resolvedPrinting"] is None
        assert body["isNoMatch"] is False
        assert body["voteTally"] == []

    def test_resolved_consensus_and_tally(self, client, django_settings):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=CardPrintingTagSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=CardPrintingTagSource.USER)

        response = client.post(
            reverse(views.post_printing_consensus),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        body = response.json()
        assert body["resolvedPrinting"]["identifier"] == str(printing.identifier)
        assert body["isNoMatch"] is False
        assert {(entry["count"], entry["isNoMatch"]) for entry in body["voteTally"]} == {(2, False)}


class TestPostSubmitPrintingTag:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_printing_tag),
            {"identifier": "does-not-exist", "isNoMatch": True, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_missing_printing_identifier_without_no_match_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_printing_tag),
            {"identifier": card.identifier, "isNoMatch": False, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_printing_identifier_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_printing_tag),
            {
                "identifier": card.identifier,
                "printingIdentifier": "11111111-1111-1111-1111-111111111111",
                "isNoMatch": False,
                "anonymousId": "anon-1",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_creates_a_vote_and_persists_consensus(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()
        printing = CanonicalCardFactory()

        response = client.post(
            reverse(views.post_submit_printing_tag),
            {
                "identifier": card.identifier,
                "printingIdentifier": str(printing.identifier),
                "isNoMatch": False,
                "anonymousId": "anon-1",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["resolvedPrinting"]["identifier"] == str(printing.identifier)
        card.refresh_from_db()
        assert card.inferred_canonical_card_id == printing.id
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="anon-1").count() == 1

    def test_resubmitting_replaces_the_previous_vote_from_the_same_anonymous_id(self, client, django_settings):
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()

        for printing in (printing_a, printing_b):
            client.post(
                reverse(views.post_submit_printing_tag),
                {
                    "identifier": card.identifier,
                    "printingIdentifier": str(printing.identifier),
                    "isNoMatch": False,
                    "anonymousId": "anon-1",
                },
                content_type="application/json",
            )

        votes = CardPrintingTag.objects.filter(card=card, anonymous_id="anon-1")
        assert votes.count() == 1
        assert votes.get().printing_id == printing_b.id

    def test_no_match_vote(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()

        response = client.post(
            reverse(views.post_submit_printing_tag),
            {"identifier": card.identifier, "isNoMatch": True, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.json()["isNoMatch"] is True
        card.refresh_from_db()
        assert card.inferred_canonical_card is None
        assert card.printing_tag_status == PrintingTagStatus.NO_MATCH

    def test_contested_votes_leave_card_unresolved(self, client, django_settings):
        # default thresholds: a single user vote alone isn't enough to resolve anything
        card = CardFactory()
        printing = CanonicalCardFactory()

        response = client.post(
            reverse(views.post_submit_printing_tag),
            {
                "identifier": card.identifier,
                "printingIdentifier": str(printing.identifier),
                "isNoMatch": False,
                "anonymousId": "anon-1",
            },
            content_type="application/json",
        )

        assert response.json()["resolvedPrinting"] is None
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        printing = CanonicalCardFactory()
        body = {
            "identifier": card.identifier,
            "printingIdentifier": str(printing.identifier),
            "isNoMatch": False,
            "anonymousId": "anon-rate-limited",
        }

        first = client.post(reverse(views.post_submit_printing_tag), body, content_type="application/json")
        second = client.post(reverse(views.post_submit_printing_tag), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429

    def test_rate_limit_is_keyed_by_anonymous_id_not_globally(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        printing = CanonicalCardFactory()

        first = client.post(
            reverse(views.post_submit_printing_tag),
            {
                "identifier": card.identifier,
                "printingIdentifier": str(printing.identifier),
                "isNoMatch": False,
                "anonymousId": "anon-a",
            },
            content_type="application/json",
        )
        second = client.post(
            reverse(views.post_submit_printing_tag),
            {
                "identifier": card.identifier,
                "printingIdentifier": str(printing.identifier),
                "isNoMatch": False,
                "anonymousId": "anon-b",
            },
            content_type="application/json",
        )

        assert first.status_code == 200
        assert second.status_code == 200


class TestGetPrintingTagQueue:
    def test_only_unresolved_cards_are_returned(self, client, django_settings):
        unresolved = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardFactory(printing_tag_status=PrintingTagStatus.NO_MATCH)

        response = client.get(reverse(views.get_printing_tag_queue))

        assert response.status_code == 200
        body = response.json()
        assert body["hits"] == 1
        assert [card["identifier"] for card in body["cards"]] == [unresolved.identifier]

    def test_contested_cards_are_returned_first(self, client, django_settings):
        # `contested` is created *before* `uncontested`, so a plain "-date_created" ordering
        # (with no regard for contested status) would put `uncontested` first - proving that
        # the contested-first behaviour, not incidental recency, drives this ordering.
        contested = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=contested, printing=printing_a)
        CardPrintingTagFactory(card=contested, printing=printing_b)
        uncontested = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        response = client.get(reverse(views.get_printing_tag_queue))

        assert response.status_code == 200
        identifiers = [card["identifier"] for card in response.json()["cards"]]
        assert identifiers == [contested.identifier, uncontested.identifier]

    def test_invalid_page_is_a_bad_request(self, client, django_settings):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        response = client.get(reverse(views.get_printing_tag_queue), {"page": "999"})

        assert response.status_code == 400

    def test_non_get_method_is_rejected(self, client, django_settings):
        response = client.post(reverse(views.get_printing_tag_queue))
        assert response.status_code == 400
