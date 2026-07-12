from cardpicker.vote_consensus import VoteTuple, resolve_weighted_consensus


class TestResolveWeightedConsensus:
    def test_no_votes_returns_none(self):
        assert resolve_weighted_consensus([], min_weight=2, min_share=0.6) is None

    def test_single_group_clears_thresholds(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_below_min_weight_returns_none(self):
        votes = [VoteTuple(outcome_key="a", weight=1.0, is_ai=False)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_tie_below_min_share_returns_none(self):
        # two outcomes with equal weight: share is exactly 0.5, below a 0.6 threshold
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="b", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="b", weight=1.0, is_ai=False),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_admin_style_weight_override(self):
        # one high-weight vote (e.g. an "admin") outweighs two conflicting low-weight votes
        votes = [
            VoteTuple(outcome_key="a", weight=5.0, is_ai=False),
            VoteTuple(outcome_key="b", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="b", weight=1.0, is_ai=False),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_ai_only_votes_never_resolve_even_with_large_weight(self):
        votes = [VoteTuple(outcome_key="a", weight=10.0, is_ai=True) for _ in range(5)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_mixed_ai_and_non_ai_can_resolve(self):
        votes = [
            VoteTuple(outcome_key="a", weight=0.5, is_ai=True),
            VoteTuple(outcome_key="a", weight=2.0, is_ai=False),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_three_way_split_leader_below_share_returns_none(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="a", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="b", weight=1.0, is_ai=False),
            VoteTuple(outcome_key="c", weight=1.0, is_ai=False),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None
