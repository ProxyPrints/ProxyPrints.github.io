"""
Tests for the moderation layer's view surface: `2/whoami/` role reporting, and (added by
later stages in this feature) the report endpoint and moderator-only queue endpoint.
See docs/features/moderation.md.
"""

import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    CardReport,
    CardReportReason,
    CardTagVote,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
)
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CardFactory,
    CardReportFactory,
    CardTagVoteFactory,
    TagFactory,
)


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    # same isolation as test_tag_votes.py: django-ratelimit counts live in the default cache
    cache.clear()
    yield
    cache.clear()


class TestGetWhoami:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    def test_anonymous(self, client):
        response = client.get(reverse(views.get_whoami))
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": False,
            "username": None,
            "moderator": False,
            "discordEnabled": False,
            "loginUrl": None,
            "logoutUrl": None,
        }

    def test_authenticated_non_moderator(self, client, plain_user):
        client.force_login(plain_user)
        response = client.get(reverse(views.get_whoami))
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "username": "pleb",
            "moderator": False,
            "discordEnabled": False,
            "loginUrl": None,
            "logoutUrl": "/accounts/logout/",
        }

    def test_moderator(self, client, moderator_user):
        client.force_login(moderator_user)
        response = client.get(reverse(views.get_whoami))
        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert body["username"] == "mod"
        assert body["moderator"] is True

    def test_group_membership_is_the_grant_not_login(self, client, moderator_user, moderators_group):
        # removing the user from the group revokes the role with no other state change -
        # being logged in (even having logged in while a moderator) grants nothing by itself
        client.force_login(moderator_user)
        moderator_user.groups.remove(moderators_group)
        response = client.get(reverse(views.get_whoami))
        assert response.json()["moderator"] is False

    def test_discord_enabled_reports_login_url(self, client, settings):
        settings.DISCORD_AUTH_ENABLED = True
        response = client.get(reverse(views.get_whoami))
        body = response.json()
        assert body["discordEnabled"] is True
        assert body["loginUrl"] == "/accounts/discord/login/"

    def test_post_is_rejected(self, client):
        response = client.post(reverse(views.get_whoami))
        assert response.status_code == 400


class TestVoteUserRecording:
    """
    The nullable `AbstractWeightedVote.user` FK: set alongside anonymous_id when the
    submitting request carries an authenticated session, None otherwise.
    """

    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def submit_tag_vote(client, card, tag_name: str, anonymous_id: str = "anon-1"):
        return client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "anonymousId": anonymous_id, "tagName": tag_name, "polarity": 1},
            content_type="application/json",
        )

    def test_anonymous_vote_records_no_user(self, client):
        card, tag = CardFactory(), TagFactory()
        response = self.submit_tag_vote(client, card, tag.name)
        assert response.status_code == 200
        vote = CardTagVote.objects.get()
        assert vote.user is None
        assert vote.anonymous_id == "anon-1"

    def test_authenticated_vote_records_user_and_anonymous_id(self, client, plain_user):
        card, tag = CardFactory(), TagFactory()
        client.force_login(plain_user)
        response = self.submit_tag_vote(client, card, tag.name)
        assert response.status_code == 200
        vote = CardTagVote.objects.get()
        assert vote.user == plain_user
        assert vote.anonymous_id == "anon-1"

    def test_unauthenticated_revote_clears_user(self, client, plain_user):
        # the row reflects the latest submission for this (card, tag, anonymous_id)
        card, tag = CardFactory(), TagFactory()
        client.force_login(plain_user)
        self.submit_tag_vote(client, card, tag.name)
        client.logout()
        self.submit_tag_vote(client, card, tag.name)
        vote = CardTagVote.objects.get()
        assert vote.user is None


