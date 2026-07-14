"""
Tests for the moderation layer's view surface: `2/whoami/` role reporting, and (added by
later stages in this feature) the report endpoint and moderator-only queue endpoint.
See docs/features/moderation.md.
"""

import pytest

from django.urls import reverse

from cardpicker import views
from cardpicker.models import CardTagVote
from cardpicker.tests.factories import CardFactory, TagFactory


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
