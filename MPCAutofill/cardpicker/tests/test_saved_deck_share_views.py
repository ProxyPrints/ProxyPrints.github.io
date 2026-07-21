"""
Tests for the per-deck share link endpoint surface (docs/proposals/proposal-g-user-accounts-
saved-decks.md's "PR-5, post-v1: per-deck share links"): 2/createDeckShare/, 2/deckShares/,
2/revokeDeckShare/, 2/getSharedDeck/. Mirrors test_saved_deck_views.py's ownership/403 pattern.
Every ciphertext/nonce/wrapped-key value used here is random bytes - the whole point of the
zero-knowledge design is that the backend never inspects them, exactly as in the parent surface.
"""

import base64
import os
from datetime import timedelta

import pytest

from django.urls import reverse
from django.utils import timezone

from cardpicker import views
from cardpicker.models import SavedDeckShare


def _b64(n: int = 16) -> str:
    return base64.b64encode(os.urandom(n)).decode("ascii")


def _deck_payload(key=None, kind=None) -> dict:
    payload = {
        "key": key,
        "ciphertext": _b64(64),
        "ciphertextNonce": _b64(12),
        "wrappedDek": _b64(48),
        "wrappedDekNonce": _b64(12),
    }
    if kind is not None:
        payload["kind"] = kind
    return payload


def _share_payload(deck_key: str, expires_in_days=None) -> dict:
    return {
        "deckKey": deck_key,
        "wrappedDek": _b64(48),
        "wrappedDekNonce": _b64(12),
        "expiresInDays": expires_in_days,
    }


@pytest.fixture()
def owned_deck_key(client, plain_user) -> str:
    client.force_login(plain_user)
    response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
    client.logout()
    return response.json()["key"]