class TestPostReportCard:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def report(client, card, reason: str, text: str | None = None, anonymous_id: str = "anon-1"):
        body: dict = {"identifier": card.identifier, "anonymousId": anonymous_id, "reason": reason}
        if text is not None:
            body["text"] = text
        return client.post(reverse(views.post_report_card), body, content_type="application/json")

    def test_report_writes_audit_row(self, client):
        card = CardFactory()
        response = self.report(client, card, "broken_image")
        assert response.status_code == 200
        assert response.json() == {"reported": True, "voteCast": False}
        report = CardReport.objects.get()
        assert report.card == card
        assert report.reason == CardReportReason.BROKEN_IMAGE
        assert report.anonymous_id == "anon-1"
        assert report.user is None
        assert report.text == ""

    def test_tag_mapped_reason_casts_positive_vote_on_seeded_sensitive_tag(self, client):
        seed_sensitive_tags()
        card = CardFactory(tags=[])
        response = self.report(client, card, "nsfw")
        assert response.status_code == 200
        assert response.json() == {"reported": True, "voteCast": True}
        vote = CardTagVote.objects.get()
        assert vote.tag.name == "NSFW"
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == "anon-1"
        # one anonymous report can never resolve a sensitive tag - it parks as pending at most
        card.refresh_from_db()
        assert card.tags == []
        assert card.tag_vote_statuses.get("NSFW") in (None, TagVoteStatus.UNRESOLVED)

    def test_broken_image_and_other_cast_no_vote(self, client):
        seed_sensitive_tags()
        card = CardFactory()
        self.report(client, card, "broken_image")
        self.report(client, card, "other", text="something else is wrong", anonymous_id="anon-2")
        assert CardTagVote.objects.count() == 0
        assert CardReport.objects.count() == 2
        assert CardReport.objects.get(reason=CardReportReason.OTHER).text == "something else is wrong"

    def test_unseeded_tag_degrades_to_report_only(self, client):
        # seed_sensitive_tags not run: the report must still land, the vote silently skipped
        card = CardFactory()
        response = self.report(client, card, "nsfw")
        assert response.status_code == 200
        assert response.json() == {"reported": True, "voteCast": False}
        assert CardReport.objects.count() == 1
        assert CardTagVote.objects.count() == 0

    def test_text_over_280_chars_is_rejected(self, client):
        card = CardFactory()
        response = self.report(client, card, "other", text="x" * 281)
        assert response.status_code == 400
        assert CardReport.objects.count() == 0

    def test_unknown_reason_is_rejected(self, client):
        card = CardFactory()
        response = self.report(client, card, "i-just-dont-like-it")
        assert response.status_code == 400

    def test_unknown_card_is_a_bad_request(self, client):
        response = client.post(
            reverse(views.post_report_card),
            {"identifier": "does-not-exist", "anonymousId": "anon-1", "reason": "nsfw"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_authenticated_report_records_user_on_report_and_vote(self, client, plain_user):
        seed_sensitive_tags()
        card = CardFactory()
        client.force_login(plain_user)
        self.report(client, card, "nsfw")
        assert CardReport.objects.get().user == plain_user
        assert CardTagVote.objects.get().user == plain_user

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, settings):
        settings.CARD_REPORT_RATE = "2/d"
        card = CardFactory()
        first = self.report(client, card, "broken_image", anonymous_id="anon-rate")
        second = self.report(client, card, "other", text="still broken", anonymous_id="anon-rate")
        third = self.report(client, card, "nsfw", anonymous_id="anon-rate")
        assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)
        assert "reports today" in third.json()["message"]
        assert CardReport.objects.count() == 2

    def test_rate_limit_is_per_anonymous_id(self, client, settings):
        settings.CARD_REPORT_RATE = "1/d"
        card = CardFactory()
        assert self.report(client, card, "broken_image", anonymous_id="anon-a").status_code == 200
        assert self.report(client, card, "broken_image", anonymous_id="anon-b").status_code == 200


class TestRejectUntrustedOrigin:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    def test_untrusted_origin_is_rejected_with_403(self, client):
        card = CardFactory()
        response = client.post(
            reverse(views.post_report_card),
            {"identifier": card.identifier, "anonymousId": "anon-1", "reason": "broken_image"},
            content_type="application/json",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.status_code == 403
        assert CardReport.objects.count() == 0

    def test_allowlisted_origin_is_accepted(self, client, settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_report_card),
            {"identifier": card.identifier, "anonymousId": "anon-1", "reason": "broken_image"},
            content_type="application/json",
            headers={"Origin": settings.CORS_ALLOWED_ORIGINS[0]},
        )
        assert response.status_code == 200

    def test_absent_origin_keeps_todays_trust_level(self, client):
        # non-browser clients (curl, scripts, the desktop tool) send no Origin header at all
        card = CardFactory()
        response = client.post(
            reverse(views.post_report_card),
            {"identifier": card.identifier, "anonymousId": "anon-1", "reason": "broken_image"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_guard_also_covers_tag_vote_submission(self, client):
        card, tag = CardFactory(), TagFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "anonymousId": "anon-1", "tagName": tag.name, "polarity": 1},
            content_type="application/json",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.status_code == 403
        assert CardTagVote.objects.count() == 0


def make_pending_pair(tag_name: str = "sensitive-tag", vote_count: int = 2) -> tuple:
    """A (card, tag) pair parked in pending_approval by anonymous crowd votes."""
    card = CardFactory(tags=[])
    tag = TagFactory(name=tag_name, moderation_class=TagModerationClass.SENSITIVE)
    for index in range(vote_count):
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id=f"crowd-{tag_name}-{index}")
    resolve_and_persist_tag_votes(card)
    card.refresh_from_db()
    assert card.tag_vote_statuses[tag.name] == TagVoteStatus.PENDING_APPROVAL
    return card, tag


