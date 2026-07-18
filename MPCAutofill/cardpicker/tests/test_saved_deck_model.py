"""
Tests for the SavedDeck/UserCryptoProfile models (docs/proposals/proposal-g-user-accounts-
saved-decks.md §8 - the zero-knowledge amendment that superseded this model's original
plaintext name/state fields). Model-level only - the CRUD endpoints (2/savedDecks/,
2/saveDeck/, etc.) get their own view-layer tests once built, mirroring
test_moderation_views.py's ownership/403 pattern. No encryption happens at this layer at all
(the server never decrypts anything, by design) - these tests only confirm the backend stores
and round-trips opaque bytes faithfully and enforces ownership-level integrity, never content.
"""

import pytest

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from cardpicker.models import SavedDeckKind
from cardpicker.tests.factories import SavedDeckFactory, UserCryptoProfileFactory


class TestSavedDeckDefaults:
    def test_defaults(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        assert deck.kind == SavedDeckKind.DECK
        assert deck.key is not None
        assert deck.created_at is not None
        assert deck.updated_at is not None

    def test_no_name_field_exists(self, plain_user):
        # the whole point of §8 - there is no plaintext title anywhere server-side
        deck = SavedDeckFactory(owner=plain_user)
        assert not hasattr(deck, "name")
        assert not hasattr(deck, "state")
        assert not hasattr(deck, "is_public")


class TestSavedDeckNoUniquenessEnforcement:
    """
    §8's Consequences section: once titles are encrypted, the server can no longer see
    plaintext names to enforce uniqueness - the old saveddeck_owner_name_unique_for_decks
    constraint is gone. Two decks belonging to the same owner never collide, regardless of
    kind, since nothing server-side distinguishes them by content at all.
    """

    def test_same_owner_can_create_many_decks_with_identical_ciphertext_shape(self, plain_user):
        # "identical shape" here just means the factory's random bytes happen to be the same
        # length - real ciphertexts always differ, but the model itself places no constraint
        # on content, so this must succeed regardless
        SavedDeckFactory(owner=plain_user, kind=SavedDeckKind.DECK)
        SavedDeckFactory(owner=plain_user, kind=SavedDeckKind.DECK)
        assert SavedDeckFactory._meta.model.objects.filter(owner=plain_user).count() == 2

    def test_snapshot_and_deck_rows_coexist_freely(self, plain_user):
        SavedDeckFactory(owner=plain_user, kind=SavedDeckKind.DECK)
        SavedDeckFactory(owner=plain_user, kind=SavedDeckKind.SNAPSHOT)
        SavedDeckFactory(owner=plain_user, kind=SavedDeckKind.SNAPSHOT)


class TestSavedDeckCascadeDelete:
    def test_deleting_owner_deletes_their_saved_decks(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        owner_id = plain_user.id
        plain_user.delete()
        assert not User.objects.filter(id=owner_id).exists()
        assert not deck.__class__.objects.filter(pk=deck.pk).exists()


class TestUserCryptoProfile:
    def test_one_profile_per_owner(self, plain_user):
        UserCryptoProfileFactory(owner=plain_user)
        # a second profile for the same owner violates the implicit OneToOneField uniqueness
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UserCryptoProfileFactory(owner=plain_user)

    def test_deleting_owner_deletes_their_crypto_profile(self, plain_user):
        profile = UserCryptoProfileFactory(owner=plain_user)
        owner_id = plain_user.id
        plain_user.delete()
        assert not User.objects.filter(id=owner_id).exists()
        assert not profile.__class__.objects.filter(pk=profile.pk).exists()

    def test_recovery_and_passphrase_slots_are_independently_stored(self, plain_user):
        # the two wrapped-master-key slots must be genuinely independent fields, not aliases
        # of each other - a passphrase change re-wraps one without touching the other (§8)
        profile = UserCryptoProfileFactory(
            owner=plain_user,
            passphrase_wrapped_master_key=b"passphrase-slot",
            recovery_wrapped_master_key=b"recovery-slot",
        )
        assert bytes(profile.passphrase_wrapped_master_key) == b"passphrase-slot"
        assert bytes(profile.recovery_wrapped_master_key) == b"recovery-slot"
