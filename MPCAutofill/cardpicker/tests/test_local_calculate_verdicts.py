"""
Tests for cardpicker.local_calculate_verdicts (Stage D, docs/features/catalog-completion-plan.md,
public issue #152) - the join-key calculator, its agreement/corroboration layer (back-face-aware
candidate selection, border/frame agreement, copyright-year era check, artist-OCR corroboration,
quality/integrity gating), and the slow-path routing calculator (see that module's own docstring
for the full design and why the phash slow-path MATCHING mechanism/a calibrated blur-or-entropy
threshold stay deferred). No network calls, no live image fetch - Stage D consumes stored
`ImageEvidence` + `Card`/`CanonicalCard`/`CanonicalPrintingMetadata`/`DFCPair` rows only, so every
fixture here is synthetic DB state (factories), matching `test_local_residual_classify.py`'s own
"host venv, no network" precedent for this pipeline's later stages. `render_set_symbol` IS
exercised for real (it's a pure local font-render, no network) so the symbol-phash tie-break is
tested against REAL keyrune glyph hashes, not a mocked distance. `is_back_face` is exercised
against a real, temporary on-disk bulk-data JSON file (same `_write_bulk_data_file`/`_record`
convention `test_printing_metadata_import.py` already establishes for that primitive), never
mocked.
"""

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import imagehash
import pytest

from django.db import connection

