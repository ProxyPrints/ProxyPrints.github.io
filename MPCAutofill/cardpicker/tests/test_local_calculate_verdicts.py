"""
Tests for cardpicker.local_calculate_verdicts (Stage D, docs/features/catalog-completion-plan.md,
public issue #152) - the join-key calculator, the copyright-year era check, and the slow-path
routing calculator (see that module's own docstring for the full rationale, and for why the rest
of the D1-D6 naming's implied calculators are still deferred). No network calls, no live image
fetch - Stage D consumes stored `ImageEvidence` + `Card`/`CanonicalCard` rows only, so every
fixture here is synthetic DB state (factories), matching `test_local_residual_classify.py`'s own
"host venv, no network" precedent for this pipeline's later stages. `render_set_symbol` IS
exercised for real (it's a pure local font-render, no network) so the symbol-phash tie-break is
tested against REAL keyrune glyph hashes, not a mocked distance.
"""

from datetime import date

import imagehash
import pytest

from cardpicker.local_calculate_verdicts import (
    COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS,
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_CONFIDENCE_BOTH,
    JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY,
    JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
    JOIN_KEY_NO_MATCH_CONFIDENCE,
    SLOW_PATH_ANONYMOUS_ID,
    SLOW_PATH_TO_REVIEW_REASON,
    _symbol_phash_tiebreak,
    _withhold_reason_for_match,
    calculate_join_key_verdict,
    calculate_slow_path_verdict,
    run_join_key_calculator,
    run_slow_path_calculator,
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
    CardFactory,
    ImageEvidenceFactory,
    SourceFactory,
)
from cardpicker.utils import twos_complement

# see test_local_identify_printing_tags.py's identical fixture for the full rationale -
# factory.Sequence counters are process-global across the whole pytest run.
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
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


class TestCopyrightYearEraCheck:
    """Task 2 (Stage D cheap deductions, issue #152): the legal-line copyright year cross-checked
    against the matched candidate's own Scryfall release year - a large gap withholds an
    otherwise-confident join-key match rather than casting it."""

    def test_a_small_gap_is_not_withheld(self, db):
        """Exactly at the threshold: still a plausible gap, not vetoed."""
        card = CardFactory(name="Some Card")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        ]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year=str(2023 - COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS),
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.skip_reason == ""
        assert verdict.confidence == JOIN_KEY_CONFIDENCE_BOTH

    def test_a_large_gap_withholds_the_match(self, db):
        """One year past the threshold: implausible, withheld as a named skip - not cast, and
        not converted into an is_no_match vote either (mirrors the moderator-flag veto's own
        "this reading isn't trustworthy evidence FOR P" framing, not "P is wrong")."""
        card = CardFactory(name="Some Card")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        ]
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
        card = CardFactory(name="Some Card")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        ]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="2030",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.skip_reason == ""

    def test_missing_copyright_year_skips_the_check_entirely(self, db):
        card = CardFactory(name="Some Card")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        ]
        evidence = _evidence(
            card, collector_line_set_code="mom", collector_line_collector_number="158", legal_line_copyright_year=""
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.skip_reason == ""

    def test_missing_released_at_skips_the_check_entirely(self, db):
        """No CanonicalPrintingMetadata sidecar row yet for this candidate - absent data must
        never manufacture a withhold."""
        card = CardFactory(name="Some Card")
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=None)]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1999",
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.printing_pk == 1
        assert verdict.skip_reason == ""

    def test_copyright_year_mismatch_also_withholds_a_symbol_tiebroken_match(self, db):
        card = CardFactory(name="Forest")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21)),
            CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
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

    def test_proxy_marker_veto_takes_precedence_over_copyright_mismatch(self, db):
        """Both conditions can hold on the same card - the existing, already-tested
        proxy-marker-veto outcome wins unchanged (checked first in _withhold_reason_for_match)."""
        card = CardFactory(name="Some Card")
        candidates = [
            CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        ]
        evidence = _evidence(
            card,
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_copyright_year="1990",
            legal_line_proxy_marker_detected=True,
        )

        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        assert verdict.skip_reason == "proxy-marker-veto"


class TestWithholdReasonForMatch:
    def test_returns_none_for_a_clean_match(self, db):
        evidence = _evidence(
            CardFactory(name="Some Card"),
            legal_line_copyright_year="2023",
        )
        candidate = CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        assert _withhold_reason_for_match(evidence, candidate) is None

    def test_a_non_numeric_parsed_year_is_treated_as_no_signal_not_a_veto(self, db):
        """Shouldn't happen in practice (the OCR parser's own year regexes only ever capture
        digit runs) but guarded rather than assumed - a non-numeric value must skip the check,
        never crash or silently veto."""
        evidence = _evidence(CardFactory(name="Some Card"))
        evidence.legal_line_copyright_year = "abcd"
        candidate = CandidatePrinting(pk=1, expansion_code="mom", collector_number="158", released_at=date(2023, 4, 21))
        assert _withhold_reason_for_match(evidence, candidate) is None


class TestCollectorNumberOnlyStaysNameScoped:
    """Task 3 (Stage D cheap deductions, issue #152): hardening/regression test, not new logic -
    the name pre-filter guard already existed (calculate_join_key_verdict only ever receives
    candidates already narrowed to the card's own name), this class pins that invariant so a
    future refactor can't silently regress it into a global cross-set match."""

    def test_never_crosses_into_a_different_names_candidates(self, db):
        """Two DIFFERENT card names sharing the SAME collector number in DIFFERENT sets - a real,
        name-scoped CandidateNameIndex must resolve each name's own card only within its own
        candidates, never reaching into the other name's candidate sharing that same number."""
        forest_printing = CanonicalCardFactory(name="Forest", expansion__code="mom", collector_number="100")
        CanonicalCardFactory(name="Island", expansion__code="war", collector_number="100")

        index = CandidateNameIndex()
        forest_candidates = index.candidates_for("Forest")
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
    and module docstring item 1)."""

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
