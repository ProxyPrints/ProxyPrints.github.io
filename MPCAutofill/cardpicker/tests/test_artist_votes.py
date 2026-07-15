import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.artist_consensus import (
    UNKNOWN,
    get_artist_vote_tally,
    get_contested_artist_card_ids,
    resolve_and_persist_artist,
    resolve_artist,
)
from cardpicker.models import ArtistVoteStatus, CardArtistVote, VoteSource
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardArtistVoteFactory,
    CardFactory,
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
    cache.clear()
    yield
    cache.clear()


class TestResolveArtist:
    def test_no_votes_returns_none(self, db):
        card = CardFactory()
        assert resolve_artist(card) is None

    def test_consensus(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        assert resolve_artist(card) == artist

    def test_unknown_wins_consensus(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=None, is_unknown=True, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=None, is_unknown=True, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        assert resolve_artist(card) == UNKNOWN

    def test_admin_override(self, db):
        card = CardFactory()
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist_a, source=VoteSource.ADMIN)
        CardArtistVoteFactory(card=card, artist=artist_b, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist_b, source=VoteSource.USER)
        assert resolve_artist(card) == artist_a

    def test_ai_only_insufficient(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        for _ in range(4):
            CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.DEDUCTION)
        assert resolve_artist(card) is None


class TestResolveAndPersistArtist:
    def test_persists_resolved_artist(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.ADMIN)

        result = resolve_and_persist_artist(card)

        assert result == artist
        card.refresh_from_db()
        assert card.inferred_canonical_artist == artist
        assert card.artist_vote_status == ArtistVoteStatus.RESOLVED

    def test_persists_unknown(self, db):
        card = CardFactory()
        CardArtistVoteFactory(card=card, artist=None, is_unknown=True, source=VoteSource.ADMIN)

        result = resolve_and_persist_artist(card)

        assert result == UNKNOWN
        card.refresh_from_db()
        assert card.inferred_canonical_artist is None
        assert card.artist_vote_status == ArtistVoteStatus.UNKNOWN

    def test_persists_unresolved(self, db):
        card = CardFactory()
        CardArtistVoteFactory(card=card, source=VoteSource.USER)

        result = resolve_and_persist_artist(card)

        assert result is None
        card.refresh_from_db()
        assert card.inferred_canonical_artist is None
        assert card.artist_vote_status == ArtistVoteStatus.UNRESOLVED

    def test_persists_contested_when_multiple_outcomes_have_votes(self, db):
        card = CardFactory()
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist_a, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist_b, source=VoteSource.USER)

        result = resolve_and_persist_artist(card)

        assert result is None
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED

    def test_persists_unresolved_not_contested_for_a_single_outcome_below_threshold(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)

        result = resolve_and_persist_artist(card)

        assert result is None
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.UNRESOLVED

    def test_does_not_consult_printing_tag_status(self, db):
        # resolve_and_persist_artist is deliberately decoupled from printing_tag_status - the
        # precedence rule (a resolved printing's artist wins) lives entirely in
        # Card.serialise()'s fallback chain, not here.
        from cardpicker.models import PrintingTagStatus

        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.ADMIN)

        result = resolve_and_persist_artist(card)

        assert result == artist
        card.refresh_from_db()
        assert card.inferred_canonical_artist == artist


class TestGetArtistVoteTally:
    def test_tally_groups_by_outcome(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist)
        CardArtistVoteFactory(card=card, artist=artist)
        CardArtistVoteFactory(card=card, artist=None, is_unknown=True)

        tally = get_artist_vote_tally(card)

        assert {(entry["count"], entry["is_unknown"]) for entry in tally} == {(2, False), (1, True)}


class TestGetContestedArtistCardIds:
    def test_multiple_distinct_artists_is_contested(self, db):
        card = CardFactory()
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist_a)
        CardArtistVoteFactory(card=card, artist=artist_b)

        assert card.pk in get_contested_artist_card_ids()

    def test_an_artist_vote_alongside_an_unknown_vote_is_contested(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist)
        CardArtistVoteFactory(card=card, artist=None, is_unknown=True)

        assert card.pk in get_contested_artist_card_ids()

    def test_agreeing_votes_are_not_contested(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist)
        CardArtistVoteFactory(card=card, artist=artist)

        assert card.pk not in get_contested_artist_card_ids()