from cardpicker.local_calculate_verdicts import (
    COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS,
    EXCLUDED_RESOLVED_TAGS,
    FALLBACK_NO_EVIDENCE_SKIP_REASON,
    FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT,
    JOIN_KEY_CONFIDENCE_BOTH,
    JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY,
    JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
    JOIN_KEY_NO_HIT_SKIP_REASONS,
    JOIN_KEY_NO_MATCH_CONFIDENCE,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
    RESOLUTION_FLOOR_DPI,
    SLOW_PATH_ANONYMOUS_ID,
    SLOW_PATH_TO_REVIEW_REASON,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
    _eligible_cards_queryset,
    _filter_by_symbol_phash,
    _resolve_candidates_for_card,
    _symbol_phash_tiebreak,
    calculate_fallback_verdict,
    calculate_join_key_verdict,
    calculate_slow_path_verdict,
    known_set_codes,
    run_fallback_calculator,
    run_join_key_calculator,
    run_slow_path_calculator,
)
from cardpicker.local_fallback import (
    FALLBACK_CONFIDENCE_MULTI_EVIDENCE,
    FALLBACK_CONFIDENCE_SINGLE_EVIDENCE,
    render_set_symbol,
)
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    CandidatePrinting,
)
from cardpicker.models import (
    Card,
    CardPrintingTag,
    CardScanLog,
    PilotRunLedger,
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

    def test_parsed_but_no_match_with_no_lexicon_supplied_keeps_pre_2026_07_23_behavior(self, db):
        """known_set_codes defaults to None - the exact pre-fix behavior, unconditionally
        (module docstring's own explicit contract for the None case)."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="sew", collector_line_collector_number="2")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""

    def test_collector_number_only_parsed_but_no_match_is_unaffected_by_the_lexicon_gate(self, db):
        """The pre-M15 case (no set code printed at all) - parsed.set_code is None, so the gate
        never applies regardless of what known_set_codes contains (even an empty lexicon)."""
        card = CardFactory(name="Some Old Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="lea", collector_number="93")]
        evidence = _evidence(card, collector_line_collector_number="999")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset())

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""

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

    def test_proxy_marker_no_longer_vetoes_a_direct_match(self, db):
        """2026-07-21 correction (docs/features/catalog-completion-plan.md's "Recovery-arc
        lessons" item 1, verified defect): the marker is catalog-required on every genuine
        upload, real printings' proxies included, so its presence must never block an otherwise-
        good join-key match. Confidence is unaffected too (deliberately NOT downgraded to a
        weaker tier - see `_apply_agreement_checks`'s own inline comment for the reasoning) -
        this is the exact same JOIN_KEY_CONFIDENCE_BOTH tier a marker-free identical match gets."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == ""
        assert verdict.printing_pk == 1
        assert verdict.is_no_match is False
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_proxy_marker_no_longer_vetoes_a_symbol_tiebroken_match(self, db):
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

        assert verdict.skip_reason == ""
        assert verdict.printing_pk == 1
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK

    def test_proxy_marker_present_or_absent_reaches_the_same_verdict(self, db):
        """The marker is genuinely a no-op now (module docstring's moderator-flag signal section)
        - not just "no longer a veto" but "no effect on the outcome at all", confirmed by
        comparing against the identical marker-free evidence rather than only asserting the
        marker-present case in isolation."""
        # ImageEvidence carries a real unique_image_evidence_per_card_hash constraint on
        # (card, content_hash) - two distinct cards (each with their own content_phash, via
        # `_evidence`'s own `content_hash=card.content_phash or 0` default) avoids a collision
        # rather than trying to attach two evidence rows to one card.
        card_absent = CardFactory(name="Some Card", content_phash=1)
        card_present = CardFactory(name="Some Card", content_phash=2)
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        marker_absent = _evidence(
            card_absent,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=False,
        )
        marker_present = _evidence(
            card_present,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )

        verdict_absent = calculate_join_key_verdict(card_absent.pk, marker_absent, candidates)
        verdict_present = calculate_join_key_verdict(card_present.pk, marker_present, candidates)

        assert verdict_absent.printing_pk == verdict_present.printing_pk
        assert verdict_absent.confidence == verdict_present.confidence
        assert verdict_absent.skip_reason == verdict_present.skip_reason == ""

    def test_proxy_marker_does_not_affect_a_genuine_no_match(self, db):
        """Confirms the marker has no effect on a genuine parsed-but-no-match outcome either -
        it was never checked on this path even back when it was a veto (module docstring: a
        marker doesn't mean printing P is wrong, it means THIS reading isn't trustworthy evidence
        FOR P), and remains a complete no-op post-correction too."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_collector_number="999", legal_line_proxy_marker_detected=True)

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""


class TestSetCodeLexiconGate:
    """Module docstring's SET-CODE LEXICON GATE (2026-07-23) - `calculate_join_key_verdict`'s
    "parsed-but-no-match" branch abstains (a named skip) instead of casting is_no_match=True when
    the parsed set_code isn't a real CanonicalExpansion code."""

    def test_out_of_lexicon_set_code_abstains_instead_of_casting_no_match(self, db):
        CanonicalExpansionFactory(code="mom")
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="zzq", collector_line_collector_number="2")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"mom"}))

        assert verdict.skip_reason == JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        assert verdict.is_no_match is False
        assert verdict.printing_pk is None

    def test_in_lexicon_set_code_still_casts_a_genuine_no_match(self, db):
        """Regression pin - the gate must not touch a real set code that simply doesn't apply to
        this card's own candidates (issue #207's pre-existing, still-valid negative evidence)."""
        CanonicalExpansionFactory(code="mom")
        CanonicalExpansionFactory(code="isd")
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="isd", collector_line_collector_number="2")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"mom", "isd"}))

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""
        assert verdict.confidence == JOIN_KEY_NO_MATCH_CONFIDENCE

    @pytest.mark.parametrize(
        "raw_text,set_code,collector_number",
        [
            # card_id 77046, live production - a proxy-watermark region OCR'd into the collector
            # line crop, "Sew" parsed as a plausible-looking 3-char set code.
            ("——— SRe © < iE 2 e Sew «", "sew", "2"),
            # card_id 31096, live production.
            ("aN 6 ree MRA Alin tO AAS OL ARON pt perl", "ree", "6"),
            # card_id 14961, live production.
            (". 'a eee +... 5 eee ee", "eee", "5"),
        ],
    )
    def test_live_proven_garbage_set_codes_abstain(self, db, raw_text, set_code, collector_number):
        CanonicalExpansionFactory(code="mom")
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text=raw_text,
            collector_line_set_code=set_code,
            collector_line_collector_number=collector_number,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"mom"}))

        assert verdict.skip_reason == JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        assert verdict.is_no_match is False

    def test_genuinely_custom_set_code_on_a_proxy_is_also_abstained_not_vetoed(self, db):
        """The documented tradeoff (module docstring's "WHY GATE ON LEXICON MEMBERSHIP ALONE"
        section): a real, deliberately-custom set code on a proxy of a non-existent printing
        (e.g. "ra03b") reads exactly like noise to a lexicon-only gate, since no separable
        confidence/quality signal was found to distinguish the two. This is the accepted cost,
        pinned here so it's a documented decision, not a silent surprise - the card still routes
        to human review (JOIN_KEY_NO_HIT_SKIP_REASONS below), it just no longer carries a
        confident-looking machine vote."""
        CanonicalExpansionFactory(code="mom")
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="ra03b", collector_line_collector_number="12")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"mom"}))

        assert verdict.skip_reason == JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON

    def test_unknown_set_code_is_a_non_rescannable_skip_that_still_routes_to_review(self, db):
        from cardpicker.local_calculate_verdicts import (
            JOIN_KEY_RESCANNABLE_SKIP_REASONS,
        )

        assert JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON not in JOIN_KEY_RESCANNABLE_SKIP_REASONS
        assert JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON in JOIN_KEY_NO_HIT_SKIP_REASONS

    def test_promo_star_suffixed_collector_number_is_unaffected_by_the_lexicon_gate(self, db):
        """Edge case named in the fix's own directive - a promo/star-suffixed collector number
        (local_ocr._COLLECTOR_NUMBER_RE's own "★?" handling, stripped before this function
        ever sees it) combined with a real, in-lexicon set code that genuinely doesn't match any
        candidate still casts a real no-match vote, exactly as before this fix - the gate is
        about the SET CODE half of the join key, not the collector number half."""
        CanonicalExpansionFactory(code="mom")
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        # local_ocr.parse_collector_line already strips a leading "★" before storing
        # collector_line_collector_number - simulated directly here since this function consumes
        # the already-parsed/stored field, not raw OCR text.
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="999")

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"mom"}))

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""

    def test_language_marker_de_globbed_code_unaffected_when_valid(self, db):
        """2026-07-22 language-marker de-globbing fix (local_ocr.py's own
        _LANGUAGE_MARKER_ADJACENCY_RE) - the DE-GLUED code ("znr", not the raw glued "znre") is
        what reaches this function, and it's a real lexicon code, so the gate never applies."""
        from cardpicker.local_ocr import parse_collector_line

        parsed = parse_collector_line("239/280 R\nZNRe EN b> DAARKEN")
        assert parsed.set_code == "znr"  # confirms the de-glob already happened upstream

        CanonicalExpansionFactory(code="znr")
        card = CardFactory(name="Verazol")
        candidates = [CandidatePrinting(pk=1, expansion_code="znr", collector_number="280")]
        evidence = _evidence(
            card,
            collector_line_raw_text="239/280 R\nZNRe EN b> DAARKEN",
            collector_line_set_code=parsed.set_code,
            collector_line_collector_number="999",  # force parsed-but-no-match
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, known_set_codes=frozenset({"znr"}))

        assert verdict.is_no_match is True
        assert verdict.skip_reason == ""

    def test_written_via_run_join_key_calculator_ends_up_as_a_scan_log_row(self, db):
        """Integration check (mirrors test_border_mismatch_writes_a_scan_log_row_via_the_full_
        runner's own convention) - the real batch runner builds and threads known_set_codes()
        through automatically, not just the pure-function unit tests above."""
        card = CardFactory(name="Test Card", content_phash=42)
        CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="zzq", collector_line_collector_number="2")

        result = run_join_key_calculator(dry_run=False)

        assert result.skip_counts.get(JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON) == 1
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert scan_log.skip_reason == JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()


