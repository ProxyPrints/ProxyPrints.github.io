"""
Tests for the SavedDeck model (docs/proposals/proposal-g-user-accounts-saved-decks.md §3).
Model-level only - the CRUD endpoints (2/savedDecks/, 2/saveDeck/, etc.) get their own view-layer
tests once built, mirroring test_moderation_views.py's ownership/403 pattern.
"""

import pytest

from django.db import IntegrityError, transaction

from cardpicker.models import SavedDeckKind
from cardpicker.tests.factories import SavedDeckFactory


class TestSavedDeckDefaults:
    def test_defaults(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user, name="My Deck", state={"members": []})
        assert deck.kind == SavedDeckKind.DECK
        assert deck.is_public is False
        assert deck.key is not None
        assert deck.created_at is not None
        assert deck.updated_at is not None


class TestSavedDeckUniqueConstraint:
    """
    saveddeck_owner_name_unique_for_decks (models.py) is scoped to kind=DECK specifically - see
    decision 7's rationale (auto-generated snapshot names like "Backup - {date}" must never
    collide with each other or block the 5-per-user FIFO ring from filling).
    """

    def test_duplicate_deck_name_for_same_owner_is_rejected(self, plain_user):
        SavedDeckFactory(owner=plain_user, name="My Deck", kind=SavedDeckKind.DECK)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SavedDeckFactory(owner=plain_user, name="My Deck", kind=SavedDeckKind.DECK)

    def test_duplicate_deck_name_for_different_owners_is_allowed(self, plain_user, moderator_user):
        SavedDeckFactory(owner=plain_user, name="My Deck", kind=SavedDeckKind.DECK)
        # should not raise - the constraint is scoped per-owner
        SavedDeckFactory(owner=moderator_user, name="My Deck", kind=SavedDeckKind.DECK)

    def test_duplicate_snapshot_name_for_same_owner_is_allowed(self, plain_user):
        # two auto-snapshots on the same day would naturally share a "Backup - {date}" name -
        # the constraint must not block the FIFO ring from filling because of this
        SavedDeckFactory(owner=plain_user, name="Backup - 2026-07-18", kind=SavedDeckKind.SNAPSHOT)
        SavedDeckFactory(owner=plain_user, name="Backup - 2026-07-18", kind=SavedDeckKind.SNAPSHOT)

    def test_snapshot_name_never_collides_with_a_deck_of_the_same_name(self, plain_user):
        SavedDeckFactory(owner=plain_user, name="My Deck", kind=SavedDeckKind.DECK)
        # should not raise - the constraint's condition=Q(kind=DECK) excludes snapshot rows
        SavedDeckFactory(owner=plain_user, name="My Deck", kind=SavedDeckKind.SNAPSHOT)


class TestSavedDeckCascadeDelete:
    def test_deleting_owner_deletes_their_saved_decks(self, plain_user):
        from django.contrib.auth.models import User

        deck = SavedDeckFactory(owner=plain_user, name="My Deck")
        owner_id = plain_user.id
        plain_user.delete()
        assert not User.objects.filter(id=owner_id).exists()
        assert not deck.__class__.objects.filter(pk=deck.pk).exists()