class TestDeckShareRequiresAuthentication:
    def test_anonymous_create_is_rejected(self, client, owned_deck_key):
        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(owned_deck_key),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_anonymous_list_is_rejected(self, client):
        response = client.get(reverse(views.get_deck_shares))
        assert response.status_code == 403

    def test_anonymous_revoke_is_rejected(self, client):
        response = client.post(
            reverse(views.post_revoke_deck_share),
            {"shareId": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_get_shared_deck_needs_no_authentication_at_all(self, client, plain_user, owned_deck_key):
        # unauthenticated is the whole point of the recipient-side fetch - a nonexistent shareId
        # still 400s (not 403), proving the auth gate simply doesn't apply to this endpoint
        response = client.post(
            reverse(views.post_get_shared_deck),
            {"shareId": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )
        assert response.status_code == 400


class TestCreateShareOwnershipAndValidation:
    def test_owner_can_create_a_share(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(owned_deck_key),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert "shareId" in response.json()
        assert "createdAt" in response.json()

    def test_another_user_cannot_share_someone_elses_deck(self, client, moderator_user, owned_deck_key):
        client.force_login(moderator_user)
        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(owned_deck_key),
            content_type="application/json",
        )
        assert response.status_code == 403
        assert not SavedDeckShare.objects.filter(deck__key=owned_deck_key).exists()

    def test_snapshots_cannot_be_shared(self, client, plain_user):
        client.force_login(plain_user)
        snapshot = client.post(
            reverse(views.post_save_deck), _deck_payload(kind="snapshot"), content_type="application/json"
        )
        snapshot_key = snapshot.json()["key"]
        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(snapshot_key),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_nonexistent_deck_is_a_400(self, client, plain_user):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload("00000000-0000-0000-0000-000000000000"),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestDeckShareCap:
    def test_cap_is_enforced_per_deck(self, client, plain_user, owned_deck_key, settings):
        settings.SAVED_DECK_SHARE_MAX_PER_DECK = 2
        client.force_login(plain_user)
        for _ in range(2):
            response = client.post(
                reverse(views.post_create_deck_share),
                _share_payload(owned_deck_key),
                content_type="application/json",
            )
            assert response.status_code == 200

        response = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(owned_deck_key),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "limit" in response.json()["message"].lower() or "maximum" in response.json()["message"].lower()


class TestListShares:
    def test_lists_only_the_requesting_users_own_shares(self, client, plain_user, moderator_user, owned_deck_key):
        client.force_login(plain_user)
        client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        client.logout()

        client.force_login(moderator_user)
        response = client.get(reverse(views.get_deck_shares))
        assert response.json()["shares"] == []

        client.logout()
        client.force_login(plain_user)
        response = client.get(reverse(views.get_deck_shares))
        shares = response.json()["shares"]
        assert len(shares) == 1
        assert shares[0]["deckKey"] == owned_deck_key
        # metadata only - never ciphertext/wrapped-key material
        assert "ciphertext" not in shares[0]
        assert "wrappedDek" not in shares[0]


class TestRevokeShare:
    def test_owner_can_revoke(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]

        response = client.post(
            reverse(views.post_revoke_deck_share), {"shareId": share_id}, content_type="application/json"
        )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert not SavedDeckShare.objects.filter(id=share_id).exists()

    def test_another_user_cannot_revoke_someone_elses_share(self, client, plain_user, moderator_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]
        client.logout()

        client.force_login(moderator_user)
        response = client.post(
            reverse(views.post_revoke_deck_share), {"shareId": share_id}, content_type="application/json"
        )
        assert response.status_code == 403
        assert SavedDeckShare.objects.filter(id=share_id).exists()

    def test_revoking_a_nonexistent_share_is_a_400(self, client, plain_user):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_revoke_deck_share),
            {"shareId": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_a_revoked_shares_fetch_fails_for_all_subsequent_attempts(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]

        # confirm it's fetchable before revocation
        fetched = client.post(
            reverse(views.post_get_shared_deck), {"shareId": share_id}, content_type="application/json"
        )
        assert fetched.status_code == 200

        client.post(reverse(views.post_revoke_deck_share), {"shareId": share_id}, content_type="application/json")

        for _ in range(2):
            fetched_again = client.post(
                reverse(views.post_get_shared_deck), {"shareId": share_id}, content_type="application/json"
            )
            assert fetched_again.status_code == 400


class TestGetSharedDeckFrozenSnapshot:
    """
    See cardpicker.models.SavedDeckShare's docstring: a share's ciphertext is copied at
    creation time, deliberately decoupled from any later edit to the live deck.
    """

    def test_share_serves_the_decks_ciphertext_at_creation_time(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create_payload = _share_payload(owned_deck_key)
        create = client.post(reverse(views.post_create_deck_share), create_payload, content_type="application/json")
        share_id = create.json()["shareId"]

        fetched = client.post(
            reverse(views.post_get_shared_deck), {"shareId": share_id}, content_type="application/json"
        )
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["wrappedDek"] == create_payload["wrappedDek"]
        assert body["wrappedDekNonce"] == create_payload["wrappedDekNonce"]
        assert "ciphertext" in body and "ciphertextNonce" in body

    def test_editing_the_live_deck_after_sharing_does_not_change_the_shares_own_snapshot(
        self, client, plain_user, owned_deck_key
    ):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]
        original_share_ciphertext = SavedDeckShare.objects.get(id=share_id).ciphertext

        # an ordinary edit-save of the live deck (regenerates its DEK/ciphertext, per
        # post_save_deck's existing behaviour)
        client.post(reverse(views.post_save_deck), _deck_payload(key=owned_deck_key), content_type="application/json")

        assert bytes(SavedDeckShare.objects.get(id=share_id).ciphertext) == bytes(original_share_ciphertext)

    def test_deleting_the_live_deck_cascades_to_its_shares(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]

        client.post(reverse(views.post_delete_deck), {"key": owned_deck_key}, content_type="application/json")

        assert not SavedDeckShare.objects.filter(id=share_id).exists()


class TestGetSharedDeckExpiry:
    def test_a_future_expiry_is_still_fetchable(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share),
            _share_payload(owned_deck_key, expires_in_days=7),
            content_type="application/json",
        )
        share_id = create.json()["shareId"]
        fetched = client.post(
            reverse(views.post_get_shared_deck), {"shareId": share_id}, content_type="application/json"
        )
        assert fetched.status_code == 200

    def test_a_past_expiry_fails_to_fetch_but_is_still_listed(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        create = client.post(
            reverse(views.post_create_deck_share), _share_payload(owned_deck_key), content_type="application/json"
        )
        share_id = create.json()["shareId"]
        share = SavedDeckShare.objects.get(id=share_id)
        share.expires_at = timezone.now() - timedelta(seconds=1)
        share.save(update_fields=["expires_at"])

        fetched = client.post(
            reverse(views.post_get_shared_deck), {"shareId": share_id}, content_type="application/json"
        )
        assert fetched.status_code == 400

        listed = client.get(reverse(views.get_deck_shares)).json()["shares"]
        assert any(s["shareId"] == share_id for s in listed)