class TestKnownSetCodes:
    def test_returns_lowercased_codes_from_the_db(self, db):
        CanonicalExpansionFactory(code="MOM")
        CanonicalExpansionFactory(code="isd")

        assert known_set_codes() == frozenset({"mom", "isd"})

    def test_empty_when_no_expansions_exist(self, db):
        assert known_set_codes() == frozenset()


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


class TestEligibleCardsQueryset:
    """`_eligible_cards_queryset`'s two knowledge-inventory excludes (module docstring's
    "CONSTANT #3" section; owner-ruled must-fix, 2026-07-22) - `RESOLUTION_FLOOR_DPI` and
    `EXCLUDED_RESOLVED_TAGS`. Exercised directly against the private queryset helper (this test
    suite's own established precedent for private helpers - `_resolve_candidates_for_card`/
    `_symbol_phash_tiebreak` above are imported and tested directly too), which isolates each
    exclusion's own boundary condition from join-key-matching mechanics entirely."""

    @staticmethod
    def _eligible_pks() -> set[int]:
        return set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).values_list("pk", flat=True))

    def test_below_floor_card_is_excluded(self, db):
        below = CardFactory(dpi=RESOLUTION_FLOOR_DPI - 1)
        assert below.pk not in self._eligible_pks()

    def test_dpi_at_the_floor_boundary_is_included(self, db):
        """The floor is `dpi < RESOLUTION_FLOOR_DPI`, exclusive - `dpi == RESOLUTION_FLOOR_DPI`
        itself is NOT below the floor and stays eligible."""
        at_floor = CardFactory(dpi=RESOLUTION_FLOOR_DPI)
        assert at_floor.pk in self._eligible_pks()

    def test_null_dpi_card_is_not_excluded_by_the_resolution_floor(self, db):
        """`Card.dpi` is a DB-level NOT NULL column today (confirmed live: 0 nulls in
        production), so this pins the QUERYSET's own null-safety defensively rather than relying
        on that constraint never moving - see `_eligible_cards_queryset`'s own docstring. A
        genuinely null-dpi row can't be produced through the ORM's normal validated write path
        (`Card.objects.filter(...).update(dpi=None)` alone raises `IntegrityError` against the
        live schema), so this test relaxes the column's own NOT NULL constraint for the duration
        of this one test only - inside pytest-django's per-test transaction, which is rolled back
        automatically afterwards (Postgres DDL is transactional), so the real schema is untouched
        outside this test."""
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE cardpicker_card ALTER COLUMN dpi DROP NOT NULL")
        card = CardFactory(dpi=RESOLUTION_FLOOR_DPI)
        Card.objects.filter(pk=card.pk).update(dpi=None)

        assert card.pk in self._eligible_pks()

    def test_custom_art_tagged_card_is_excluded(self, db):
        assert EXCLUDED_RESOLVED_TAGS[0] == "custom-art"
        card = CardFactory(tags=["custom-art"])
        assert card.pk not in self._eligible_pks()

    def test_non_english_tagged_card_is_excluded(self, db):
        assert EXCLUDED_RESOLVED_TAGS[1] == "non-english"
        card = CardFactory(tags=["non-english"])
        assert card.pk not in self._eligible_pks()

    def test_untagged_card_is_included(self, db):
        card = CardFactory(tags=[])
        assert card.pk in self._eligible_pks()

    def test_differently_tagged_card_is_included(self, db):
        """A tag that ISN'T one of the two `EXCLUDED_RESOLVED_TAGS` doesn't withhold the card -
        the exclusion is scoped to those two tag names specifically, not "any tag at all"."""
        card = CardFactory(tags=["altered-art"])
        assert card.pk in self._eligible_pks()


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
        """Mirrors this module's own established "a withhold only rejects a would-be MATCH, it's
        not a blanket 'ignore this card's evidence' switch" precedent (originally established by
        the proxy-marker check back when it was a veto, before its 2026-07-21 correction)."""
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


