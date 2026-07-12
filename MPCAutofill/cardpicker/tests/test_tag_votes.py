import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import CardTagVote, VotePolarity, VoteSource
from cardpicker.tag_consensus import (
    get_resolved_tag_overlay,
    get_tag_vote_tally,
    resolve_and_persist_tag_votes,
    resolve_tag,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardTagVoteFactory,
    SourceFactory,
    TagFactory,
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


class TestResolveTag:
    def test_no_votes_returns_none(self, db):
        card = CardFactory()
        tag = TagFactory()
        assert resolve_tag(card, tag) is None

    def test_apply_consensus(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert resolve_tag(card, tag) == VotePolarity.APPLY

    def test_not_applicable_consensus(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)
        assert resolve_tag(card, tag) == VotePolarity.NOT_APPLICABLE

    def test_votes_on_a_different_tag_are_not_counted(self, db):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        assert resolve_tag(card, tag_b) is None


class TestResolveAndPersistTagVotes:
    def test_applies_a_resolved_apply_vote(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Borderless"]

    def test_removes_a_resolved_not_applicable_vote(self, db):
        card = CardFactory(tags=["Borderless"])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == []

    def test_unresolved_tag_does_not_change_tags(self, db):
        card = CardFactory(tags=["Existing"])
        tag = TagFactory(name="Contested")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Existing"]

    def test_multiple_tags_resolve_independently_on_the_same_card(self, db):
        card = CardFactory(tags=[])
        apply_tag = TagFactory(name="Apply Me")
        reject_tag = TagFactory(name="Reject Me")
        CardTagVoteFactory(card=card, tag=apply_tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        CardTagVoteFactory(card=card, tag=reject_tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Apply Me"]


class TestGetTagVoteTally:
    def test_tally_groups_by_polarity(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE)

        tally = get_tag_vote_tally(card, tag)

        assert {(entry["polarity"], entry["count"]) for entry in tally} == {(1, 2), (-1, 1)}


class TestGetResolvedTagOverlay:
    def test_batches_across_multiple_cards_and_tags(self, db):
        card_a = CardFactory()
        card_b = CardFactory()
        tag_a = TagFactory(name="Tag A")
        tag_b = TagFactory(name="Tag B")
        CardTagVoteFactory(card=card_a, tag=tag_a, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        CardTagVoteFactory(card=card_b, tag=tag_b, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        overlay = get_resolved_tag_overlay([card_a.pk, card_b.pk])

        assert overlay == {card_a.pk: {"Tag A": 1}, card_b.pk: {"Tag B": -1}}

    def test_unresolved_pairs_are_omitted(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        overlay = get_resolved_tag_overlay([card.pk])

        assert overlay == {}


class TestPostTagConsensus:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_tag_consensus),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_returns_an_entry_for_every_seeded_tag(self, client, django_settings):
        card = CardFactory()
        TagFactory(name="Tag A")
        TagFactory(name="Tag B")

        response = client.post(
            reverse(views.post_tag_consensus),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        body = response.json()
        assert {entry["tagName"] for entry in body["tags"]} == {"Tag A", "Tag B"}
        assert all(entry["resolvedPolarity"] is None for entry in body["tags"])


class TestPostSubmitTagVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": "does-not-exist", "tagName": "x", "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_tag_name_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": "does-not-exist", "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_invalid_polarity_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 99, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_creates_a_vote_and_persists_consensus(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")

        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["resolvedPolarity"] == 1
        card.refresh_from_db()
        assert card.tags == ["Borderless"]
        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 1

    def test_changing_your_mind_updates_the_same_row_rather_than_adding_another(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()

        for polarity in (1, -1):
            client.post(
                reverse(views.post_submit_tag_vote),
                {"identifier": card.identifier, "tagName": tag.name, "polarity": polarity, "anonymousId": "anon-1"},
                content_type="application/json",
            )

        votes = CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1")
        assert votes.count() == 1
        assert votes.get().polarity == -1

    def test_a_vote_on_one_tag_does_not_clear_a_vote_on_another_tag_by_the_same_person(self, client, django_settings):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()

        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag_a.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag_b.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert CardTagVote.objects.filter(card=card, anonymous_id="anon-1").count() == 2

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        tag = TagFactory()
        body = {
            "identifier": card.identifier,
            "tagName": tag.name,
            "polarity": 1,
            "anonymousId": "anon-rate-limited",
        }

        first = client.post(reverse(views.post_submit_tag_vote), body, content_type="application/json")
        second = client.post(reverse(views.post_submit_tag_vote), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429
