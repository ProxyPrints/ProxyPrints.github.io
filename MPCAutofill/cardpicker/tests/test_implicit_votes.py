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
    AUTO_DERIVED_TAG_VOTE_SURFACE,
    IMPLICIT_VOTE_SURFACE,
    _cast_auto_derived_tag_vote_and_resolve,
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


class TestCastAutoDerivedTagVoteAndResolve:
    """
    Direct coverage of `_cast_auto_derived_tag_vote_and_resolve` (issue #790) - a question-feed
    candidate pick's derived attribute chip. Same guards as `_cast_implicit_vote_and_resolve`
    (both route through `_cast_implicit_sourced_vote_and_resolve`), distinguished only by
    `vote_surface` - these tests focus on that distinction plus the source/weight recast; the
    guard behaviour itself is already covered by `TestCastImplicitVoteAndResolve` above.
    """

    def test_casts_a_positive_implicit_vote_with_the_auto_derived_surface(self, db):
        card = CardFactory()
        tag = TagFactory()

        _cast_auto_derived_tag_vote_and_resolve(card, tag, "anon-1")

        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.source == VoteSource.IMPLICIT
        assert vote.polarity == VotePolarity.APPLY
        assert vote.vote_surface == AUTO_DERIVED_TAG_VOTE_SURFACE
        assert vote.user is None

    def test_auto_derived_surface_is_distinct_from_the_editor_filter_surface(self):
        assert AUTO_DERIVED_TAG_VOTE_SURFACE != IMPLICIT_VOTE_SURFACE

    def test_never_overwrites_a_real_vote_by_the_same_identity(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(
            card=card, tag=tag, anonymous_id="anon-1", polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER
        )

        _cast_auto_derived_tag_vote_and_resolve(card, tag, "anon-1")

        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.source == VoteSource.USER
        assert vote.polarity == VotePolarity.NOT_APPLICABLE


class TestPostSubmitTagVoteAutoDerivedSource:
    """
    `post_submit_tag_vote`'s dispatch between a genuine tag-question answer (VoteSource.USER)
    and a question-feed candidate-pick auto-derived attribute (VoteSource.IMPLICIT) - issue
    #790's central fix. The two are indistinguishable in the request shape except for
    `voteSurface`, and the source is decided server-side from that value, never trusted
    directly from the client.
    """

    @staticmethod
    def submit(client, card, tag_name: str, polarity: int, vote_surface: str, anonymous_id: str = "anon-1"):
        return client.post(
            reverse(views.post_submit_tag_vote),
            {
                "identifier": card.identifier,
                "anonymousId": anonymous_id,
                "tagName": tag_name,
                "polarity": polarity,
                "voteSurface": vote_surface,
            },
            content_type="application/json",
        )

    def test_the_auto_derived_surface_casts_an_implicit_vote(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()

        response = self.submit(client, card, tag.name, polarity=1, vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE)

        assert response.status_code == 200
        vote = CardTagVote.objects.get(card=card, tag=tag)
        assert vote.source == VoteSource.IMPLICIT
        assert vote.vote_surface == AUTO_DERIVED_TAG_VOTE_SURFACE

    def test_a_genuine_tag_question_answer_still_casts_a_user_vote(self, client, django_settings):
        # the pre-existing behaviour for a real answer (BorderColorQuestion.tsx et al.,
        # voteSurface "question-feed") is unaffected by the new branch.
        card = CardFactory()
        tag = TagFactory()

        response = self.submit(client, card, tag.name, polarity=1, vote_surface="question-feed")

        assert response.status_code == 200
        vote = CardTagVote.objects.get(card=card, tag=tag)
        assert vote.source == VoteSource.USER
        assert vote.vote_surface == "question-feed"

    def test_the_auto_derived_surface_with_a_non_apply_polarity_falls_through_to_the_user_path(
        self, client, django_settings
    ):
        # getAutoTagChips only ever casts polarity=1 - a client sending this surface with any
        # other polarity is outside that contract, so it is treated as an ordinary vote rather
        # than silently reinterpreted as a positive implicit one.
        card = CardFactory()
        tag = TagFactory()

        response = self.submit(
            client, card, tag.name, polarity=VotePolarity.NOT_APPLICABLE, vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE
        )

        assert response.status_code == 200
        vote = CardTagVote.objects.get(card=card, tag=tag)
        assert vote.source == VoteSource.USER
        assert vote.polarity == VotePolarity.NOT_APPLICABLE

    def test_a_moderators_auto_derived_vote_records_no_user(self, client, django_settings, moderator_user):
        # is_privileged_vote grants privileged weight to a USER-sourced vote from a moderator's
        # account regardless of source - an IMPLICIT vote must not carry that account through,
        # or a moderator's own candidate pick would resolve a tag at privileged weight.
        card = CardFactory()
        tag = TagFactory()
        client.force_login(moderator_user)

        self.submit(client, card, tag.name, polarity=1, vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE)

        vote = CardTagVote.objects.get(card=card, tag=tag)
        assert vote.user is None


class TestAutoDerivedVotesCannotResolveATagAlone:
    """
    End-to-end proof that recasting fixes the outcome, not just the label (issue #790's own
    "verify this first" - `resolve_tag`/`resolve_weighted_consensus` DO weight tag votes by
    source, so this is not a no-op relabelling). At the default settings
    (PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MIN_SHARE=0.6), two USER votes on a tag resolve it;
    two auto-derived votes on the same shape never do, no matter how many pile up, because
    VoteSource.IMPLICIT is both under-weighted (0.25, capped at 1.0 combined) and excluded from
    the human-backed gate `resolve_weighted_consensus` requires to resolve anything at all.
    """

    def test_two_genuine_votes_resolve_the_tag(self, client, django_settings):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Full Art")

        TestPostSubmitTagVoteAutoDerivedSource.submit(
            client, card, tag.name, polarity=1, vote_surface="question-feed", anonymous_id="anon-1"
        )
        TestPostSubmitTagVoteAutoDerivedSource.submit(
            client, card, tag.name, polarity=1, vote_surface="question-feed", anonymous_id="anon-2"
        )

        card.refresh_from_db()
        assert card.tag_vote_statuses["Full Art"] == TagVoteStatus.RESOLVED_APPLY
        assert "Full Art" in card.tags

    def test_two_auto_derived_votes_do_not_resolve_the_tag(self, client, django_settings):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Full Art")

        TestPostSubmitTagVoteAutoDerivedSource.submit(
            client, card, tag.name, polarity=1, vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE, anonymous_id="anon-1"
        )
        TestPostSubmitTagVoteAutoDerivedSource.submit(
            client, card, tag.name, polarity=1, vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE, anonymous_id="anon-2"
        )

        card.refresh_from_db()
        assert card.tag_vote_statuses.get("Full Art", TagVoteStatus.UNRESOLVED) != TagVoteStatus.RESOLVED_APPLY
        assert "Full Art" not in card.tags

    def test_five_auto_derived_votes_still_do_not_resolve_the_tag(self, client, django_settings):
        # volume never substitutes for a human-backed vote, regardless of how many pile up -
        # this is what distinguishes the fix from merely lowering weight (a large enough pile
        # of even 0.25-weight USER-sourced votes would eventually clear PRINTING_TAG_MIN_VOTES;
        # IMPLICIT votes cannot, because of the human-backed gate, not just the weight).
        card = CardFactory(tags=[])
        tag = TagFactory(name="Full Art")

        for i in range(5):
            TestPostSubmitTagVoteAutoDerivedSource.submit(
                client,
                card,
                tag.name,
                polarity=1,
                vote_surface=AUTO_DERIVED_TAG_VOTE_SURFACE,
                anonymous_id=f"anon-{i}",
            )

        card.refresh_from_db()
        assert card.tag_vote_statuses.get("Full Art", TagVoteStatus.UNRESOLVED) != TagVoteStatus.RESOLVED_APPLY
        assert "Full Art" not in card.tags