class TestCopyrightYearEraCheck:
    """Task 2 (Stage D cheap deductions, issue #152): the legal-line copyright year cross-checked
    against the matched printing's own Scryfall release year (`CanonicalPrintingMetadata.
    released_at`) - a large gap withholds an otherwise-confident join-key match rather than
    casting it. Exercised through `calculate_join_key_verdict`, same convention
    `TestAgreementChecks` already establishes for the other agreement checks - real backing
    `CanonicalCard`/`CanonicalPrintingMetadata` rows, since the check reuses THAT query rather
    than a field on `CandidatePrinting` itself."""

    def test_a_small_gap_is_not_withheld(self, db):
        """Exactly at the threshold: still a plausible gap, not vetoed."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year=str(2023 - COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS),
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_a_large_gap_withholds_the_match(self, db):
        """One year past the threshold: implausible, withheld as a named skip - not cast, and
        not converted into an is_no_match vote either (mirrors the moderator-flag veto's own
        "this reading isn't trustworthy evidence FOR P" framing, not "P is wrong")."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year=str(2023 - COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS - 1),
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "copyright-year-mismatch"
        assert verdict.printing_pk is None
        assert verdict.is_no_match is False

    def test_a_copyright_year_after_release_is_not_withheld(self, db):
        """Only the "predates release" direction is guarded against (module docstring) - a
        copyright year AFTER the release year isn't the failure mode being checked for here."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="2030",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_missing_copyright_year_skips_the_check_entirely(self, db):
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", legal_line_copyright_year=""
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_missing_released_at_skips_the_check_entirely(self, db):
        """No CanonicalPrintingMetadata.released_at yet for this printing - absent data must
        never manufacture a withhold."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=None)
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1999",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_no_printing_metadata_sidecar_skips_the_check_entirely(self, db):
        """A real CanonicalCard row with NO CanonicalPrintingMetadata sidecar at all - same
        "nothing to compare" degrade-to-agreement semantics border/frame already establish."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1990",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_copyright_year_mismatch_also_withholds_a_symbol_tiebroken_match(self, db):
        printing_a = CanonicalCardFactory(name="Forest", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, released_at=date(2023, 4, 21))
        printing_b = CanonicalCardFactory(name="Forest", expansion__code="vow", collector_number="158")
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=printing_b.pk, expansion_code="vow", collector_number="158"),
        ]
        evidence = _evidence(
            card,
            collector_line_collector_number="158",
            symbol_phash=_hash_of("mom"),
            legal_line_copyright_year="1990",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "copyright-year-mismatch"
        assert verdict.printing_pk is None

    def test_proxy_marker_no_longer_masks_a_real_copyright_mismatch(self, db):
        """2026-07-21 correction: the marker used to win outright when both conditions held on
        the same card (checked first, before the copyright-year query even ran). Now that it's a
        pure no-op, the copyright-year-mismatch withhold - a genuine, informative check - fires
        exactly as it would with the marker absent."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1990",
            legal_line_proxy_marker_detected=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "copyright-year-mismatch"

    def test_a_non_numeric_parsed_year_is_treated_as_no_signal_not_a_veto(self, db):
        """Shouldn't happen in practice (the OCR parser's own year regexes only ever capture
        digit runs) but guarded rather than assumed - a non-numeric value must skip the check,
        never crash or silently veto."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")
        evidence.legal_line_copyright_year = "abcd"
        evidence.save(update_fields=["legal_line_copyright_year"])

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_copyright_year_mismatch_writes_a_scan_log_row_via_the_full_runner(self, db):
        """Integration check, same convention as border-mismatch's own: a copyright-year
        mismatch is a permanent skip, not added to JOIN_KEY_RESCANNABLE_SKIP_REASONS."""
        card = CardFactory(name="Test Card", content_phash=42)
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, released_at=date(2023, 4, 21))
        _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1990",
        )

        result = run_join_key_calculator(dry_run=False)

        assert result.votes_written == 0
        log = CardScanLog.objects.get(card=card)
        assert log.skip_reason == "copyright-year-mismatch"

        # non-rescannable: re-running does NOT re-select this card.
        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 0


class TestCollectorNumberOnlyStaysNameScoped:
    """Task 3 (Stage D cheap deductions, issue #152): hardening/regression test, not new logic -
    the name pre-filter guard already existed (`calculate_join_key_verdict` only ever receives
    candidates already narrowed to the card's own name via `_resolve_candidates_for_card`), this
    class pins that invariant so a future refactor can't silently regress it into a global
    cross-set match."""

    def test_never_crosses_into_a_different_names_candidates(self, db):
        """Two DIFFERENT card names sharing the SAME collector number in DIFFERENT sets - a real,
        name-scoped CandidateNameIndex must resolve each name's own card only within its own
        candidates, never reaching into the other name's candidate sharing that same number."""
        forest_printing = CanonicalCardFactory(name="Forest", expansion__code="mom", collector_number="100")
        CanonicalCardFactory(name="Island", expansion__code="war", collector_number="100")

        index = CandidateNameIndex()
        forest_candidates = _resolve_candidates_for_card("Forest", index)
        assert len(forest_candidates) == 1
        assert forest_candidates[0].pk == forest_printing.pk

        card = CardFactory(name="Forest")
        evidence = _evidence(card, collector_line_collector_number="100")  # no set code - pre-M15 shape

        verdict = calculate_join_key_verdict(card.pk, evidence, forest_candidates)

        assert verdict.printing_pk == forest_printing.pk
        assert verdict.skip_reason == ""

    def test_a_mixed_candidate_list_from_two_names_is_ambiguous_not_a_false_match(self, db):
        """Simulates the exact bug the invariant rules out (a caller passing a candidates list
        that spans more than one card's name) - defense in depth: matching purely on collector
        number with no set code can't tell the two apart, so the result is a genuine 'ambiguous'
        skip, never a silent wrong-printing match."""
        forest_printing = CanonicalCardFactory(name="Forest", expansion__code="mom", collector_number="100")
        island_printing = CanonicalCardFactory(name="Island", expansion__code="war", collector_number="100")

        misscoped_candidates = [
            CandidatePrinting(pk=forest_printing.pk, expansion_code="mom", collector_number="100"),
            CandidatePrinting(pk=island_printing.pk, expansion_code="war", collector_number="100"),
        ]
        card = CardFactory(name="Forest")
        evidence = _evidence(card, collector_line_collector_number="100")

        verdict = calculate_join_key_verdict(card.pk, evidence, misscoped_candidates)

        assert verdict.skip_reason == "ambiguous"
        assert verdict.printing_pk is None


class TestCalculateSlowPathVerdict:
    """Task 1 (Stage D cheap deductions, issue #152, owner decision #220's option (b)): a pure
    routing verdict, not a match - assertions here are against the RETURNED SlowPathVerdict
    object's own raw_signals, not any persisted row (the CardScanLog routing marker this
    calculator writes carries no signals itself - see run_slow_path_calculator's own docstring
    and module docstring)."""

    def test_carries_the_raw_extracted_signals(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(
            card,
            collector_line_raw_text="158",
            collector_line_collector_number="158",
            legal_line_raw_text="TM & (c) 2019",
            legal_line_copyright_year="2019",
        )

        verdict = calculate_slow_path_verdict(card.pk, "ambiguous", evidence)

        assert verdict.card_id == card.pk
        assert verdict.reason == "ambiguous"
        assert verdict.raw_signals["collector_line_raw_text"] == "158"
        assert verdict.raw_signals["collector_line_collector_number"] == "158"
        assert verdict.raw_signals["legal_line_raw_text"] == "TM & (c) 2019"
        assert verdict.raw_signals["legal_line_copyright_year"] == "2019"
        # every declared raw-signal field is present, even ones this fixture didn't set -
        # confirms the packaging is complete, not just whichever fields happened to be non-empty.
        assert "layout_class" in verdict.raw_signals
        assert "bleed_class" in verdict.raw_signals
        assert "symbol_phash" in verdict.raw_signals


class TestRunSlowPathCalculator:
    def _no_hit_card(self, *, skip_reason=None, is_no_match=False):
        card = CardFactory(name="Some Card", content_phash=42)
        evidence = _evidence(card, collector_line_raw_text="garbled")
        if is_no_match:
            CardPrintingTag.objects.create(
                card=card,
                printing=None,
                is_no_match=True,
                anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                source=VoteSource.OCR,
            )
        else:
            CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=skip_reason)
        return card, evidence

    def test_dry_run_counts_a_no_match_vote_without_writing(self, db):
        card, _ = self._no_hit_card(is_no_match=True)

        result = run_slow_path_calculator(dry_run=True)

        assert result.cards_considered == 1
        assert result.routed_would_cast == 1
        assert result.reason_counts.get("parsed-but-no-match") == 1
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).count() == 0

    def test_write_routes_an_ambiguous_skip_to_review(self, db):
        card, _ = self._no_hit_card(skip_reason="ambiguous")

        result = run_slow_path_calculator(dry_run=False)

        assert result.routed_written == 1
        log = CardScanLog.objects.get(card=card, anonymous_id=SLOW_PATH_ANONYMOUS_ID)
        assert log.skip_reason == SLOW_PATH_TO_REVIEW_REASON

    def test_an_agreement_layer_withhold_is_also_routed(self, db):
        """The slow-path calculator sweeps up the agreement/corroboration layer's own withhold
        outcomes (border-mismatch/frame-mismatch/truncated-image/copyright-year-mismatch), not
        just the original join-key checks."""
        card, _ = self._no_hit_card(skip_reason="border-mismatch")

        result = run_slow_path_calculator(dry_run=False)

        assert result.routed_written == 1
        assert result.reason_counts.get("border-mismatch") == 1

    def test_a_confident_join_key_match_is_not_eligible_for_slow_path(self, db):
        """A card the join-key calculator DID resolve confidently (a real printing vote, not
        is_no_match) never gets routed - it has no no-hit outcome for this calculator to sweep
        up."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).count() == 0

    def test_a_rescannable_no_evidence_skip_is_not_eligible_yet(self, db):
        """The join-key calculator hasn't actually looked at this card's evidence at all yet
        (transient "no-evidence") - nothing to route on until a future join-key pass runs."""
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-evidence")

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 0

    def test_idempotent_against_its_own_anonymous_id(self, db):
        self._no_hit_card(skip_reason="no-text")

        first = run_slow_path_calculator(dry_run=False)
        assert first.routed_written == 1

        second = run_slow_path_calculator(dry_run=False)
        assert second.cards_considered == 0
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).count() == 1

    def test_stale_evidence_since_the_join_key_pass_is_not_routed(self, db):
        """The card's image changed since the join-key calculator looked at it - the ImageEvidence
        row this calculator would route is no longer CURRENT, so it's skipped rather than routing
        stale signals to a reviewer."""
        card = CardFactory(name="Some Card", content_phash=99)
        ImageEvidenceFactory(
            card=card,
            content_hash=42,  # stale - card.content_phash is 99
            extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        )
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).count() == 0


class TestFilterBySymbolPhash:
    """Mirrors TestSymbolPhashTiebreak's own cases - same underlying arithmetic, different return
    shape (a full set of surviving pks vs. one winning CandidatePrinting), see
    _filter_by_symbol_phash's own docstring for why the two are duplicated rather than shared."""

    def test_returns_none_without_a_symbol_hash(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        assert _filter_by_symbol_phash(None, candidates) is None

    def test_returns_none_with_no_candidates(self):
        assert _filter_by_symbol_phash(_hash_of("mom"), []) is None

    def test_returns_none_for_an_unrenderable_expansion_code(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="zzznotarealcode", collector_number="1")]
        assert _filter_by_symbol_phash(_hash_of("mom"), candidates) is None

    def test_returns_every_pk_sharing_the_winning_expansion(self):
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mir", collector_number="1"),
            CandidatePrinting(pk=2, expansion_code="mir", collector_number="2"),
            CandidatePrinting(pk=3, expansion_code="som", collector_number="1"),
        ]
        assert _filter_by_symbol_phash(_hash_of("mir"), candidates) == {1, 2}


