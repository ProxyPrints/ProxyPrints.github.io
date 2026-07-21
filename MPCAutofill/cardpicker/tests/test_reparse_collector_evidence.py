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

import pytest

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.management.commands.reparse_collector_evidence import (
    reparse_and_retract,
    select_card_ids_no_text,
    select_card_ids_parser_bug,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardPrintingTagFactory,
    ImageEvidenceFactory,
    SourceFactory,
)

# see test_local_calculate_verdicts.py's identical fixture for the full rationale -
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
        # nothing actually written
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
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

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

        call_command("reparse_collector_evidence", card_ids_file=str(ids_file), write=True, run_id=generate_run_id())

        assert not CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        evidence = card.image_evidence.get()
        assert evidence.collector_line_set_code == "cmr"
