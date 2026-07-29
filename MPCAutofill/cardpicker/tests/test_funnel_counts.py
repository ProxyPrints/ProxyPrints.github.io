import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory, SourceFactory


@pytest.fixture(autouse=True)
def _clear_funnel_cache():
    cache.delete("funnel-counts-v1")
    yield
    cache.delete("funnel-counts-v1")


@pytest.fixture
def source(db):
    return SourceFactory()


@pytest.fixture
def canonical_printing(db):
    return CanonicalCardFactory()


class TestFunnelCountsEmpty:
    def test_empty_database_returns_zeros(self, client, db):
        response = client.get(reverse("get_funnel_counts"))
        assert response.status_code == 200
        data = response.json()
        assert data["zones"]["high_match"] == {"count": 0, "confirmed": 0}
        assert data["zones"]["no_match"] == {"count": 0, "confirmed": 0}
        assert data["zones"]["ambiguous"] == {"count": 0, "confirmed": 0}
        assert data["zones"]["withheld"] == {"count": 0, "confirmed": 0}


class TestFunnelCountsHighMatch:
    def test_machine_vote_counts_as_high_match(self, client, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
            confidence=0.85,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 1

    def test_user_vote_not_counted_as_high_match(self, client, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="user-v1",
            source=VoteSource.USER,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 0

    def test_deduction_vote_counts_as_high_match(self, client, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="deduction-v1",
            source=VoteSource.DEDUCTION,
            confidence=0.75,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 1

    def test_machine_no_match_excluded_from_high_match(self, client, db, source):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 0

    def test_high_match_confirmed_when_human_backs_the_machines_printing(self, client, db, source, canonical_printing):
        """The positive case: machine suggested it, a human voted for it, it resolved."""
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="human-voter-uuid",
            source=VoteSource.USER,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 1
        assert data["zones"]["high_match"]["confirmed"] == 1

    def test_high_match_not_confirmed_when_resolved_differs(self, client, db, source):
        card_printing = CanonicalCardFactory()
        other_printing = CanonicalCardFactory()
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=other_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=card_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["confirmed"] == 0

    def test_high_match_not_confirmed_when_unresolved(self, client, db, source, canonical_printing):
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["high_match"]["count"] == 1
        assert data["zones"]["high_match"]["confirmed"] == 0


class TestFunnelCountsNoMatch:
    def test_no_match_vote_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["no_match"]["count"] == 1
        assert data["zones"]["no_match"]["confirmed"] == 0

    def test_user_no_match_not_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="user-v1",
            source=VoteSource.USER,
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["no_match"]["count"] == 0


class TestFunnelCountsAmbiguous:
    def test_ambiguous_scan_log_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardScanLog.objects.create(
            card=card,
            anonymous_id="ocr-v1",
            skip_reason="ambiguous",
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["ambiguous"]["count"] == 1
        assert data["zones"]["ambiguous"]["confirmed"] == 0

    def test_non_ambiguous_reason_not_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardScanLog.objects.create(
            card=card,
            anonymous_id="ocr-v1",
            skip_reason="no-text",
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["ambiguous"]["count"] == 0


class TestFunnelCountsWithheld:
    def test_border_mismatch_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardScanLog.objects.create(
            card=card,
            anonymous_id="ocr-v1",
            skip_reason="border-mismatch",
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["withheld"]["count"] == 1
        assert data["zones"]["withheld"]["confirmed"] == 0

    def test_frame_mismatch_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardScanLog.objects.create(
            card=card,
            anonymous_id="ocr-v1",
            skip_reason="frame-mismatch",
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["withheld"]["count"] == 1

    def test_other_reason_not_counted(self, client, db, source):
        card = CardFactory(source=source)
        CardScanLog.objects.create(
            card=card,
            anonymous_id="ocr-v1",
            skip_reason="unfetchable-image",
        )
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
        assert data["zones"]["withheld"]["count"] == 0


class TestFunnelCountsCaching:
    def test_cache_populated_on_first_request(self, client, db):
        assert cache.get("funnel-counts-v1") is None
        client.get(reverse("get_funnel_counts"))
        assert cache.get("funnel-counts-v1") is not None

    def test_cache_returned_on_second_request(self, client, db, source, canonical_printing):
        card = CardFactory(source=source)
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        response1 = client.get(reverse("get_funnel_counts"))
        cached = cache.get("funnel-counts-v1")
        response2 = client.get(reverse("get_funnel_counts"))
        assert response1.json() == response2.json()
        assert response2.json() == cached


class TestFunnelCountsAnonymous:
    def test_anonymous_access_works(self, client, db):
        response = client.get(reverse("get_funnel_counts"))
        assert response.status_code == 200


class TestFunnelCountsConfirmedRequiresAHuman:
    """
    Regression tests for the 2026-07-29 `confirmed` semantics fix.

    The bucket's first form asked only whether a MACHINE vote existed for the printing the
    card had already resolved to - it never consulted a human vote, so a card whose only
    voter was a machine counted as "confirmed". Every test below fails against that query.
    """

    def test_machine_only_resolved_card_is_not_confirmed(self, client, db, source, canonical_printing):
        """THE case: zero human votes, one machine vote, card resolved to that printing.

        On healthy data `vote_consensus`'s human-backed gate makes this state unreachable -
        which is exactly why the counter must not be the one place that assumes it, since
        this is the state where an inflated confirmation figure misleads most.
        """
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["count"] == 1  # still a machine high-match
        assert data["zones"]["high_match"]["confirmed"] == 0  # but nobody confirmed it

    def test_deduction_only_resolved_card_is_not_confirmed(self, client, db, source, canonical_printing):
        """DEDUCTION is machine-derived too - the other half of the high_match zone."""
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="deduction-v1",
            source=VoteSource.DEDUCTION,
        )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["confirmed"] == 0

    def test_human_vote_for_a_different_printing_does_not_confirm(self, client, db, source):
        """A human who voted for ANOTHER printing has not confirmed this resolution."""
        resolved_printing = CanonicalCardFactory()
        other_printing = CanonicalCardFactory()
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=resolved_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=resolved_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=other_printing,
            is_no_match=False,
            anonymous_id="human-voter-uuid",
            source=VoteSource.USER,
        )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["confirmed"] == 0

    def test_human_vote_on_a_different_card_does_not_confirm(self, client, db, source, canonical_printing):
        """Confirmation is per-card - another card's human vote must not leak across."""
        confirmed_card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        unconfirmed_card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        for card in (confirmed_card, unconfirmed_card):
            CardPrintingTag.objects.create(
                card=card,
                printing=canonical_printing,
                is_no_match=False,
                anonymous_id="ocr-v1",
                source=VoteSource.OCR,
            )
        CardPrintingTag.objects.create(
            card=confirmed_card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="human-voter-uuid",
            source=VoteSource.USER,
        )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["count"] == 2
        assert data["zones"]["high_match"]["confirmed"] == 1

    def test_admin_vote_confirms(self, client, db, source, canonical_printing):
        """ADMIN is human-backed under the consensus split."""
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="admin-uuid",
            source=VoteSource.ADMIN,
        )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["confirmed"] == 1

    def test_implicit_vote_does_not_confirm(self, client, db, source, canonical_printing):
        """IMPLICIT is a passive by-product of a card selection, never human-backed.

        `VoteSource.IMPLICIT`'s own docstring: "never human-backed". It must not be able to
        confirm a printing, no matter how many implicit votes pile up.
        """
        card = CardFactory(
            source=source,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=canonical_printing,
        )
        CardPrintingTag.objects.create(
            card=card,
            printing=canonical_printing,
            is_no_match=False,
            anonymous_id="ocr-v1",
            source=VoteSource.OCR,
        )
        for i in range(5):
            CardPrintingTag.objects.create(
                card=card,
                printing=canonical_printing,
                is_no_match=False,
                anonymous_id=f"implicit-voter-{i}",
                source=VoteSource.IMPLICIT,
                vote_surface="display-editor-filter",
            )
        data = client.get(reverse("get_funnel_counts")).json()
        assert data["zones"]["high_match"]["confirmed"] == 0

    def test_human_backed_source_list_tracks_vote_consensus(self, db):
        """The source list is derived, not a second hand-maintained copy."""
        from cardpicker.models import VoteSource as _VoteSource
        from cardpicker.views import HUMAN_BACKED_VOTE_SOURCES
        from cardpicker.vote_consensus import is_human_backed_source

        assert set(HUMAN_BACKED_VOTE_SOURCES) == {s for s in _VoteSource.values if is_human_backed_source(s)}
        assert _VoteSource.USER in HUMAN_BACKED_VOTE_SOURCES
        assert _VoteSource.ADMIN in HUMAN_BACKED_VOTE_SOURCES
        # the consensus split, not catalog_stats' stats-page split
        assert _VoteSource.FEDERATED not in HUMAN_BACKED_VOTE_SOURCES
        assert _VoteSource.IMPLICIT not in HUMAN_BACKED_VOTE_SOURCES
        assert _VoteSource.OCR not in HUMAN_BACKED_VOTE_SOURCES
        assert _VoteSource.DEDUCTION not in HUMAN_BACKED_VOTE_SOURCES
