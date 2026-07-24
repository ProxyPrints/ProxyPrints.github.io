import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    CardTagVote,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import CardFactory, CardTagVoteFactory, TagFactory
from cardpicker.views import (
    IMPLICIT_VOTE_SURFACE,
    _cast_implicit_vote_and_resolve,
    _retract_implicit_vote_and_resolve,
)


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


class TestCastImplicitVoteAndResolve:
    """
    Direct coverage of `_cast_implicit_vote_and_resolve`'s write-side guards (owner-ratified
    2026-07-22 vote-weight scenario matrix, "write-side guards"/prior condition 8, and D7's
    lifecycle - one implicit vote per (identity, card, tag), a later pick supersedes).
    """

    def test_casts_a_fresh_implicit_vote(self, db):
        card = CardFactory()
        tag = TagFactory()

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.source == VoteSource.IMPLICIT
        assert vote.polarity == VotePolarity.APPLY
        assert vote.vote_surface == IMPLICIT_VOTE_SURFACE
        assert vote.user is None

    def test_a_later_implicit_pick_by_the_same_identity_supersedes_the_earlier_one(self, db):
        card = CardFactory()
        tag = TagFactory()

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")
        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 1

    def test_never_overwrites_a_real_vote_by_the_same_identity(self, db):
        # the (card, tag, anonymous_id) uniqueness constraint is shared across every source -
        # an implicit cast must never silently downgrade a real vote to an implicit one just
        # because the same identity later browsed with this tag's filter chip active.
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(
            card=card, tag=tag, anonymous_id="anon-1", polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER
        )

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.source == VoteSource.USER
        assert vote.polarity == VotePolarity.NOT_APPLICABLE

    def test_sensitive_tags_never_accept_an_implicit_vote(self, db):
        card = CardFactory()
        tag = TagFactory(moderation_class=TagModerationClass.SENSITIVE)

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 0

    @pytest.mark.parametrize(
        "blocked_status",
        [TagVoteStatus.RESOLVED_APPLY, TagVoteStatus.RESOLVED_REJECT, TagVoteStatus.PENDING_APPROVAL],
    )
    def test_refuses_a_blocked_persisted_status(self, db, blocked_status):
        card = CardFactory()
        tag = TagFactory(name="Blocked")
        card.tag_vote_statuses = {"Blocked": blocked_status}
        card.save(update_fields=["tag_vote_statuses"])

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 0

    @pytest.mark.parametrize("open_status", [TagVoteStatus.CONTESTED, TagVoteStatus.UNRESOLVED])
    def test_accepts_a_still_open_persisted_status(self, db, open_status):
        card = CardFactory()
        tag = TagFactory(name="Open")
        card.tag_vote_statuses = {"Open": open_status}
        card.save(update_fields=["tag_vote_statuses"])

        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        assert CardTagVote.objects.filter(card=card, tag=tag, source=VoteSource.IMPLICIT).count() == 1

    def test_re_runs_consensus_after_casting(self, db, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses["Borderless"] == TagVoteStatus.RESOLVED_APPLY

        # sanity: an implicit vote on an already-RESOLVED_APPLY pair is refused, so the status
        # can't spuriously change here - this asserts the *lack* of disruption, not a resolve.
        _cast_implicit_vote_and_resolve(card, tag, "anon-1")
        card.refresh_from_db()
        assert card.tag_vote_statuses["Borderless"] == TagVoteStatus.RESOLVED_APPLY


class TestRetractImplicitVoteAndResolve:
    def test_deletes_an_existing_implicit_vote(self, db):
        card = CardFactory()
        tag = TagFactory()
        _cast_implicit_vote_and_resolve(card, tag, "anon-1")

        _retract_implicit_vote_and_resolve(card, tag, "anon-1")

        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 0

    def test_never_deletes_a_real_vote_sharing_the_same_key(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(
            card=card, tag=tag, anonymous_id="anon-1", polarity=VotePolarity.APPLY, source=VoteSource.USER
        )

        _retract_implicit_vote_and_resolve(card, tag, "anon-1")

        assert (
            CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1", source=VoteSource.USER).count() == 1
        )

    def test_retracting_nothing_is_a_no_op(self, db):
        card = CardFactory()
        tag = TagFactory()
        _retract_implicit_vote_and_resolve(card, tag, "anon-1")
        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 0


class TestPostCastImplicitVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": "does-not-exist", "tagNames": [], "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_casts_implicit_votes_for_every_named_tag(self, client, django_settings):
        card = CardFactory()
        TagFactory(name="Foil")
        TagFactory(name="Extended Art")

        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": ["Foil", "Extended Art"], "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card, source=VoteSource.IMPLICIT).count() == 2
        assert {entry["tagName"] for entry in response.json()["tags"]} == {"Foil", "Extended Art"}

    def test_unknown_tag_name_is_silently_skipped_not_an_error(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": ["does-not-exist"], "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card).count() == 0

    def test_empty_tag_list_is_a_harmless_no_op(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": [], "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["tags"] == []

    def test_sensitive_tag_in_the_list_is_guarded_alongside_normal_ones(self, client, django_settings):
        card = CardFactory()
        normal_tag = TagFactory(name="Foil")
        sensitive_tag = TagFactory(name="NSFW", moderation_class=TagModerationClass.SENSITIVE)

        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": ["Foil", "NSFW"], "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card, tag=normal_tag).count() == 1
        assert CardTagVote.objects.filter(card=card, tag=sensitive_tag).count() == 0

    def test_rate_limited_after_exceeding_the_implicit_specific_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_IMPLICIT_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        tag = TagFactory()
        body = {"identifier": card.identifier, "tagNames": [tag.name], "anonymousId": "anon-rate-limited"}

        first = client.post(reverse(views.post_cast_implicit_vote), body, content_type="application/json")
        second = client.post(reverse(views.post_cast_implicit_vote), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429

    def test_implicit_rate_limit_is_independent_of_the_shared_submission_rate(self, client, django_settings, settings):
        # a person who's already exhausted PRINTING_TAG_SUBMISSION_RATE via real tag votes must
        # still be able to cast implicit votes under their own, separate budget.
        settings.PRINTING_TAG_SUBMISSION_RATE = "0/h"
        card = CardFactory()
        tag = TagFactory()

        response = client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": [tag.name], "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200


class TestPostRetractImplicitVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_retract_implicit_vote),
            {"identifier": "does-not-exist", "tagName": "x", "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_tag_name_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_retract_implicit_vote),
            {"identifier": card.identifier, "tagName": "does-not-exist", "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_retracts_an_existing_implicit_vote(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        client.post(
            reverse(views.post_cast_implicit_vote),
            {"identifier": card.identifier, "tagNames": ["Foil"], "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert CardTagVote.objects.filter(card=card, tag=tag, source=VoteSource.IMPLICIT).count() == 1

        response = client.post(
            reverse(views.post_retract_implicit_vote),
            {"identifier": card.identifier, "tagName": "Foil", "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card, tag=tag, source=VoteSource.IMPLICIT).count() == 0

    def test_does_not_retract_a_real_vote_sharing_the_same_key(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(
            card=card, tag=tag, anonymous_id="anon-1", polarity=VotePolarity.APPLY, source=VoteSource.USER
        )

        response = client.post(
            reverse(views.post_retract_implicit_vote),
            {"identifier": card.identifier, "tagName": "Foil", "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert (
            CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1", source=VoteSource.USER).count() == 1
        )
