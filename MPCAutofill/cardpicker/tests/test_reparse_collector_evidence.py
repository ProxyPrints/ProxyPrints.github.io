"""
Tests for cardpicker.management.commands.reparse_collector_evidence (issue #259 follow-up,
"Stage D no-text bucket: OCR preprocessing/crop recovery" - the supersede/re-vote tooling). No
network calls, no live image fetch - see that module's own docstring for why (it consumes
stored ImageEvidence/Card/CanonicalCard rows only, exactly the same substrate
test_local_calculate_verdicts.py's own suite already establishes as network-free). Uses the real
default consensus weights (settings.PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MIN_SHARE=0.6, USER
vote weight 1.0, OCR vote weight PRINTING_TAG_MACHINE_WEIGHT=0.5 - confirmed live in
vote_consensus._SOURCE_WEIGHTS), same convention test_purge_machine_votes.py already follows,
so the resolved-consensus safety-gate test's arithmetic matches what a real card would actually
do in production.
"""

from typing import Any

import pytest

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.management.commands.reparse_collector_evidence import (
    reparse_and_retract,
    select_card_ids_no_text,
    select_card_ids_parser_bug,
    select_card_ids_proxy_marker_veto,
    select_card_ids_set_code_lexicon_gate,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PilotRunLedger,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardPrintingTagFactory,
    ImageEvidenceFactory,
)


