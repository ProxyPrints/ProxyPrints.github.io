"""Tests for calculator_family() and purge_stale_machine_votes() in cardpicker.models,
and the versioned anonymous_id progress invariant in _eligible_base_queryset."""
import uuid

from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
    _eligible_base_queryset,
)
from cardpicker.models import (
    CardPrintingTag,
    VoteSource,
    calculator_family,
    purge_stale_machine_votes,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    CardPrintingTagFactory,
)


class TestCalculatorFamily:
    def test_versioned_id_returns_family(self):
        assert calculator_family("local-ocr-v1") == "local-ocr"
        assert calculator_family("local-ocr-v2") == "local-ocr"
        assert calculator_family("stage-d-join-key-v1") == "stage-d-join-key"
        assert calculator_family("ai-art-detector-v99") == "ai-art-detector"

    def test_uuid_returns_none(self):
        assert calculator_family(str(uuid.uuid4())) is None

    def test_unversioned_id_returns_none(self):
        # IDs without the -vN suffix return None
        assert calculator_family("anonymous_0") is None
        assert calculator_family("local-ocr") is None


class TestPurgeStateMachineVotes:
    def test_version_bump_overwrites_including_legacy_null_run_id(self, db):
        """v2 write purges v1 rows including the legacy run_id=None variant, then inserts v2."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
            run_id=None,
        )
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="local-ocr-v1").count() == 1

        purge_stale_machine_votes(CardPrintingTag, "local-ocr-v2", "card_id", [card.pk])
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v2",
            source=VoteSource.OCR,
        )

        assert not CardPrintingTag.objects.filter(card=card, anonymous_id="local-ocr-v1").exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="local-ocr-v2").count() == 1

    def test_same_version_replace_no_uniqueness_explosion(self, db):
        """Re-writing the same anonymous_id purges the prior row and re-inserts cleanly."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        purge_stale_machine_votes(CardPrintingTag, "local-ocr-v1", "card_id", [card.pk])
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        assert CardPrintingTag.objects.filter(card=card, anonymous_id="local-ocr-v1").count() == 1

    def test_isolation_other_family_and_human_vote_survive(self, db):
        """Votes from a different calculator family and human UUID votes are untouched."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        phash_vote = CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id="local-phash-v1",
            source=VoteSource.OCR,
        )
        human_vote = CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id=str(uuid.uuid4()),
            source=VoteSource.USER,
        )

        # Purge only the local-ocr family — phash and human votes must survive unchanged
        purge_stale_machine_votes(CardPrintingTag, "local-ocr-v2", "card_id", [card.pk])

        assert CardPrintingTag.objects.filter(pk=phash_vote.pk).exists()
        assert CardPrintingTag.objects.filter(pk=human_vote.pk).exists()


class TestProgressInvariant:
    def test_current_version_vote_excludes_card(self, db):
        """A card already voted by the current anonymous_id is not in the eligible queryset."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id=OCR_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        assert not _eligible_base_queryset(OCR_ANONYMOUS_ID).filter(pk=card.pk).exists()

    def test_old_version_vote_leaves_card_eligible(self, db):
        """A card with only an old-version vote is still selected for the current version."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        # A hypothetical prior-version id: same family as OCR_ANONYMOUS_ID but different suffix
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id="local-ocr-v0",
            source=VoteSource.OCR,
        )

        assert _eligible_base_queryset(OCR_ANONYMOUS_ID).filter(pk=card.pk).exists()
