"""
Tests for cardpicker.management.commands.rejudge_fallback_channel (compare-and-retract-on-
change for the stage-d-fallback-v1 channel). No network calls, no live image fetch - see that
module's own docstring for why (it consumes stored ImageEvidence/Card/CanonicalCard rows only,
exactly the same substrate test_local_calculate_verdicts.py's own suite already establishes as
network-free). Uses the real default consensus weights (settings.PRINTING_TAG_MIN_VOTES=2,
PRINTING_TAG_MIN_SHARE=0.6, USER vote weight 1.0, OCR vote weight PRINTING_TAG_MACHINE_WEIGHT=0.5
- confirmed live in vote_consensus._SOURCE_WEIGHTS), same convention test_reparse_collector_
evidence.py already follows, so the resolved-consensus safety-gate test's arithmetic matches what
a real card would actually do in production.
"""

import pytest

from cardpicker.local_calculate_verdicts import (
    FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
    run_fallback_calculator,
)
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.management.commands.rejudge_fallback_channel import (
    rejudge_and_retract,
    select_card_ids_all_channel,
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
    CanonicalPrintingMetadataFactory,
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
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def _join_key_no_hit(card):
    """The join-key no-hit state that GATES fallback eligibility (module docstring) - must exist
    for a card to be in the fallback channel's population at all, and must NEVER be touched by
    the re-judge."""
    return CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")


def _black_white_card(name="Some Card", content_phash=42):
    """A two-printing card whose stored evidence's border reading (`layout_class="black"`)
    narrows the fallback calculator to exactly the black-bordered printing - the fresh verdict
    this fixture always produces is `("vote", <black printing pk>)`."""
    printing_black = CanonicalCardFactory(name=name, expansion__code="mom", collector_number="158")
    CanonicalPrintingMetadataFactory(canonical_card=printing_black, border_color="black")
    printing_white = CanonicalCardFactory(name=name, expansion__code="vow", collector_number="200")
    CanonicalPrintingMetadataFactory(canonical_card=printing_white, border_color="white")
    card = CardFactory(name=name, content_phash=content_phash)
    _evidence(card, layout_class="black")
    return card, printing_black, printing_white


class TestSelectCardIdsAllChannel:
    def test_finds_cards_with_a_fallback_vote_or_a_fallback_scan_row(self, db):
        card_voted = CardFactory(name="Card A", content_phash=1)
        printing = CanonicalCardFactory(name="Card A", expansion__code="mom", collector_number="1")
        CardPrintingTagFactory(
            card=card_voted,
            printing=printing,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )
        card_scanned = CardFactory(name="Card B", content_phash=2)
        CardScanLog.objects.create(
            card=card_scanned, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason="ambiguous"
        )
        card_other_channel = CardFactory(name="Card C", content_phash=3)
        CardScanLog.objects.create(card=card_other_channel, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")

        assert select_card_ids_all_channel() == [card_voted.pk, card_scanned.pk]

    def test_a_card_with_both_a_vote_and_historical_scan_rows_appears_once(self, db):
        card = CardFactory(name="Card D", content_phash=4)
        printing = CanonicalCardFactory(name="Card D", expansion__code="mom", collector_number="1")
        CardPrintingTagFactory(
            card=card, printing=printing, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, source=VoteSource.OCR
        )
        CardScanLog.objects.create(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason="ambiguous")
        CardScanLog.objects.create(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason="eliminated")

        assert select_card_ids_all_channel() == [card.pk]


class TestRejudgeAndRetract:
    def test_changed_vote_retracts_the_stale_vote_and_recomputes_consensus(self, db):
        """The recorded fallback vote names the WHITE printing, but the current stored evidence's
        border reading narrows to the BLACK one - a genuine recorded-vs-fresh change, so the
        stale vote is retracted and the card's consensus recomputed (still UNRESOLVED: no votes
        remain that could clear the human-backed gate)."""
        card, printing_black, printing_white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,  # the STALE vote - fresh evidence says black
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = rejudge_and_retract([card.pk], run_id="rejudge-1", dry_run=False)

        assert result.considered == 1
        assert result.changed == 1
        assert result.retracted == 1
        assert result.gate_refused_card_ids == []
        assert result.transitions == {f"vote:{printing_white.pk} -> vote:{printing_black.pk}": 1}
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()
        assert not CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_retracted_card_becomes_eligible_for_the_fallback_channel_again(self, db):
        """End-to-end proof of the two-step runbook's own claim (module docstring) - once the
        re-judge retracts the stale recorded state, the standard, UNCHANGED
        run_fallback_calculator casts a fresh, correct vote on its very next invocation."""
        card, printing_black, _printing_white = _black_white_card()
        _join_key_no_hit(card)
        # recorded state: an "ambiguous" skip from BEFORE the stored evidence gained its current
        # border reading - the fresh verdict is a real vote, so the skip row is retracted.
        CardScanLog.objects.create(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason="ambiguous", run_id="old-run"
        )

        # RUN-SCOPED ELIGIBILITY (2026-07-29) changed what this precondition means, and the test
        # says so rather than quietly pinning the weaker version. The stale scan-log row no longer
        # excludes the card from a NEW run at all - prior runs do not suppress work - so the
        # exclusion is asserted under the row's OWN run_id, which is where it still holds and
        # which is what makes a killed run resume. The retraction runbook is NOT obsoleted by
        # that: its job was always to remove the stale RECORD (and, in the vote case, to stop a
        # stale row being counted by consensus), and un-suppressing eligibility does neither.
        before = run_fallback_calculator(run_id="old-run", dry_run=False)
        assert before.cards_considered == 0  # excluded: THIS run's own non-rescannable row exists

        result = rejudge_and_retract([card.pk], run_id="rejudge-2", dry_run=False)
        assert result.changed == 1
        assert result.retracted == 1
        assert result.transitions == {f"skip:ambiguous -> vote:{printing_black.pk}": 1}

        after = run_fallback_calculator(run_id="a-fresh-run", dry_run=False)
        assert after.cards_considered == 1
        assert after.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert vote.printing_id == printing_black.pk

    def test_join_key_rows_are_never_deleted(self, db):
        """Fallback eligibility is GATED on the join-key no-hit state existing (module
        docstring) - a retraction must remove ONLY stage-d-fallback-v1 rows, never the join-key
        vote/scan rows that keep the card inside the fallback population."""
        card, printing_black, printing_white = _black_white_card()
        join_key_vote = CardPrintingTagFactory(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = rejudge_and_retract([card.pk], run_id="rejudge-3", dry_run=False)

        assert result.retracted == 1
        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()
        # the join-key is_no_match vote survives completely untouched...
        assert (
            CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).get().pk == join_key_vote.pk
        )
        # ...and the card is straight back in the fallback channel's own eligible population.
        after = run_fallback_calculator(dry_run=False)
        assert after.cards_considered == 1
        assert after.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert vote.printing_id == printing_black.pk

    def test_unchanged_when_the_fresh_verdict_matches_the_recorded_vote(self, db):
        card, printing_black, _printing_white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_black,  # agrees with the current evidence's border reading
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = rejudge_and_retract([card.pk], run_id="rejudge-4", dry_run=False)

        assert result.unchanged == 1
        assert result.changed == 0
        assert result.retracted == 0
        assert result.transitions == {}
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()

    def test_unchanged_when_the_fresh_verdict_repeats_the_recorded_skip(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _evidence(card)  # no layout_class/artist_ocr_name/symbol_phash at all
        _join_key_no_hit(card)
        CardScanLog.objects.create(
            card=card,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            skip_reason=FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
        )

        result = rejudge_and_retract([card.pk], run_id="rejudge-5", dry_run=False)

        assert result.unchanged == 1
        assert result.retracted == 0
        assert CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()

    def test_dry_run_counts_without_writing_anything(self, db):
        card, printing_black, printing_white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        result = rejudge_and_retract([card.pk], run_id="rejudge-6", dry_run=True)

        assert result.considered == 1
        assert result.changed == 1
        assert result.retracted == 0
        assert result.transitions == {f"vote:{printing_white.pk} -> vote:{printing_black.pk}": 1}
        assert result.audit == [
            {
                "card_id": card.pk,
                "recorded": ("vote", printing_white.pk),
                "fresh": ("vote", printing_black.pk),
            }
        ]
        # nothing actually written - the stale vote survives untouched.
        assert CardPrintingTag.objects.filter(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, printing=printing_white
        ).exists()

    def test_resolved_consensus_gate_refuses_retraction_and_lists_for_human_review(self, db):
        """SAFETY GATE (module docstring) - a card whose printing_tag_status is currently
        RESOLVED (via two agreeing human votes here, real default weights: 2x USER weight 1.0 =
        2.0 >= PRINTING_TAG_MIN_VOTES, 100% share >= PRINTING_TAG_MIN_SHARE) must not have its
        stale fallback vote retracted, even though the fresh fallback verdict differs from
        what's recorded - it's listed for human review instead."""
        card, printing_black, printing_white = _black_white_card(name="Resolved Card", content_phash=11)
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,  # the STALE fallback vote - fresh evidence says black
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )
        # two agreeing HUMAN votes for the CORRECT printing - resolves the card independently of
        # the fallback vote above (which doesn't even agree with them).
        CardPrintingTagFactory(card=card, printing=printing_black, anonymous_id="human-1", source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_black, anonymous_id="human-2", source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = rejudge_and_retract([card.pk], run_id="rejudge-7", dry_run=False)

        assert result.changed == 1
        assert result.gate_refused_card_ids == [card.pk]
        assert result.retracted == 0
        # the stale fallback vote survives untouched - gated, not force-retracted.
        assert CardPrintingTag.objects.filter(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, printing=printing_white
        ).exists()
        # the human votes and join-key row are obviously untouched too.
        assert CardPrintingTag.objects.filter(card=card, source=VoteSource.USER).count() == 2
        assert CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

    def test_card_without_current_evidence_is_counted_and_left_alone(self, db):
        """A re-judge without evidence is not a basis for retraction - the recorded rows stay."""
        card = CardFactory(name="Stale Evidence Card", content_phash=99)
        _evidence(card, content_hash=42, layout_class="black")  # stale - card.content_phash is 99
        CardScanLog.objects.create(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason="ambiguous")

        result = rejudge_and_retract([card.pk], run_id="rejudge-8", dry_run=False)

        assert result.considered == 0
        assert result.no_evidence == 1
        assert result.retracted == 0
        assert CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()

    def test_card_with_no_prior_fallback_state_is_not_touched(self, db):
        """Only reachable under an explicit --card-ids-file naming a card outside the channel's
        recorded population - nothing recorded to compare against, so nothing to retract."""
        card, _printing_black, _printing_white = _black_white_card(name="No Prior Card")

        result = rejudge_and_retract([card.pk], run_id="rejudge-9", dry_run=False)

        assert result.considered == 1
        assert result.no_prior_fallback_state == 1
        assert result.changed == 0
        assert result.retracted == 0


class TestRejudgeFallbackChannelCommand:
    def test_requires_exactly_one_of_card_ids_file_or_selector(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("rejudge_fallback_channel")

    def test_card_ids_file_end_to_end_and_counters_persisted_on_completion(self, db, tmp_path):
        from django.core.management import call_command

        card, _printing_black, printing_white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")

        # --skip-dryrun-check: this test exercises the write path in isolation, not the
        # forced-dry-run guard (issue #362) - that guard has its own dedicated test class below.
        call_command(
            "rejudge_fallback_channel",
            card_ids_file=str(ids_file),
            write=True,
            run_id=generate_run_id(),
            skip_dryrun_check=True,
        )

        assert not CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).exists()
        assert CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

        ledger = PilotRunLedger.objects.get(command="rejudge_fallback_channel")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.dry_run is False
        assert ledger.votes_written == 1
        assert ledger.counters["considered"] == 1
        assert ledger.counters["changed"] == 1
        assert ledger.counters["retracted"] == 1
        assert ledger.counters["unchanged"] == 0
        assert ledger.counters["no_evidence"] == 0
        assert ledger.counters["no_prior_fallback_state"] == 0
        assert ledger.counters["gate_refused"] == 0
        assert ledger.counters["gate_refused_card_ids"] == []
        assert ledger.counters["transitions"] == {f"vote:{printing_white.pk} -> vote:{_printing_black.pk}": 1}
        assert ledger.counters["scope"]
        assert ledger.counters["skip_dryrun_check_used"] is True

    def test_all_channel_selector_dry_run_end_to_end(self, db, capsys):
        from django.core.management import call_command

        card, _printing_black, printing_white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=printing_white,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )

        call_command("rejudge_fallback_channel", selector="all-channel")  # dry-run (default)

        # nothing written on a dry-run...
        assert CardPrintingTag.objects.filter(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, printing=printing_white
        ).exists()
        # ...but the ledger row completed with its counters persisted.
        ledger = PilotRunLedger.objects.get(command="rejudge_fallback_channel")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.dry_run is True
        assert ledger.counters["changed"] == 1
        assert ledger.counters["retracted"] == 0
        printed = capsys.readouterr().out
        assert "DRY RUN" in printed
        assert "sample:" in printed


class TestRejudgeFallbackChannelDryRunGuard:
    """Phase 0 rails (issues #362/#153's milestone): the forced-dry-run guard (issue #362),
    wired into rejudge_fallback_channel's own Command.handle() exactly like
    reparse_collector_evidence's."""

    def _ids_file(self, tmp_path):
        card, _black, _white = _black_white_card()
        _join_key_no_hit(card)
        CardPrintingTagFactory(
            card=card,
            printing=_white,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            is_no_match=False,
        )
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")
        return ids_file

    def test_write_refused_without_a_prior_matching_dry_run(self, db, tmp_path):
        from django.core.management import CommandError, call_command

        ids_file = self._ids_file(tmp_path)

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("rejudge_fallback_channel", card_ids_file=str(ids_file), write=True)

        assert PilotRunLedger.objects.filter(command="rejudge_fallback_channel").count() == 0

    def test_write_succeeds_after_a_matching_dry_run(self, db, tmp_path):
        from django.core.management import call_command

        ids_file = self._ids_file(tmp_path)

        call_command("rejudge_fallback_channel", card_ids_file=str(ids_file))  # dry-run (default)
        call_command("rejudge_fallback_channel", card_ids_file=str(ids_file), write=True)

        ledgers = list(PilotRunLedger.objects.filter(command="rejudge_fallback_channel").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_write_refused_when_scope_differs_from_the_dry_run(self, db, tmp_path):
        """A dry-run of one --card-ids-file must never authorize --write for a DIFFERENT one -
        matching docs/features/catalog-completion-plan.md's own "the EXACT same invocation"
        wording."""
        from django.core.management import CommandError, call_command

        ids_file_a = self._ids_file(tmp_path)
        other = tmp_path / "other.txt"
        other.write_text(ids_file_a.read_text())

        call_command("rejudge_fallback_channel", card_ids_file=str(ids_file_a))  # dry-run of A only

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("rejudge_fallback_channel", card_ids_file=str(other), write=True)
