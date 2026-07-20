"""
Regression guard for `run_image_evidence_cohort` (docs/reports/2026-07-20-canary-reprofile.md's
"Bug found" section): a real 400-card prod canary hit a deterministic, 100%-reproducing crash at
the very end of every invocation - the final summary line called `stop_event.is_set()` (a
`multiprocessing.Manager()` proxy method) AFTER `manager.shutdown()` had already torn the manager
down, so `manage.py` always exited non-zero even though every actual `persist_evidence` write had
already completed successfully inside the (already-exited) `ProcessPoolExecutor` block. Fixed by
reading `stop_event.is_set()` into a local BEFORE `manager.shutdown()` runs.

This test never spawns a real OS-level worker process (no real fork, no cross-process DB
visibility to arrange, no real fetch/OCR) - `ProcessPoolExecutor` and the module-level
`_process_one_card` are both monkeypatched with synchronous, in-process stand-ins so the test
stays cheap and fast while still exercising the exact code path (a non-empty cohort reaching
`manager.shutdown()` and the final summary line) the real bug lived in. A single real `Card` row
(via `CardFactory`, `content_phash` set) is needed only so the cohort isn't empty - the
`if not cohort_ids: return` early-out on an empty cohort never reaches the buggy line at all,
which is exactly why an empty-cohort smoke test alone would not have caught this.
"""

from concurrent.futures import Future
from typing import Any

import pytest

from django.core.management import call_command

from cardpicker.management.commands import run_image_evidence_cohort as cohort_command
from cardpicker.tests.factories import CardFactory


class _SyncPoolStub:
    """Drop-in stand-in for `ProcessPoolExecutor` that runs submitted work synchronously, in the
    test process, and returns real (already-resolved) `concurrent.futures.Future` objects - so the
    command's own `as_completed(futures)` loop (untouched, real stdlib) works unmodified against
    them. No forking, no worker processes, no `initializer=` call."""

    def __init__(self, max_workers: int | None = None, initializer: Any = None) -> None:
        pass

    def __enter__(self) -> "_SyncPoolStub":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def submit(self, fn: Any, *args: Any) -> "Future[Any]":
        future: "Future[Any]" = Future()
        try:
            result = fn(*args)
        except BaseException as exc:  # pragma: no cover - defensive, mirrors real pool behaviour
            future.set_exception(exc)
        else:
            future.set_result(result)
        return future


def _stub_process_one_card(card_id: int, dry_run: bool, run_id: str, stop_event: Any) -> tuple[int, str]:
    """Replaces the real per-card work unit - no DB fetch, no `extract_card_evidence`/
    `persist_evidence` call, just the (card_id, outcome) tuple `handle()` consumes."""
    return card_id, "ok"


@pytest.mark.django_db
def test_command_exits_cleanly_with_a_non_empty_cohort(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The regression case itself: a non-empty cohort must reach `manager.shutdown()` and the
    final summary line without raising - this is exactly the path the real prod canary crashed
    on (traceback: `AttributeError`/`FileNotFoundError` from calling `stop_event.is_set()` on a
    manager already shut down)."""
    CardFactory(content_phash=123456789)

    monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _SyncPoolStub)
    monkeypatch.setattr(cohort_command, "_process_one_card", _stub_process_one_card)

    # No exception escaping call_command is the regression assertion - the bug this guards
    # against made this raise on every invocation, not just some.
    call_command("run_image_evidence_cohort", "--limit", "1", "--workers", "1", "--run-id", "test-run")

    out = capsys.readouterr().out
    assert "DONE" in out
    assert "lockout_hit=False" in out


@pytest.mark.django_db
def test_empty_cohort_still_exits_cleanly(capsys: pytest.CaptureFixture) -> None:
    """Sanity check for the OTHER early-return path (`if not cohort_ids: return`, before
    `manager.shutdown()` is ever reached) - kept alongside the regression case above so both
    exits from `handle()` are covered, not just the one the bug lived in."""
    call_command("run_image_evidence_cohort", "--limit", "0", "--run-id", "test-run-empty")

    out = capsys.readouterr().out
    assert "Nothing to do." in out
