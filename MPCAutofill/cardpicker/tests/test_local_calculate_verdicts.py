"""
Tests for cardpicker.local_calculate_verdicts (Stage D, docs/features/catalog-completion-plan.md,
public issue #152) - the join-key calculator plus its agreement/corroboration layer (back-face-
aware candidate selection, border/frame agreement, artist-OCR corroboration, quality/integrity
gating - see that module's own docstring for the full design and why the phash slow-path/a
calibrated blur-or-entropy threshold stay deferred). No network calls, no live image fetch -
Stage D consumes stored `ImageEvidence` + `Card`/`CanonicalCard`/`CanonicalPrintingMetadata`/
`DFCPair` rows only, so every fixture here is synthetic DB state (factories), matching
`test_local_residual_classify.py`'s own "host venv, no network" precedent for this pipeline's
later stages. `render_set_symbol` IS exercised for real (it's a pure local font-render, no
network) so the symbol-phash tie-break is tested against REAL keyrune glyph hashes, not a mocked
distance. `is_back_face` is exercised against a real, temporary on-disk bulk-data JSON file (same
`_write_bulk_data_file`/`_record` convention `test_printing_metadata_import.py` already
establishes for that primitive), never mocked.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import imagehash
import pytest

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT,
    JOIN_KEY_CONFIDENCE_BOTH,
    JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY,
    JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
    JOIN_KEY_NO_MATCH_CONFIDENCE,
    _resolve_candidates_for_card,
    _symbol_phash_tiebreak,
    calculate_join_key_verdict,
    run_join_key_calculator,
)
from cardpicker.local_fallback import render_set_symbol
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    CandidatePrinting,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    DFCPairFactory,
    ImageEvidenceFactory,
    SourceFactory,
)
from cardpicker.utils import twos_complement


def _write_bulk_data_file(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    """Same shape as test_printing_metadata_import.py's own helper - deliberately duplicated
    (not imported cross-module) matching this test suite's own per-module small-helper
    convention."""
    path = tmp_path / "default_cards.json"
    path.write_text("[\n" + "\n".join(json.dumps(record) + "," for record in records) + "\n]")
    return path


def _dfc_record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": str(uuid.uuid4()), "layout": "transform"}
    base.update(overrides)
    return base


# see test_local_identify_printing_tags.py's identical fixture for the full rationale -
# factory.Sequence counters are process-global across the whole pytest run.
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
    DFCPairFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


def _hash_of(expansion_code: str) -> int:
    image = render_set_symbol(expansion_code)
    assert image is not None
    return twos_complement(str(imagehash.phash(image)), 64)


def _evidence(card, **overrides):
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


class TestCalculateJoinKeyVerdict:
    def test_exact_set_and_number_match(self, db):
        card = CardFactory(name="Lightning Bolt")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.is_no_match is False
        assert verdict.skip_reason == ""
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_collector_number_only_unique_match(self, db):
        """Pre-M15: no set code on the collector line, but the name's candidates don't share
        this number across sets - a real, unambiguous match without symbol tie-break."""
        card = CardFactory(name="Some Old Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="lea", collector_number="93")]
        evidence = _evidence(card, collector_line_collector_number="93")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY

    def test_parsed_but_no_match_casts_is_no_match(self, db):
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_collector_number="999")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.is_no_match is True
        assert verdict.printing_pk is None
        assert verdict.skip_reason == ""
        assert verdict.confidence == JOIN_KEY_NO_MATCH_CONFIDENCE

    def test_no_text_is_a_named_skip(self, db):
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_collector_number="")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "no-text"
        assert verdict.printing_pk is None
        assert verdict.is_no_match is False

    def test_ambiguous_resolved_by_symbol_tiebreak(self, db):
        """Two candidates share a collector number across different sets (the pre-M15
        ambiguous case) - the card's OWN rendered symbol clearly picks one."""
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
        ]
        evidence = _evidence(card, collector_line_collector_number="158", symbol_phash=_hash_of("mom"))

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK
        assert verdict.skip_reason == ""

    def test_ambiguous_stays_ambiguous_without_a_usable_symbol_hash(self, db):
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
        ]
        evidence = _evidence(card, collector_line_collector_number="158", symbol_phash=None)

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "ambiguous"
        assert verdict.printing_pk is None

    def test_proxy_marker_vetoes_a_direct_match(self, db):
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "proxy-marker-veto"
        assert verdict.printing_pk is None
        assert verdict.is_no_match is False

    def test_proxy_marker_vetoes_a_symbol_tiebroken_match(self, db):
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
        ]
        evidence = _evidence(
            card,
            collector_line_collector_number="158",
            symbol_phash=_hash_of("mom"),
            legal_line_proxy_marker_detected=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "proxy-marker-veto"
        assert verdict.printing_pk is None

    def test_proxy_marker_does_not_affect_a_genuine_no_match(self, db):
        """The veto only rejects a would-be MATCH - it's not a blanket 'ignore this card's
        evidence' switch (module docstring: a marker doesn't mean printing P is wrong, it means
        THIS reading isn't trustworthy evidence FOR P)."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_collector_number="999", legal_line_proxy_marker_detected=True)

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""


class TestSymbolPhashTiebreak:
    def test_returns_none_without_a_symbol_hash(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        assert _symbol_phash_tiebreak(None, candidates) is None

    def test_returns_none_with_no_candidates(self):
        assert _symbol_phash_tiebreak(_hash_of("mom"), []) is None

    def test_returns_none_for_an_unrenderable_expansion_code(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="zzznotarealcode", collector_number="1")]
        assert _symbol_phash_tiebreak(_hash_of("mom"), candidates) is None

    def test_picks_the_unique_close_match(self):
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mir", collector_number="1"),
            CandidatePrinting(pk=2, expansion_code="som", collector_number="1"),
        ]
        winner = _symbol_phash_tiebreak(_hash_of("mir"), candidates)
        assert winner is not None and winner.pk == 1


class TestRunJoinKeyCalculator:
    def test_dry_run_counts_without_writing(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        result = run_join_key_calculator(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert CardPrintingTag.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_write_casts_a_vote_and_never_resolves_alone(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        result = run_join_key_calculator(dry_run=False)

        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card)
        assert vote.printing_id == printing.pk
        assert vote.anonymous_id == JOIN_KEY_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.run_id == result.run_id

        card.refresh_from_db()
        # a single VoteSource.OCR vote (weight 0.5) can never clear the human-backed gate alone.
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_skip_writes_a_scan_log_row(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_collector_number="")  # no-text

        result = run_join_key_calculator(dry_run=False)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.count() == 0
        log = CardScanLog.objects.get(card=card)
        assert log.anonymous_id == JOIN_KEY_ANONYMOUS_ID
        assert log.skip_reason == "no-text"

    def test_idempotent_against_its_own_anonymous_id(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        first = run_join_key_calculator(dry_run=False)
        assert first.votes_written == 1

        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 0
        assert CardPrintingTag.objects.filter(card=card).count() == 1

    def test_card_without_evidence_is_a_rescannable_no_evidence_skip(self, db):
        CardFactory(name="Some Card", content_phash=42)

        result = run_join_key_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1
        log = CardScanLog.objects.get(skip_reason="no-evidence")
        assert log.anonymous_id == JOIN_KEY_ANONYMOUS_ID

        # rescannable: adding evidence and re-running picks the card back up.
        card = log.card
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_card_without_a_stable_content_hash_is_skipped_entirely(self, db):
        CardFactory(name="Some Card", content_phash=None)

        result = run_join_key_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.count() == 0

    def test_evidence_from_a_stale_content_hash_is_not_used(self, db):
        """An ImageEvidence row keyed to an OLDER content_hash than the card's CURRENT
        content_phash must never be trusted - the card's image has since changed."""
        card = CardFactory(name="Some Card", content_phash=99)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            content_hash=42,  # stale - card.content_phash is 99
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        result = run_join_key_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1

    def test_back_face_card_resolves_via_the_combined_scryfall_name(self, db, tmp_path):
        """End-to-end: a card uploaded under just its BACK face's name (a split-image DFC
        source) still gets a real join-key vote, via `_resolve_candidates_for_card`'s DFCPair
        fallback - the structural gap `_resolve_candidates_for_card`'s own docstring describes."""
        card = CardFactory(name="Insectile Aberration", content_phash=42)
        printing = CanonicalCardFactory(
            name="Delver of Secrets // Insectile Aberration", expansion__code="isd", collector_number="51"
        )
        DFCPairFactory(front="Delver of Secrets", back="Insectile Aberration")
        path = _write_bulk_data_file(
            tmp_path,
            [_dfc_record(card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}])],
        )
        _evidence(card, collector_line_set_code="isd", collector_line_collector_number="51")

        result = run_join_key_calculator(dry_run=False, default_cards_path=path)

        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card)
        assert vote.printing_id == printing.pk


