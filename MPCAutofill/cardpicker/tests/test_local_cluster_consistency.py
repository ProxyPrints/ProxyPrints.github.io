"""
Tests for cardpicker.local_cluster_consistency (docs/theory.md §6's cluster-consistency
detector) - a pure DB read, no mocking needed beyond the ORM itself.
"""

import pytest

from cardpicker.local_cluster_consistency import find_cluster_printing_divergences
from cardpicker.models import PrintingTagStatus
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory

# See test_local_lands_identify.py's identical fixture for the full rationale -
# factory.Sequence counters are process-global across the whole pytest run.
_SHARED_FACTORIES = [CardFactory, CanonicalCardFactory]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


def _resolved_card(content_phash, printing):
    return CardFactory(
        content_phash=content_phash,
        printing_tag_status=PrintingTagStatus.RESOLVED,
        inferred_canonical_card=printing,
    )


@pytest.mark.django_db
class TestFindClusterPrintingDivergences:
    def test_no_cards_at_all(self):
        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 0
        assert result.resolved_cards_considered == 0
        assert result.divergent == ()

    def test_singleton_hash_is_not_a_cluster(self):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=111, printing=printing)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 0
        assert result.resolved_cards_considered == 1
        assert result.divergent == ()

    def test_two_members_same_printing_is_consistent(self):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=222, printing=printing)
        _resolved_card(content_phash=222, printing=printing)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 1
        assert result.resolved_cards_considered == 2
        assert result.divergent == ()

    def test_two_members_different_printings_is_divergent(self):
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        card_a = _resolved_card(content_phash=333, printing=printing_a)
        card_b = _resolved_card(content_phash=333, printing=printing_b)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 1
        assert len(result.divergent) == 1

        cluster = result.divergent[0]
        assert cluster.content_phash == 333
        assert set(cluster.members) == {(card_a.pk, printing_a.pk), (card_b.pk, printing_b.pk)}

    def test_three_members_two_agree_one_diverges_still_flagged(self):
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        _resolved_card(content_phash=444, printing=printing_a)
        _resolved_card(content_phash=444, printing=printing_a)
        _resolved_card(content_phash=444, printing=printing_b)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 1
        assert len(result.divergent) == 1
        assert len(result.divergent[0].members) == 3

    def test_unresolved_card_is_excluded_even_with_a_matching_hash(self):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=555, printing=printing)
        CardFactory(content_phash=555, printing_tag_status=PrintingTagStatus.UNRESOLVED, inferred_canonical_card=None)

        result = find_cluster_printing_divergences()
        # the unresolved card doesn't count toward resolved_cards_considered, and the resolved
        # card alone isn't a cluster (needs 2+ RESOLVED members).
        assert result.resolved_cards_considered == 1
        assert result.clusters_checked == 0

    def test_null_content_phash_is_excluded(self):
        printing = CanonicalCardFactory()
        CardFactory(
            content_phash=None, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )

        result = find_cluster_printing_divergences()
        assert result.resolved_cards_considered == 0

    def test_independent_clusters_at_different_hashes_dont_interfere(self):
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        printing_c = CanonicalCardFactory()
        # cluster at hash 666: consistent
        _resolved_card(content_phash=666, printing=printing_a)
        _resolved_card(content_phash=666, printing=printing_a)
        # cluster at hash 777: divergent
        _resolved_card(content_phash=777, printing=printing_b)
        _resolved_card(content_phash=777, printing=printing_c)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 2
        assert len(result.divergent) == 1
        assert result.divergent[0].content_phash == 777
