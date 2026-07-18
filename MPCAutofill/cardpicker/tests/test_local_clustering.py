"""
Low-level tests for cardpicker.local_clustering (docs/features/printing-tags.md's hash-at-ingest
architecture, 2026-07-16) - the numpy-vectorized near-duplicate scan specifically, independent
of run_pilot/select_candidates (see test_local_identify_printing_tags.py's TestClusterDedup for
the integration-level tests through the real Card/select_candidates path).
"""

from cardpicker.local_clustering import (
    NEAR_DUPLICATE_MAX_DISTANCE,
    _compute_exact_match_clusters,
    _compute_near_duplicate_hints,
    _find_pairs_within_distance,
    _unsigned_hash_array,
)


class TestFindPairsWithinDistance:
    def test_finds_a_close_pair_across_a_chunk_boundary(self):
        # chunk_size=2 forces card 0 and card 3 into DIFFERENT chunks - the pair must still be
        # found (each chunk is compared against the FULL array, not just itself).
        hash_by_card_id = {0: 0b0000, 1: 0b1111, 2: 0b1111, 3: 0b0001}
        hashes = _unsigned_hash_array(list(hash_by_card_id.keys()), hash_by_card_id)

        pairs = _find_pairs_within_distance(hashes, max_distance=NEAR_DUPLICATE_MAX_DISTANCE, chunk_size=2)

        pair_indices = {(i, j) for i, j, _d in pairs}
        assert (0, 3) in pair_indices  # distance 1, indices 0 and 3

    def test_never_returns_a_self_pair_or_a_duplicate_reversed_pair(self):
        hash_by_card_id = {0: 0b0000, 1: 0b0000}
        hashes = _unsigned_hash_array(list(hash_by_card_id.keys()), hash_by_card_id)

        pairs = _find_pairs_within_distance(hashes, max_distance=NEAR_DUPLICATE_MAX_DISTANCE, chunk_size=2)

        assert pairs == [(0, 1, 0)]

    def test_beyond_threshold_pairs_are_excluded(self):
        hash_by_card_id = {0: 0b0000, 1: 0b0111}  # distance 3
        hashes = _unsigned_hash_array(list(hash_by_card_id.keys()), hash_by_card_id)

        pairs = _find_pairs_within_distance(hashes, max_distance=2, chunk_size=2)

        assert pairs == []

    def test_empty_input_returns_empty(self):
        hashes = _unsigned_hash_array([], {})
        assert _find_pairs_within_distance(hashes, max_distance=2) == []


class TestComputeExactMatchClusters:
    def test_groups_by_exact_hash_lowest_pk_representative(self):
        hash_by_card_id = {5: 100, 2: 100, 9: 100, 3: 200}

        result = _compute_exact_match_clusters(hash_by_card_id)

        assert result == {2: [5, 9]}

    def test_singleton_hash_produces_no_cluster(self):
        assert _compute_exact_match_clusters({1: 100, 2: 200}) == {}


class TestComputeNearDuplicateHints:
    def test_symmetric_adjacency_for_a_close_pair(self):
        hash_by_card_id = {1: 0b0000, 2: 0b0001}

        result = _compute_near_duplicate_hints(hash_by_card_id)

        assert result == {1: {2}, 2: {1}}

    def test_d0_pairs_also_appear_as_near_duplicate_hints(self):
        # NEAR_DUPLICATE_MAX_DISTANCE (2) >= 0, so exact matches are a subset of the near-dup
        # scan's own results too - the two tiers overlap by design (see module docstring).
        hash_by_card_id = {1: 123, 2: 123}

        result = _compute_near_duplicate_hints(hash_by_card_id)

        assert result == {1: {2}, 2: {1}}