class TestResolveCandidatesForCard:
    """`_resolve_candidates_for_card` - back-face-aware candidate selection (module docstring,
    issue #199/#213)."""

    def test_direct_match_short_circuits_before_any_back_face_check(self, db):
        CanonicalCardFactory(name="Lightning Bolt", expansion__code="lea", collector_number="1")
        index = CandidateNameIndex()

        candidates = _resolve_candidates_for_card("Lightning Bolt", index)

        assert len(candidates) == 1
        assert candidates[0].expansion_code == "lea"

    def test_back_face_name_resolves_via_the_combined_scryfall_name(self, db, tmp_path):
        CanonicalCardFactory(
            name="Delver of Secrets // Insectile Aberration", expansion__code="isd", collector_number="51"
        )
        DFCPairFactory(front="Delver of Secrets", back="Insectile Aberration")
        path = _write_bulk_data_file(
            tmp_path,
            [_dfc_record(card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}])],
        )
        index = CandidateNameIndex()

        candidates = _resolve_candidates_for_card("Insectile Aberration", index, default_cards_path=path)

        assert len(candidates) == 1
        assert candidates[0].expansion_code == "isd"

    def test_non_back_face_name_with_no_direct_match_stays_empty(self, db, tmp_path):
        path = _write_bulk_data_file(tmp_path, [])
        index = CandidateNameIndex()

        candidates = _resolve_candidates_for_card("Some Totally Unknown Card", index, default_cards_path=path)

        assert candidates == []

    def test_back_face_without_a_synced_dfc_pair_row_stays_empty(self, db, tmp_path):
        """A real, honestly-reported gap (module docstring) - not every back face is guaranteed
        to have a synced DFCPair row at any given moment; this must degrade to empty, not raise."""
        path = _write_bulk_data_file(
            tmp_path,
            [_dfc_record(card_faces=[{"name": "Some Front"}, {"name": "Some Back"}])],
        )
        index = CandidateNameIndex()  # deliberately no DFCPairFactory row for this pair

        candidates = _resolve_candidates_for_card("Some Back", index, default_cards_path=path)

        assert candidates == []


