"""
Tests for the SavedDeckShare model (docs/proposals/proposal-g-user-accounts-saved-decks.md's
"PR-5, post-v1: per-deck share links"). Model-level only - the endpoint surface
(2/createDeckShare/, 2/deckShares/, 2/revokeDeckShare/, 2/getSharedDeck/) gets its own view-layer
tests, mirroring test_saved_deck_views.py's ownership/403 pattern. No encryption happens at this
layer (the server never decrypts anything, by design) - these tests only confirm the backend
stores and round-trips opaque bytes faithfully, cascades correctly, and expires correctly.
"""

from datetime import timedelta

from django.utils import timezone

from cardpicker.tests.factories import SavedDeckFactory, SavedDeckShareFactory


class TestSavedDeckShareDefaults:
    def test_defaults(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share = SavedDeckShareFactory(deck=deck)
        assert share.id is not None
        assert share.created_at is not None
        assert share.expires_at is None
        assert not share.is_expired()


class TestSavedDeckShareExpiry:
    def test_future_expiry_is_not_expired(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share = SavedDeckShareFactory(deck=deck, expires_at=timezone.now() + timedelta(days=7))
        assert not share.is_expired()

    def test_past_expiry_is_expired(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share = SavedDeckShareFactory(deck=deck, expires_at=timezone.now() - timedelta(seconds=1))
        assert share.is_expired()


class TestSavedDeckShareCascadeDelete:
    def test_deleting_the_deck_deletes_its_shares(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share = SavedDeckShareFactory(deck=deck)
        share_pk = share.pk
        deck.delete()
        assert not share.__class__.objects.filter(pk=share_pk).exists()

    def test_deleting_owner_cascades_through_the_deck_to_its_shares(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share = SavedDeckShareFactory(deck=deck)
        share_pk = share.pk
        plain_user.delete()
        assert not share.__class__.objects.filter(pk=share_pk).exists()


class TestSavedDeckShareIndependence:
    def test_a_deck_can_have_multiple_independent_shares(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share_one = SavedDeckShareFactory(deck=deck)
        share_two = SavedDeckShareFactory(deck=deck)
        assert share_one.id != share_two.id
        assert deck.shares.count() == 2

    def test_revoking_one_share_does_not_touch_a_sibling_share(self, plain_user):
        deck = SavedDeckFactory(owner=plain_user)
        share_one = SavedDeckShareFactory(deck=deck)
        share_two = SavedDeckShareFactory(deck=deck)
        share_one.delete()
        assert deck.shares.filter(pk=share_two.pk).exists()
