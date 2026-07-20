"""
Regression guard for `run_image_evidence_cohort` (docs/reports/2026-07-20-canary-reprofile.md's
"Bug found" section): a real 400-card prod canary hit a deterministic, 100%-reproducing crash at
the very end of every invocation - the final summary line called `stop_event.is_set()` (a
`multiprocessing.Manager()` proxy method) AFTER `manager.shutdown()` had already torn the manager
down, so `manage.py` always exited non-zero even though every actual `persist_evidence` write had
already completed successfully inside the (already-exited) `ProcessPoolExecutor` block. Originally
fixed by reading `stop_event.is_set()` into a local BEFORE `manager.shutdown()` runs.

2026-07-20 update (Stage C fetch/compute decoupling, #228/#235): the command was rewritten to run
fetch (a `ThreadPoolExecutor`) and compute (a `ProcessPoolExecutor`) as two concurrent stages
instead of one bundled per-card unit - see the command's own module docstring. The
`multiprocessing.Manager().Event()` the original bug lived in is GONE entirely under the new
design (a plain `threading.Event`, shared within one process, covers the same "tell every other
in-flight/not-yet-started task to stop" contract now that a lockout can only ever originate in
the fetch stage) - this doesn't just avoid the old bug, it makes that exact bug class impossible
(there is no manager left to shut down). The tests below still assert the OBSERVABLE property
(clean exit + a correct `lockout_hit=` summary line) survives, rather than trusting that argument
alone - proving the property held under the new architecture, not just reasoning about it.

This test file never spawns a real OS-level worker process/thread doing real fetch/OCR work -
`ThreadPoolExecutor`/`ProcessPoolExecutor` are monkeypatched with a synchronous, in-process
stand-in (`_SyncPoolStub`, works for either since both share the stdlib `Executor` interface), and
the module-level `_fetch_one_card`/`_compute_one_card` work units are stubbed too, so the test
suite stays cheap and fast while still exercising the real dispatch/backpressure logic in
`_run_cohort` (`as_completed`/`wait`/`FIRST_COMPLETED` are all real stdlib, unmocked, running
against the stub pool's already-resolved `Future` objects).
"""

import threading
from concurrent.futures import Future
from io import BytesIO
from typing import Any, Optional

import pytest

from django.core.management import call_command

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.management.commands import run_image_evidence_cohort as cohort_command
from cardpicker.tests.factories import CardFactory


class _SyncPoolStub:
    """Drop-in stand-in for `ThreadPoolExecutor`/`ProcessPoolExecutor` that runs submitted work
    synchronously, in the test process, and returns real (already-resolved) `concurrent.futures.
    Future` objects - so `_run_cohort`'s own `as_completed`/`wait(..., FIRST_COMPLETED)` calls
    (untouched, real stdlib) work unmodified against them. No forking, no real threads, no
    `initializer=` call."""

    def __init__(self, max_workers: Optional[int] = None, initializer: Any = None) -> None:
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


def _stub_fetch_ok(card_id: int, stop_event: threading.Event) -> "cohort_command._FetchOutcome":
    """Replaces the real fetch-stage step - no DB fetch, no network, always a clean success with
    a trivial content_hash/image_bytes/fetch_latency_ms."""
    return cohort_command._FetchOutcome(
        card_id=card_id, content_hash=123, image_bytes=b"fake-jpeg-bytes", fetch_latency_ms=1.5, outcome=None
    )


def _stub_compute_ok(
    card_id: int,
    content_hash: Optional[int],
    image_bytes: Optional[bytes],
    fetch_latency_ms: float,
    dry_run: bool,
    run_id: str,
) -> tuple[int, str]:
    """Replaces the real compute-stage step - no PIL decode, no extractors, no persist_evidence
    call, just the (card_id, outcome) tuple `_run_cohort` consumes."""
    return card_id, "ok"


@pytest.fixture(autouse=True)
def _stub_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file replaces both real executors with the synchronous stub - none of
    them need genuine concurrency to exercise the dispatch logic under test."""
    monkeypatch.setattr(cohort_command, "ThreadPoolExecutor", _SyncPoolStub)
    monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _SyncPoolStub)


@pytest.mark.django_db
def test_command_exits_cleanly_with_a_non_empty_cohort(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The regression case itself: a non-empty cohort must reach the final summary line without
    raising - this is exactly the path the real prod canary crashed on (traceback: `AttributeError`
    /`FileNotFoundError` from calling `stop_event.is_set()` on a manager already shut down)."""
    CardFactory(content_phash=123456789)

    monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
    monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

    # No exception escaping call_command is the regression assertion - the bug this guards
    # against made this raise on every invocation, not just some.
    call_command("run_image_evidence_cohort", "--limit", "1", "--workers", "1", "--run-id", "test-run")

    out = capsys.readouterr().out
    assert "DONE" in out
    assert "completed=1/1" in out
    assert "lockout_hit=False" in out


