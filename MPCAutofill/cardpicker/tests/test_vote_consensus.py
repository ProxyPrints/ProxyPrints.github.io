from django.conf import settings

from cardpicker.models import VoteSource
from cardpicker.tests.factories import CardArtistVoteFactory, CardFactory
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
    is_human_backed_source,
    resolve_weighted_consensus,
)


class TestIsHumanBackedSource:
    """Direct coverage of the 2026-07-15 AI->DEDUCTION/OCR split's single source of truth for
    the human-backed gate - both new machine-derived values must read as non-human-backed,
    same as the old single AI value did; everything else (including a future FEDERATED vote,
    whose human-backed-ness is reported by the exporting peer, not derived from `source`) is
    human-backed by default."""

    def test_deduction_and_ocr_are_not_human_backed(self):
        assert is_human_backed_source(VoteSource.DEDUCTION) is False
        assert is_human_backed_source(VoteSource.OCR) is False

    def test_user_admin_federated_are_human_backed(self):
        assert is_human_backed_source(VoteSource.USER) is True
        assert is_human_backed_source(VoteSource.ADMIN) is True
        assert is_human_backed_source(VoteSource.FEDERATED) is True


class TestResolveWeightedConsensus:
    def test_no_votes_returns_none(self):
        assert resolve_weighted_consensus([], min_weight=2, min_share=0.6) is None

    def test_single_group_clears_thresholds(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_below_min_weight_returns_none(self):
        votes = [VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_tie_below_min_share_returns_none(self):
        # two outcomes with equal weight: share is exactly 0.5, below a 0.6 threshold
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_admin_style_weight_override(self):
        # one high-weight vote (e.g. an "admin") outweighs two conflicting low-weight votes
        votes = [
            VoteTuple(outcome_key="a", weight=5.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_ai_only_votes_never_resolve_even_with_large_weight(self):
        votes = [VoteTuple(outcome_key="a", weight=10.0, is_human_backed=False) for _ in range(5)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_mixed_ai_and_non_ai_can_resolve(self):
        votes = [
            VoteTuple(outcome_key="a", weight=0.5, is_human_backed=False),
            VoteTuple(outcome_key="a", weight=2.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_three_way_split_leader_below_share_returns_none(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="c", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None


class TestFederatedWeighting:
    """
    Federation-readiness stub (see docs/federation-v1.md) - no import path creates federated
    votes yet, so these tests exercise the plumbing directly via VoteTuple/settings rather than
    through a real submit view.
    """

    def test_federated_source_uses_the_configured_weight(self):
        assert _SOURCE_WEIGHTS[VoteSource.FEDERATED] == settings.VOTE_FEDERATED_WEIGHT

    def test_federated_vote_with_human_backed_true_satisfies_the_gate(self):
        votes = [
            VoteTuple(outcome_key="a", weight=settings.VOTE_FEDERATED_WEIGHT * 5, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_federated_vote_with_human_backed_false_does_not_satisfy_the_gate_alone(self):
        # mirrors test_ai_only_votes_never_resolve_even_with_large_weight - a federated vote
        # explicitly marked not-human-backed can never single-handedly clear consensus, same
        # as an AI vote, regardless of how much weight it carries
        votes = [VoteTuple(outcome_key="a", weight=settings.VOTE_FEDERATED_WEIGHT * 100, is_human_backed=False)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None


class TestFederatedModelFields:
    def test_federated_source_and_peer_round_trip(self, db):
        card = CardFactory()
        vote = CardArtistVoteFactory(card=card, source=VoteSource.FEDERATED, peer="peer-instance-1")
        vote.refresh_from_db()
        assert vote.source == VoteSource.FEDERATED
        assert vote.peer == "peer-instance-1"

    def test_peer_defaults_to_none_for_non_federated_votes(self, db):
        card = CardFactory()
        vote = CardArtistVoteFactory(card=card, source=VoteSource.USER)
        vote.refresh_from_db()
        assert vote.peer is None
