import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    ArtistVoteStatus,
    CanonicalArtist,
    CardArtistVote,
    VoteSource,
)
from cardpicker.tests.factories import CanonicalArtistFactory, CardFactory


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


class TestPostArtistAutocomplete:
    def test_query_too_short_after_cleaning_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": " a "}, content_type="application/json"
        )
        assert response.status_code == 400

    def test_query_over_max_length_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": "a" * 101}, content_type="application/json"
        )
        assert response.status_code == 400

    def test_prefix_matches_are_case_insensitive(self, client, django_settings):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        CanonicalArtistFactory(name="Someone Else")

        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": "rebecca"}, content_type="application/json"
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert results == [{"id": artist.pk, "name": artist.name}]

    def test_prefix_matches_sort_before_substring_matches(self, client, django_settings):
        substring = CanonicalArtistFactory(name="John Substring Avon")
        prefix = CanonicalArtistFactory(name="Avon Prefix")

        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": "avon"}, content_type="application/json"
        )

        names = [result["name"] for result in response.json()["results"]]
        assert names == [prefix.name, substring.name]

    def test_results_are_capped_at_the_page_size(self, client, django_settings):
        for i in range(15):
            CanonicalArtistFactory(name=f"Capped Artist {i:02}")

        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": "Capped Artist"}, content_type="application/json"
        )

        assert len(response.json()["results"]) == 10

    def test_no_matches_returns_empty_results(self, client, django_settings):
        response = client.post(
            reverse(views.post_artist_autocomplete), {"query": "nobody"}, content_type="application/json"
        )
        assert response.json()["results"] == []

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.ARTIST_AUTOCOMPLETE_RATE = "1/m"
        CanonicalArtistFactory(name="Rate Limited Artist")

        first = client.post(reverse(views.post_artist_autocomplete), {"query": "Rate"}, content_type="application/json")
        second = client.post(
            reverse(views.post_artist_autocomplete), {"query": "Rate"}, content_type="application/json"
        )

        assert first.status_code == 200
        assert second.status_code == 429


class TestPostSubmitArtistWriteInVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": "does-not-exist", "anonymousId": "anon-1", "freeText": "New Artist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_neither_artist_id_nor_free_text_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_both_artist_id_and_free_text_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {
                "identifier": card.identifier,
                "anonymousId": "anon-1",
                "artistId": artist.pk,
                "freeText": "New Artist",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_artist_id_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "artistId": 999999},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_blank_free_text_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "freeText": "   "},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_free_text_over_max_length_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "freeText": "a" * 101},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_artist_id_path_casts_a_vote_against_the_existing_artist(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()
        artist = CanonicalArtistFactory()

        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "artistId": artist.pk},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["createdNewArtist"] is False
        assert body["castArtist"] == {"id": artist.pk, "name": artist.name}
        assert body["resolvedArtist"]["name"] == artist.name
        card.refresh_from_db()
        assert card.inferred_canonical_artist_id == artist.id
        assert card.artist_vote_status == ArtistVoteStatus.RESOLVED
        vote = CardArtistVote.objects.get(card=card, anonymous_id="anon-1")
        assert vote.artist_id == artist.id
        assert vote.source == VoteSource.USER
        assert vote.is_unknown is False

    def test_free_text_creates_a_new_artist_when_no_match_exists(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()

        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "freeText": "  Brand   New Artist  "},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["createdNewArtist"] is True
        assert body["castArtist"]["name"] == "Brand New Artist"
        new_artist = CanonicalArtist.objects.get(name="Brand New Artist")
        card.refresh_from_db()
        assert card.inferred_canonical_artist_id == new_artist.id

    def test_free_text_reuses_an_existing_artist_case_insensitively_no_twin_row(
        self, client, django_settings, settings
    ):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()
        existing = CanonicalArtistFactory(name="Rebecca Guay")

        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "freeText": "rebecca guay"},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["createdNewArtist"] is False
        assert body["castArtist"] == {"id": existing.pk, "name": existing.name}
        assert CanonicalArtist.objects.filter(name__iexact="rebecca guay").count() == 1
        vote = CardArtistVote.objects.get(card=card, anonymous_id="anon-1")
        assert vote.artist_id == existing.id

    def test_resubmitting_replaces_the_previous_vote_from_the_same_anonymous_id(self, client, django_settings):
        card = CardFactory()
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()

        for artist in (artist_a, artist_b):
            client.post(
                reverse(views.post_submit_artist_writein_vote),
                {"identifier": card.identifier, "anonymousId": "anon-1", "artistId": artist.pk},
                content_type="application/json",
            )

        votes = CardArtistVote.objects.filter(card=card, anonymous_id="anon-1")
        assert votes.count() == 1
        assert votes.get().artist_id == artist_b.id

    def test_conflicting_write_in_votes_land_as_contested_not_resolved(self, client, django_settings):
        # default PRINTING_TAG_MIN_VOTES=2/MIN_SHARE=0.6: two distinct outcomes at weight 1 each
        # clear the vote-count floor but neither reaches the 0.6 share needed to win, so this
        # should land CONTESTED (junk/disagreement doesn't silently resolve) rather than
        # RESOLVED - same standard gate every other artist vote goes through, unmodified.
        card = CardFactory()
        artist = CanonicalArtistFactory(name="Existing Artist")

        client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-a", "artistId": artist.pk},
            content_type="application/json",
        )
        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-b", "freeText": "A Different Artist"},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["resolvedArtist"] is None
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED
        assert card.inferred_canonical_artist is None

    def test_untrusted_origin_is_rejected(self, client, django_settings):
        card = CardFactory()
        artist = CanonicalArtistFactory()

        response = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "artistId": artist.pk},
            content_type="application/json",
            HTTP_ORIGIN="https://evil.example.com",
        )

        assert response.status_code == 403

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        artist = CanonicalArtistFactory()
        body = {"identifier": card.identifier, "anonymousId": "anon-rate-limited", "artistId": artist.pk}

        first = client.post(reverse(views.post_submit_artist_writein_vote), body, content_type="application/json")
        second = client.post(reverse(views.post_submit_artist_writein_vote), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429

    def test_shares_the_rate_budget_with_post_submit_artist_vote(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        artist = CanonicalArtistFactory()

        first = client.post(
            reverse(views.post_submit_artist_vote),
            {
                "identifier": card.identifier,
                "artistName": artist.name,
                "isUnknown": False,
                "anonymousId": "anon-shared",
            },
            content_type="application/json",
        )
        second = client.post(
            reverse(views.post_submit_artist_writein_vote),
            {"identifier": card.identifier, "anonymousId": "anon-shared", "artistId": artist.pk},
            content_type="application/json",
        )

        assert first.status_code == 200
        assert second.status_code == 429
