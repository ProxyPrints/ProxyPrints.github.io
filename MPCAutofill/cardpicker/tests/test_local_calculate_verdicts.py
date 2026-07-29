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

from django.core.management import CommandError
from django.db import connection

from cardpicker.collector_line_artist import build_artist_lexicon, load_artist_lexicon
from cardpicker.local_calculate_verdicts import (
    COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS,
    EXCLUDED_RESOLVED_TAGS,
    FALLBACK_NO_EVIDENCE_SKIP_REASON,
    FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON,
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
    TRANSFERRED_INTERIM_GUARD_SKIP_REASON,
    _eligible_cards_queryset,
    _filter_by_symbol_phash,
    _purge_and_write_printing_tag_votes,
    _resolve_candidates_for_card,
    _split_new_printing_tag_votes,
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
    CanonicalPrintingMetadata,
    Card,
    CardPrintingTag,
    CardScanLog,
    PilotRunLedger,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_metadata_import import ensure_scryfall_cache_present
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    DFCPairFactory,
    ImageEvidenceFactory,
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


class TestSplitNewPrintingTagVotes:
    """Direct unit coverage for the 2026-07-24 concurrent-dispatch vote-collision guard (the
    shakedown's failed run_ids stage-e-stream-20260724T2144*, a SEPARATE failure from that same
    run's envtrip-20260724T214616-be6e5db9 host-load trip - see this guard's own docstring),
    independent of either calculator's full orchestration - mirrors
    test_local_lands_identify.py's own TestSplitNewVotes structure for the sibling PR #411
    guard."""

    def test_empty_batch_returns_empty(self, db):
        assert _split_new_printing_tag_votes([]) == ([], 0)

    def test_no_pre_existing_vote_keeps_everything(self, db):
        card = CardFactory(name="Some Card")
        vote = CardPrintingTag(card_id=card.pk, printing_id=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID)

        new_votes, already_voted = _split_new_printing_tag_votes([vote])

        assert new_votes == [vote]
        assert already_voted == 0

    def test_an_existing_no_match_vote_for_the_same_identity_is_skipped(self, db):
        card = CardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )
        vote = CardPrintingTag(card_id=card.pk, printing_id=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID)

        new_votes, already_voted = _split_new_printing_tag_votes([vote])

        assert new_votes == []
        assert already_voted == 1

    def test_an_existing_match_vote_for_the_same_identity_is_skipped_even_with_a_different_printing(self, db):
        """The invariant this guard enforces is 'at most one vote per (card, anonymous_id)',
        matching _eligible_cards_queryset's own exclude - not 'at most one vote per (card,
        printing, anonymous_id)', which is all the DB's own cardprintingtag_unique_printing_vote
        constraint alone would check."""
        card = CardFactory(name="Some Card")
        printing_a = CanonicalCardFactory(name="Some Card")
        printing_b = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card, printing=printing_a, is_no_match=False, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )
        vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing_b.pk, is_no_match=False, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        )

        new_votes, already_voted = _split_new_printing_tag_votes([vote])

        assert new_votes == []
        assert already_voted == 1

    def test_an_existing_vote_under_a_different_identity_is_not_a_collision(self, db):
        card = CardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )
        vote = CardPrintingTag(card_id=card.pk, printing_id=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID)

        new_votes, already_voted = _split_new_printing_tag_votes([vote])

        assert new_votes == [vote]
        assert already_voted == 0

    def test_mixed_batch_skips_only_the_colliding_vote(self, db):
        collided_card = CardFactory(name="Some Card")
        clean_card = CardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=collided_card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )
        colliding_vote = CardPrintingTag(
            card_id=collided_card.pk, printing_id=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        )
        clean_vote = CardPrintingTag(
            card_id=clean_card.pk, printing_id=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        )

        new_votes, already_voted = _split_new_printing_tag_votes([colliding_vote, clean_vote])

        assert new_votes == [clean_vote]
        assert already_voted == 1