class TestAgreementChecks:
    """The agreement/corroboration layer (module docstring) - border/frame agreement,
    artist-OCR corroboration, quality/integrity gating. Exercised through
    `calculate_join_key_verdict` directly, same style `TestCalculateJoinKeyVerdict` already
    uses, with a REAL backing `CanonicalCard`/`CanonicalPrintingMetadata` row where a check needs
    one to compare against."""

    def test_border_mismatch_withholds_the_match(self, db):
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="white")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            layout_class="black",  # disagrees with the printing's real "white" border_color
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "border-mismatch"
        assert verdict.printing_pk is None

    def test_border_agreement_does_not_veto_the_match(self, db):
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black", frame="2015")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", layout_class="black"
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_frame_mismatch_withholds_the_match(self, db):
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        # a parsed collector NUMBER implies a "modern" frame reading - "1993" is an "old" printing.
        CanonicalPrintingMetadataFactory(canonical_card=printing, frame="1993")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "frame-mismatch"
        assert verdict.printing_pk is None

    def test_frame_agreement_does_not_veto_the_match(self, db):
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, frame="2015")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_no_printing_metadata_sidecar_skips_border_and_frame_checks(self, db):
        """A real CanonicalCard row with NO CanonicalPrintingMetadata sidecar - "nothing to
        compare" degrades to agreement, same as frame_style_is_consistent's own documented
        printing_frame_value=None semantics."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", layout_class="white"
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk

    def test_artist_disagreement_downgrades_confidence(self, db):
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            artist_ocr_name="Someone Totally Different",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT

    def test_artist_agreement_keeps_the_base_confidence(self, db):
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", artist_ocr_name="Rebecca Guay"
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_no_artist_ocr_reading_keeps_the_base_confidence(self, db):
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_truncated_image_vetoes_a_direct_match(self, db):
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", image_is_truncated=True
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "truncated-image"
        assert verdict.printing_pk is None
        assert verdict.is_no_match is False

    def test_truncated_image_vetoes_a_symbol_tiebroken_match(self, db):
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
        ]
        evidence = _evidence(
            card,
            collector_line_collector_number="158",
            symbol_phash=_hash_of("mom"),
            image_is_truncated=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "truncated-image"
        assert verdict.printing_pk is None

    def test_truncated_image_does_not_affect_a_genuine_no_match(self, db):
        """Mirrors the existing proxy-marker-veto precedent: the veto only rejects a would-be
        MATCH, it's not a blanket 'ignore this card's evidence' switch."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_collector_number="999", image_is_truncated=True  # parsed-but-no-match
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""

    def test_border_mismatch_writes_a_scan_log_row_via_the_full_runner(self, db):
        """Integration check (module docstring's rescannability deviation): a border/frame
        mismatch is a permanent skip, not added to JOIN_KEY_RESCANNABLE_SKIP_REASONS - confirmed
        here via the real batch runner rather than only the pure-function unit tests above."""
        card = CardFactory(name="Test Card", content_phash=42)
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="white")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158", layout_class="black")

        result = run_join_key_calculator(dry_run=False)

        assert result.votes_written == 0
        log = CardScanLog.objects.get(card=card)
        assert log.skip_reason == "border-mismatch"

        # non-rescannable: re-running does NOT re-select this card.
        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 0
