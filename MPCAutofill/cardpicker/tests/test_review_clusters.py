"""
Tests for cardpicker.review_clusters (issue #262): the exact-signal union-find clustering pass
over the review queue, and its cache wrapper. See that module's own docstring for the "why
exact-only, why not Hamming near-duplicate" rationale this test suite verifies.
"""

import pytest

from django.core.cache import cache

from cardpicker.local_calculate_verdicts import (
    SLOW_PATH_ANONYMOUS_ID,
    SLOW_PATH_TO_REVIEW_REASON,
)
from cardpicker.models import CardScanLog, PrintingTagStatus
from cardpicker.review_clusters import (
    MIN_ALNUM_DENSITY,
    MIN_NORMALIZED_TEXT_LENGTH,
    REVIEW_CLUSTER_CACHE_KEY,
    SIGNAL_TYPE_CONTENT_PHASH,
    SIGNAL_TYPE_LEGAL_LINE_TEXT,
    SIGNAL_TYPE_SYMBOL_PHASH,
    compute_review_clusters,
    find_cluster,
    get_cached_review_clusters,
    invalidate_review_cluster_cache,
    normalize_legal_line_text,
)
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_review_card(*, content_phash=None, symbol_phash=None, legal_line_raw_text="", name=None):
    """A card routed to the slow-path review queue (a real CardScanLog row, same as
    local_calculate_verdicts.run_slow_path_calculator would write) with an optional CURRENT
    ImageEvidence row (content_hash matching this card's own content_phash, same freshness
    convention every real caller relies on)."""
    card = CardFactory(content_phash=content_phash, **({"name": name} if name else {}))
    CardScanLog.objects.create(card=card, anonymous_id=SLOW_PATH_ANONYMOUS_ID, skip_reason=SLOW_PATH_TO_REVIEW_REASON)
    if content_phash is not None:
        ImageEvidenceFactory(
            card=card,
            content_hash=content_phash,
            symbol_phash=symbol_phash,
            legal_line_raw_text=legal_line_raw_text,
        )
    return card


class TestNormalizeLegalLineText:
    def test_blank_text_is_none(self):
        assert normalize_legal_line_text("") is None

    def test_short_ocr_noise_is_rejected(self):
        # the measurement's own named example - "top-15 groups include pure OCR noise like '4'"
        assert normalize_legal_line_text("4") is None

    def test_exactly_at_the_length_boundary_is_accepted(self):
        text = "notforsale12"
        assert len(text) == MIN_NORMALIZED_TEXT_LENGTH
        assert normalize_legal_line_text(text) == text

    def test_one_below_the_length_boundary_is_rejected(self):
        assert normalize_legal_line_text("notforsale1") is None

    def test_low_density_garbage_is_rejected_even_past_the_length_bar(self):
        # 15 real alphanumeric characters (>= MIN_NORMALIZED_TEXT_LENGTH) buried in 60 symbol
        # characters - passes the length guardrail alone but must fail the density guardrail.
        raw = "1" * 15 + "@" * 60
        normalized = "1" * 15
        density = len(normalized) / len(raw)
        assert density < MIN_ALNUM_DENSITY
        assert normalize_legal_line_text(raw) is None

    def test_genuine_legal_line_with_linebreaks_is_accepted(self):
        raw = "NOT FOR SALE\nCardConjurer.com"
        normalized = normalize_legal_line_text(raw)
        assert normalized == "notforsalecardconjurercom"

    def test_case_insensitive_and_symbol_stripped(self):
        assert normalize_legal_line_text("MTG*EN*Midjourney (c) 2024") == normalize_legal_line_text(
            "mtg en midjourney c 2024"
        )