class TestPurgeAndWritePrintingTagVotes:
    """`_purge_and_write_printing_tag_votes` (2026-07-28) - the shared purge+insert primitive all
    three `CardPrintingTag`-casting calculators now use. Two properties it exists to guarantee:
    the pair is ATOMIC (the operator kills runs mid-flight deliberately, and an untransacted
    DELETE-then-INSERT loses votes outright if killed between the two), and the purge is scoped to
    `new_votes` so a card the collision guard SKIPPED keeps the winner's committed row."""

    def _stale_family_vote(self, card, printing):
        """A row from an older version of the SAME calculator family - deleted by
        `purge_stale_machine_votes`, but NOT a collision as far as the split is concerned (it
        checks the exact current anonymous_id), so its card is genuinely in `new_votes`."""
        return CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="stage-d-join-key-v0",
            source=VoteSource.OCR,
        )

    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        stale = self._stale_family_vote(card, printing)
        new_vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            _purge_and_write_printing_tag_votes(JOIN_KEY_ANONYMOUS_ID, [new_vote])

        # without transaction.atomic() the DELETE would already have committed and this row would
        # be gone, with nothing written in its place.
        assert CardPrintingTag.objects.filter(pk=stale.pk).exists()

    def test_the_happy_path_purges_the_stale_row_and_writes_the_new_one(self, db):
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        stale = self._stale_family_vote(card, printing)
        new_vote = CardPrintingTag(
            card_id=card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        )

        _purge_and_write_printing_tag_votes(JOIN_KEY_ANONYMOUS_ID, [new_vote])

        assert not CardPrintingTag.objects.filter(pk=stale.pk).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 1

    def test_an_empty_new_votes_list_purges_nothing(self, db):
        """A batch in which EVERY vote collided must not purge anything - passing the raw batch
        here (rather than the split's output) would delete each winner's row and write nothing."""
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        winner = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        _purge_and_write_printing_tag_votes(JOIN_KEY_ANONYMOUS_ID, [])

        assert CardPrintingTag.objects.filter(pk=winner.pk).exists()


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

    def test_concurrent_dispatch_collision_is_skipped_not_crashed(self, db, monkeypatch):
        """Regression for the Stage E Phase 2 shakedown's first live trip
        (envtrip-20260724T214616-be6e5db9, failed run_ids stage-e-stream-20260724T2144*) - see
        _split_new_printing_tag_votes' own docstring for the full root-cause writeup. Reproduces
        the exact TOCTOU a concurrent streamed re-entry hits: this card was genuinely eligible
        when ITS OWN eligibility read ran (no vote existed yet), but another, concurrent
        dispatch's own write landed before this invocation reached its own bulk_create -
        simulated here by monkeypatching the eligibility read to stay stale (representing the
        already-consumed queryset a real concurrent caller would have) while a colliding vote is
        seeded directly, reproducing the literal production key
        (JOIN_KEY_ANONYMOUS_ID, is_no_match=True)."""
        import cardpicker.local_calculate_verdicts as module

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_collector_number="999")  # no candidate match -> is_no_match=True
        monkeypatch.setattr(module, "_eligible_cards_queryset", lambda *args, **kwargs: Card.objects.filter(pk=card.pk))

        # the WINNER of the race: a vote already landed for this exact (card, anonymous_id) pair.
        CardPrintingTag.objects.create(
            card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )

        result = run_join_key_calculator(dry_run=False)  # must not raise IntegrityError

        # 2026-07-28: the split/count now runs BEFORE the purge, so the guard actually guards -
        # the loser SKIPS and counts, and the winner's committed row is left alone (a skipped
        # card is not in `new_votes`, so `_purge_and_write_printing_tag_votes` never purges it).
        # Previously the purge ran first and deleted exactly the row the split then went looking
        # for, making `already_voted` structurally 0 in every deployment forever - the "zero
        # forever would suggest the guard itself is dead code" failure
        # `stage_e_dispatch.DispatchOutcome.stage_d_join_key_already_voted`'s own comment warns
        # about. No crash; one vote remains.
        assert result.already_voted == 1
        assert result.votes_written == 0
        assert result.no_match_votes_written == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 1

    def test_ignore_conflicts_survives_a_race_the_pre_write_check_itself_missed(self, db, monkeypatch):
        """The pre-write guard above (`_split_new_printing_tag_votes`) is check-then-insert, not
        atomic - a residual query-to-insert race window remains where a colliding vote could land
        between the guard's own existence check and this calculator's `bulk_create` call. Proves
        the SECOND line of defense (`bulk_create(..., ignore_conflicts=True)`) alone survives that
        residual window, by monkeypatching the guard itself to (falsely) report the vote as new -
        exactly what it would see if the collision landed a moment after its own read - while the
        colliding row is already in the DB by the time `bulk_create` runs."""
        import cardpicker.local_calculate_verdicts as module

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_collector_number="999")  # no candidate match -> is_no_match=True

        real_split = module._split_new_printing_tag_votes

        def _stale_split(votes_batch):
            # Reports every vote as new (already_voted=0), then seeds the collision AFTER the
            # guard's own "check" has already run - the exact residual window this test targets.
            new_votes, _already_voted = real_split(votes_batch)
            CardPrintingTag.objects.create(
                card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
            )
            return new_votes, 0

        monkeypatch.setattr(module, "_split_new_printing_tag_votes", _stale_split)

        run_join_key_calculator(dry_run=False)  # must not raise IntegrityError despite the stale guard

        # exactly one vote survives - ignore_conflicts=True silently dropped the duplicate insert
        # attempt, it did not raise and did not create a second row.
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 1