class TestPostModerationQueue:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def fetch(client, page: int = 1):
        return client.post(reverse(views.post_moderation_queue), {"page": page}, content_type="application/json")

    def test_anonymous_is_403(self, client):
        response = self.fetch(client)
        assert response.status_code == 403
        assert response.json()["name"] == "Moderator access required"

    def test_authenticated_non_moderator_is_403(self, client, plain_user):
        client.force_login(plain_user)
        assert self.fetch(client).status_code == 403

    def test_moderator_sees_pending_pairs_with_report_counts_and_excerpts(self, client, moderator_user):
        card, tag = make_pending_pair(tag_name="NSFW")
        CardReportFactory(card=card, reason=CardReportReason.NSFW, text="way too spicy")
        CardReportFactory(card=card, reason=CardReportReason.NSFW, text="")
        CardReportFactory(card=card, reason=CardReportReason.NSFW, text="really not ok")

        client.force_login(moderator_user)
        response = self.fetch(client)
        assert response.status_code == 200
        body = response.json()
        assert body["hits"] == 1
        (item,) = body["items"]
        assert item["card"]["identifier"] == card.identifier
        assert item["tagName"] == "NSFW"
        assert item["reportCount"] == 3
        # newest-first, empty text excluded
        assert item["reportExcerpts"] == ["really not ok", "way too spicy"]

    def test_only_pending_pairs_are_served(self, client, moderator_user):
        make_pending_pair(tag_name="pending-tag")
        # a resolved standard pair and a contested sensitive pair must not appear
        standard_card = CardFactory(tags=[])
        standard_tag = TagFactory(name="standard-tag")
        CardTagVoteFactory(card=standard_card, tag=standard_tag, polarity=VotePolarity.APPLY, anonymous_id="a-1")
        CardTagVoteFactory(card=standard_card, tag=standard_tag, polarity=VotePolarity.APPLY, anonymous_id="a-2")
        resolve_and_persist_tag_votes(standard_card)

        client.force_login(moderator_user)
        body = self.fetch(client).json()
        assert [item["tagName"] for item in body["items"]] == ["pending-tag"]

    def test_most_reported_first_zero_report_pairs_last(self, client, moderator_user):
        barely_reported, _ = make_pending_pair(tag_name="low-res")
        organic, _ = make_pending_pair(tag_name="sensitive-b")
        heavily_reported, _ = make_pending_pair(tag_name="incorrect-info")
        CardReportFactory(card=barely_reported, reason=CardReportReason.LOW_QUALITY)
        for _ in range(3):
            CardReportFactory(card=heavily_reported, reason=CardReportReason.WRONG_CARD)

        client.force_login(moderator_user)
        body = self.fetch(client).json()
        assert [item["tagName"] for item in body["items"]] == ["incorrect-info", "low-res", "sensitive-b"]

    def test_moderator_approval_via_submit_tag_vote_resolves_and_clears_the_queue(self, client, moderator_user):
        # the end-to-end transition: Approve in the UI is an ordinary submitTagVote POST from
        # the moderator's session - the pair resolves through the normal pass and leaves the
        # queue, and the card's tags gain the sensitive tag
        card, tag = make_pending_pair(tag_name="NSFW")
        client.force_login(moderator_user)
        vote = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "anonymousId": "mod-anon", "tagName": tag.name, "polarity": 1},
            content_type="application/json",
        )
        assert vote.status_code == 200

        card.refresh_from_db()
        assert card.tag_vote_statuses[tag.name] == TagVoteStatus.RESOLVED_APPLY
        assert card.tags == [tag.name]
        assert self.fetch(client).json()["hits"] == 0

    def test_moderator_reject_also_clears_the_queue(self, client, moderator_user):
        card, tag = make_pending_pair(tag_name="NSFW")
        client.force_login(moderator_user)
        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "anonymousId": "mod-anon", "tagName": tag.name, "polarity": -1},
            content_type="application/json",
        )
        card.refresh_from_db()
        assert card.tag_vote_statuses[tag.name] == TagVoteStatus.RESOLVED_REJECT
        assert card.tags == []
        assert self.fetch(client).json()["hits"] == 0