@pytest.mark.django_db
def test_empty_cohort_still_exits_cleanly(capsys: pytest.CaptureFixture) -> None:
    """Sanity check for the OTHER early-return path (`if not cohort_ids: return`, before either
    executor is ever constructed) - kept alongside the regression case above so both exits from
    `handle()` are covered, not just the one the bug lived in."""
    call_command("run_image_evidence_cohort", "--limit", "0", "--run-id", "test-run-empty")

    out = capsys.readouterr().out
    assert "Nothing to do." in out


class TestFetchOneCard:
    """`_fetch_one_card` is the new fetch-stage work unit - runs on a thread, never touches an
    extractor, and is the only place a `GoogleFetchLockoutError` can now originate (see the
    command's own module docstring, change point 2)."""

    def test_returns_skipped_lockout_without_touching_the_db_once_stop_event_is_set(self) -> None:
        stop_event = threading.Event()
        stop_event.set()

        result = cohort_command._fetch_one_card(card_id=999999, stop_event=stop_event)

        assert result.outcome == "skipped-lockout"
        assert result.image_bytes is None

    @pytest.mark.django_db
    def test_returns_dropped_for_a_nonexistent_card(self) -> None:
        stop_event = threading.Event()

        result = cohort_command._fetch_one_card(card_id=999999, stop_event=stop_event)

        assert result.outcome == "dropped"

    @pytest.mark.django_db
    def test_lockout_sets_stop_event_and_returns_lockout_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(content_phash=123456789)
        stop_event = threading.Event()

        def _raise_lockout(card: Any, dpi: Optional[int] = None) -> None:
            raise GoogleFetchLockoutError("locked out")

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", _raise_lockout)

        result = cohort_command._fetch_one_card(card_id=card.pk, stop_event=stop_event)

        assert result.outcome == "lockout"
        assert stop_event.is_set()

    @pytest.mark.django_db
    def test_successful_fetch_returns_none_outcome_with_populated_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(content_phash=42)
        stop_event = threading.Event()

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: b"raw-bytes")

        result = cohort_command._fetch_one_card(card_id=card.pk, stop_event=stop_event)

        assert result.outcome is None
        assert result.content_hash == 42
        assert result.image_bytes == b"raw-bytes"
        assert result.fetch_latency_ms >= 0.0


class TestComputeOneCard:
    """`_compute_one_card` is the new compute-stage work unit - decodes the already-fetched raw
    bytes itself (lazily, via `Image.open`) rather than receiving a pre-decoded buffer, so the
    real pixel decode cost lands on the compute side (see the command's own module docstring)."""

    @pytest.mark.django_db
    def test_decodes_image_bytes_and_calls_compute_card_evidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (10, 10), (1, 2, 3)).save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        captured: dict[str, Any] = {}

        def _stub_compute_card_evidence(
            card_id: int, content_hash: Optional[int], image: Any, fetch_latency_ms: float
        ) -> Any:
            captured["card_id"] = card_id
            captured["content_hash"] = content_hash
            captured["image_size"] = image.size if image is not None else None
            captured["fetch_latency_ms"] = fetch_latency_ms

            class _Result:
                fields = {"fetch_ok": True}

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        card_id, outcome = cohort_command._compute_one_card(
            card_id=7, content_hash=99, image_bytes=raw_bytes, fetch_latency_ms=12.3, dry_run=False, run_id="r"
        )

        assert card_id == 7
        assert outcome == "ok"
        assert captured["card_id"] == 7
        assert captured["content_hash"] == 99
        assert captured["image_size"] == (10, 10)
        assert captured["fetch_latency_ms"] == 12.3

    @pytest.mark.django_db
    def test_passes_none_image_through_for_a_failed_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _stub_compute_card_evidence(
            card_id: int, content_hash: Optional[int], image: Any, fetch_latency_ms: float
        ) -> Any:
            captured["image"] = image

            class _Result:
                fields = {"fetch_ok": False}

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        card_id, outcome = cohort_command._compute_one_card(
            card_id=7, content_hash=None, image_bytes=None, fetch_latency_ms=0.0, dry_run=False, run_id="r"
        )

        assert captured["image"] is None
        assert outcome == "fetch_failed"

    @pytest.mark.django_db
    def test_dry_run_never_calls_persist_evidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        persist_calls = []

        import cardpicker.image_evidence as image_evidence_module

        class _Result:
            fields = {"fetch_ok": True}

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", lambda *a, **k: _Result())
        monkeypatch.setattr(
            image_evidence_module, "persist_evidence", lambda result, run_id=None: persist_calls.append(1)
        )

        cohort_command._compute_one_card(
            card_id=7, content_hash=None, image_bytes=None, fetch_latency_ms=0.0, dry_run=True, run_id="r"
        )

        assert persist_calls == []