class TestComputeReviewClusters:
    def test_singletons_are_excluded_from_the_cluster_list(self, db):
        make_review_card(content_phash=111)
        make_review_card(content_phash=222)
        assert compute_review_clusters() == []

    def test_exact_content_phash_match_forms_a_cluster(self, db):
        a = make_review_card(content_phash=42)
        b = make_review_card(content_phash=42)
        clusters = compute_review_clusters()
        assert len(clusters) == 1
        (cluster,) = clusters
        assert cluster.size == 2
        assert {m.identifier for m in cluster.members} == {a.identifier, b.identifier}
        assert cluster.signals == [
            _signal(SIGNAL_TYPE_CONTENT_PHASH, "42", 2),
        ]

    def test_near_but_not_exact_content_phash_never_merges(self, db):
        # this is the measurement's own headline guardrail: no Hamming-distance edges, ever -
        # a one-bit-different hash must never be treated as "the same card".
        make_review_card(content_phash=0b1010)
        make_review_card(content_phash=0b1011)
        assert compute_review_clusters() == []

    def test_exact_symbol_phash_match_forms_a_cluster(self, db):
        a = make_review_card(content_phash=1, symbol_phash=99)
        b = make_review_card(content_phash=2, symbol_phash=99)
        clusters = compute_review_clusters()
        assert len(clusters) == 1
        (cluster,) = clusters
        assert {m.identifier for m in cluster.members} == {a.identifier, b.identifier}
        assert cluster.signals == [_signal(SIGNAL_TYPE_SYMBOL_PHASH, "99", 2)]

    def test_exact_normalized_text_match_forms_a_cluster(self, db):
        a = make_review_card(content_phash=1, legal_line_raw_text="NOT FOR SALE CardConjurer.com")
        b = make_review_card(content_phash=2, legal_line_raw_text="not for sale cardconjurer.com")
        clusters = compute_review_clusters()
        assert len(clusters) == 1
        (cluster,) = clusters
        assert {m.identifier for m in cluster.members} == {a.identifier, b.identifier}
        assert cluster.signals == [_signal(SIGNAL_TYPE_LEGAL_LINE_TEXT, "notforsalecardconjurercom", 2)]

    def test_ocr_noise_text_contributes_no_edge(self, db):
        # two cards that would otherwise be unrelated singletons must NOT merge just because
        # their (OCR-noise) legal-line readings happen to both normalize to "4".
        make_review_card(content_phash=1, legal_line_raw_text="4")
        make_review_card(content_phash=2, legal_line_raw_text="4")
        assert compute_review_clusters() == []

    def test_cross_signal_type_transitivity_merges_a_three_card_chain(self, db):
        # A-B share content_phash, B-C share legal text, A and C share NOTHING directly - the
        # measurement's own "conservative grouping... union" headline number depends on this
        # cross-signal-type transitivity being intentional, not a bug.
        a = make_review_card(content_phash=7)
        b = make_review_card(content_phash=7, legal_line_raw_text="shared legal line text!!")
        c = make_review_card(content_phash=8, legal_line_raw_text="shared legal line text!!")
        clusters = compute_review_clusters()
        assert len(clusters) == 1
        (cluster,) = clusters
        assert cluster.size == 3
        assert {m.identifier for m in cluster.members} == {a.identifier, b.identifier, c.identifier}
        signal_types = {s.signal_type for s in cluster.signals}
        assert signal_types == {SIGNAL_TYPE_CONTENT_PHASH, SIGNAL_TYPE_LEGAL_LINE_TEXT}

    def test_multiple_disjoint_clusters_sorted_by_size_descending(self, db):
        for _ in range(3):
            make_review_card(content_phash=1)
        for _ in range(2):
            make_review_card(content_phash=2)
        clusters = compute_review_clusters()
        assert [c.size for c in clusters] == [3, 2]

    def test_a_card_without_any_signal_stays_a_singleton(self, db):
        make_review_card(content_phash=None)
        make_review_card(content_phash=None)
        assert compute_review_clusters() == []

    def test_decision_count_arithmetic_matches_the_issue_262_measurement_shape(self, db):
        """Fixture-scale sanity check against issue #262's own read-only measurement ("16,928
        cards -> 11,802 decisions: 2,208 multi-card clusters covering 7,334 cards + 9,594
        singletons"). Reproducing that exact figure needs the real production content_phash/
        symbol_phash/legal_line data at 16,928-card scale, which isn't available to a test - what
        IS cheaply verifiable here is the underlying arithmetic invariant the measurement itself
        relies on: total review-queue population == (number of cards absorbed into multi-card
        clusters) + (number of singleton cards), i.e. "decisions" = len(clusters) + singletons,
        never double-counted and never dropped, at a small synthetic scale mirroring the real
        shape (a few large groups, mostly singletons)."""
        total_cards = 0
        expected_clustered_cards = 0
        for phash, group_size in ((1, 5), (2, 3), (3, 2)):  # three multi-card clusters
            for _ in range(group_size):
                make_review_card(content_phash=phash)
            total_cards += group_size
            expected_clustered_cards += group_size
        singleton_count = 6
        for i in range(singleton_count):
            make_review_card(content_phash=100 + i)
        total_cards += singleton_count

        clusters = compute_review_clusters()
        assert len(clusters) == 3  # the three multi-card clusters, singletons excluded
        clustered_cards = sum(c.size for c in clusters)
        assert clustered_cards == expected_clustered_cards
        decisions = len(clusters) + singleton_count
        assert clustered_cards + singleton_count == total_cards
        assert decisions == 3 + 6 == 9  # 3 cluster-decisions + 6 singleton-decisions

    def test_resolved_cards_drop_out_of_the_queue(self, db):
        make_review_card(content_phash=55)
        b = make_review_card(content_phash=55)
        b.printing_tag_status = PrintingTagStatus.NO_MATCH
        b.save()
        clusters = compute_review_clusters()
        assert clusters == []  # a is now a singleton once b (its only pair) resolved out

    def test_stale_evidence_is_not_used(self, db):
        # `a`'s image has since changed (a re-upload) - its live content_phash no longer matches
        # the ImageEvidence row written for it, so that row's symbol_phash must never be trusted,
        # even though it's numerically identical to `b`'s own (CURRENT) symbol_phash reading.
        a = make_review_card(content_phash=1, symbol_phash=77)
        make_review_card(content_phash=2, symbol_phash=77)
        a.content_phash = 999
        a.save()
        clusters = compute_review_clusters()
        # without the freshness check, a and b would incorrectly merge on symbol_phash=77 -
        # with it, a contributes no symbol_phash signal at all, so both stay singletons.
        assert clusters == []


