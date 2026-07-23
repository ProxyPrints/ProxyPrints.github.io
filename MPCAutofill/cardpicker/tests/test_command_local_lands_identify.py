"""
Tests for cardpicker.management.commands.local_lands_identify - the "house lifecycle" half of
issue #359 (Phase 0 rails, matching issues #345/#373's own PilotRunLedger self-recording/
counters-before-output/forced-dry-run-guard pattern, already used by local_calculate_verdicts/
consensus_recompute). run_lands_identify itself is exercised in test_local_lands_identify.py -
this file only covers the command's own lifecycle wiring, not the identification pipeline logic.
"""

from unittest.mock import patch

import pytest

from django.core.management import CommandError, call_command

from cardpicker.models import CardPrintingTag, PilotRunLedger
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory


class TestLocalLandsIdentifyCommand:
    def test_command_defaults_to_dry_run_and_writes_no_votes(self, db, capsys):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        call_command("local_lands_identify", "--sample-size", "300", "--fetch-budget", "0")

        output = capsys.readouterr().out
        assert "[DRY RUN]" in output
        assert CardPrintingTag.objects.count() == 0

    def test_command_refuses_to_run_against_a_stale_image(self, db):
        with patch(
            "cardpicker.management.commands.local_lands_identify.find_stale_applied_migrations",
            return_value=[("cardpicker", "0099_fake_future_migration")],
        ):
            with pytest.raises(CommandError, match="STALE IMAGE"):
                call_command("local_lands_identify")


class TestLocalLandsIdentifyLedger:
    def test_dry_run_writes_a_completed_ledger_row_with_counters(self, db):
        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        call_command("local_lands_identify", "--sample-size", "300", "--fetch-budget", "0")

        ledger = PilotRunLedger.objects.get(command="local_lands_identify")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
        assert ledger.counters["land_pool_size"] == 1
        assert ledger.counters["evidence_backed"] == 0
        assert ledger.counters["fetch_attempted"] == 0

    def test_apply_writes_a_completed_ledger_row_with_votes_written(self, db):
        printing = CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        with patch("cardpicker.management.commands.local_lands_identify.run_lands_identify") as mock_run:
            from cardpicker.local_lands_identify import (
                LandIdentifyOutcome,
                LandsIdentifyResult,
            )

            mock_run.return_value = LandsIdentifyResult(
                dry_run=False,
                run_id="test-run",
                land_pool_size=1,
                sample_size=300,
                sampled=1,
                fetch_budget=10,
                fetch_attempted=0,
                evidence_backed=1,
                ocr_resolved=1,
                votes_written=1,
                outcomes=[
                    LandIdentifyOutcome(
                        card_id=1,
                        card_name="Plains",
                        candidate_count=1,
                        evidence_backed=True,
                        ocr_resolved_pk=printing.pk,
                    )
                ],
            )
            call_command("local_lands_identify", "--write", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="local_lands_identify")
        assert ledger.dry_run is False
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.votes_written == 1
        assert ledger.counters["evidence_backed"] == 1

    def test_a_genuine_failure_marks_the_ledger_row_failed(self, db):
        with patch(
            "cardpicker.management.commands.local_lands_identify.run_lands_identify",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                call_command("local_lands_identify", "--write", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="local_lands_identify")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert ledger.finished_at is not None

    def test_broken_pipe_during_terminal_summary_does_not_flip_completed_to_failed(self, db, monkeypatch):
        """Production incident 2026-07-23: a client-side timeout severed stdout AFTER every write
        had already committed and the ledger row had already been saved COMPLETED - the terminal
        summary print must never be able to flip that back to FAILED."""
        import cardpicker.management.commands.local_lands_identify as cmd_module

        CanonicalCardFactory(name="Plains")
        CardFactory(name="Plains")

        real_print = print

        def raising_print(*args, **kwargs):
            msg = args[0] if args else ""
            if isinstance(msg, str) and msg.startswith("[DRY RUN] done."):
                raise BrokenPipeError("stdout severed")
            real_print(*args, **kwargs)

        monkeypatch.setattr(cmd_module, "print", raising_print, raising=False)

        call_command("local_lands_identify", "--sample-size", "300", "--fetch-budget", "0")

        ledger = PilotRunLedger.objects.get(command="local_lands_identify")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None


class TestLocalLandsIdentifyDryRunGuard:
    """The forced-dry-run guard (issue #362, wired in here per #359's "house lifecycle" ask) -
    local_lands_identify always operates over the whole currently-eligible pool (no
    --card-ids-file/--selector-style caller-chosen cohort), so scope=None: any matching recent
    dry-run of this command satisfies the guard, regardless of --sample-size/--fetch-budget."""

    def test_write_refused_without_a_prior_matching_dry_run(self, db):
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("local_lands_identify", "--write")
        assert not PilotRunLedger.objects.filter(command="local_lands_identify").exists()

    def test_write_succeeds_after_a_matching_dry_run(self, db):
        call_command("local_lands_identify", "--sample-size", "300", "--fetch-budget", "0")  # dry-run
        call_command("local_lands_identify", "--write", "--sample-size", "300", "--fetch-budget", "0")

        ledgers = list(PilotRunLedger.objects.filter(command="local_lands_identify").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, capsys):
        call_command("local_lands_identify", "--write", "--skip-dryrun-check")

        printed = capsys.readouterr().out
        assert "[SKIP-DRYRUN-CHECK]" in printed
        ledger = PilotRunLedger.objects.get(command="local_lands_identify")
        assert ledger.counters["skip_dryrun_check_used"] is True