class TestSerialisePrecedenceChain:
    def test_falls_back_to_inferred_canonical_artist(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory(name="Vote Artist")
        card.inferred_canonical_artist = artist
        card.save(update_fields=["inferred_canonical_artist"])

        assert card.serialise().canonicalArtist.name == "Vote Artist"

    def test_resolved_printing_artist_beats_inferred_canonical_artist(self, db):
        printing = CanonicalCardFactory()
        card = CardFactory(inferred_canonical_card=printing)
        vote_artist = CanonicalArtistFactory(name="Vote Artist")
        card.inferred_canonical_artist = vote_artist
        card.save(update_fields=["inferred_canonical_artist"])

        assert card.serialise().canonicalArtist.name == printing.artist.name
        assert card.serialise().canonicalArtist.name != "Vote Artist"

    def test_confirmed_canonical_card_artist_beats_everything_inferred(self, db):
        confirmed = CanonicalCardFactory()
        inferred = CanonicalCardFactory()
        card = CardFactory(canonical_card=confirmed, inferred_canonical_card=inferred)

        assert card.serialise().canonicalArtist.name == confirmed.artist.name


class TestPostArtistCandidates:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_artist_candidates),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_defaults_to_deduped_artists_of_ranked_printing_candidates(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Brainstorm", artist=artist)
        CanonicalCardFactory(name="Brainstorm", artist=artist)  # same artist, shouldn't duplicate

        response = client.post(
            reverse(views.post_artist_candidates),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert [result["name"] for result in response.json()["results"]] == [artist.name]

    def test_query_switches_to_typeahead_search(self, client, django_settings):
        card = CardFactory()
        matching = CanonicalArtistFactory(name="John Avon")
        CanonicalArtistFactory(name="Someone Else")

        response = client.post(
            reverse(views.post_artist_candidates),
            {"identifier": card.identifier, "query": "Avon"},
            content_type="application/json",
        )

        result_names = {result["name"] for result in response.json()["results"]}
        assert result_names == {matching.name}


class TestPostArtistConsensus:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_artist_consensus),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_no_votes_yet(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_artist_consensus),
            {"identifier": card.identifier},
            content_type="application/json",
        )
        body = response.json()
        assert body["resolvedArtist"] is None
        assert body["isUnknown"] is False
        assert body["voteTally"] == []


class TestPostSubmitArtistVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_artist_vote),
            {"identifier": "does-not-exist", "isUnknown": True, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_missing_artist_name_without_unknown_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_vote),
            {"identifier": card.identifier, "isUnknown": False, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_artist_name_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_artist_vote),
            {
                "identifier": card.identifier,
                "artistName": "Nobody By This Name",
                "isUnknown": False,
                "anonymousId": "anon-1",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_creates_a_vote_and_persists_consensus(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()
        artist = CanonicalArtistFactory()

        response = client.post(
            reverse(views.post_submit_artist_vote),
            {
                "identifier": card.identifier,
                "artistName": artist.name,
                "isUnknown": False,
                "anonymousId": "anon-1",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["resolvedArtist"]["name"] == artist.name
        card.refresh_from_db()
        assert card.inferred_canonical_artist_id == artist.id
        assert card.artist_vote_status == ArtistVoteStatus.RESOLVED
        assert CardArtistVote.objects.filter(card=card, anonymous_id="anon-1").count() == 1

    def test_resubmitting_replaces_the_previous_vote_from_the_same_anonymous_id(self, client, django_settings):
        card = CardFactory()
        artist_a = CanonicalArtistFactory()
        artist_b = CanonicalArtistFactory()

        for artist in (artist_a, artist_b):
            client.post(
                reverse(views.post_submit_artist_vote),
                {
                    "identifier": card.identifier,
                    "artistName": artist.name,
                    "isUnknown": False,
                    "anonymousId": "anon-1",
                },
                content_type="application/json",
            )

        votes = CardArtistVote.objects.filter(card=card, anonymous_id="anon-1")
        assert votes.count() == 1
        assert votes.get().artist_id == artist_b.id

    def test_unknown_vote(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory()

        response = client.post(
            reverse(views.post_submit_artist_vote),
            {"identifier": card.identifier, "isUnknown": True, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.json()["isUnknown"] is True
        card.refresh_from_db()
        assert card.inferred_canonical_artist is None
        assert card.artist_vote_status == ArtistVoteStatus.UNKNOWN

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        artist = CanonicalArtistFactory()
        body = {
            "identifier": card.identifier,
            "artistName": artist.name,
            "isUnknown": False,
            "anonymousId": "anon-rate-limited",
        }

        first = client.post(reverse(views.post_submit_artist_vote), body, content_type="application/json")
        second = client.post(reverse(views.post_submit_artist_vote), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429