class TestReviewClusterCache:
    def test_cache_miss_computes_and_populates(self, db):
        assert cache.get(REVIEW_CLUSTER_CACHE_KEY) is None
        make_review_card(content_phash=1)
        make_review_card(content_phash=1)
        clusters = get_cached_review_clusters()
        assert len(clusters) == 1
        assert cache.get(REVIEW_CLUSTER_CACHE_KEY) == clusters

    def test_cache_hit_does_not_reflect_a_new_card(self, db):
        make_review_card(content_phash=1)
        make_review_card(content_phash=1)
        first = get_cached_review_clusters()
        assert len(first) == 1

        make_review_card(content_phash=1)  # a third card sharing the same signal
        cached_again = get_cached_review_clusters()
        assert cached_again == first  # still stale - cache wasn't invalidated

    def test_force_refresh_bypasses_the_cache(self, db):
        make_review_card(content_phash=1)
        make_review_card(content_phash=1)
        get_cached_review_clusters()

        make_review_card(content_phash=1)
        refreshed = get_cached_review_clusters(force_refresh=True)
        assert refreshed[0].size == 3

    def test_invalidate_clears_the_cache(self, db):
        make_review_card(content_phash=1)
        make_review_card(content_phash=1)
        get_cached_review_clusters()
        assert cache.get(REVIEW_CLUSTER_CACHE_KEY) is not None
        invalidate_review_cluster_cache()
        assert cache.get(REVIEW_CLUSTER_CACHE_KEY) is None


class TestFindCluster:
    def test_finds_by_cluster_id(self, db):
        make_review_card(content_phash=1)
        make_review_card(content_phash=1)
        clusters = compute_review_clusters()
        found = find_cluster(clusters, clusters[0].cluster_id)
        assert found is clusters[0]

    def test_returns_none_for_an_unknown_id(self, db):
        assert find_cluster([], "does-not-exist") is None


def _signal(signal_type: str, value: str, member_count: int):
    from cardpicker.review_clusters import ClusterSignal

    return ClusterSignal(signal_type=signal_type, value=value, member_count=member_count)
