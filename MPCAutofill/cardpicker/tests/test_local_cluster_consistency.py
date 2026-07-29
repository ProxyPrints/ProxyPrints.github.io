"""
Tests for cardpicker.local_cluster_consistency (docs/theory.md §6's cluster-consistency
detector) - a pure DB read, no mocking needed beyond the ORM itself.
"""

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.local_cluster_consistency import find_cluster_printing_divergences
from cardpicker.models import PrintingTagStatus
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory


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


@pytest.mark.django_db
class TestVacuityIsSurfaced:
    """
    An empty `divergent` means two entirely different things - "nothing disagreed" and "nothing
    was compared" - and until 2026-07-29 both rendered as the same green line. These tests pin
    the distinction: see `local_cluster_consistency`'s module docstring for the production
    numbers (0 clusters checked against 33,631 available d=0 groups) and for the two dormant
    calculators that failed this exact way.
    """

    def test_a_check_with_no_clusters_reports_itself_vacuous(self):
        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 0
        assert result.divergent == ()
        assert result.is_vacuous is True

    def test_a_check_with_a_real_cluster_is_not_vacuous(self):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=888, printing=printing)
        _resolved_card(content_phash=888, printing=printing)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 1
        assert result.divergent == ()
        # same empty `divergent` as the test above, opposite meaning - which is the point.
        assert result.is_vacuous is False

    def test_unresolved_duplicates_count_toward_the_ceiling_but_not_the_check(self):
        # the exact production shape: plenty of d=0 groups exist, almost nothing is resolved.
        CardFactory(content_phash=999, printing_tag_status=PrintingTagStatus.UNRESOLVED, inferred_canonical_card=None)
        CardFactory(content_phash=999, printing_tag_status=PrintingTagStatus.UNRESOLVED, inferred_canonical_card=None)

        result = find_cluster_printing_divergences()
        assert result.clusters_checked == 0
        assert result.is_vacuous is True
        # the group is visible as an unrealised opportunity, so a reader can tell "starved of
        # resolutions" apart from "no duplicate images exist at all".
        assert result.d0_groups_in_catalogue == 1

    def test_the_ceiling_is_zero_when_no_duplicate_images_exist(self):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=1000, printing=printing)

        result = find_cluster_printing_divergences()
        assert result.is_vacuous is True
        assert result.d0_groups_in_catalogue == 0


@pytest.mark.django_db
class TestManagementCommandRefusesToLookGreenWhenVacuous:
    def test_vacuous_run_prints_the_dormant_banner_and_fails(self, capsys):
        with pytest.raises(CommandError, match="vacuous"):
            call_command("local_cluster_consistency_check")
        out = capsys.readouterr().out
        assert "DORMANT - NOT AN ALL-CLEAR" in out
        assert "no divergent clusters found" not in out

    def test_allow_vacuous_still_prints_the_banner_but_exits_cleanly(self, capsys):
        call_command("local_cluster_consistency_check", "--allow-vacuous")
        out = capsys.readouterr().out
        assert "DORMANT - NOT AN ALL-CLEAR" in out
        assert "no divergent clusters found" not in out

    def test_a_real_consistent_cluster_reports_the_all_clear_with_its_denominator(self, capsys):
        printing = CanonicalCardFactory()
        _resolved_card(content_phash=1234, printing=printing)
        _resolved_card(content_phash=1234, printing=printing)

        call_command("local_cluster_consistency_check")
        out = capsys.readouterr().out
        assert "DORMANT" not in out
        # the all-clear now carries the number of clusters it is an all-clear over.
        assert "no divergent clusters found across 1 cluster(s) checked." in out