def _evidence(card, **overrides):
    """Same shape as test_local_calculate_verdicts.py's own `_evidence` helper - deliberately
    duplicated (not imported cross-module), matching this test suite's own per-module small-
    helper convention."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestSelectCardIdsParserBug:
    def test_finds_cards_whose_stored_set_code_matches_the_old_bug_shape(self, db):
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)
        _evidence(card_a, collector_line_set_code="361r", collector_line_collector_number="158")
        _evidence(card_b, collector_line_set_code="mom", collector_line_collector_number="12")

        assert select_card_ids_parser_bug() == [card_a.pk]

    def test_ignores_blank_set_code(self, db):
        card = CardFactory(name="Card C", content_phash=3)
        _evidence(card, collector_line_set_code="", collector_line_collector_number="")

        assert select_card_ids_parser_bug() == []

    def test_a_real_multi_char_set_code_is_not_mistaken_for_the_bug_shape(self, db):
        # a genuine digit-led set code (e.g. "40k" for Warhammer 40k Universes Beyond, per
        # local_ocr.py's own _DENOMINATOR_RARITY_TOKEN_RE comment) must not be selected just for
        # looking similar - the actual #260 bug shape requires the token to have been the FIRST
        # token found by the OLD (buggy) parser, which is a positional fact this selector can't
        # recover from the stored value alone; deliberately conservative in the OTHER direction
        # instead (a genuine "40k"-shaped code IS still 2-3 digits + a letter, so it WOULD match
        # this regex too - documented here as a known, accepted false-candidate: reparse_and_
        # retract's own "unchanged" outcome is what protects against actually retracting
        # anything for a card whose parse didn't really change).
        card = CardFactory(name="Card D", content_phash=4)
        _evidence(card, collector_line_set_code="40k", collector_line_collector_number="7")

        assert select_card_ids_parser_bug() == [card.pk]


class TestSelectCardIdsNoText:
    def test_finds_cards_from_exactly_the_given_run_id(self, db):
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)
        CardScanLog.objects.create(
            card=card_a, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text", run_id="run-1"
        )
        CardScanLog.objects.create(
            card=card_b, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text", run_id="run-2"
        )

        assert select_card_ids_no_text("run-1") == [card_a.pk]

    def test_ignores_a_different_skip_reason(self, db):
        card = CardFactory(name="Card E", content_phash=5)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous", run_id="run-1"
        )

        assert select_card_ids_no_text("run-1") == []


class TestSelectCardIdsProxyMarkerVeto:
    """2026-07-21, moderator-flag-signal correction - mirrors TestSelectCardIdsNoText exactly,
    structurally, just against the "proxy-marker-veto" skip_reason instead."""

    def test_finds_cards_from_exactly_the_given_run_id(self, db):
        card_a = CardFactory(name="Card F", content_phash=6)
        card_b = CardFactory(name="Card G", content_phash=7)
        CardScanLog.objects.create(
            card=card_a, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto", run_id="run-1"
        )
        CardScanLog.objects.create(
            card=card_b, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto", run_id="run-2"
        )

        assert select_card_ids_proxy_marker_veto("run-1") == [card_a.pk]

    def test_ignores_a_different_skip_reason(self, db):
        card = CardFactory(name="Card H", content_phash=8)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text", run_id="run-1")

        assert select_card_ids_proxy_marker_veto("run-1") == []


class TestSelectCardIdsSetCodeLexiconGate:
    """2026-07-23, module docstring's SET-CODE LEXICON GATE - unlike the two selectors above,
    this one targets CardPrintingTag VOTES (is_no_match=True), not a CardScanLog skip row,
    since the pre-fix behavior cast a real vote, not a skip."""

    def test_finds_cards_from_exactly_the_given_run_id(self, db):
        card_a = CardFactory(name="Card I", content_phash=9)
        card_b = CardFactory(name="Card J", content_phash=10)
        CardPrintingTagFactory(
            card=card_a,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="run-1",
        )
        CardPrintingTagFactory(
            card=card_b,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="run-2",
        )

        assert select_card_ids_set_code_lexicon_gate("run-1") == [card_a.pk]

    def test_ignores_a_real_match_vote(self, db):
        card = CardFactory(name="Card K", content_phash=11)
        printing = CanonicalCardFactory(name="Card K", expansion__code="mom", collector_number="1")
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="run-1",
        )

        assert select_card_ids_set_code_lexicon_gate("run-1") == []


class TestReparseAndRetract:
    def test_dry_run_counts_without_writing_anything(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",  # the OLD #260-bug misparse
            collector_line_collector_number="158",
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="parsed-but-no-match", run_id="old-run"
        )

        result = reparse_and_retract([card.pk], run_id="reparse-1", dry_run=True)

        assert result.considered == 1
        assert result.changed == 1
        assert result.retracted == 0
        assert result.fields_fixed == 1  # counted...
        # ...but nothing actually written
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "361r"
        assert CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert printing.pk  # keeps the printing reference alive/used, avoids an unused warning

    def test_write_fixes_the_parser_bug_cohort_and_retracts_the_stale_scan_log(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",
            collector_line_collector_number="158",
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="parsed-but-no-match", run_id="old-run"
        )

        result = reparse_and_retract([card.pk], run_id="reparse-1", dry_run=False)

        assert result.changed == 1
        assert result.retracted == 1
        assert result.fields_fixed == 1
        assert result.gate_refused_card_ids == []

        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"  # the FIXED parser's own correct read
        assert evidence.collector_line_collector_number == "158"
        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert printing.pk

    def test_card_becomes_eligible_again_for_local_calculate_verdicts_after_retraction(self, db):
        """End-to-end proof of the two-step runbook's own claim (this command's module
        docstring) - once step 1 retracts the stale scan-log, the standard, UNCHANGED
        local_calculate_verdicts run (step 2) casts a fresh, correct vote on its very next
        invocation."""
        from cardpicker.local_calculate_verdicts import run_join_key_calculator

        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",
            collector_line_collector_number="158",
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="parsed-but-no-match", run_id="old-run"
        )

        # before retraction: local_calculate_verdicts' own eligibility query excludes this card
        # (a non-rescannable scan-log row already exists for it).
        before = run_join_key_calculator(dry_run=False)
        assert before.cards_considered == 0
        assert CardPrintingTag.objects.filter(card=card).count() == 0

        reparse_and_retract([card.pk], run_id="reparse-1", dry_run=False)

        after = run_join_key_calculator(dry_run=False)
        assert after.cards_considered == 1
        assert after.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk

    def test_no_text_selector_recovers_once_evidence_reflects_a_completed_reextraction(self, db):
        """The load-bearing case this command's own design pivot exists for (see its module
        docstring's "WHY COMPARE AGAINST THE RECORDED VERDICT" section): a card's ImageEvidence
        already carries a FRESH, correct parse (simulating a completed
        run_image_evidence_cohort --card-ids-file re-extraction) - the STALE "no-text" scan-log
        from BEFORE that re-extraction is what still needs retracting, even though re-parsing
        the (already-current) raw text changes no ImageEvidence field at all."""
        card = CardFactory(name="Other Card", content_phash=7)
        printing = CanonicalCardFactory(name="Other Card", expansion__code="mom", collector_number="12")
        _evidence(
            card,
            collector_line_raw_text="12/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="12",
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text", run_id="stage-d-run-1"
        )

        card_ids = select_card_ids_no_text("stage-d-run-1")
        assert card_ids == [card.pk]

        result = reparse_and_retract(card_ids, run_id="reparse-2", dry_run=False)

        assert result.changed == 1
        assert result.retracted == 1
        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert printing.pk

    def test_proxy_marker_veto_selector_dry_run_counts_without_writing_anything(self, db):
        """Mirrors test_dry_run_counts_without_writing_anything above (which only exercises the
        parser-bug fixture) - dry_run's own generic gate in reparse_and_retract applies uniformly
        across every selector, but this selector's own cohort deserves its own explicit dry-run
        assertion rather than relying on that genericness alone."""
        card = CardFactory(name="Marked Card Dry Run", content_phash=11)
        printing = CanonicalCardFactory(name="Marked Card Dry Run", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto", run_id="stage-d-run-dry"
        )

        card_ids = select_card_ids_proxy_marker_veto("stage-d-run-dry")
        assert card_ids == [card.pk]

        result = reparse_and_retract(card_ids, run_id="reparse-dry", dry_run=True)

        assert result.considered == 1
        assert result.changed == 1
        assert result.retracted == 0
        # nothing actually written - the stale skip row and its evidence both survive untouched
        assert CardScanLog.objects.filter(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto"
        ).exists()
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert printing.pk

    def test_proxy_marker_veto_selector_recovers_immediately_no_reextraction_needed(self, db):
        """2026-07-21, moderator-flag-signal correction: unlike the no-text case above, this
        selector needs NO simulated re-extraction step - the stored ImageEvidence never changes
        at all (`legal_line_proxy_marker_detected=True` throughout); it's the CODE fix in
        `local_calculate_verdicts._apply_agreement_checks` alone that makes the fresh verdict
        differ from the stale recorded skip, immediately, on this command's very first pass
        against a stale proxy-marker-veto row."""
        card = CardFactory(name="Marked Card", content_phash=9)
        printing = CanonicalCardFactory(name="Marked Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto", run_id="stage-d-run-x"
        )

        card_ids = select_card_ids_proxy_marker_veto("stage-d-run-x")
        assert card_ids == [card.pk]

        result = reparse_and_retract(card_ids, run_id="reparse-3", dry_run=False)

        assert result.changed == 1
        assert result.retracted == 1
        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        # unchanged by this command (it never re-votes, only retracts) - still True, confirming
        # the stored evidence itself never had to change for the retraction to be correct.
        assert card.image_evidence.get().legal_line_proxy_marker_detected is True
        assert printing.pk

    def test_proxy_marker_veto_selector_end_to_end_recasts_the_real_vote(self, db):
        """Full two-step runbook proof (mirrors test_card_becomes_eligible_again_for_local_
        calculate_verdicts_after_retraction above): once this selector retracts the stale
        proxy-marker-veto skip, the standard, UNCHANGED local_calculate_verdicts run casts the
        real match the corrected code now allows, with the marker still present throughout."""
        from cardpicker.local_calculate_verdicts import run_join_key_calculator

        card = CardFactory(name="Marked Card Two", content_phash=10)
        printing = CanonicalCardFactory(name="Marked Card Two", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
            legal_line_proxy_marker_detected=True,
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="proxy-marker-veto", run_id="stage-d-run-y"
        )

        before = run_join_key_calculator(dry_run=False)
        assert before.cards_considered == 0  # excluded: a non-rescannable scan-log row exists

        reparse_and_retract(select_card_ids_proxy_marker_veto("stage-d-run-y"), run_id="reparse-4", dry_run=False)

        after = run_join_key_calculator(dry_run=False)
        assert after.cards_considered == 1
        assert after.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk

    def test_set_code_lexicon_gate_selector_retracts_a_lexicon_invalid_no_match_vote(self, db):
        """2026-07-23 - the FULL cohort selector deliberately over-selects (module docstring's
        own reasoning on select_card_ids_set_code_lexicon_gate), but reparse_and_retract's own
        comparison only actually retracts the lexicon-invalid subset - proven here end to end,
        not just via the pure calculate_join_key_verdict unit tests."""
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="——— SRe © < iE 2 e Sew «",
            collector_line_set_code="sew",  # not a real CanonicalExpansion code
            collector_line_collector_number="2",
        )
        CardPrintingTagFactory(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="stage-d-run-z",
        )

        card_ids = select_card_ids_set_code_lexicon_gate("stage-d-run-z")
        assert card_ids == [card.pk]

        result = reparse_and_retract(card_ids, run_id="reparse-5", dry_run=False)

        assert result.changed == 1
        assert result.retracted == 1
        # reparse_and_retract only ever DELETES the stale vote (step 1 of the two-step runbook -
        # module docstring) - it never writes the fresh verdict itself, that's step 2's job (the
        # next local_calculate_verdicts run, proven end to end just below).
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

    def test_set_code_lexicon_gate_selector_end_to_end_recasts_the_fresh_abstention(self, db):
        """Full two-step runbook proof (mirrors test_proxy_marker_veto_selector_end_to_end_
        recasts_the_real_vote's own convention) - once this selector retracts the stale
        is_no_match vote, the standard, UNCHANGED local_calculate_verdicts run writes the fresh
        "unknown-set-code" scan-log row the corrected code now produces."""
        from cardpicker.local_calculate_verdicts import run_join_key_calculator

        card = CardFactory(name="Some Card", content_phash=44)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="aN 6 ree MRA Alin tO AAS OL ARON pt perl",
            collector_line_set_code="ree",
            collector_line_collector_number="6",
        )
        CardPrintingTagFactory(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="stage-d-run-z3",
        )

        before = run_join_key_calculator(dry_run=False)
        assert before.cards_considered == 0  # excluded: an is_no_match vote already exists

        reparse_and_retract(select_card_ids_set_code_lexicon_gate("stage-d-run-z3"), run_id="reparse-7", dry_run=False)

        after = run_join_key_calculator(dry_run=False)
        assert after.cards_considered == 1
        assert after.skip_counts.get("unknown-set-code") == 1
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert scan_log.skip_reason == "unknown-set-code"

    def test_set_code_lexicon_gate_selector_leaves_a_genuinely_in_lexicon_no_match_vote_unchanged(self, db):
        """The over-selection's own safety net (module docstring) - a real, in-lexicon set code
        that simply doesn't match this card's own candidates is left as the same genuine
        no-match vote it already was, not retracted."""
        card = CardFactory(name="Some Card", content_phash=43)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalExpansionFactory(code="isd")
        _evidence(
            card,
            collector_line_raw_text="2/280 R ISD EN",
            collector_line_set_code="isd",  # a REAL set code, just not this card's own candidate
            collector_line_collector_number="2",
        )
        CardPrintingTagFactory(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id="stage-d-run-z2",
        )

        card_ids = select_card_ids_set_code_lexicon_gate("stage-d-run-z2")
        result = reparse_and_retract(card_ids, run_id="reparse-6", dry_run=False)

        assert result.unchanged == 1
        assert result.retracted == 0
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.is_no_match is True

    def test_unchanged_when_fresh_verdict_matches_the_recorded_vote(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = reparse_and_retract([card.pk], run_id="reparse-3", dry_run=False)

        assert result.unchanged == 1
        assert result.changed == 0
        assert result.retracted == 0
        assert result.fields_fixed == 0  # stored fields already matched the fresh re-parse here
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

    def test_unchanged_branch_still_gets_its_stale_fields_persisted_under_write(self, db):
        """The bug this PR fixes: a card whose join-key CONCLUSION is unchanged (the recorded
        vote's own printing matches what a fresh re-parse would also match) used to keep a
        STALE collector_line_set_code/collector_line_collector_number forever, because the old
        code only ever called evidence.save() inside the verdict-CHANGED branch. The recorded
        vote here is constructed directly (independent of ImageEvidence's own stored fields, per
        _recorded_join_key_state's own contract) so the verdict genuinely lands in the
        `unchanged` branch even though the stored fields are objectively stale."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",  # reparses to set_code="cmr", number="158"
            collector_line_set_code="xxx",  # deliberately stale/wrong - differs from the fresh parse
            collector_line_collector_number="000",
        )
        # the recorded vote already agrees with what the FRESH parse will conclude (same printing,
        # not a no-match) - so the verdict comparison itself lands in `unchanged`, independent of
        # what ImageEvidence's own (stale) fields say.
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = reparse_and_retract([card.pk], run_id="reparse-unchanged-write", dry_run=False)

        assert result.unchanged == 1
        assert result.changed == 0
        assert result.retracted == 0
        assert result.fields_fixed == 1
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"
        assert evidence.collector_line_collector_number == "158"
        # the vote itself is completely untouched - this is a field-persistence fix only.
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk

    def test_unchanged_branch_dry_run_only_counts_the_field_fix_without_writing(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="xxx",
            collector_line_collector_number="000",
        )
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = reparse_and_retract([card.pk], run_id="reparse-unchanged-dry", dry_run=True)

        assert result.unchanged == 1
        assert result.fields_fixed == 1
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "xxx"  # nothing actually written
        assert evidence.collector_line_collector_number == "000"

    def test_card_with_no_prior_join_key_state_is_not_touched(self, db):
        card = CardFactory(name="Untouched Card", content_phash=9)
        CanonicalCardFactory(name="Untouched Card", expansion__code="mom", collector_number="1")
        _evidence(
            card,
            collector_line_raw_text="1/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="1",
        )

        result = reparse_and_retract([card.pk], run_id="reparse-4", dry_run=False)

        assert result.considered == 1
        assert result.no_prior_join_key_state == 1
        assert result.changed == 0
        assert result.retracted == 0
        assert result.fields_fixed == 0  # stored fields already matched the fresh re-parse here

    def test_no_prior_join_key_state_branch_still_gets_stale_fields_persisted_under_write(self, db):
        """Same fix, the OTHER previously-unreached branch (module docstring): a card with no
        recorded join-key vote/scan-log row at all also used to keep a stale stored parse
        forever - only a genuine verdict CHANGE ever triggered the save before this fix."""
        card = CardFactory(name="No Prior State Card", content_phash=42)
        CanonicalCardFactory(name="No Prior State Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="xxx",
            collector_line_collector_number="000",
        )

        result = reparse_and_retract([card.pk], run_id="reparse-no-prior-write", dry_run=False)

        assert result.no_prior_join_key_state == 1
        assert result.changed == 0
        assert result.retracted == 0
        assert result.fields_fixed == 1
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"
        assert evidence.collector_line_collector_number == "158"

    def test_card_without_current_evidence_is_counted_and_skipped(self, db):
        card = CardFactory(name="No Evidence Card", content_phash=None)

        result = reparse_and_retract([card.pk], run_id="reparse-5", dry_run=False)

        assert result.considered == 0
        assert result.no_evidence == 1

    def test_resolved_consensus_gate_refuses_retraction_and_lists_for_human_review(self, db):
        """SAFETY GATE (module docstring) - a card whose printing_tag_status is currently
        RESOLVED (via two agreeing human votes here, real default weights: 2x USER weight 1.0 =
        2.0 >= PRINTING_TAG_MIN_VOTES, 100% share >= PRINTING_TAG_MIN_SHARE) must not have its
        stale join-key vote/scan-log retracted, even though the fresh join-key verdict differs
        from what's recorded - it's listed for human review instead."""
        card = CardFactory(name="Resolved Card", content_phash=11)
        printing = CanonicalCardFactory(name="Resolved Card", expansion__code="cmr", collector_number="158")
        other_printing = CanonicalCardFactory(name="Resolved Card", expansion__code="znr", collector_number="99")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",  # stale, pre-#260-fix misparse
            collector_line_collector_number="158",
        )
        # the join-key calculator's own stale vote, cast against the WRONG printing under the
        # old bug (this is the vote this command's fresh recompute will disagree with).
        CardPrintingTagFactory(
            card=card,
            printing=other_printing,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )
        # two agreeing HUMAN votes for the CORRECT printing - resolves the card independently of
        # the join-key vote above (which doesn't even agree with them).
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id="human-1", source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id="human-2", source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = reparse_and_retract([card.pk], run_id="reparse-6", dry_run=False)

        assert result.changed == 1
        assert result.gate_refused_card_ids == [card.pk]
        assert result.retracted == 0
        # the stale join-key vote survives untouched - gated, not force-retracted.
        assert CardPrintingTag.objects.filter(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, printing=other_printing
        ).exists()
        # the human votes are obviously untouched too.
        assert CardPrintingTag.objects.filter(card=card, source=VoteSource.USER).count() == 2
        # the ImageEvidence parsed-field update still happens for a gated card (harmless - not
        # vote/consensus state).
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"

    def test_no_match_resolved_consensus_also_gates_retraction(self, db):
        """resolve_printing returns the NO_MATCH sentinel (not None) for a resolved no-match
        consensus - verified against that function's own source, not assumed (module docstring)
        - so this gate must cover that case too, not just a resolved printing."""
        card = CardFactory(name="No Match Card", content_phash=13)
        CanonicalCardFactory(name="No Match Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",
            collector_line_collector_number="158",
        )
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
        )
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, anonymous_id="human-1", source=VoteSource.USER
        )
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, anonymous_id="human-2", source=VoteSource.USER
        )
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.NO_MATCH

        result = reparse_and_retract([card.pk], run_id="reparse-7", dry_run=False)

        assert result.gate_refused_card_ids == [card.pk]
        assert result.retracted == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()