class TestCohortStats:
    """The shared completed/fetch_failures bookkeeping the decoupled driver's two call sites
    (fetch-stage terminal outcomes, compute-stage results) both feed into."""

    def test_lockout_outcome_is_not_counted_at_all(self) -> None:
        stats = cohort_command._CohortStats(total=5, stdout_write=lambda _msg: None)

        stats.record("lockout")

        assert stats.completed == 0
        assert stats.fetch_failures == 0

    def test_ok_outcome_counts_as_completed_not_a_failure(self) -> None:
        stats = cohort_command._CohortStats(total=5, stdout_write=lambda _msg: None)

        stats.record("ok")

        assert stats.completed == 1
        assert stats.fetch_failures == 0

    @pytest.mark.parametrize("outcome", ["fetch_failed", "dropped"])
    def test_failure_outcomes_count_as_both_completed_and_a_failure(self, outcome: str) -> None:
        stats = cohort_command._CohortStats(total=5, stdout_write=lambda _msg: None)

        stats.record(outcome)

        assert stats.completed == 1
        assert stats.fetch_failures == 1

    def test_skipped_lockout_counts_as_completed_not_a_failure(self) -> None:
        """Matches the old bundled design's own convention exactly: a task pre-empted by an
        already-set stop_event still counts toward `completed` (it did run to a terminal
        state), just not toward `fetch_failures`."""
        stats = cohort_command._CohortStats(total=5, stdout_write=lambda _msg: None)

        stats.record("skipped-lockout")

        assert stats.completed == 1
        assert stats.fetch_failures == 0


class TestRunCohortBackpressure:
    """The new queue/dispatch logic itself - `_run_cohort`'s sliding window (`pending`, capped at
    `queue_depth`) is the mechanism that bounds how many fetched-but-not-yet-computed buffers can
    be outstanding at once (docs/features/catalog-completion-plan.md's Stage C decoupling design,
    "a bounded number of outstanding fetched-but-not-yet-computed buffers... enforced however the
    implementation chooses to gate submission"). `_run_cohort` itself runs on a real background
    thread (it has to, to observe it mid-flight), but the compute "pool" it submits to is a
    manually-driven stand-in - futures the test resolves one at a time - rather than anything that
    executes work concurrently, so there is exactly one thing under test: does `_run_cohort`'s own
    submission loop ever let more than `queue_depth` compute futures sit unresolved at once. A
    real executor underneath would add its own scheduling nondeterminism without adding anything
    to the assertion."""

    def test_never_exceeds_queue_depth_outstanding_compute_tasks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import time as _time
        from concurrent.futures import ThreadPoolExecutor as _RealThreadPoolExecutor

        queue_depth = 2
        constructed: list["_ManualComputePool"] = []

        class _ManualComputePool:
            """`ProcessPoolExecutor` stand-in whose `submit()` never runs `fn` itself - it just
            hands back a fresh, unresolved `Future` and records it. The test resolves each one
            explicitly, in its own time, to control exactly how many are ever left outstanding."""

            def __init__(self, max_workers: Optional[int] = None, initializer: Any = None) -> None:
                self.live: list[tuple[Future, tuple[Any, ...]]] = []
                self.lock = threading.Lock()
                constructed.append(self)

            def __enter__(self) -> "_ManualComputePool":
                return self

            def __exit__(self, *exc_info: Any) -> bool:
                return False

            def submit(self, fn: Any, *args: Any) -> "Future[Any]":
                future: "Future[Any]" = Future()
                with self.lock:
                    self.live.append((future, args))
                return future

        # The fetch stage stays REAL (a genuine ThreadPoolExecutor) so fetch results arrive on
        # their own schedule, independent of this test's polling loop - only the compute side is
        # manually controlled.
        monkeypatch.setattr(cohort_command, "ThreadPoolExecutor", _RealThreadPoolExecutor)
        monkeypatch.setattr(
            cohort_command,
            "_fetch_one_card",
            lambda card_id, stop_event: cohort_command._FetchOutcome(
                card_id=card_id, content_hash=1, image_bytes=b"x", fetch_latency_ms=0.0, outcome=None
            ),
        )
        monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _ManualComputePool)

        cohort_ids = list(range(1, 9))  # more cards than queue_depth, so the window must bind

        result: dict[str, Any] = {}

        def _run() -> None:
            result["value"] = cohort_command._run_cohort(
                cohort_ids=cohort_ids,
                fetch_threads=4,
                workers=1,
                queue_depth=queue_depth,
                dry_run=True,
                run_id="test",
                stdout_write=lambda _msg: None,
            )

        run_thread = threading.Thread(target=_run)
        run_thread.start()

        deadline = _time.monotonic() + 5
        while not constructed and _time.monotonic() < deadline:
            _time.sleep(0.005)
        assert constructed, "ProcessPoolExecutor was never constructed - _run_cohort didn't reach the compute stage"
        pool = constructed[0]

        max_outstanding = 0
        resolved = 0
        while resolved < len(cohort_ids) and _time.monotonic() < deadline:
            with pool.lock:
                unresolved = [(future, args) for future, args in pool.live if not future.done()]
            max_outstanding = max(max_outstanding, len(unresolved))
            if unresolved:
                future, args = unresolved[0]
                future.set_result((args[0], "ok"))
                resolved += 1
            else:
                _time.sleep(0.005)

        run_thread.join(timeout=5)
        assert not run_thread.is_alive(), "background _run_cohort thread never finished"
        assert resolved == len(cohort_ids)
        assert max_outstanding <= queue_depth
        assert result["value"][0] == len(cohort_ids)  # completed count
