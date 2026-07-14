"""
The privileged-approval gate for sensitive tags (see docs/features/moderation.md).

Deliberately a separate file from test_vote_consensus.py/test_tag_votes.py: those suites
passing WITHOUT MODIFICATION is the regression proof that standard-tag behavior is
byte-identical under the gate, so this feature must not touch them.
"""


from django.conf import settings

from cardpicker.models import (
    CardTagVote,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tag_consensus import (
    get_resolved_tag_overlay,
    get_tag_review_queue_pairs,
    resolve_and_persist_tag_votes,
    resolve_tag,
)
from cardpicker.tests.factories import CardFactory, CardTagVoteFactory, TagFactory
from cardpicker.vote_consensus import (
    PENDING_PRIVILEGED,
    VoteTuple,
    resolve_weighted_consensus,
)


def sensitive_tag(name: str = "nsfw-like"):
    return TagFactory(name=name, moderation_class=TagModerationClass.SENSITIVE)


class TestRequirePrivilegedGate:
    """`resolve_weighted_consensus(require_privileged=True)` in isolation - the gate matrix."""

    def test_crowd_consensus_without_privileged_vote_is_pending(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True) is (
            PENDING_PRIVILEGED
        )

    def test_privileged_vote_in_winning_group_resolves(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=5.0, is_human_backed=True, is_privileged=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True) == "a"

    def test_privileged_vote_on_losing_side_is_not_a_co_sign(self):
        # the gate requires a privileged vote backing the WINNER - a moderator arguing for a
        # different outcome must not unlock the crowd's outcome over their own objection.
        # (a heavier privileged vote usually flips or contests the result through the normal
        # weight math; this fixed-weight case isolates the gate semantics themselves.)
        votes = [
            VoteTuple(outcome_key="a", weight=10.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=10.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True, is_privileged=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True) is (
            PENDING_PRIVILEGED
        )

    def test_below_threshold_is_unresolved_not_pending(self):
        # None means "not enough signal"; the sentinel is reserved for "would resolve, needs
        # a co-sign" - a single sub-threshold vote is the former
        votes = [VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True) is None

    def test_default_require_privileged_false_never_produces_the_sentinel(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"


class TestSensitiveTagGate:
    """`resolve_tag`/`resolve_and_persist_tag_votes` with a sensitive tag - the DB-level pass."""

    def test_crowd_votes_on_sensitive_tag_park_as_pending_approval(self, db):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)

        assert resolve_tag(card, tag) is PENDING_PRIVILEGED
        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {tag.name: TagVoteStatus.PENDING_APPROVAL}
        assert card.tags == []  # a pending tag has zero search consequences

    def test_pending_does_not_reindex_but_moderator_approval_does(self, db, monkeypatch, moderator_user):
        reindexed_cards = []
        monkeypatch.setattr("cardpicker.documents.reindex_card_safely", reindexed_cards.append)
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        resolve_and_persist_tag_votes(card)
        assert reindexed_cards == []  # pending: tags untouched, nothing to push to ES

        # the privileged vote re-enters the SAME normal pass - resolution, tags merge, and the
        # ES push all happen through the pre-existing machinery, not a moderation-specific one
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, user=moderator_user)
        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {tag.name: TagVoteStatus.RESOLVED_APPLY}
        assert card.tags == [tag.name]
        assert reindexed_cards == [card]

    def test_lone_moderator_vote_clears_the_threshold_at_privileged_weight(self, db, moderator_user):
        # VOTE_PRIVILEGED_WEIGHT defaults to the admin weight (5), so one moderator resolves a
        # sensitive tag alone, exactly like one admin would
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, user=moderator_user)
        assert settings.VOTE_PRIVILEGED_WEIGHT >= settings.PRINTING_TAG_MIN_VOTES
        assert resolve_tag(card, tag) == VotePolarity.APPLY

    def test_admin_source_vote_counts_as_privileged(self, db):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        assert resolve_tag(card, tag) == VotePolarity.APPLY

    def test_moderator_reject_resolves_against_the_crowd_through_normal_weight_math(self, db, moderator_user):
        # crowd: 2x APPLY (weight 2). moderator: NOT_APPLICABLE at weight 5 -> winner is
        # NOT_APPLICABLE with share 5/7 - the "re-resolves through the normal pass" behavior
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, user=moderator_user)
        assert resolve_tag(card, tag) == VotePolarity.NOT_APPLICABLE

    def test_revoking_moderator_de_privileges_their_votes(self, db, moderator_user, moderators_group):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, user=moderator_user)
        assert resolve_tag(card, tag) == VotePolarity.APPLY

        moderator_user.groups.remove(moderators_group)
        # same rows, no privileged backing anymore: sub-threshold at weight 1
        assert resolve_tag(card, tag) is None

    def test_standard_tag_with_identical_votes_resolves_without_any_co_sign(self, db):
        # the mirror-image of test_crowd_votes_on_sensitive_tag_park_as_pending_approval:
        # only moderation_class differs, and the gate never engages
        card = CardFactory(tags=[])
        tag = TagFactory(name="ordinary")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)

        resolve_and_persist_tag_votes(card)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {tag.name: TagVoteStatus.RESOLVED_APPLY}
        assert card.tags == [tag.name]

    def test_seeded_sensitive_taxonomy_is_gated_end_to_end(self, db):
        # the same flow through the real seeded rows rather than a synthetic sensitive tag
        seed_sensitive_tags()
        from cardpicker.models import Tag

        nsfw = Tag.objects.get(name="NSFW")
        card = CardFactory(tags=[])
        CardTagVoteFactory(card=card, tag=nsfw, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=nsfw, polarity=VotePolarity.APPLY)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses == {"NSFW": TagVoteStatus.PENDING_APPROVAL}
        assert card.tags == []


class TestOverlayRespectsTheGate:
    """
    get_resolved_tag_overlay is the second resolution path into Card.tags (the update_database
    bulk-sync merge) - a pending sensitive pair must be invisible to it, or a scheduled re-scan
    applies the very change the interactive path held for approval.
    """

    def test_pending_sensitive_pair_is_absent_from_the_overlay(self, db):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        assert get_resolved_tag_overlay([card.pk]) == {}

    def test_moderator_backed_sensitive_pair_is_present(self, db, moderator_user):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, user=moderator_user)
        assert get_resolved_tag_overlay([card.pk]) == {card.pk: {tag.name: VotePolarity.APPLY}}

    def test_standard_pair_resolves_in_overlay_exactly_as_before(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="ordinary")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        assert get_resolved_tag_overlay([card.pk]) == {card.pk: {tag.name: VotePolarity.APPLY}}


class TestPublicQueueExcludesPending:
    def test_pending_approval_pair_is_not_served_by_the_public_tag_queue(self, db):
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        resolve_and_persist_tag_votes(card)
        assert (card.pk, tag.name) not in get_tag_review_queue_pairs()

    def test_contested_sensitive_pair_still_reaches_the_public_queue(self, db):
        # the gate only intercepts would-be resolutions; gathering votes on a contested
        # sensitive pair is still the public queue's job
        card = CardFactory(tags=[])
        tag = sensitive_tag()
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE)
        resolve_and_persist_tag_votes(card)
        assert (card.pk, tag.name) in get_tag_review_queue_pairs()


class TestVoteUserFactoryPassthrough:
    def test_card_tag_vote_factory_accepts_user(self, db, plain_user):
        vote = CardTagVoteFactory(user=plain_user)
        assert CardTagVote.objects.get(pk=vote.pk).user == plain_user
