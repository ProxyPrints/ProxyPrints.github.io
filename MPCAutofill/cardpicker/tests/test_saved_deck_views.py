"""
Tests for the saved-decks endpoint surface (docs/proposals/proposal-g-user-accounts-saved-decks.md
§3/§8): 2/savedDecks/, 2/saveDeck/, 2/loadDeck/, 2/deleteDeck/, 2/cryptoProfile/,
2/saveCryptoProfile/, 2/resetSavedDecks/. Mirrors test_moderation_views.py's ownership/403
pattern. Every ciphertext/nonce/wrapped-key value used here is random bytes - the whole point
of the zero-knowledge design is that the backend never inspects them, so random bytes are
exactly as valid a test fixture as a real client-produced blob.
"""

import base64
import os

import pytest

from django.urls import reverse

from cardpicker import views
from cardpicker.models import SavedDeck, SavedDeckKind, UserCryptoProfile


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


def _crypto_profile_payload(kdf_iterations: int = 600_000) -> dict:
    return {
        "salt": _b64(16),
        "kdfIterations": kdf_iterations,
        "passphraseWrappedMasterKey": _b64(48),
        "passphraseWrappedMasterKeyNonce": _b64(12),
        "recoveryWrappedMasterKey": _b64(48),
        "recoveryWrappedMasterKeyNonce": _b64(12),
    }


class TestSavedDecksRequireAuthentication:
    def test_anonymous_get_saved_decks_is_rejected(self, client):
        response = client.get(reverse(views.get_saved_decks))
        assert response.status_code == 403

    def test_anonymous_save_deck_is_rejected(self, client):
        response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        assert response.status_code == 403

    def test_anonymous_crypto_profile_is_rejected(self, client):
        response = client.get(reverse(views.get_crypto_profile))
        assert response.status_code == 403


class TestSaveAndListDecks:
    def test_create_then_list(self, client, plain_user):
        client.force_login(plain_user)
        response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        assert response.status_code == 200
        key = response.json()["key"]

        response = client.get(reverse(views.get_saved_decks))
        decks = response.json()["decks"]
        assert len(decks) == 1
        assert decks[0]["key"] == key
        assert decks[0]["kind"] == "deck"

    def test_update_in_place_does_not_create_a_second_row(self, client, plain_user):
        client.force_login(plain_user)
        create = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        key = create.json()["key"]
        new_ciphertext = _b64(64)
        update_payload = _deck_payload(key=key)
        update_payload["ciphertext"] = new_ciphertext
        update = client.post(reverse(views.post_save_deck), update_payload, content_type="application/json")
        assert update.status_code == 200
        assert update.json()["key"] == key
        assert SavedDeck.objects.filter(owner=plain_user).count() == 1

        loaded = client.post(reverse(views.post_load_deck), {"key": key}, content_type="application/json")
        assert loaded.json()["ciphertext"] == new_ciphertext

    def test_list_is_scoped_to_the_requesting_user(self, client, plain_user, moderator_user):
        client.force_login(plain_user)
        client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        client.logout()

        client.force_login(moderator_user)
        response = client.get(reverse(views.get_saved_decks))
        assert response.json()["decks"] == []


class TestSavedDeckOwnership:
    @pytest.fixture()
    def owned_deck_key(self, client, plain_user) -> str:
        client.force_login(plain_user)
        response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        client.logout()
        return response.json()["key"]

    def test_another_user_cannot_load(self, client, moderator_user, owned_deck_key):
        client.force_login(moderator_user)
        response = client.post(reverse(views.post_load_deck), {"key": owned_deck_key}, content_type="application/json")
        assert response.status_code == 403

    def test_another_user_cannot_update(self, client, moderator_user, owned_deck_key):
        client.force_login(moderator_user)
        response = client.post(
            reverse(views.post_save_deck),
            _deck_payload(key=owned_deck_key),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_another_user_cannot_delete(self, client, moderator_user, owned_deck_key):
        client.force_login(moderator_user)
        response = client.post(
            reverse(views.post_delete_deck), {"key": owned_deck_key}, content_type="application/json"
        )
        assert response.status_code == 403
        assert SavedDeck.objects.filter(key=owned_deck_key).exists()

    def test_owner_can_delete(self, client, plain_user, owned_deck_key):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_delete_deck), {"key": owned_deck_key}, content_type="application/json"
        )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert not SavedDeck.objects.filter(key=owned_deck_key).exists()

    def test_nonexistent_key_is_a_400(self, client, plain_user):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_load_deck),
            {"key": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )
        assert response.status_code == 400


class TestSavedDeckCap:
    def test_cap_is_enforced_on_create_only(self, client, plain_user, settings):
        settings.SAVED_DECK_MAX_PER_USER = 2
        client.force_login(plain_user)
        for _ in range(2):
            response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
            assert response.status_code == 200

        response = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        assert response.status_code == 400
        assert "limit" in response.json()["message"].lower()

    def test_snapshots_are_not_capped(self, client, plain_user, settings):
        settings.SAVED_DECK_MAX_PER_USER = 1
        client.force_login(plain_user)
        client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        for _ in range(5):
            response = client.post(
                reverse(views.post_save_deck),
                _deck_payload(kind="snapshot"),
                content_type="application/json",
            )
            assert response.status_code == 200

    def test_update_never_blocked_by_the_cap(self, client, plain_user, settings):
        settings.SAVED_DECK_MAX_PER_USER = 1
        client.force_login(plain_user)
        create = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        key = create.json()["key"]
        response = client.post(reverse(views.post_save_deck), _deck_payload(key=key), content_type="application/json")
        assert response.status_code == 200