class TestTransferredEvidenceIsEligible:
    """Issue #473 PR-2's INTERIM STAGE D GUARD (TRANSFERRED_INTERIM_GUARD_SKIP_REASON) excluded a
    card whose CURRENT evidence row was created via evidence transfer from the join-key/fallback
    calculators outright - its own "observation" is the same bytes an md5-sibling already voted
    from, not an independent one. PR-3 (2026-07-25, owner-ratified group-level vote pooling)
    RETIRES that guard: a transferred card is now exactly as eligible as any other card in every
    Stage D calculator, because the independence concern the guard existed to protect is now
    handled correctly at the GROUP tally level instead (`vote_consensus.pool_group_votes` - see
    `test_md5_group_pooling.py::TestTransferredEvidencePoolsWithItsSource` for the pooling-level
    pin of that same claim). These tests replace the old skip-assertions with the mirror-image
    vote-cast assertions; `TRANSFERRED_INTERIM_GUARD_SKIP_REASON` itself stays imported/exported
    only because historical `CardScanLog` rows from before this change still carry it (see its own
    module-level comment) - no test here expects a NEW row with that reason."""

    def test_join_key_votes_a_transferred_evidence_card(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            transferred=True,
            transferred_from_card_id=999,
        )

        result = run_join_key_calculator(dry_run=False)

        assert result.cards_considered == 1
        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.is_no_match is False
        # no historical-guard skip row is written for this card at all
        assert not CardScanLog.objects.filter(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=TRANSFERRED_INTERIM_GUARD_SKIP_REASON
        ).exists()

    def test_join_key_votes_identically_regardless_of_transferred(self, db):
        """Control - the exact same evidence, minus transferred=True, casts the same vote. Proves
        the retired guard's absence is a true no-op on outcome, not just "doesn't skip"."""
        card_transferred = CardFactory(name="Some Card", content_phash=42)
        card_real = CardFactory(name="Some Card", content_phash=43)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card_transferred,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            transferred=True,
            transferred_from_card_id=999,
        )
        _evidence(
            card_real,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            transferred=False,
        )

        result = run_join_key_calculator(dry_run=False)

        assert result.cards_considered == 2
        assert result.votes_written == 2
        transferred_vote = CardPrintingTag.objects.get(card=card_transferred)
        real_vote = CardPrintingTag.objects.get(card=card_real)
        assert transferred_vote.printing_id == real_vote.printing_id

    def test_fallback_votes_a_transferred_evidence_card(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")
        _evidence(
            card,
            layout_class="black",
            transferred=True,
            transferred_from_card_id=999,
        )

        result = run_fallback_calculator(dry_run=False)

        assert result.cards_considered == 1
        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        assert not CardScanLog.objects.filter(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason=TRANSFERRED_INTERIM_GUARD_SKIP_REASON
        ).exists()

    def test_slow_path_still_routes_transferred_evidence_to_review(self, db):
        """The slow-path calculator casts no machine vote (only a CardScanLog routing marker to a
        HUMAN reviewer) - it was never guarded on `transferred` either before or after PR-3, so
        this behavior is unchanged; see its own loop comment."""
        card = CardFactory(name="Some Card", content_phash=42)
        CardPrintingTag.objects.create(
            card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )
        _evidence(
            card,
            collector_line_collector_number="999",
            transferred=True,
            transferred_from_card_id=999,
        )

        result = run_slow_path_calculator(dry_run=False)

        assert result.cards_considered == 1
        assert result.routed_written == 1
        log = CardScanLog.objects.get(card=card, anonymous_id=SLOW_PATH_ANONYMOUS_ID)
        assert log.skip_reason == SLOW_PATH_TO_REVIEW_REASON


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


class TestEligibleCardsQuerysetCardScanLogScoping:
    """Issue #469 (Tron §8 gate finding, 2026-07-25): `_eligible_cards_queryset`'s
    `CardScanLog`-derived exclusion subquery is now scoped by `card_id__in=card_ids` whenever
    `card_ids` is provided, instead of always scanning the whole (2,093,147-row-live,
    append-only) `CardScanLog` table. This is a pure cost narrowing - proves the resulting
    ELIGIBLE SET is identical scoped vs. unscoped for a `card_ids`-bounded caller, and that
    `card_ids=None` (BULK mode) is completely untouched by the scoping branch."""

    def test_scoped_and_unscoped_eligible_sets_agree(self, db):
        excluded_card = CardFactory(name="Excluded Card")
        # a non-rescannable skip reason (anything outside JOIN_KEY_RESCANNABLE_SKIP_REASONS,
        # which is frozenset({"no-evidence"})) makes this card permanently excluded.
        CardScanLog.objects.create(card=excluded_card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")
        eligible_card = CardFactory(name="Eligible Card")
        other_scoped_card = CardFactory(name="Also In Scope But Untouched")

        unscoped = set(
            _eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID)
            .filter(pk__in=[excluded_card.pk, eligible_card.pk, other_scoped_card.pk])
            .values_list("pk", flat=True)
        )
        scoped = set(
            _eligible_cards_queryset(
                JOIN_KEY_ANONYMOUS_ID, card_ids=[excluded_card.pk, eligible_card.pk, other_scoped_card.pk]
            ).values_list("pk", flat=True)
        )

        assert excluded_card.pk not in unscoped
        assert unscoped == scoped == {eligible_card.pk, other_scoped_card.pk}

    def test_card_ids_scoping_still_excludes_a_scan_logged_card_outside_the_scope_list(self, db):
        """The CardScanLog row itself doesn't have to be for a card IN `card_ids` to matter to
        THIS test's own scoping correctness - this only pins that a card genuinely excluded by
        its own scan-log row stays excluded when it IS in `card_ids`, the same outcome the
        unscoped subquery already gave it."""
        excluded_card = CardFactory(name="Excluded Card")
        CardScanLog.objects.create(
            card=excluded_card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="unknown-set-code"
        )

        scoped = set(
            _eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, card_ids=[excluded_card.pk]).values_list("pk", flat=True)
        )

        assert scoped == set()

    def test_card_ids_none_matches_pre_fix_bulk_behaviour(self, db):
        """BULK mode (`card_ids=None`, every existing management-command caller) must never take
        the `card_id__in` scoping branch - this pins the observable outcome (a scan-logged card
        stays excluded, an untouched card stays eligible) unchanged from before this fix, the
        same outcome `TestEligibleCardsQueryset` above already exercises for every OTHER
        exclusion; this whole test file's full pre-existing suite passing unmodified (no test
        below needed updating for this fix) is the fuller "byte-identical BULK behaviour" proof."""
        excluded_card = CardFactory(name="Excluded Card")
        CardScanLog.objects.create(card=excluded_card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")
        eligible_card = CardFactory(name="Eligible Card")

        pks = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, card_ids=None).values_list("pk", flat=True))

        assert excluded_card.pk not in pks
        assert eligible_card.pk in pks


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

    # --- THE COLLECTOR-LINE ARTIST GATE (2026-07-29, module docstring) -----------------------
    # `run_join_key_calculator` parses set+number out of `collector_line_raw_text` and DISCARDS
    # the artist printed in that same string. When the parsed printing's artist disagrees with
    # that recovered artist, the parse contradicts its own source - abstain, don't vote.

    ARTIST_GATE_LEXICON = build_artist_lexicon(["Rebecca Guay", "Lindsey Look", "Ron Spears", "Ron Spencer"])

    def test_collector_line_artist_disagreement_abstains_instead_of_voting(self, db):
        """The stored parse resolves to a Rebecca Guay printing, but the very collector line it
        was parsed out of reads `LINDSEY L` - a misread collector number. No vote is cast."""
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text="158/281R\nMOM ¢ EN LINDSEY L",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, artist_lexicon=self.ARTIST_GATE_LEXICON)

        assert verdict.skip_reason == JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON
        assert verdict.printing_pk is None
        assert verdict.is_no_match is False  # an abstention, NOT a negative vote

    def test_the_same_evidence_votes_when_the_gate_is_not_wired(self, db):
        """The control for the test above - identical inputs, no `artist_lexicon`, so the
        pre-2026-07-29 behaviour (a confident vote on a parse the card's own pixels contradict) is
        reproduced exactly. Proves the abstention above comes from the gate, not from anything
        incidental about the fixture."""
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text="158/281R\nMOM ¢ EN LINDSEY L",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == printing.pk
        assert verdict.skip_reason == ""

    def test_collector_line_artist_agreement_leaves_the_match_alone(self, db):
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Lindsey Look"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text="158/281R\nMOM ¢ EN LINDSEY L",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, artist_lexicon=self.ARTIST_GATE_LEXICON)

        assert verdict.printing_pk == printing.pk
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_an_ambiguous_truncated_reading_never_manufactures_an_abstention(self, db):
        """`RON SPEA` is compatible with both "Ron Spears" and "Ron Spencer" - a printing by
        EITHER must still get its vote. Only a reading incompatible with every plausible
        interpretation abstains."""
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Ron Spencer"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text="158/281R\nMOM ¢ EN RON SPEA",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, artist_lexicon=self.ARTIST_GATE_LEXICON)

        assert verdict.printing_pk == printing.pk

    def test_unreadable_collector_line_artist_leaves_the_match_alone(self, db):
        """Missing data is not evidence - the same rule every other check in this layer applies."""
        printing = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        card = CardFactory(name="Test Card")
        candidates = [CandidatePrinting(pk=printing.pk, expansion_code="mom", collector_number="158")]
        evidence = _evidence(
            card,
            collector_line_raw_text="158/281R\nMOM ¢ EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates, artist_lexicon=self.ARTIST_GATE_LEXICON)

        assert verdict.printing_pk == printing.pk

    def test_artist_mismatch_still_routes_to_human_review(self, db):
        """An abstention that doesn't route is a review-queue gap - `artist-mismatch` is exactly
        the cohort a reviewer should see, so it must be a `JOIN_KEY_NO_HIT_SKIP_REASONS` member."""
        assert JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON in JOIN_KEY_NO_HIT_SKIP_REASONS

    def test_load_artist_lexicon_reads_the_real_canonical_artist_table(self, db):
        """The one DB-touching entry point, against the real ORM - `run_join_key_calculator`
        builds this once per batch."""
        CanonicalCardFactory(name="Test Card", expansion__code="mom", collector_number="158", artist__name="Ron Spears")

        lexicon = load_artist_lexicon()

        assert "Ron Spears" in lexicon.names

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

    def test_concurrent_dispatch_collision_is_skipped_not_crashed(self, db, monkeypatch):
        """Same shakedown regression as TestRunJoinKeyCalculator's own version of this test - this
        calculator writes CardPrintingTag under its own STAGE_D_FALLBACK_ANONYMOUS_ID identity too
        and is equally exposed to the concurrent-dispatch collision
        _split_new_printing_tag_votes' own docstring writes up."""
        import cardpicker.local_calculate_verdicts as module

        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        card, _ = self._no_hit_card(layout_class="black")
        monkeypatch.setattr(module, "_eligible_cards_queryset", lambda *args, **kwargs: Card.objects.filter(pk=card.pk))

        # the WINNER of the race: a vote already landed for this exact (card, anonymous_id) pair.
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        result = run_fallback_calculator(dry_run=False)  # must not raise IntegrityError

        # 2026-07-28: split/count BEFORE purge - see the identical assertion's own comment in
        # `test_concurrent_dispatch_collision_is_skipped_not_crashed` above. The loser skips and
        # counts; the winner's committed row survives. No crash; one vote remains.
        assert result.already_voted == 1
        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 1


class TestCandidateNameIndexLazyProcessCache:
    """Issue #469 (Tron §8 gate finding, 2026-07-25): `CandidateNameIndex()` (a 113,224-row live
    scan, measured 1.48s) used to be built UNCONDITIONALLY at the top of
    `run_join_key_calculator`/`run_fallback_calculator`, before any eligibility check - fixed to
    build lazily (only once a card actually needs candidate resolution) and to cache the result
    per worker process, invalidated by a cheap `(CanonicalCard max pk, count, CanonicalExpansion
    max pk, count)` version stamp - `docs/proposals/stage-e-streaming.md` §4 item 5's own
    "once per worker process lifetime, with an explicit invalidation event" ruling. Every test
    here resets the module-level cache first (`reset_candidate_name_index_cache_for_tests`) so
    construction COUNTS are deterministic and don't depend on Postgres's own incidental
    sequence-advance-across-rollback behaviour."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        import cardpicker.local_calculate_verdicts as module

        module.reset_candidate_name_index_cache_for_tests()
        yield
        module.reset_candidate_name_index_cache_for_tests()

    @staticmethod
    def _count_constructions(monkeypatch) -> list[int]:
        """Returns a single-element mutable counter, incremented once per real
        `CandidateNameIndex.__init__` call - patches the REAL `__init__` (not a full replacement)
        so the returned index objects stay fully functional, not a stub."""
        import cardpicker.local_calculate_verdicts as module

        count = [0]
        real_init = CandidateNameIndex.__init__

        def counting_init(self, *args, **kwargs):
            count[0] += 1
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(module.CandidateNameIndex, "__init__", counting_init)
        return count

    def test_join_key_calculator_never_constructs_the_index_when_the_eligible_set_is_empty(self, db, monkeypatch):
        count = self._count_constructions(monkeypatch)
        # no Card fixtures at all - the eligible queryset is empty.

        result = run_join_key_calculator(dry_run=True)

        assert result.cards_considered == 0
        assert count[0] == 0

    def test_fallback_calculator_never_constructs_the_index_when_the_eligible_set_is_empty(self, db, monkeypatch):
        count = self._count_constructions(monkeypatch)
        # no Card fixtures at all - the eligible queryset is empty.

        result = run_fallback_calculator(dry_run=True)

        assert result.cards_considered == 0
        assert count[0] == 0

    def test_join_key_calculator_constructs_the_index_once_when_a_card_is_eligible(self, db, monkeypatch):
        count = self._count_constructions(monkeypatch)
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        result = run_join_key_calculator(dry_run=True)

        assert result.cards_considered == 1
        assert count[0] == 1

    def test_cache_hit_across_two_calls_in_one_process(self, db, monkeypatch):
        """The second `run_join_key_calculator` call reuses the SAME cached `CandidateNameIndex`
        - no CanonicalCard/CanonicalExpansion write happened in between, so the version stamp is
        unchanged and no second construction happens. `dry_run=False` on the first call so its
        own vote actually lands, making card_a ineligible for the second call - otherwise a
        dry-run casts no vote and card_a would simply be reconsidered."""
        count = self._count_constructions(monkeypatch)
        card_a = CardFactory(name="Card A", content_phash=1)
        CanonicalCardFactory(name="Card A", expansion__code="mom", collector_number="1")
        _evidence(card_a, collector_line_set_code="mom", collector_line_collector_number="1")

        first = run_join_key_calculator(dry_run=False)
        assert first.votes_written == 1
        assert count[0] == 1

        # a SECOND card matching the SAME already-indexed canonical printing - no new
        # CanonicalCard/CanonicalExpansion write happens here, only a new Card/ImageEvidence
        # (neither participates in the version stamp).
        card_b = CardFactory(name="Card A", content_phash=2)
        _evidence(card_b, collector_line_set_code="mom", collector_line_collector_number="1")

        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 1  # card_a is now excluded - already voted on
        assert second.votes_written == 1
        # still 1 - the second call hit the cache rather than rebuilding.
        assert count[0] == 1

    def test_cache_reused_across_join_key_and_fallback_calculators(self, db, monkeypatch):
        """The cache is module-level, not per-caller - `run_fallback_calculator` reuses the same
        cached index `run_join_key_calculator` already built, in the same worker process."""
        count = self._count_constructions(monkeypatch)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        card_a = CardFactory(name="Some Card", content_phash=42)
        _evidence(card_a, collector_line_set_code="mom", collector_line_collector_number="158")
        run_join_key_calculator(dry_run=True)
        assert count[0] == 1

        card_b = CardFactory(name="Some Card", content_phash=43)
        _evidence(card_b, layout_class="black")
        CardScanLog.objects.create(card=card_b, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")

        run_fallback_calculator(dry_run=True)
        assert count[0] == 1

    def test_cache_invalidated_when_a_canonical_card_is_added(self, db, monkeypatch):
        """A `CanonicalCard` landing between two dispatches (the exact "explicit invalidation
        event" `docs/proposals/stage-e-streaming.md` §4 item 5 calls for) forces a rebuild - and
        the rebuilt index actually sees the newly-added candidate, not a stale snapshot.
        `dry_run=False` on the first call so card_a's vote actually lands, making it ineligible
        for the second call - the second call's `cards_considered` then isolates card_b alone."""
        count = self._count_constructions(monkeypatch)
        card_a = CardFactory(name="Card A", content_phash=1)
        CanonicalCardFactory(name="Card A", expansion__code="mom", collector_number="1")
        _evidence(card_a, collector_line_set_code="mom", collector_line_collector_number="1")

        first = run_join_key_calculator(dry_run=False)
        assert first.votes_written == 1
        assert count[0] == 1

        # a new CanonicalCard row lands - the invalidation event.
        CanonicalCardFactory(name="Card B", expansion__code="won", collector_number="2")
        card_b = CardFactory(name="Card B", content_phash=2)
        _evidence(card_b, collector_line_set_code="won", collector_line_collector_number="2")

        second = run_join_key_calculator(dry_run=False)
        assert second.cards_considered == 1  # card_a already voted on, only card_b is eligible
        assert second.votes_written == 1  # proves the REBUILT index actually sees "Card B"
        assert count[0] == 2

    def test_cache_invalidated_when_a_bare_canonical_expansion_is_added(self, db, monkeypatch):
        """A `CanonicalExpansion` row added on its own (no `CanonicalCard` change) also moves the
        version stamp - covers the stamp's OTHER half, not just CanonicalCard."""
        count = self._count_constructions(monkeypatch)
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        run_join_key_calculator(dry_run=True)
        assert count[0] == 1

        CanonicalExpansionFactory(code="xyz")  # a bare expansion row, no CanonicalCard attached

        card_two = CardFactory(name="Some Card", content_phash=99)
        _evidence(card_two, collector_line_set_code="mom", collector_line_collector_number="158")
        run_join_key_calculator(dry_run=True)

        assert count[0] == 2


class TestCandidateNameIndexVersionStampDetectsInPlaceWrites:
    """PR #526's finding, applied to `CandidateNameIndex` (issue #533's third blocking
    prerequisite, 2026-07-29). A version stamp built only from max-pk and row count is blind to an
    UPDATE, and `import_scryfall_printing_metadata._sync_printing_metadata` BACKFILLS
    `CanonicalPrintingMetadata.edhrec_rank` IN PLACE via
    `bulk_update(fields=_METADATA_SYNC_FIELDS)` - moving neither. `CandidateNameIndex.__init__`
    reads that exact column (`printing_metadata__edhrec_rank`), so under the original four-term
    `(CanonicalCard max pk, count, CanonicalExpansion max pk, count)` stamp a worker process that
    built its index before a metadata import served a stale, under-populated one for its whole
    lifetime.

    Every test here mutates the underlying data in a way that does NOT move max pk or row count on
    ANY stamped table, and asserts the cache invalidates anyway. Each one ALSO asserts that the
    original four terms are byte-identical across the mutation, so the test is proving the stamp
    catches something max-pk/count genuinely cannot rather than accidentally passing on an
    incidental row-count move."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        import cardpicker.local_calculate_verdicts as module

        module.reset_candidate_name_index_cache_for_tests()
        yield
        module.reset_candidate_name_index_cache_for_tests()

    @staticmethod
    def _stamp():
        import cardpicker.local_calculate_verdicts as module

        return module._candidate_name_index_version_stamp()

    @staticmethod
    def _count_constructions(monkeypatch) -> list[int]:
        import cardpicker.local_calculate_verdicts as module

        count = [0]
        real_init = CandidateNameIndex.__init__

        def counting_init(self, *args, **kwargs):
            count[0] += 1
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(module.CandidateNameIndex, "__init__", counting_init)
        return count

    def test_in_place_edhrec_rank_backfill_moves_the_stamp(self, db):
        """THE #526 CASE. `.update()` on an existing row - a bare SQL UPDATE, no INSERT, no
        DELETE - so every max-pk and every row count on every stamped table is unchanged."""
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, edhrec_rank=None)

        before = self._stamp()
        updated = CanonicalPrintingMetadata.objects.filter(canonical_card=printing).update(edhrec_rank=1234)
        after = self._stamp()

        assert updated == 1
        # the four terms the ORIGINAL stamp was made of did not move - this is the whole point.
        assert before[:4] == after[:4]
        # ...nor did the metadata table's own max pk / row count.
        assert before[4:6] == after[4:6]
        assert before != after

    def test_in_place_edhrec_re_rank_moves_the_stamp(self, db):
        """Beyond #526: `illustration_id` is a stable UUID, so a non-null COUNT alone was enough
        there. `edhrec_rank` is re-ranked on every weekly Scryfall dump, so a value ->
        DIFFERENT VALUE update is the routine case - and it moves neither the row count nor the
        non-null count. Only the SUM term catches it."""
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, edhrec_rank=1234)

        before = self._stamp()
        CanonicalPrintingMetadata.objects.filter(canonical_card=printing).update(edhrec_rank=99)
        after = self._stamp()

        assert before[:4] == after[:4]  # original four terms blind to it
        assert before[4:7] == after[4:7]  # so are max pk, row count AND the non-null count
        assert before[7] != after[7]  # the sum term is the one that sees it
        assert before != after

    def test_a_metadata_row_created_for_an_existing_card_moves_the_stamp(self, db):
        """The other hole the original four-term stamp had: `CanonicalPrintingMetadata` is a
        SEPARATE TABLE whose primary key IS `canonical_card_id`, so creating the sidecar row for
        an already-existing `CanonicalCard` moves neither CanonicalCard max pk nor CanonicalCard
        count - and the four-term stamp had no CanonicalPrintingMetadata term at all."""
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")

        before = self._stamp()
        CanonicalPrintingMetadataFactory(canonical_card=printing, edhrec_rank=7)
        after = self._stamp()

        assert before[:4] == after[:4]
        assert before != after

    def test_a_deleted_metadata_row_moves_the_stamp(self, db):
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, edhrec_rank=7)

        before = self._stamp()
        CanonicalPrintingMetadata.objects.filter(canonical_card=printing).delete()
        after = self._stamp()

        assert before[:4] == after[:4]
        assert before != after

    def test_the_cache_actually_rebuilds_on_an_in_place_backfill_and_serves_the_new_data(self, db, monkeypatch):
        """End-to-end on the cache itself, not just the stamp: build, backfill in place, ask
        again - a SECOND construction happens and the returned index carries the new rank. Without
        the `edhrec_rank` terms this test fails on BOTH assertions (one construction, stale rank),
        which is exactly the stale-index-for-the-worker's-whole-lifetime defect #526 caught."""
        import cardpicker.local_calculate_verdicts as module

        count = self._count_constructions(monkeypatch)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, edhrec_rank=None)

        first = module._get_cached_candidate_name_index()
        assert count[0] == 1
        assert [c.edhrec_rank for c in first.candidates_for("Some Card")] == [None]

        # a second call with NO write in between must NOT rebuild - otherwise "it invalidates"
        # would be indistinguishable from "it never caches".
        module._get_cached_candidate_name_index()
        assert count[0] == 1

        CanonicalPrintingMetadata.objects.filter(canonical_card=printing).update(edhrec_rank=42)

        second = module._get_cached_candidate_name_index()
        assert count[0] == 2
        assert [c.edhrec_rank for c in second.candidates_for("Some Card")] == [42]

    def test_the_cached_index_is_identical_to_a_freshly_built_one(self, db):
        """The cache is a PERFORMANCE change only: a cache hit must answer exactly what a fresh
        build would. Compared over `candidates_for` output for every indexed name, plus the
        de-concatenation fallback, rather than on object identity."""
        import cardpicker.local_calculate_verdicts as module

        first_printing = CanonicalCardFactory(name="Vazal, the Compleat", expansion__code="mom", collector_number="1")
        CanonicalPrintingMetadataFactory(canonical_card=first_printing, edhrec_rank=17)
        CanonicalCardFactory(name="Some Card", expansion__code="won", collector_number="2")

        cached = module._get_cached_candidate_name_index()
        cached_again = module._get_cached_candidate_name_index()
        assert cached_again is cached  # a real cache hit, not a silent rebuild

        fresh = CandidateNameIndex()
        for name in ("Vazal, the Compleat", "Some Card", "VazaltheCompleat", "Nonexistent Card"):
            assert [
                (c.pk, c.expansion_code, c.collector_number, c.edhrec_rank) for c in cached.candidates_for(name)
            ] == [(c.pk, c.expansion_code, c.collector_number, c.edhrec_rank) for c in fresh.candidates_for(name)]


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
    by the pure-function tests in this file; these exercise the ledger/guard WIRING around it.

    None of these tests are exercising the scryfall-cache guard (issue #402, see
    TestScryfallCacheGuard below) - they all pass --allow-missing-scryfall-cache since the test
    environment has no real scryfall_cache/default_cards.json on disk."""

    def test_write_refused_without_a_prior_matching_dry_run(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("local_calculate_verdicts", "--write", "--allow-missing-scryfall-cache")
        assert not PilotRunLedger.objects.filter(command="local_calculate_verdicts").exists()

    def test_write_succeeds_after_a_matching_dry_run(self, db):
        from django.core.management import call_command

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache")  # dry-run (default)
        call_command("local_calculate_verdicts", "--write", "--allow-missing-scryfall-cache")

        ledgers = list(PilotRunLedger.objects.filter(command="local_calculate_verdicts").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True
        assert ledgers[1].dry_run is False
        assert ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, capsys):
        from django.core.management import call_command

        call_command("local_calculate_verdicts", "--write", "--skip-dryrun-check", "--allow-missing-scryfall-cache")

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
        call_command("local_calculate_verdicts", "--write", "--skip-dryrun-check", "--allow-missing-scryfall-cache")

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None


class TestCommandCountersAndDiffReport:
    """The run_id 20260726T165343-3e8301db counters={} incident's two fixes: the completion-time
    per-calculator counters MUST land in the PilotRunLedger row itself (not stdout only), and
    --diff-report MUST produce a reviewable per-card JSONL artifact. Command-level, same
    zero-network fixture shape as TestCommandLedgerHardeningAndDryRunGuard above."""

    def test_dry_run_counters_land_in_the_ledger_row(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache")

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["join_key"] == {
            "considered": 1,
            "would_cast": 1,
            "votes_written": 0,
            "already_voted": 0,
            "skip_counts": {},
        }
        assert ledger.counters["fallback"] == {
            "considered": 0,
            "would_cast": 0,
            "votes_written": 0,
            "already_voted": 0,
            "skip_counts": {},
        }
        assert ledger.counters["slow_path"] == {"considered": 0, "would_cast": 0, "votes_written": 0, "skip_counts": {}}

    def test_write_counters_land_in_the_ledger_row(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("local_calculate_verdicts", "--write", "--skip-dryrun-check", "--allow-missing-scryfall-cache")

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.counters["join_key"]["would_cast"] == 1
        assert ledger.counters["join_key"]["votes_written"] == 1
        # merge_counters preserves the creation-time payload rather than clobbering it.
        assert ledger.counters["skip_dryrun_check_used"] is True

    def test_skip_reasons_land_in_the_counters_skip_counts(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_collector_number="")  # no-text

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache")

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.counters["join_key"]["skip_counts"] == {"no-text": 1}

    def test_diff_report_writes_well_formed_jsonl(self, db, tmp_path):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")
        CardPrintingTag.objects.create(
            card=card, printing=None, is_no_match=True, anonymous_id="another-identity", source=VoteSource.OCR
        )
        report_path = tmp_path / "diff.jsonl"

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache", "--diff-report", str(report_path))

        lines = report_path.read_text().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["card_id"] == card.pk
        assert row["calculator"] == "join-key"
        assert row["would_cast"]["is_no_match"] is False
        assert "detail" in row["would_cast"]
        assert row["existing_votes"] == [{"anonymous_id": "another-identity", "printing_id": None, "is_no_match": True}]

    def test_diff_report_has_no_rows_for_skip_only_cards(self, db, tmp_path):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card, collector_line_collector_number="")  # no-text - a skip, not a would-cast
        report_path = tmp_path / "diff.jsonl"

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache", "--diff-report", str(report_path))

        assert report_path.read_text() == ""


class TestScryfallCacheGuard:
    """Issue #402's fail-loud staleness guard: `ensure_scryfall_cache_present` (unit-level, pure
    file-existence check - see TestGetBackFaceNames above for the sibling soft-fail lookup it's
    deliberately NOT replacing) plus its wiring into `local_calculate_verdicts`'s own
    Command.handle()."""

    def test_raises_when_the_cache_file_is_missing(self, tmp_path):
        missing_path = tmp_path / "does_not_exist.json"

        with pytest.raises(CommandError, match="SCRYFALL CACHE MISSING"):
            ensure_scryfall_cache_present(default_cards_path=missing_path)

    def test_does_not_raise_when_the_cache_file_is_present(self, tmp_path):
        path = _write_bulk_data_file(tmp_path, [])

        ensure_scryfall_cache_present(default_cards_path=path)  # no exception

    def test_command_refuses_to_start_when_the_cache_is_missing(self, db, monkeypatch, tmp_path):
        from django.core.management import call_command

        import cardpicker.printing_metadata_import as printing_metadata_import_module

        monkeypatch.setattr(printing_metadata_import_module, "_cache_path", lambda: tmp_path / "does_not_exist.json")

        with pytest.raises(CommandError, match="SCRYFALL CACHE MISSING"):
            call_command("local_calculate_verdicts")
        assert not PilotRunLedger.objects.filter(command="local_calculate_verdicts").exists()

    def test_command_proceeds_when_the_flag_overrides_a_missing_cache(self, db, monkeypatch, tmp_path):
        from django.core.management import call_command

        import cardpicker.printing_metadata_import as printing_metadata_import_module

        monkeypatch.setattr(printing_metadata_import_module, "_cache_path", lambda: tmp_path / "does_not_exist.json")

        call_command("local_calculate_verdicts", "--allow-missing-scryfall-cache")  # no exception (dry-run)

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.status == PilotRunLedger.Status.COMPLETED

    def test_command_proceeds_when_the_cache_is_actually_present(self, db, monkeypatch, tmp_path):
        from django.core.management import call_command

        import cardpicker.printing_metadata_import as printing_metadata_import_module

        real_path = _write_bulk_data_file(tmp_path, [])
        monkeypatch.setattr(printing_metadata_import_module, "_cache_path", lambda: real_path)

        call_command("local_calculate_verdicts")  # no exception (dry-run), no override flag needed

        ledger = PilotRunLedger.objects.get(command="local_calculate_verdicts")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
