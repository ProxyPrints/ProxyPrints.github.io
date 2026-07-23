"""
Tests for cardpicker.management.commands.retract_stage_d_by_run_id (pre-pilot zeroing plan).
Uses the real default consensus weights (settings.PRINTING_TAG_MIN_VOTES=2,
PRINTING_TAG_MIN_SHARE=0.6, USER vote weight 1.0, OCR vote weight
PRINTING_TAG_MACHINE_WEIGHT=0.5 - confirmed live in vote_consensus._SOURCE_WEIGHTS), same
convention test_purge_machine_votes.py/test_reparse_collector_evidence.py already follow, so the
resolved-consensus safety-gate test's arithmetic matches what a real card would actually do in
production.
"""

from unittest.mock import patch

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands.retract_stage_d_by_run_id import (
    retract_run_id,
    retract_run_ids,
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
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
)

# see test_reparse_collector_evidence.py's identical fixture for the full rationale -
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


class TestRetractRunId:
    def test_dry_run_counts_without_deleting_anything(self, db):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="ambiguous"
        )

        result = retract_run_id("target-run", write=False)

        assert result.votes_deleted == 1
        assert result.skips_deleted == 1
        assert result.cards_resynced == 0
        assert CardPrintingTag.objects.filter(run_id="target-run").count() == 1
        assert CardScanLog.objects.filter(run_id="target-run").count() == 1

    def test_write_deletes_exactly_the_scoped_vote_and_non_rescannable_skip_rows(self, db):
        card = CardFactory(name="Forest")
        other_card = CardFactory(name="Island")

        # in scope: JOIN_KEY_ANONYMOUS_ID + target-run, a vote and a non-rescannable skip.
        CardPrintingTagFactory(
            card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="ambiguous"
        )
        # NOT in scope: rescannable skip reason - left alone entirely, counted separately.
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="no-evidence"
        )
        # NOT in scope: same anonymous_id, a DIFFERENT run_id.
        CardPrintingTagFactory(
            card=other_card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="other-run"
        )
        # NOT in scope: same run_id, a DIFFERENT anonymous_id (a different engine's own vote).
        CardPrintingTagFactory(
            card=card, source=VoteSource.OCR, anonymous_id="stage-d-fallback-v1", run_id="target-run"
        )
        # NOT in scope: a human vote, no run_id at all.
        CardPrintingTagFactory(card=card, source=VoteSource.USER, anonymous_id="human-1")

        result = retract_run_id("target-run", write=True)

        assert result.votes_deleted == 1
        assert result.skips_deleted == 1
        assert result.skipped_rescannable == 1
        assert result.cards_resynced == 1
        assert result.skipped_resolved_gate == 0

        assert not CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run").exists()
        assert not CardScanLog.objects.filter(
            anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="ambiguous"
        ).exists()
        # survivors, all of them:
        assert CardScanLog.objects.filter(
            anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="no-evidence"
        ).exists()
        assert CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="other-run").exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="stage-d-fallback-v1").exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="human-1", source=VoteSource.USER).exists()

    def test_resolved_consensus_gate_skips_the_card_entirely(self, db):
        printing = CanonicalCardFactory(name="Resolved Card", expansion__code="cmr", collector_number="158")
        other_printing = CanonicalCardFactory(name="Resolved Card", expansion__code="znr", collector_number="99")
        card = CardFactory(name="Resolved Card")
        CardPrintingTagFactory(
            card=card,
            printing=other_printing,
            source=VoteSource.OCR,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            run_id="target-run",
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-2")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = retract_run_id("target-run", write=True)

        assert result.votes_deleted == 0
        assert result.skips_deleted == 0
        assert result.cards_resynced == 0
        assert result.skipped_resolved_gate == 1
        assert result.skipped_resolved_gate_card_ids == [card.pk]
        # the stale machine vote survives untouched - gated, not force-retracted.
        assert CardPrintingTag.objects.filter(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, printing=other_printing
        ).exists()

    def test_no_match_resolved_consensus_also_gates_retraction(self, db):
        card = CardFactory(name="No Match Card")
        CardPrintingTagFactory(
            card=card,
            printing=None,
            is_no_match=True,
            source=VoteSource.OCR,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            run_id="target-run",
        )
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, source=VoteSource.USER, anonymous_id="human-1"
        )
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, source=VoteSource.USER, anonymous_id="human-2"
        )
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.NO_MATCH

        result = retract_run_id("target-run", write=True)

        assert result.skipped_resolved_gate == 1
        assert result.votes_deleted == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

    def test_dry_run_gate_check_is_also_reported_without_deleting(self, db):
        """The gate is checked (and reported) identically in dry-run mode - a dry run's own
        report already reflects exactly what a real run would refuse, per this command's own
        docstring."""
        printing = CanonicalCardFactory(name="Resolved Card", expansion__code="cmr", collector_number="158")
        card = CardFactory(name="Resolved Card")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-2")
        resolve_and_persist_printing(card)

        result = retract_run_id("target-run", write=False)

        assert result.skipped_resolved_gate == 1
        assert result.votes_deleted == 0
        assert CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run").exists()

    def test_idempotent_rerun_after_a_prior_write_produces_zero_further_change(self, db):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )

        first = retract_run_id("target-run", write=True)
        assert first.votes_deleted == 1
        assert first.cards_resynced == 1

        second = retract_run_id("target-run", write=True)
        assert second.votes_deleted == 0
        assert second.cards_resynced == 0
        assert second.skipped_resolved_gate == 0

    def test_resolve_and_persist_printing_called_once_per_affected_card_under_write(self, db):
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Island")
        CardPrintingTagFactory(
            card=card_a, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )
        CardScanLog.objects.create(
            card=card_b, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run", skip_reason="ambiguous"
        )

        with patch(
            "cardpicker.management.commands.retract_stage_d_by_run_id.resolve_and_persist_printing"
        ) as mock_resolve:
            result = retract_run_id("target-run", write=True)

        assert result.cards_resynced == 2
        assert mock_resolve.call_count == 2
        called_card_ids = sorted(call.args[0].pk for call in mock_resolve.call_args_list)
        assert called_card_ids == sorted([card_a.pk, card_b.pk])

    def test_resolve_and_persist_printing_never_called_in_dry_run(self, db):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="target-run"
        )

        with patch(
            "cardpicker.management.commands.retract_stage_d_by_run_id.resolve_and_persist_printing"
        ) as mock_resolve:
            retract_run_id("target-run", write=False)

        mock_resolve.assert_not_called()