class TestCalculateFallbackVerdict:
    """PIECE 1 (module docstring) - the border/artist/symbol intersection model, ported off
    already-persisted ImageEvidence fields rather than a live image. See local_fallback.py's own
    module docstring for the evidence-combination model this reproduces exactly."""

    def test_border_alone_narrows_to_one_and_casts_a_vote(self, db):
        printing_black = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing_black, border_color="black")
        printing_white = CanonicalCardFactory(name="Test Card", expansion__code="vow", collector_number="200")
        CanonicalPrintingMetadataFactory(canonical_card=printing_white, border_color="white")
        card = CardFactory(name="Test Card")
        candidates = [
            CandidatePrinting(pk=printing_black.pk, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=printing_white.pk, expansion_code="vow", collector_number="200"),
        ]
        evidence = _evidence(card, layout_class="black")

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing_black.pk
        assert verdict.evidence_types_used == ("border",)
        assert verdict.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE
        assert verdict.skip_reason == ""

    def test_symbol_alone_narrows_to_one_and_casts_a_vote(self, db):
        printing_a = CanonicalCardFactory(name="Test Card", expansion__code="mir", collector_number="1")
        printing_b = CanonicalCardFactory(name="Test Card", expansion__code="som", collector_number="1")
        card = CardFactory(name="Test Card")
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="mir", collector_number="1"),
            CandidatePrinting(pk=printing_b.pk, expansion_code="som", collector_number="1"),
        ]
        evidence = _evidence(card, symbol_phash=_hash_of("mir"))

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing_a.pk
        assert verdict.evidence_types_used == ("symbol",)
        assert verdict.confidence == FALLBACK_CONFIDENCE_SINGLE_EVIDENCE

    def test_border_and_artist_agreement_gives_multi_evidence_confidence(self, db):
        printing_a = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, border_color="black")
        printing_b = CanonicalCardFactory(
            name="Test Card", expansion__code="vow", collector_number="200", artist__name="Someone Else"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_b, border_color="white")
        card = CardFactory(name="Test Card")
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=printing_b.pk, expansion_code="vow", collector_number="200"),
        ]
        evidence = _evidence(card, layout_class="black", artist_ocr_name="Rebecca Guay")

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing_a.pk
        assert set(verdict.evidence_types_used) == {"border", "artist"}
        assert verdict.confidence == FALLBACK_CONFIDENCE_MULTI_EVIDENCE

    def test_border_and_artist_disagreement_abstains_never_a_false_accept(self, db):
        """The no-false-accept property (module docstring): border evidence alone points at
        printing_a, artist evidence alone points at printing_b - their intersection is empty, so
        this MUST abstain ('eliminated'), never pick either candidate."""
        printing_a = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, border_color="black")
        printing_b = CanonicalCardFactory(
            name="Test Card", expansion__code="vow", collector_number="200", artist__name="Someone Else"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_b, border_color="white")
        card = CardFactory(name="Test Card")
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=printing_b.pk, expansion_code="vow", collector_number="200"),
        ]
        # border evidence -> printing_a ("black"); artist evidence -> printing_b ("Someone Else")
        evidence = _evidence(card, layout_class="black", artist_ocr_name="Someone Else")

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk is None
        assert verdict.skip_reason == "eliminated"

    def test_ambiguous_when_the_only_reading_matches_more_than_one_candidate(self, db):
        printing_a = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, border_color="black")
        printing_b = CanonicalCardFactory(name="Test Card", expansion__code="vow", collector_number="200")
        CanonicalPrintingMetadataFactory(canonical_card=printing_b, border_color="black")
        card = CardFactory(name="Test Card")
        candidates = [
            CandidatePrinting(pk=printing_a.pk, expansion_code="mom", collector_number="158"),
            CandidatePrinting(pk=printing_b.pk, expansion_code="vow", collector_number="200"),
        ]
        evidence = _evidence(card, layout_class="black")

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk is None
        assert verdict.skip_reason == "ambiguous"

    def test_no_sub_check_produced_a_reading_abstains_even_with_a_single_candidate(self, db):
        """A single remaining candidate is NOT itself evidence - local_fallback.py's own rule
        (module docstring) checks "did any sub-check produce a reading at all" BEFORE ever looking
        at how many candidates survive, so a lone candidate with zero corroborating evidence must
        still abstain, not be nodded through by default."""
        printing = CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158")
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(card)  # no layout_class, no artist_ocr_name, no symbol_phash

        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk is None
        assert verdict.skip_reason == FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON


class TestRunFallbackCalculator:
    def _no_hit_card(self, *, skip_reason="no-text", is_no_match=False, **evidence_overrides):
        card = CardFactory(name="Some Card", content_phash=42)
        evidence = _evidence(card, **evidence_overrides)
        if is_no_match:
            CardPrintingTag.objects.create(
                card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
            )
        else:
            CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=skip_reason)
        return card, evidence

    def test_dry_run_counts_without_writing(self, db):
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        self._no_hit_card(layout_class="black")

        result = run_fallback_calculator(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert CardPrintingTag.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0

    def test_write_casts_a_vote_and_never_resolves_alone(self, db):
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        card, _ = self._no_hit_card(layout_class="black")

        result = run_fallback_calculator(dry_run=False)

        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        assert vote.source == VoteSource.OCR
        assert vote.run_id == result.run_id

        card.refresh_from_db()
        # a single VoteSource.OCR vote (weight 0.5) can never clear the human-backed gate alone.
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_a_card_the_join_key_calculator_already_resolved_is_not_eligible(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        _evidence(card, layout_class="black")
        CardPrintingTag.objects.create(
            card=card, printing=printing, is_no_match=False, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )

        result = run_fallback_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert CardPrintingTag.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0

    def test_skip_writes_a_scan_log_row(self, db):
        card, _ = self._no_hit_card()  # no layout_class/artist_ocr_name/symbol_phash at all

        result = run_fallback_calculator(dry_run=False)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0
        log = CardScanLog.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert log.skip_reason == FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON

    def test_idempotent_against_its_own_anonymous_id(self, db):
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        card, _ = self._no_hit_card(layout_class="black")

        first = run_fallback_calculator(dry_run=False)
        assert first.votes_written == 1

        second = run_fallback_calculator(dry_run=False)
        assert second.cards_considered == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 1

    def test_card_without_evidence_is_a_rescannable_no_evidence_skip(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")

        result = run_fallback_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get(FALLBACK_NO_EVIDENCE_SKIP_REASON) == 1
        log = CardScanLog.objects.get(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert log.skip_reason == FALLBACK_NO_EVIDENCE_SKIP_REASON

        # rescannable: adding evidence and re-running picks the card back up.
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        _evidence(card, layout_class="black")

        second = run_fallback_calculator(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_evidence_from_a_stale_content_hash_is_not_used(self, db):
        card = CardFactory(name="Some Card", content_phash=99)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")
        _evidence(card, content_hash=42, layout_class="black")  # stale - card.content_phash is 99

        result = run_fallback_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get(FALLBACK_NO_EVIDENCE_SKIP_REASON) == 1


class TestFallbackSlowPathInteraction:
    def test_a_card_the_fallback_calculator_resolved_is_not_routed_to_slow_path(self, db):
        """Wiring necessity (module docstring's PIECE 1 section): without this exclusion,
        slow-path would route a card to human review that the fallback calculator resolves
        moments earlier in the SAME invocation - the management command runs join-key -> fallback
        -> slow-path in that order."""
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="black")
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).count() == 0

    def test_a_card_the_fallback_calculator_only_scanned_is_still_routed(self, db):
        """The exclusion is scoped to a real fallback VOTE only - a card the fallback calculator
        scanned but abstained on (no confident hit from either calculator) still has nothing
        automated resolving it, and belongs in the review queue exactly as before this PR."""
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")
        CardScanLog.objects.create(
            card=card,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            skip_reason=FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
        )

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 1
        assert CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID, card=card).count() == 1


class TestCommandLedgerHardeningAndDryRunGuard:
    """Phase 0 rails (issues #362/#153's milestone): the Command.handle() lifecycle itself, on an
    empty (zero-eligible-card) DB - the calculator behaviour above is already exhaustively covered
    by the pure-function tests in this file; these exercise the ledger/guard WIRING around it."""

    def test_write_refused_without_a_prior_matching_dry_run(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("local_calculate_verdicts", "--write")
        assert not PilotRunLedger.objects.filter(command="local_calculate_verdicts").exists()

    def test_write_succeeds_after_a_matching_dry_run(self, db):
        from django.core.management import call_command

        call_command("local_calculate_verdicts")  # dry-run (default)
        call_command("local_calculate_verdicts", "--write")

        ledgers = list(PilotRunLedger.objects.filter(command="local_calculate_verdicts").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True
        assert ledgers[1].dry_run is False
        assert ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, capsys):
        from django.core.management import call_command

        call_command("local_calculate_verdicts", "--write", "--skip-dryrun-check")

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.counters["skip_dryrun_check_used"] is True

    def test_broken_pipe_during_terminal_summary_does_not_flip_completed_to_failed(self, db, monkeypatch):
        """Production incident 2026-07-23: a client-side timeout severed stdout AFTER every write
        had already committed and the ledger row had already been saved COMPLETED - the terminal
        summary print must never be able to flip that back to FAILED."""
        from django.core.management import call_command

        import cardpicker.management.commands.local_calculate_verdicts as cmd_module

        real_print = print

        def raising_print(*args: Any, **kwargs: Any) -> None:
            msg = args[0] if args else ""
            if isinstance(msg, str) and msg.startswith("[") and "done. run_id=" in msg:
                raise BrokenPipeError("stdout severed")
            real_print(*args, **kwargs)

        monkeypatch.setattr(cmd_module, "print", raising_print, raising=False)

        # No exception escapes call_command - resilient_terminal_output swallows the simulated
        # BrokenPipeError from the terminal summary print.
        call_command("local_calculate_verdicts", "--write", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
