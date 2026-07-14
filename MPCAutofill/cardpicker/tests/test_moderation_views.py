"""
Tests for the moderation layer's view surface: `2/whoami/` role reporting, and (added by
later stages in this feature) the report endpoint and moderator-only queue endpoint.
See docs/features/moderation.md.
"""

import pytest

from django.urls import reverse

from cardpicker import views


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
