"""
Tests for cardpicker.pilot_run_lifecycle - the shared PilotRunLedger lifecycle rails (Phase 0
rails, issues #362/#153's milestone). Covers the three pieces directly, in isolation from any one
command - each command's own test file additionally covers the WIRING (its own scope computation,
its own ledger call sites) end to end.
"""

from datetime import timedelta

import pytest

from django.core.management.base import CommandError
from django.utils import timezone

from cardpicker.models import PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    enforce_dry_run_precondition,
    initial_counters,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)


class TestResilientTerminalOutput:
    def test_swallows_broken_pipe_error(self):
        with resilient_terminal_output():
            raise BrokenPipeError("stdout severed")
        # no exception escaped - that's the assertion.

    def test_swallows_io_error(self):
        with resilient_terminal_output():
            raise IOError("stdout severed")

    def test_does_not_swallow_other_exceptions(self):
        with pytest.raises(ValueError):
            with resilient_terminal_output():
                raise ValueError("a genuine bug, not a severed pipe")

    def test_body_runs_normally_when_nothing_raises(self):
        ran = []
        with resilient_terminal_output():
            ran.append(1)
        assert ran == [1]


class TestScopeHash:
    def test_deterministic_for_the_same_parts(self):
        assert scope_hash("a", "bc") == scope_hash("a", "bc")

    def test_differs_for_different_parts(self):
        assert scope_hash("a", "bc") != scope_hash("ab", "c")

    def test_differs_for_reordered_parts(self):
        assert scope_hash("a", "b") != scope_hash("b", "a")

    def test_short_and_hex(self):
        result = scope_hash("selector", "no-text", "run-1")
        assert len(result) == 16
        int(result, 16)  # raises ValueError if not valid hex


class TestInitialAndMergeCounters:
    def test_initial_counters_is_none_when_nothing_to_record(self):
        assert initial_counters() is None
        assert initial_counters(scope=None, skip_dryrun_check_used=False) is None

    def test_initial_counters_carries_scope(self):
        assert initial_counters(scope="abc123") == {"scope": "abc123"}

    def test_initial_counters_carries_skip_flag(self):
        assert initial_counters(skip_dryrun_check_used=True) == {"skip_dryrun_check_used": True}

    def test_initial_counters_carries_both(self):
        assert initial_counters(scope="abc123", skip_dryrun_check_used=True) == {
            "scope": "abc123",
            "skip_dryrun_check_used": True,
        }

    def test_merge_counters_preserves_existing_keys_and_adds_new_ones(self):
        merged = merge_counters({"scope": "abc123"}, {"votes_written": 5})
        assert merged == {"scope": "abc123", "votes_written": 5}

    def test_merge_counters_handles_none_existing(self):
        assert merge_counters(None, {"votes_written": 5}) == {"votes_written": 5}

    def test_merge_counters_new_keys_win_on_collision(self):
        assert merge_counters({"votes_written": 1}, {"votes_written": 2}) == {"votes_written": 2}


class TestEnforceDryRunPrecondition:
    def test_returns_false_and_does_nothing_when_not_in_write_mode(self, db):
        result = enforce_dry_run_precondition(
            command="some_command", write_mode=False, skip_check=False, window_hours=48
        )
        assert result is False

    def test_raises_when_write_mode_and_no_matching_dry_run_exists(self, db):
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=False, window_hours=48)

    def test_skip_check_bypasses_and_returns_true(self, db, capsys):
        result = enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=True, window_hours=48)
        assert result is True
        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        assert "some_command" in printed

    def test_passes_when_a_matching_completed_dry_run_exists(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        result = enforce_dry_run_precondition(
            command="some_command", write_mode=True, skip_check=False, window_hours=48
        )
        assert result is False

    def test_ignores_a_dry_run_row_for_a_different_command(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="a_different_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=False, window_hours=48)

    def test_ignores_a_non_completed_dry_run_row(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.RUNNING,
        )
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=False, window_hours=48)

    def test_ignores_a_write_mode_row_even_if_completed(self, db):
        # a prior --write invocation is not a dry-run, regardless of its own outcome.
        PilotRunLedger.objects.create(
            run_id="write-1",
            command="some_command",
            dry_run=False,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=False, window_hours=48)

    def test_ignores_a_dry_run_row_outside_the_recency_window(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now() - timedelta(hours=72),
        )
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            enforce_dry_run_precondition(command="some_command", write_mode=True, skip_check=False, window_hours=48)

    def test_a_wider_window_hours_accepts_an_older_dry_run(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now() - timedelta(hours=72),
        )
        result = enforce_dry_run_precondition(
            command="some_command", write_mode=True, skip_check=False, window_hours=96
        )
        assert result is False

    def test_scope_must_match_when_given(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
            counters={"scope": "scope-a"},
        )
        with pytest.raises(CommandError, match="scope='scope-b'"):
            enforce_dry_run_precondition(
                command="some_command", write_mode=True, skip_check=False, window_hours=48, scope="scope-b"
            )

    def test_scope_match_passes(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
            counters={"scope": "scope-a"},
        )
        result = enforce_dry_run_precondition(
            command="some_command", write_mode=True, skip_check=False, window_hours=48, scope="scope-a"
        )
        assert result is False

    def test_scope_none_on_caller_side_matches_any_scoped_or_unscoped_dry_run_row(self, db):
        PilotRunLedger.objects.create(
            run_id="dry-1",
            command="some_command",
            dry_run=True,
            status=PilotRunLedger.Status.COMPLETED,
            finished_at=timezone.now(),
            counters={"scope": "scope-a"},
        )
        result = enforce_dry_run_precondition(
            command="some_command", write_mode=True, skip_check=False, window_hours=48, scope=None
        )
        assert result is False