class TestSnapshotFIFORing:
    def test_ring_prunes_to_five(self, client, plain_user):
        client.force_login(plain_user)
        for _ in range(8):
            response = client.post(
                reverse(views.post_save_deck),
                _deck_payload(kind="snapshot"),
                content_type="application/json",
            )
            assert response.status_code == 200
        assert SavedDeck.objects.filter(owner=plain_user, kind=SavedDeckKind.SNAPSHOT).count() == 5

    def test_ring_keeps_the_newest(self, client, plain_user):
        client.force_login(plain_user)
        keys = []
        for _ in range(6):
            response = client.post(
                reverse(views.post_save_deck),
                _deck_payload(kind="snapshot"),
                content_type="application/json",
            )
            keys.append(response.json()["key"])
        remaining_keys = set(str(k) for k in SavedDeck.objects.filter(owner=plain_user).values_list("key", flat=True))
        # the first-created snapshot must be the one pruned away
        assert keys[0] not in remaining_keys
        assert keys[-1] in remaining_keys


class TestCryptoProfile:
    def test_does_not_exist_initially(self, client, plain_user):
        client.force_login(plain_user)
        response = client.get(reverse(views.get_crypto_profile))
        assert response.json() == {
            "exists": False,
            "salt": None,
            "kdfIterations": None,
            "passphraseWrappedMasterKey": None,
            "passphraseWrappedMasterKeyNonce": None,
            "recoveryWrappedMasterKey": None,
            "recoveryWrappedMasterKeyNonce": None,
        }

    def test_create_then_fetch(self, client, plain_user):
        client.force_login(plain_user)
        payload = _crypto_profile_payload()
        create = client.post(reverse(views.post_save_crypto_profile), payload, content_type="application/json")
        assert create.status_code == 200
        assert create.json()["saved"] is True

        fetched = client.get(reverse(views.get_crypto_profile)).json()
        assert fetched["exists"] is True
        assert fetched["salt"] == payload["salt"]
        assert fetched["kdfIterations"] == 600_000
        assert fetched["passphraseWrappedMasterKey"] == payload["passphraseWrappedMasterKey"]
        assert fetched["recoveryWrappedMasterKey"] == payload["recoveryWrappedMasterKey"]

    def test_below_minimum_iterations_is_rejected(self, client, plain_user):
        client.force_login(plain_user)
        payload = _crypto_profile_payload(kdf_iterations=1000)
        response = client.post(reverse(views.post_save_crypto_profile), payload, content_type="application/json")
        assert response.status_code == 400

    def test_replacing_the_profile_only_touches_the_profile_not_decks(self, client, plain_user):
        client.force_login(plain_user)
        client.post(reverse(views.post_save_crypto_profile), _crypto_profile_payload(), content_type="application/json")
        deck = client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        deck_key = deck.json()["key"]
        original_ciphertext = SavedDeck.objects.get(key=deck_key).ciphertext

        # simulate a passphrase change: replace the profile with fresh wrapped-key material
        new_payload = _crypto_profile_payload()
        client.post(reverse(views.post_save_crypto_profile), new_payload, content_type="application/json")

        assert UserCryptoProfile.objects.filter(owner=plain_user).count() == 1
        fetched = client.get(reverse(views.get_crypto_profile)).json()
        assert fetched["passphraseWrappedMasterKey"] == new_payload["passphraseWrappedMasterKey"]
        # the deck body itself must be completely untouched by a profile replacement
        assert bytes(SavedDeck.objects.get(key=deck_key).ciphertext) == bytes(original_ciphertext)


class TestResetSavedDecks:
    def test_requires_explicit_confirm(self, client, plain_user):
        client.force_login(plain_user)
        response = client.post(
            reverse(views.post_reset_saved_decks), {"confirm": False}, content_type="application/json"
        )
        assert response.status_code == 400

    def test_deletes_every_deck_and_the_crypto_profile(self, client, plain_user):
        client.force_login(plain_user)
        client.post(reverse(views.post_save_crypto_profile), _crypto_profile_payload(), content_type="application/json")
        for _ in range(3):
            client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")

        response = client.post(
            reverse(views.post_reset_saved_decks), {"confirm": True}, content_type="application/json"
        )
        assert response.status_code == 200
        assert response.json()["deletedDeckCount"] == 3
        assert not SavedDeck.objects.filter(owner=plain_user).exists()
        assert not UserCryptoProfile.objects.filter(owner=plain_user).exists()

    def test_only_resets_the_requesting_users_own_data(self, client, plain_user, moderator_user):
        client.force_login(plain_user)
        client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        client.logout()

        client.force_login(moderator_user)
        client.post(reverse(views.post_save_deck), _deck_payload(), content_type="application/json")
        client.post(reverse(views.post_reset_saved_decks), {"confirm": True}, content_type="application/json")

        assert not SavedDeck.objects.filter(owner=moderator_user).exists()
        assert SavedDeck.objects.filter(owner=plain_user).count() == 1
