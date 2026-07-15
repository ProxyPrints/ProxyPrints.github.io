import pytest

from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    ArtistVoteStatus,
    PrintingTagStatus,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.question_feed import get_next_question_feed_item, get_remaining_estimate
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    SourceFactory,
    TagFactory,
)

# see test_printing_consensus.py for why this capture-and-restore fixture exists
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


def make_ai_suggested_card(anonymous_id: str = "ai-bot") -> tuple:
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=anonymous_id)
    return card, printing


def make_pending_pair(tag_name: str = "sensitive-tag") -> tuple:
    # printing/artist already resolved so this card would only ever match the old tier-3
    # moderation candidate set (now removed from this feed entirely - see
    # test_pending_approval_pairs_never_appear_in_the_feed below) - isolates it from tiers 2/4,
    # which would otherwise also match this card via its (irrelevant, default-unresolved)
    # printing/artist status
    card = CardFactory(
        tags=[], printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
    )
    tag = TagFactory(name=tag_name, moderation_class=TagModerationClass.SENSITIVE)
    for index in range(2):
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id=f"crowd-{index}")
    resolve_and_persist_tag_votes(card)
    card.refresh_from_db()
    return card, tag


class TestGetNextQuestionFeedItem:
    def test_no_data_returns_none(self, db):
        assert get_next_question_feed_item("anon-1") is None

    def test_tier_1_returns_confirm_suggestion_with_the_ai_suggested_printing(self, db):
        card, printing = make_ai_suggested_card()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier
        assert item.suggestedPrinting.identifier == str(printing.identifier)

    def test_tier_1_excludes_cards_this_voter_already_voted_on(self, db):
        make_ai_suggested_card(anonymous_id="ai-bot")
        # the only tier-1 candidate has this same anonymous_id's own vote already
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        # falls through past the excluded tier-1 card - no other data exists, so None
        assert item is None or item.card.identifier != card.identifier

    def test_a_second_voters_own_exclusion_does_not_affect_a_first_voter(self, db):
        card, _ = make_ai_suggested_card()

        item_for_second_voter = get_next_question_feed_item("anon-2")

        assert item_for_second_voter is not None
        assert item_for_second_voter.card.identifier == card.identifier

    def test_tier_2_contested_printing_wins_over_tier_4_fresh_unresolved(self, db):
        # tier 4 candidate: a plain unresolved card with no votes at all
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # tier 2 candidate: a contested card (two different printings voted for)
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == contested_card.identifier

    def test_tier_4_fresh_unresolved_printing_when_nothing_higher_priority_exists(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == card.identifier

    def test_tier_4_prioritizes_a_card_one_vote_from_resolving_over_a_totally_fresh_one(self, db):
        # zero votes at all - the common case, 28k+ of these exist at once
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # one AI vote + one *agreeing* human vote (weight 1.5 < PRINTING_TAG_MIN_VOTES=2, so
        # not yet resolved) - excluded from tier 1 (has a human vote) and not contested
        # (agreeing, not conflicting), so it falls through to tier 4 same as a fresh card,
        # but is one vote closer to actually resolving than one with zero votes.
        almost_resolved = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.USER)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == almost_resolved.identifier

    def test_tier_4_artist_when_no_printing_candidates_remain(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "artist"
        assert item.card.identifier == card.identifier

    def test_pending_approval_pairs_never_appear_in_the_feed(self, db):
        # pending-approval (card, tag) pairs used to surface here as a moderator-only tier 3 -
        # that hijacked the whole feed for moderators for as long as any report stayed pending
        # (see this module's docstring) and has moved to a dedicated Moderation tab
        # (`POST 2/moderationQueue/`, tested in test_moderation_views.py); get_next_question_
        # feed_item no longer even takes a `user` argument, since nothing here needs one any
        # more - this feed must never serve a pending-approval pair again, for any role
        make_pending_pair()

        assert get_next_question_feed_item("anon-1") is None

    def test_own_vote_exclusion_is_scoped_to_the_specific_tag_not_the_whole_card(self, db):
        """A voter who already answered one contested tag on a card must still be served a
        *different* still-open contested tag on the same card - own-vote exclusion must not
        be card-level (regression test for a bug caught in review before this shipped)."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        tag_a = TagFactory(name="Full Art")
        tag_b = TagFactory(name="Etched")
        for tag in (tag_a, tag_b):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses[tag_a.name] == TagVoteStatus.CONTESTED
        assert card.tag_vote_statuses[tag_b.name] == TagVoteStatus.CONTESTED
        # this voter already answered tag_a, but not tag_b
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "tag"
        assert item.card.identifier == card.identifier
        assert item.tagName == tag_b.name


class TestGetRemainingEstimate:
    def test_is_non_negative(self, db):
        assert get_remaining_estimate() >= 0

    def test_counts_unresolved_printing_cards(self, db):
        before = get_remaining_estimate()
        # artist_vote_status=RESOLVED so this card contributes to only the printing count -
        # a fresh CardFactory() defaults artist_vote_status to UNRESOLVED too, which would
        # otherwise add 1 to the artist-tier count as well and make this assertion brittle
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        after = get_remaining_estimate()
        assert after == before + 1

    def test_pending_approval_pairs_are_not_counted(self, db):
        # this feed's "remaining" count is ordinary-tagging advisory copy only - pending
        # moderation reports have their own badge on the dedicated Moderation tab instead
        # (see this module's docstring)
        before = get_remaining_estimate()
        make_pending_pair()
        assert get_remaining_estimate() == before


class TestGetQuestionFeedView:
    def test_missing_anonymous_id_is_a_bad_request(self, client, django_settings):
        response = client.get(reverse(views.get_question_feed))
        assert response.status_code == 400

    def test_returns_null_item_when_caught_up(self, client, django_settings):
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.status_code == 200
        assert response.json()["item"] is None
        assert response.json()["remainingEstimate"] == 0

    def test_returns_the_next_item(self, client, django_settings):
        card, _ = make_ai_suggested_card()
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.status_code == 200
        assert response.json()["item"]["card"]["identifier"] == card.identifier

    def test_pending_approval_pairs_never_surface_here_even_for_a_moderator_session(
        self, client, django_settings, moderator_user
    ):
        make_pending_pair()

        client.force_login(moderator_user)
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.json()["item"] is None