class TestRetractRunIds:
    def test_runs_each_target_run_id_independently_and_reports_all(self, db):
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Island")
        CardPrintingTagFactory(card=card_a, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-1")
        CardPrintingTagFactory(card=card_b, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-2")

        results = retract_run_ids(["run-1", "run-2"], write=True)

        assert set(results.keys()) == {"run-1", "run-2"}
        assert results["run-1"].votes_deleted == 1
        assert results["run-2"].votes_deleted == 1
        assert not CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()


class TestRetractStageDByRunIdCommand:
    def test_requires_at_least_one_run_id(self, db):
        with pytest.raises(CommandError):
            call_command("retract_stage_d_by_run_id")

    def test_dry_run_prints_counts_and_deletes_nothing(self, db, capsys):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-A")

        call_command("retract_stage_d_by_run_id", "--run-id=run-A")

        printed = capsys.readouterr().out
        assert "[DRY RUN]" in printed
        assert "votes_deleted=1" in printed
        assert "Dry run - nothing deleted" in printed
        assert CardPrintingTag.objects.filter(run_id="run-A").exists()

    def test_write_deletes_and_writes_ledger_counters(self, db, capsys):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-A")
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-A", skip_reason="no-evidence"
        )

        call_command("retract_stage_d_by_run_id", "--run-id=run-A", "--write")

        printed = capsys.readouterr().out
        assert "[WRITE]" in printed
        assert not CardPrintingTag.objects.filter(run_id="run-A").exists()

        ledger = PilotRunLedger.objects.get(command="retract_stage_d_by_run_id")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.dry_run is False
        assert ledger.counters["totals"]["votes_deleted"] == 1
        assert ledger.counters["totals"]["skipped_rescannable"] == 1
        assert ledger.counters["totals"]["cards_resynced"] == 1
        assert ledger.counters["per_run_id"]["run-A"]["votes_deleted"] == 1

    def test_multiple_run_id_flags_are_all_targeted(self, db, capsys):
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Island")
        CardPrintingTagFactory(card=card_a, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-1")
        CardPrintingTagFactory(card=card_b, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-2")

        call_command("retract_stage_d_by_run_id", "--run-id=run-1", "--run-id=run-2", "--write")

        assert not CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        ledger = PilotRunLedger.objects.get(command="retract_stage_d_by_run_id")
        assert set(ledger.counters["target_run_ids"]) == {"run-1", "run-2"}
        assert ledger.counters["totals"]["votes_deleted"] == 2

    def test_comma_separated_run_ids_flag_works_and_combines_with_repeatable_flag(self, db):
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Island")
        card_c = CardFactory(name="Mountain")
        CardPrintingTagFactory(card=card_a, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-1")
        CardPrintingTagFactory(card=card_b, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-2")
        CardPrintingTagFactory(card=card_c, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-3")

        call_command("retract_stage_d_by_run_id", "--run-id=run-1", "--run-ids=run-2,run-3", "--write")

        assert not CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        ledger = PilotRunLedger.objects.get(command="retract_stage_d_by_run_id")
        assert set(ledger.counters["target_run_ids"]) == {"run-1", "run-2", "run-3"}

    def test_gate_refused_cards_are_listed_in_output_and_ledger(self, db, capsys):
        printing = CanonicalCardFactory(name="Resolved Card", expansion__code="cmr", collector_number="158")
        card = CardFactory(name="Resolved Card")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-A"
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-2")
        resolve_and_persist_printing(card)

        call_command("retract_stage_d_by_run_id", "--run-id=run-A", "--write")

        printed = capsys.readouterr().out
        assert "HUMAN REVIEW NEEDED" in printed
        assert str(card.pk) in printed
        ledger = PilotRunLedger.objects.get(command="retract_stage_d_by_run_id")
        assert ledger.counters["totals"]["skipped_resolved_gate"] == 1
        assert card.pk in ledger.counters["per_run_id"]["run-A"]["skipped_resolved_gate_card_ids"]
        # gated, not force-retracted:
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()

    def test_refuses_to_run_against_a_stale_image(self, db):
        with patch(
            "cardpicker.management.commands.retract_stage_d_by_run_id.find_stale_applied_migrations",
            return_value=[("cardpicker", "0099_fake_future_migration")],
        ):
            with pytest.raises(CommandError, match="STALE IMAGE"):
                call_command("retract_stage_d_by_run_id", "--run-id=run-A")

    def test_failure_marks_the_ledger_row_failed(self, db):
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, source=VoteSource.OCR, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="run-A")

        with patch(
            "cardpicker.management.commands.retract_stage_d_by_run_id.retract_run_ids",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                call_command("retract_stage_d_by_run_id", "--run-id=run-A", "--write")

        ledger = PilotRunLedger.objects.get(command="retract_stage_d_by_run_id")
        assert ledger.status == PilotRunLedger.Status.FAILED
