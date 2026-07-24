from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    ArtistVoteStatus,
    PrintingTagStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    TagFactory,
)


def _post_vote_queue(client, kind: str, page: int = 1):
    return client.post(
        reverse(views.post_vote_queue),
        {"kind": kind, "page": page},
        content_type="application/json",
    )


class TestPostVoteQueuePrinting:
    def test_only_unresolved_cards_are_returned(self, client, django_settings):
        unresolved = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardFactory(printing_tag_status=PrintingTagStatus.NO_MATCH)

        response = _post_vote_queue(client, "printing")

        assert response.status_code == 200
        body = response.json()
        assert body["hits"] == 1
        assert [item["card"]["identifier"] for item in body["items"]] == [unresolved.identifier]
        assert all(item["tagName"] is None for item in body["items"])

    def test_contested_cards_are_returned_first(self, client, django_settings):
        contested = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=contested, printing=printing_a)
        CardPrintingTagFactory(card=contested, printing=printing_b)
        uncontested = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        response = _post_vote_queue(client, "printing")

        identifiers = [item["card"]["identifier"] for item in response.json()["items"]]
        assert identifiers == [contested.identifier, uncontested.identifier]

    def test_invalid_page_is_a_bad_request(self, client, django_settings):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        response = _post_vote_queue(client, "printing", page=999)

        assert response.status_code == 400

    def test_non_post_method_is_rejected(self, client, django_settings):
        response = client.get(reverse(views.post_vote_queue))
        assert response.status_code == 400

    def test_invalid_kind_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_vote_queue),
            {"kind": "not-a-real-kind", "page": 1},
            content_type="application/json",
        )
        assert response.status_code == 400


class TestPostVoteQueueArtist:
    def test_only_unresolved_and_contested_cards_are_returned(self, client, django_settings):
        unresolved = CardFactory(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        CardFactory(artist_vote_status=ArtistVoteStatus.RESOLVED)
        CardFactory(artist_vote_status=ArtistVoteStatus.UNKNOWN)
        contested = CardFactory(artist_vote_status=ArtistVoteStatus.CONTESTED)

        response = _post_vote_queue(client, "artist")

        identifiers = {item["card"]["identifier"] for item in response.json()["items"]}
        assert identifiers == {unresolved.identifier, contested.identifier}

    def test_contested_cards_are_returned_first(self, client, django_settings):
        contested = CardFactory(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()
        CardArtistVoteFactory(card=contested, artist=artist_a)
        CardArtistVoteFactory(card=contested, artist=artist_b)
        uncontested = CardFactory(artist_vote_status=ArtistVoteStatus.UNRESOLVED)

        response = _post_vote_queue(client, "artist")

        identifiers = [item["card"]["identifier"] for item in response.json()["items"]]
        assert identifiers == [contested.identifier, uncontested.identifier]


class TestPostVoteQueueTag:
    def test_resolved_pairs_are_excluded(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)

        response = _post_vote_queue(client, "tag")

        assert response.json()["items"] == []

    def test_a_resolved_pair_stays_excluded_even_as_unrelated_votes_trickle_in(self, client, django_settings):
        # regression guard matching the plan's "persisted state, not raw vote existence"
        # requirement - once resolved, new votes on a *different* tag on the same card must
        # not resurface the already-resolved pair
        card = CardFactory(tags=[])
        resolved_tag = TagFactory(name="Borderless")
        other_tag = TagFactory(name="Extended")
        CardTagVoteFactory(card=card, tag=resolved_tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)

        CardTagVoteFactory(card=card, tag=other_tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        resolve_and_persist_tag_votes(card)

        response = _post_vote_queue(client, "tag")

        tag_names = {item["tagName"] for item in response.json()["items"]}
        assert "Borderless" not in tag_names
        assert "Extended" in tag_names

    def test_contested_pair_outranks_a_less_contested_pair(self, client, django_settings):
        # a 1-vs-1 split (net weight 0) is a closer contest than a lone unresolved vote
        # (net weight 1) and should sort first
        contested_card = CardFactory(tags=[])
        contested_tag = TagFactory(name="Contested Tag")
        CardTagVoteFactory(card=contested_card, tag=contested_tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(
            card=contested_card, tag=contested_tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER
        )
        resolve_and_persist_tag_votes(contested_card)

        lopsided_card = CardFactory(tags=[])
        lopsided_tag = TagFactory(name="Lopsided Tag")
        CardTagVoteFactory(card=lopsided_card, tag=lopsided_tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        resolve_and_persist_tag_votes(lopsided_card)

        response = _post_vote_queue(client, "tag")

        tag_names = [item["tagName"] for item in response.json()["items"]]
        assert tag_names[0] == "Contested Tag"

    def test_items_include_the_tag_name(self, client, django_settings):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Showcase")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        resolve_and_persist_tag_votes(card)

        response = _post_vote_queue(client, "tag")

        [item] = response.json()["items"]
        assert item["tagName"] == "Showcase"
        assert item["card"]["identifier"] == card.identifier
