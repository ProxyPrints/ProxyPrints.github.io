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
from cardpicker.tag_consensus import (
    get_contested_tag_pairs,
    get_resolved_tag_overlay,
    get_suggested_filter_tags_overlay,
    get_tag_net_polarity,
    get_tag_review_queue_pairs,
    get_tag_vote_tally,
    resolve_and_persist_tag_votes,
    resolve_tag,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
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


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


class TestResolveTag:
    def test_no_votes_returns_none(self, db):
        card = CardFactory()
        tag = TagFactory()
        assert resolve_tag(card, tag) is None

    def test_apply_consensus(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert resolve_tag(card, tag) == VotePolarity.APPLY

    def test_not_applicable_consensus(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)
        assert resolve_tag(card, tag) == VotePolarity.NOT_APPLICABLE

    def test_votes_on_a_different_tag_are_not_counted(self, db):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        assert resolve_tag(card, tag_b) is None


class TestResolveAndPersistTagVotes:
    def test_applies_a_resolved_apply_vote(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Borderless"]

    def test_removes_a_resolved_not_applicable_vote(self, db):
        card = CardFactory(tags=["Borderless"])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == []

    def test_unresolved_tag_does_not_change_tags(self, db):
        card = CardFactory(tags=["Existing"])
        tag = TagFactory(name="Contested")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Existing"]

    def test_multiple_tags_resolve_independently_on_the_same_card(self, db):
        card = CardFactory(tags=[])
        apply_tag = TagFactory(name="Apply Me")
        reject_tag = TagFactory(name="Reject Me")
        CardTagVoteFactory(card=card, tag=apply_tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        CardTagVoteFactory(card=card, tag=reject_tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tags == ["Apply Me"]

    def test_persists_resolved_apply_status(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.RESOLVED_APPLY}

    def test_persists_resolved_reject_status(self, db):
        card = CardFactory(tags=["Borderless"])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.RESOLVED_REJECT}

    def test_persists_contested_when_both_polarities_present(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.CONTESTED}

    def test_machine_only_dissent_against_a_lone_human_stays_unresolved_not_contested(self, db):
        # owner-ratified 2026-07-22 vote-weight scenario matrix, decision D3 (matrix cell B3):
        # dissent whose only weight is machine-derived must not be classified CONTESTED - that
        # word is reserved for a genuine human-vs-human disagreement, so a queue built off
        # `tag_vote_statuses` doesn't get flooded by 23k+ scale deduction dissent.
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        for _ in range(3):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.DEDUCTION)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.UNRESOLVED}

    def test_implicit_only_dissent_against_a_lone_human_also_stays_unresolved(self, db):
        # IMPLICIT is non-human-backed too - same D3 treatment as machine-derived dissent.
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.IMPLICIT)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.UNRESOLVED}

    def test_persists_unresolved_for_a_single_vote_below_threshold(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.UNRESOLVED}

    def test_a_resolved_tag_status_survives_unrelated_new_votes_on_a_different_tag(self, db):
        # regression guard for the kind=tag queue's "persisted state, not raw vote existence"
        # requirement - once a tag resolves, later votes on a *different* tag on the same card
        # must not disturb its already-persisted status
        card = CardFactory(tags=[])
        resolved_tag = TagFactory(name="Borderless")
        other_tag = TagFactory(name="Extended")
        CardTagVoteFactory(card=card, tag=resolved_tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)

        CardTagVoteFactory(card=card, tag=other_tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses["Borderless"] == TagVoteStatus.RESOLVED_APPLY


class TestGetTagVoteTally:
    def test_tally_groups_by_polarity(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE)

        tally = get_tag_vote_tally(card, tag)

        assert {(entry["polarity"], entry["count"]) for entry in tally} == {(1, 2), (-1, 1)}


class TestGetResolvedTagOverlay:
    def test_batches_across_multiple_cards_and_tags(self, db):
        card_a = CardFactory()
        card_b = CardFactory()
        tag_a = TagFactory(name="Tag A")
        tag_b = TagFactory(name="Tag B")
        CardTagVoteFactory(card=card_a, tag=tag_a, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        CardTagVoteFactory(card=card_b, tag=tag_b, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN)

        overlay = get_resolved_tag_overlay([card_a.pk, card_b.pk])

        assert overlay == {card_a.pk: {"Tag A": 1}, card_b.pk: {"Tag B": -1}}

    def test_unresolved_pairs_are_omitted(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        overlay = get_resolved_tag_overlay([card.pk])

        assert overlay == {}


class TestGetSuggestedFilterTagsOverlay:
    """
    Owner-ratified 2026-07-22 vote-weight scenario matrix, decision D6's second half: which
    tags qualify as a "suggested" /editor filter chip for a card.
    """

    def test_a_single_real_vote_at_the_weight_threshold_qualifies(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        assert get_suggested_filter_tags_overlay([card.pk]) == {card.pk: ["Foil"]}

    def test_below_the_weight_threshold_does_not_qualify(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.DEDUCTION)

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_implicit_weight_alone_never_qualifies(self, db):
        # implicit weight is excluded entirely (same D6 exclusion as get_tag_net_polarity) -
        # even many implicit votes, well past what would clear the weight threshold if counted,
        # must not bootstrap their own filter-chip suggestion.
        card = CardFactory()
        tag = TagFactory(name="Foil")
        for i in range(10):
            CardTagVoteFactory(
                card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.IMPLICIT, anonymous_id=f"impl-{i}"
            )

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_leaning_reject_does_not_qualify_as_a_suggested_apply_chip(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER)

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_already_resolved_apply_is_excluded(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_stale_resolved_reject_status_excludes_even_a_now_apply_leaning_weight(self, db):
        # exercises the STATUS guard specifically (not just the weight/leaning check): a
        # persisted RESOLVED_REJECT status from an earlier consensus run must still exclude the
        # pair even if the underlying votes have since changed to lean APPLY - the overlay must
        # never race ahead of `resolve_and_persist_tag_votes` re-running.
        card = CardFactory(tags=["Foil"])
        tag = TagFactory(name="Foil")
        admin_vote = CardTagVoteFactory(
            card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.ADMIN
        )
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses["Foil"] == TagVoteStatus.RESOLVED_REJECT

        admin_vote.delete()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_genuinely_contested_status_is_excluded(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_pending_approval_status_is_excluded(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="NSFW", moderation_class=TagModerationClass.SENSITIVE)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_sensitive_tag_is_always_excluded_regardless_of_status(self, db):
        card = CardFactory()
        tag = TagFactory(name="NSFW", moderation_class=TagModerationClass.SENSITIVE)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        assert get_suggested_filter_tags_overlay([card.pk]) == {}

    def test_batches_across_multiple_cards(self, db):
        card_a = CardFactory()
        card_b = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card_b, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        overlay = get_suggested_filter_tags_overlay([card_a.pk, card_b.pk])

        assert overlay == {card_a.pk: ["Foil"], card_b.pk: ["Foil"]}

    def test_absent_from_the_provided_card_ids_is_never_returned(self, db):
        card = CardFactory()
        other_card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        overlay = get_suggested_filter_tags_overlay([other_card.pk])

        assert overlay == {}


class TestGetContestedTagPairs:
    def test_both_polarities_present_is_contested(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE)

        assert (card.pk, tag.pk) in get_contested_tag_pairs()

    def test_agreeing_votes_are_not_contested(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)

        assert (card.pk, tag.pk) not in get_contested_tag_pairs()

    def test_contested_pairs_are_scoped_to_the_specific_tag(self, db):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.NOT_APPLICABLE)
        CardTagVoteFactory(card=card, tag=tag_b, polarity=VotePolarity.APPLY)

        pairs = get_contested_tag_pairs()

        assert (card.pk, tag_a.pk) in pairs
        assert (card.pk, tag_b.pk) not in pairs


class TestGetTagReviewQueuePairs:
    def test_resolved_pairs_are_excluded(self, db, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)

        assert get_tag_review_queue_pairs() == []

    def test_machine_only_dissent_stays_in_the_queue_despite_losing_contested_status(self, db):
        # decision D3's own scope note: de-escalating out of CONTESTED does NOT mean removed
        # from the review queue - a pair with a real human vote on one side and only machine
        # dissent on the other still genuinely needs a human tiebreak, so it must remain a
        # candidate (now filed as UNRESOLVED rather than CONTESTED).
        card = CardFactory(tags=[])
        tag = TagFactory(name="Machine Dissent")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        for _ in range(3):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.DEDUCTION)
        resolve_and_persist_tag_votes(card)

        assert (card.pk, "Machine Dissent") in get_tag_review_queue_pairs()

    def test_contested_before_lopsided(self, db):
        contested_card = CardFactory(tags=[])
        contested_tag = TagFactory(name="Contested Tag")
        CardTagVoteFactory(card=contested_card, tag=contested_tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=contested_card, tag=contested_tag, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(contested_card)

        lopsided_card = CardFactory(tags=[])
        lopsided_tag = TagFactory(name="Lopsided Tag")
        CardTagVoteFactory(card=lopsided_card, tag=lopsided_tag, polarity=VotePolarity.APPLY)
        resolve_and_persist_tag_votes(lopsided_card)

        pairs = get_tag_review_queue_pairs()

        assert pairs[0] == (contested_card.pk, "Contested Tag")

    def test_same_card_is_not_served_back_to_back_when_a_different_card_is_available(self, db):
        # two cards, each with two tags tied at net weight 0 - symmetric group sizes, so
        # round-robin interleaving can (and must) keep every card's items apart for the whole
        # sequence, unlike an asymmetric setup where the smaller group exhausting first would
        # force the larger group's leftover items to end up adjacent regardless of interleaving
        card_a = CardFactory(tags=[])
        tag_1 = TagFactory(name="Tag 1")
        tag_2 = TagFactory(name="Tag 2")
        CardTagVoteFactory(card=card_a, tag=tag_1, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card_a, tag=tag_1, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(card_a)
        CardTagVoteFactory(card=card_a, tag=tag_2, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card_a, tag=tag_2, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(card_a)

        card_b = CardFactory(tags=[])
        tag_3 = TagFactory(name="Tag 3")
        tag_4 = TagFactory(name="Tag 4")
        CardTagVoteFactory(card=card_b, tag=tag_3, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card_b, tag=tag_3, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(card_b)
        CardTagVoteFactory(card=card_b, tag=tag_4, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card_b, tag=tag_4, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(card_b)

        pairs = get_tag_review_queue_pairs()

        card_ids_in_order = [card_id for card_id, _ in pairs]
        # neither card's two items are adjacent, since the other card's item is always
        # available to interleave with at every step
        for card in (card_a, card_b):
            positions = [i for i, card_id in enumerate(card_ids_in_order) if card_id == card.pk]
            assert positions[1] - positions[0] > 1


class TestPostTagConsensus:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_tag_consensus),
            {"identifier": "does-not-exist"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_returns_an_entry_for_every_seeded_tag(self, client, django_settings):
        card = CardFactory()
        TagFactory(name="Tag A")
        TagFactory(name="Tag B")

        response = client.post(
            reverse(views.post_tag_consensus),
            {"identifier": card.identifier},
            content_type="application/json",
        )

        body = response.json()
        assert {entry["tagName"] for entry in body["tags"]} == {"Tag A", "Tag B"}
        assert all(entry["resolvedPolarity"] is None for entry in body["tags"])


class TestGetTagNetPolarity:
    def test_no_votes_is_zero(self, db):
        card = CardFactory()
        tag = TagFactory()
        assert get_tag_net_polarity(card, tag) == 0.0

    def test_unanimous_positive_is_one(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert get_tag_net_polarity(card, tag) == 1.0

    def test_unanimous_negative_is_negative_one(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER)
        assert get_tag_net_polarity(card, tag) == -1.0

    def test_even_split_by_weight_is_zero(self, db):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.USER)
        assert get_tag_net_polarity(card, tag) == 0.0

    def test_votes_on_a_different_tag_are_not_counted(self, db):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert get_tag_net_polarity(card, tag_b) == 0.0

    @pytest.mark.parametrize("implicit_vote_count", [0, 1, 5, 50])
    def test_net_polarity_is_invariant_to_any_number_of_implicit_votes(self, db, implicit_vote_count):
        # owner-ratified 2026-07-22 vote-weight scenario matrix, decision D6: IMPLICIT weight
        # must be excluded entirely from this confidence-fill scalar - piling on any number of
        # implicit votes (agreeing OR dissenting) must never move the value away from the real,
        # non-implicit vote's own net polarity.
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        for i in range(implicit_vote_count):
            CardTagVoteFactory(
                card=card,
                tag=tag,
                polarity=VotePolarity.NOT_APPLICABLE if i % 2 == 0 else VotePolarity.APPLY,
                source=VoteSource.IMPLICIT,
                anonymous_id=f"implicit-{i}",
            )
        assert get_tag_net_polarity(card, tag) == 1.0


class TestPostSubmitTagVote:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": "does-not-exist", "tagName": "x", "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_tag_name_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": "does-not-exist", "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_invalid_polarity_is_a_bad_request(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 99, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_creates_a_vote_and_persists_consensus(self, client, django_settings, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")

        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["resolvedPolarity"] == 1
        card.refresh_from_db()
        assert card.tags == ["Borderless"]
        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 1

    def test_changing_your_mind_updates_the_same_row_rather_than_adding_another(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()

        for polarity in (1, -1):
            client.post(
                reverse(views.post_submit_tag_vote),
                {"identifier": card.identifier, "tagName": tag.name, "polarity": polarity, "anonymousId": "anon-1"},
                content_type="application/json",
            )

        votes = CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1")
        assert votes.count() == 1
        assert votes.get().polarity == -1

    def test_a_vote_on_one_tag_does_not_clear_a_vote_on_another_tag_by_the_same_person(self, client, django_settings):
        card = CardFactory()
        tag_a = TagFactory()
        tag_b = TagFactory()

        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag_a.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag_b.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert CardTagVote.objects.filter(card=card, anonymous_id="anon-1").count() == 2

    def test_retraction_deletes_the_vote_and_unresolves_consensus(self, client, django_settings):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 1

        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 0, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 0
        assert response.json()["resolvedPolarity"] is None
        card.refresh_from_db()
        assert card.tags == []

    def test_retracting_a_vote_that_was_never_cast_is_a_no_op(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()
        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 0, "anonymousId": "anon-1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 0

    def test_retraction_only_removes_this_anonymous_ids_own_vote(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()
        CardTagVoteFactory(card=card, tag=tag, anonymous_id="anon-other", polarity=1)
        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 0, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-1").count() == 0
        assert CardTagVote.objects.filter(card=card, tag=tag, anonymous_id="anon-other").count() == 1

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.PRINTING_TAG_SUBMISSION_RATE = "1/m"
        card = CardFactory()
        tag = TagFactory()
        body = {
            "identifier": card.identifier,
            "tagName": tag.name,
            "polarity": 1,
            "anonymousId": "anon-rate-limited",
        }

        first = client.post(reverse(views.post_submit_tag_vote), body, content_type="application/json")
        second = client.post(reverse(views.post_submit_tag_vote), body, content_type="application/json")

        assert first.status_code == 200
        assert second.status_code == 429

    def test_vote_surface_is_persisted_verbatim_when_sent(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()

        client.post(
            reverse(views.post_submit_tag_vote),
            {
                "identifier": card.identifier,
                "tagName": tag.name,
                "polarity": 1,
                "anonymousId": "anon-1",
                "voteSurface": "question-feed",
            },
            content_type="application/json",
        )

        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.vote_surface == "question-feed"

    def test_vote_surface_is_null_when_omitted_old_client_unaffected(self, client, django_settings):
        card = CardFactory()
        tag = TagFactory()

        response = client.post(
            reverse(views.post_submit_tag_vote),
            {"identifier": card.identifier, "tagName": tag.name, "polarity": 1, "anonymousId": "anon-1"},
            content_type="application/json",
        )

        assert response.status_code == 200
        vote = CardTagVote.objects.get(card=card, tag=tag, anonymous_id="anon-1")
        assert vote.vote_surface is None