class TestReparseCollectorEvidenceCommand:
    def test_requires_exactly_one_selector(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("reparse_collector_evidence")

    def test_no_text_selector_requires_stage_d_run_id(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("reparse_collector_evidence", selector="no-text")

    def test_proxy_marker_veto_selector_requires_stage_d_run_id(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("reparse_collector_evidence", selector="proxy-marker-veto")

    def test_set_code_lexicon_gate_selector_requires_stage_d_run_id(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("reparse_collector_evidence", selector="set-code-lexicon-gate")

    def test_card_ids_file_selector_end_to_end(self, db, tmp_path):
        from django.core.management import call_command

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="cmr", collector_number="158")
        _evidence(
            card,
            collector_line_raw_text="158/361R\nCMR EN",
            collector_line_set_code="361r",
            collector_line_collector_number="158",
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="parsed-but-no-match", run_id="old-run"
        )
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")

        # --skip-dryrun-check: this test exercises the write path in isolation, not the
        # forced-dry-run guard (issue #362) - that guard has its own dedicated test class below.
        call_command(
            "reparse_collector_evidence",
            card_ids_file=str(ids_file),
            write=True,
            run_id=generate_run_id(),
            skip_dryrun_check=True,
        )

        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"


def _card_and_ids_file(tmp_path, filename="ids.txt", name="Some Card", expansion_code="cmr"):
    card = CardFactory(name=name, content_phash=42)
    CanonicalCardFactory(name=name, expansion__code=expansion_code, collector_number="158")
    _evidence(
        card,
        collector_line_raw_text=f"158/361R\n{expansion_code.upper()} EN",
        collector_line_set_code="361r",
        collector_line_collector_number="158",
    )
    ids_file = tmp_path / filename
    ids_file.write_text(f"{card.pk}\n")
    return card, ids_file


class TestReparseCollectorEvidenceDryRunGuard:
    """Phase 0 rails (issues #362/#153's milestone): the forced-dry-run guard (issue #362) and
    the counters-before-output hardening (production incident 2026-07-23), both wired into
    reparse_collector_evidence's own Command.handle()."""

    def test_write_refused_without_a_prior_matching_dry_run(self, db, tmp_path):
        from django.core.management import CommandError, call_command

        _card, ids_file = _card_and_ids_file(tmp_path)

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("reparse_collector_evidence", card_ids_file=str(ids_file), write=True)

    def test_write_succeeds_after_a_matching_dry_run(self, db, tmp_path):
        from django.core.management import call_command

        _card, ids_file = _card_and_ids_file(tmp_path)

        call_command("reparse_collector_evidence", card_ids_file=str(ids_file))  # dry-run (default)
        call_command("reparse_collector_evidence", card_ids_file=str(ids_file), write=True)

        ledgers = list(PilotRunLedger.objects.filter(command="reparse_collector_evidence").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_write_refused_when_scope_differs_from_the_dry_run(self, db, tmp_path):
        """A dry-run of one --card-ids-file must never authorize --write for a DIFFERENT one -
        matching docs/features/catalog-completion-plan.md's own "the EXACT same invocation"
        wording."""
        from django.core.management import CommandError, call_command

        _card_a, ids_file_a = _card_and_ids_file(tmp_path, filename="a.txt", name="Card A", expansion_code="aaa")
        _card_b, ids_file_b = _card_and_ids_file(tmp_path, filename="b.txt", name="Card B", expansion_code="bbb")

        call_command("reparse_collector_evidence", card_ids_file=str(ids_file_a))  # dry-run of A only

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("reparse_collector_evidence", card_ids_file=str(ids_file_b), write=True)

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, tmp_path, capsys):
        from django.core.management import call_command

        _card, ids_file = _card_and_ids_file(tmp_path)

        call_command("reparse_collector_evidence", card_ids_file=str(ids_file), write=True, skip_dryrun_check=True)

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        ledger = PilotRunLedger.objects.get(command="reparse_collector_evidence")
        assert ledger.counters["skip_dryrun_check_used"] is True

    def test_broken_pipe_during_terminal_summary_does_not_flip_completed_to_failed(self, db, tmp_path, monkeypatch):
        """Production incident 2026-07-23: a client-side timeout severed stdout AFTER every write
        had already committed and the ledger row had already been saved COMPLETED - the terminal
        summary prints (self.stdout.write) must never be able to flip that back to FAILED."""
        from django.core.management import call_command
        from django.core.management.base import OutputWrapper

        _card, ids_file = _card_and_ids_file(tmp_path)

        real_write = OutputWrapper.write

        def raising_write(self: OutputWrapper, msg: str = "", *args: Any, **kwargs: Any) -> None:
            if isinstance(msg, str) and msg.startswith("considered="):
                raise BrokenPipeError("stdout severed")
            return real_write(self, msg, *args, **kwargs)

        monkeypatch.setattr(OutputWrapper, "write", raising_write, raising=False)

        call_command("reparse_collector_evidence", card_ids_file=str(ids_file), write=True, skip_dryrun_check=True)

        ledger = PilotRunLedger.objects.get(command="reparse_collector_evidence")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
