"""
Tests for cardpicker.local_illustration (Stage D illustration deduction calculator, issue #507).

Covers: IllustrationIndex construction, 0/1/N vote shapes, confidence division, single-faced
filtering, dry-run no-writes, live gate (verify_zero_resolutions), purgeability via run_id,
and eligibility constraints (no join-key vote, no artist-ocr, no evidence, multi-faced skip).
"""

import uuid

import pytest

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_illustration import (
    BASE_CONFIDENCE,
    ILLUSTRATION_ANONYMOUS_ID,
    NO_ARTIST_OCR_SKIP_REASON,
    NO_CANDIDATE_MATCH_SKIP_REASON,
    NO_EVIDENCE_SKIP_REASON,
    NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON,
    IllustrationIndex,
    calculate_illustration_verdict,
    run_illustration_calculator,
)
from cardpicker.models import CardPrintingTag, PrintingTagStatus, VoteSource
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    ImageEvidenceFactory,
)


def _make_evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def _eligible_card(**overrides):
    defaults = dict(
        name="Lightning Bolt",
        printing_tag_status=PrintingTagStatus.UNRESOLVED,
        canonical_card=None,
        content_phash=1,  # non-null required: run_illustration_calculator skips content_phash=None
    )
    defaults.update(overrides)
    return CardFactory(**defaults)


def _join_key_no_hit_card(card):
    CardPrintingTag.objects.create(
        card=card,
        printing=None,
        is_no_match=True,
        anonymous_id=JOIN_KEY_ANONYMOUS_ID,
        source=VoteSource.OCR,
    )


# ---------------------------------------------------------------------------
# IllustrationIndex
# ---------------------------------------------------------------------------


class TestIllustrationIndex:
    def test_basic_index_construction(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        illustration_uuid = uuid.uuid4()
        CanonicalPrintingMetadataFactory(
            canonical_card=cc,
            illustration_id=illustration_uuid,
        )

        index = IllustrationIndex()

        assert str(illustration_uuid) in index.illustration_printings(artist.pk, "lightning bolt")
        assert index.artist_by_pk[cc.pk] == "Christopher Rush"
        assert index.card_pk_to_artist_pk[cc.pk] == artist.pk

    def test_multiple_illustrations_for_same_artist_name(self, db):
        artist = CanonicalArtistFactory(name="Artist One")
        expansion = CanonicalExpansionFactory(code="m21")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        illustration1 = uuid.uuid4()
        illustration2 = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=illustration1)
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=illustration2)

        index = IllustrationIndex()

        illustrations = index.illustration_printings(artist.pk, "dragon")
        assert len(illustrations) == 2
        assert str(illustration1) in illustrations
        assert str(illustration2) in illustrations

    def test_different_artists_same_card_name(self, db):
        artist1 = CanonicalArtistFactory(name="Artist One")
        artist2 = CanonicalArtistFactory(name="Artist Two")
        expansion = CanonicalExpansionFactory(code="m21")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist1, expansion=expansion)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist2, expansion=expansion)
        illustration1 = uuid.uuid4()
        illustration2 = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=illustration1)
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=illustration2)

        index = IllustrationIndex()

        illustrations1 = index.illustration_printings(artist1.pk, "dragon")
        illustrations2 = index.illustration_printings(artist2.pk, "dragon")
        assert str(illustration1) in illustrations1
        assert str(illustration2) in illustrations2
        assert str(illustration2) not in illustrations1

    def test_index_skips_null_illustration_id(self, db):
        artist = CanonicalArtistFactory(name="Artist One")
        expansion = CanonicalExpansionFactory(code="m21")
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=None)

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "dragon") == {}

    def test_empty_index(self, db):
        index = IllustrationIndex()
        assert index.illustration_printings(999, "nonexistent") == {}


# ---------------------------------------------------------------------------
# calculate_illustration_verdict
# ---------------------------------------------------------------------------


class TestCalculateIllustrationVerdict:
    def _build_index_and_mocks(self, artist_name, card_name, illustration_uuid, printing_pk):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="test")
        cc = CanonicalCardFactory(name=card_name, artist=artist, expansion=expansion, pk=printing_pk)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration_uuid)
        index = IllustrationIndex()
        candidate = type("_C", (), {"pk": cc.pk})()
        return index, [candidate]

    def test_single_illustration_votes_all_printings(self, db):
        illustration_uuid = uuid.uuid4()
        index, candidates = self._build_index_and_mocks(
            "Christopher Rush", "Lightning Bolt", illustration_uuid, printing_pk=100
        )
        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == ""
        assert verdict.confidence == BASE_CONFIDENCE
        assert verdict.illustration_count == 1
        assert 100 in verdict.printing_pks

    def test_no_artist_match_abstains(self, db):
        index, candidates = self._build_index_and_mocks(
            "Christopher Rush", "Lightning Bolt", uuid.uuid4(), printing_pk=100
        )

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Unknown Artist"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == NO_CANDIDATE_MATCH_SKIP_REASON
        assert verdict.printing_pks == ()

    def test_no_illustration_index_entry_abstains(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="test")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion, pk=200)
        index = IllustrationIndex()
        candidate = type("_C", (), {"pk": cc.pk})()

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
            illustration_index=index,
            candidates=[candidate],
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON

    def test_multiple_illustrations_spreads_confidence(self, db):
        artist = CanonicalArtistFactory(name="Artist X")
        expansion = CanonicalExpansionFactory(code="test")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=301)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=302)
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=uuid.uuid4())
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=uuid.uuid4())
        index = IllustrationIndex()
        candidates = [type("_C", (), {"pk": cc1.pk})(), type("_C", (), {"pk": cc2.pk})()]

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Artist X"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="dragon",
        )

        assert verdict.skip_reason == ""
        assert verdict.illustration_count == 2
        assert verdict.confidence == pytest.approx(BASE_CONFIDENCE / 2)
        assert len(verdict.printing_pks) == 2


# ---------------------------------------------------------------------------
# run_illustration_calculator (integration)
# ---------------------------------------------------------------------------


class TestRunIllustrationCalculator:
    def test_dry_run_writes_nothing(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=True)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0

    def test_live_writes_votes_and_resolves(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written >= 1
        votes = CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert votes.count() >= 1
        vote = votes.first()
        assert vote.source == VoteSource.DEDUCTION
        assert vote.confidence == BASE_CONFIDENCE

    def test_skips_multi_faced_cards(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush", layout_class="split")

        result = run_illustration_calculator(dry_run=True)

        assert result.multi_faced_skipped >= 1
        assert result.cards_considered == 0

    def test_skips_no_artist_ocr(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="")

        result = run_illustration_calculator(dry_run=True)

        assert result.skip_counts.get(NO_ARTIST_OCR_SKIP_REASON, 0) >= 1

    def test_skips_no_evidence(self, db):
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)

        result = run_illustration_calculator(dry_run=True)

        assert result.skip_counts.get(NO_EVIDENCE_SKIP_REASON, 0) >= 1

    def test_gate_check_passes(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)

        touched_ids = list(
            CardPrintingTag.objects.filter(run_id=result.run_id, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).values_list(
                "card_id", flat=True
            )
        )

        from cardpicker.local_identify_printing_tags import verify_zero_resolutions

        violations = verify_zero_resolutions(touched_ids)
        assert violations == []

    def test_purgeability_by_run_id(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)
        run_id = result.run_id

        assert CardPrintingTag.objects.filter(run_id=run_id).count() >= 1

        from django.core.management import call_command

        call_command("purge_machine_votes", run_id=run_id)

        assert CardPrintingTag.objects.filter(run_id=run_id).count() == 0
