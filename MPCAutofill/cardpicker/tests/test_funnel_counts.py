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

    def test_high_match_confirmed_when_resolved_matches_machine(self, client, db, source, canonical_printing):
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
        response = client.get(reverse("get_funnel_counts"))
        data = response.json()
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
