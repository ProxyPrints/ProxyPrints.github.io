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
`_run_cohort` (`wait`/`FIRST_COMPLETED` are real stdlib, unmocked, running against the stub pool's
already-resolved `Future` objects).

2026-07-22 update (parent-process memory leak fix, see the command's own module docstring's
"PARENT-PROCESS MEMORY LEAK" section for the two production incidents and root cause): fetch-stage
submission is now windowed (drip-fed via `_submit_more_fetch`, bounded by `queue_depth`) rather
than submitted for the whole cohort up front, and `_run_cohort`'s return tuple gained a fifth
`rss_limit_hit` value. `TestRunCohortFetchMemoryBound` below is the regression guard for the fix
itself - it asserts the actual property that broke (peak simultaneously-alive fetch buffers stays
bounded by `queue_depth`, not by cohort size), using the same real-`ThreadPoolExecutor` +
manually-driven-compute-stub pattern `TestRunCohortBackpressure` already established for
observing `_run_cohort` mid-flight.

2026-07-23 update (PilotRunLedger self-recording): every command-level test that reaches
`handle()`'s `_parent_connections.close_all()` call (i.e. anything past a non-empty cohort - see
that call's own comment for why it exists, real fork-safety, not just this test file's problem)
now needs `@pytest.mark.django_db(transaction=True)` instead of the plain form. Reason: plain
`@pytest.mark.django_db` wraps a test in one outer atomic() block; Django's own `close()` behaves
differently inside an atomic block (`closed_in_transaction=True`, leaves `self.connection` non-None
rather than nulling it) than outside one (`self.connection = None`, safe lazy reconnect on next
query) - see `django.db.backends.base.base.BaseDatabaseWrapper.close`. In production there is no
surrounding atomic block, so the plain-close-and-lazily-reconnect path this command always relied
on (fetch threads reusing the connection pool post-close, and now this run's own ledger
COMPLETED/FAILED write after `_run_cohort` returns) already worked correctly; only the test-only
atomic wrapper made a second post-close query raise `psycopg2.InterfaceError: connection already
closed`. `transaction=True` swaps that wrapper for real commit-and-truncate isolation (matching
prod's own "no atomic block" shape), which is the documented pytest-django fix for code under test
that manages DB connections directly - not a workaround. Tests that never reach that line (the
"Nothing to do" empty-cohort early return, and every pool-internals/`_fetch_one_card`/
`_compute_one_card` unit test that never calls `handle()` at all) are deliberately left on the
plain marker - transaction=True is slower and only worth paying for where it's actually needed.
"""

import threading
from concurrent.futures import Future
from io import BytesIO
from typing import Any, Optional

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.management.commands import run_image_evidence_cohort as cohort_command
from cardpicker.models import CardScanLog, ImageEvidence, PilotRunLedger
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory


class _SyncPoolStub:
    """Drop-in stand-in for `ThreadPoolExecutor`/`ProcessPoolExecutor` that runs submitted work
    synchronously, in the test process, and returns real (already-resolved) `concurrent.futures.
    Future` objects - so `_run_cohort`'s own `as_completed`/`wait(..., FIRST_COMPLETED)` calls
    (untouched, real stdlib) work unmodified against them. No forking, no real threads, no
    `initializer=` call."""

    def __init__(
        self, max_workers: Optional[int] = None, initializer: Any = None, initargs: tuple[Any, ...] = ()
    ) -> None:
        # `initargs` (2026-07-29) is accepted and DELIBERATELY not applied: this stub is documented
        # above as never calling `initializer=`, and the tests that care about the worker-side
        # artist context (`TestComputeOneCardArtistWiring`) call `_init_worker` themselves so the
        # process state under test is explicit rather than a side effect of pool construction.
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


def _stub_fetch_ok(
    card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
) -> "cohort_command._FetchOutcome":
    """Replaces the real fetch-stage step - no DB fetch, no network, always a clean success with
    a trivial content_hash/image_bytes/fetch_latency_ms. `run_id`/`dry_run` (2026-07-25, issue
    #473 PR-2) are accepted and ignored - this stub never exercises the evidence-transfer check,
    only `_submit_more_fetch`'s own wider call signature."""
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
    profile: bool = False,
    short_circuit: Optional[bool] = None,
    known_set_codes: Optional[frozenset[str]] = None,
    md5_checksum: Optional[str] = None,
    sha256_checksum: Optional[str] = None,
    card_artist_names: tuple[str, ...] = (),
) -> tuple[int, str, Optional[dict[str, float]], bool]:
    """Replaces the real compute-stage step - no PIL decode, no extractors, no persist_evidence
    call, just the (card_id, outcome, profile, short_circuited) tuple `_run_cohort` consumes.
    `profile` (2026-07-20 diagnostic addition, #235) is accepted but unused here - the stub never
    produces a real timing breakdown, matching the real function's own `None` when `--profile` is
    not passed. `short_circuit` (2026-07-21, Recovery-arc lessons item 1) is likewise accepted but
    unused - the stub always reports `short_circuited=False`."""
    return card_id, "ok", None, False


@pytest.fixture(autouse=True)
def _stub_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file replaces both real executors with the synchronous stub - none of
    them need genuine concurrency to exercise the dispatch logic under test."""
    monkeypatch.setattr(cohort_command, "ThreadPoolExecutor", _SyncPoolStub)
    monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _SyncPoolStub)


@pytest.mark.django_db(transaction=True)
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
    # against made this raise on every invocation, not just some. --skip-dryrun-check: this test
    # exercises the write path in isolation, not the forced-dry-run guard (issue #362) - that
    # guard has its own dedicated test class below.
    call_command(
        "run_image_evidence_cohort", "--limit", "1", "--workers", "1", "--run-id", "test-run", "--skip-dryrun-check"
    )

    out = capsys.readouterr().out
    assert "DONE" in out
    assert "completed=1/1" in out
    assert "lockout_hit=False" in out


@pytest.mark.django_db
def test_empty_cohort_still_exits_cleanly(capsys: pytest.CaptureFixture) -> None:
    """Sanity check for the OTHER early-return path (`if not cohort_ids: return`, before either
    executor is ever constructed) - kept alongside the regression case above so both exits from
    `handle()` are covered, not just the one the bug lived in."""
    call_command("run_image_evidence_cohort", "--limit", "0", "--run-id", "test-run-empty", "--skip-dryrun-check")

    out = capsys.readouterr().out
    assert "Nothing to do." in out


@pytest.mark.django_db(transaction=True)
def test_card_ids_file_bypasses_the_resume_filter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
) -> None:
    """issue #259's targeted re-extraction path: a card already carrying a FULL
    `ImageEvidence.extractor_versions` (normally excluded by the resume filter, see the module
    docstring's step 2) must still be picked up when it's named explicitly via
    `--card-ids-file` - that's the whole point of the flag (a forced re-run against cards whose
    evidence already exists, e.g. to re-OCR with issue #259's improved preprocessing)."""
    from cardpicker.management.commands.run_image_evidence_cohort import (
        MANIFEST_EXTRACTOR_KEYS,
    )
    from cardpicker.tests.factories import ImageEvidenceFactory

    card = CardFactory(content_phash=123456789)
    ImageEvidenceFactory(
        card=card, content_hash=123456789, extractor_versions={key: "v1" for key in MANIFEST_EXTRACTOR_KEYS}
    )

    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(f"{card.pk}\n")

    monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
    monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

    call_command(
        "run_image_evidence_cohort",
        "--card-ids-file",
        str(ids_file),
        "--workers",
        "1",
        "--run-id",
        "test-run-ids",
        "--skip-dryrun-check",
    )

    out = capsys.readouterr().out
    assert "explicit card ids" in out
    assert "completed=1/1" in out


@pytest.mark.django_db(transaction=True)
def test_card_ids_file_with_a_nonexistent_card_id_drops_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
) -> None:
    """A stale/typo'd id in the file must not crash the run - `_fetch_one_card`'s own
    `Card.DoesNotExist` handling (unchanged by this flag) already covers this. Stubs
    `_fetch_one_card` to return the same "dropped" outcome that handling produces (matching
    every other test in this file's own convention of never exercising a real DB query through
    the synchronous pool stub, which shares this test's own connection rather than a real
    forked/threaded one)."""

    def _stub_fetch_dropped(
        card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
    ) -> "cohort_command._FetchOutcome":
        return cohort_command._FetchOutcome(card_id=card_id, outcome="dropped")

    monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_dropped)
    monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("999999999\n")

    call_command(
        "run_image_evidence_cohort",
        "--card-ids-file",
        str(ids_file),
        "--workers",
        "1",
        "--run-id",
        "t",
        "--skip-dryrun-check",
    )

    out = capsys.readouterr().out
    assert "DONE" in out
    assert "fetch_failures=1" in out


class TestPilotRunLedger:
    """2026-07-23: `run_image_evidence_cohort` was the last Stage C/D pilot command with no
    `PilotRunLedger` row of its own (see the command's own prior --run-id --help text) - its
    completion counters were log-only and lost once the run's stdout scrolled away. This class
    covers the self-recording lifecycle added to close that gap, following
    `local_calculate_verdicts`'s own exact RUNNING-at-start/COMPLETED-or-FAILED-at-end pattern."""

    @pytest.mark.django_db(transaction=True)
    def test_a_run_writes_a_completed_ledger_row_with_its_counters(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        CardFactory(content_phash=123456789)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        # NOTE: no --skip-dryrun-check needed - the --limit bulk path is ungated (issue #362,
        # narrowed per owner decision on PR #373's review - see TestDryRunGuard below).
        call_command(
            "run_image_evidence_cohort",
            "--limit",
            "1",
            "--workers",
            "1",
            "--run-id",
            "ledger-run-1",
        )
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-run-1")
        assert ledger.command == "run_image_evidence_cohort"
        assert ledger.dry_run is False
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
        assert ledger.counters == {
            "cohort_size": 1,
            "completed": 1,
            "fetch_failures": 0,
            "short_circuited": 0,
            "lockout_hit": False,
            "rss_limit_hit": False,
            "elapsed_s": ledger.counters["elapsed_s"],  # timing - only its presence/type matters
            # peak_rss_mb (2026-07-24, stage-e-streaming.md §3 decision (6)) - a real /proc read on
            # this (Linux, containerized) test host, so only its presence/type matters here too.
            "peak_rss_mb": ledger.counters["peak_rss_mb"],
            "scope": ledger.counters["scope"],  # opaque hash - see TestDryRunGuard below
        }
        assert isinstance(ledger.counters["elapsed_s"], float)
        assert ledger.counters["peak_rss_mb"] is None or isinstance(ledger.counters["peak_rss_mb"], float)

    @pytest.mark.django_db(transaction=True)
    def test_dry_run_flag_is_recorded_on_the_ledger(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        CardFactory(content_phash=123456789)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command(
            "run_image_evidence_cohort", "--limit", "1", "--workers", "1", "--run-id", "ledger-dry-run", "--dry-run"
        )
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-dry-run")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED

    @pytest.mark.django_db(transaction=True)
    def test_fetch_failures_and_short_circuited_land_in_ledger_counters(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Exercises the two counters called out explicitly in this command's own task spec
        (short_circuited/fetch_failures) end to end, not just the all-zeros happy path above."""
        CardFactory(content_phash=1)
        CardFactory(content_phash=2)

        def _stub_fetch_one_dropped(
            card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
        ) -> "cohort_command._FetchOutcome":
            return cohort_command._FetchOutcome(card_id=card_id, outcome="dropped")

        def _stub_compute_short_circuited(
            card_id: int,
            content_hash: Optional[int],
            image_bytes: Optional[bytes],
            fetch_latency_ms: float,
            dry_run: bool,
            run_id: str,
            profile: bool = False,
            short_circuit: Optional[bool] = None,
            known_set_codes: Optional[frozenset[str]] = None,
            md5_checksum: Optional[str] = None,
            sha256_checksum: Optional[str] = None,
            card_artist_names: tuple[str, ...] = (),
        ) -> tuple[int, str, Optional[dict[str, float]], bool]:
            return card_id, "ok", None, True

        # First card's fetch is dropped (counts as a fetch_failure and never reaches compute);
        # the real fetch stub only fires for whichever card the resume filter actually submits,
        # so a single stub covering both call sites keeps this deterministic regardless of order.
        calls = {"count": 0}

        def _fetch_first_dropped_rest_ok(
            card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
        ) -> "cohort_command._FetchOutcome":
            calls["count"] += 1
            if calls["count"] == 1:
                return _stub_fetch_one_dropped(card_id, stop_event, run_id, dry_run)
            return _stub_fetch_ok(card_id, stop_event, run_id, dry_run)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _fetch_first_dropped_rest_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_short_circuited)

        call_command(
            "run_image_evidence_cohort",
            "--limit",
            "2",
            "--workers",
            "1",
            "--run-id",
            "ledger-counters",
            "--skip-dryrun-check",
        )
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-counters")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["cohort_size"] == 2
        assert ledger.counters["completed"] == 2
        assert ledger.counters["fetch_failures"] == 1
        assert ledger.counters["short_circuited"] == 1
        assert ledger.counters["lockout_hit"] is False

    @pytest.mark.django_db
    def test_empty_cohort_still_writes_a_completed_ledger_row_with_zeroed_counters(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        # NOTE: no --skip-dryrun-check needed - the --limit bulk path is ungated (issue #362,
        # narrowed per owner decision on PR #373's review - see TestDryRunGuard below).
        call_command("run_image_evidence_cohort", "--limit", "0", "--run-id", "ledger-empty-cohort")
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-empty-cohort")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
        assert ledger.counters == {
            "cohort_size": 0,
            "completed": 0,
            "fetch_failures": 0,
            "short_circuited": 0,
            "lockout_hit": False,
            "rss_limit_hit": False,
            "peak_rss_mb": ledger.counters["peak_rss_mb"],  # opaque - see TestPilotRunLedger above
            "scope": ledger.counters["scope"],  # opaque hash - see TestDryRunGuard below
        }
        assert ledger.counters["peak_rss_mb"] is None or isinstance(ledger.counters["peak_rss_mb"], float)

    @pytest.mark.django_db(transaction=True)
    def test_max_rss_mb_exceeded_marks_ledger_completed_not_failed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The `--max-rss-mb` guard raises `CommandError` to force a nonzero exit (see
        `TestMaxRssGuardEndToEnd` above), but the run itself drained cleanly and every write
        already committed - matching the module docstring's own "checkpoint, not a failure"
        framing, the ledger row must land COMPLETED (with rss_limit_hit=True in its counters),
        never FAILED."""
        CardFactory(content_phash=123456789)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 2000.0)

        with pytest.raises(CommandError, match="max-rss-mb"):
            call_command(
                "run_image_evidence_cohort",
                "--limit",
                "1",
                "--workers",
                "1",
                "--run-id",
                "ledger-rss-exceeded",
                "--max-rss-mb",
                "1000",
                "--skip-dryrun-check",
            )
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-rss-exceeded")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["rss_limit_hit"] is True

    @pytest.mark.django_db(transaction=True)
    def test_a_genuine_mid_run_exception_marks_the_ledger_failed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Distinguishes a real crash (ledger row never reaches COMPLETED, still RUNNING when the
        exception hits) from the --max-rss-mb checkpoint case above - both raise, but only this
        one should land FAILED."""
        CardFactory(content_phash=123456789)

        def _stub_run_cohort_raises(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom - simulated mid-run crash")

        monkeypatch.setattr(cohort_command, "_run_cohort", _stub_run_cohort_raises)

        # NOTE: no --skip-dryrun-check needed - the --limit bulk path is ungated (issue #362,
        # narrowed per owner decision on PR #373's review - see TestDryRunGuard below).
        with pytest.raises(RuntimeError, match="boom"):
            call_command(
                "run_image_evidence_cohort",
                "--limit",
                "1",
                "--workers",
                "1",
                "--run-id",
                "ledger-genuine-failure",
            )
        capsys.readouterr()

        ledger = PilotRunLedger.objects.get(run_id="ledger-genuine-failure")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert ledger.finished_at is not None
        # counters holds only the creation-time scope metadata (issue #362) - no REAL completion
        # counters (cohort_size etc.) were ever computed, since the crash hit before _run_cohort
        # returned.
        assert "cohort_size" not in (ledger.counters or {})
        # 2026-07-24 (stage-e-streaming.md §3 decision (6), the "empty-failed-row" gap -
        # mark_ledger_failed's own docstring): a died-before-first-flush run still leaves an
        # honest, triage-able failure_reason alongside whatever creation-time counters (scope)
        # already existed - never an empty/silent dict.
        assert ledger.counters is not None
        assert "RuntimeError" in ledger.counters["failure_reason"]
        assert "boom - simulated mid-run crash" in ledger.counters["failure_reason"]
        assert ledger.counters["scope"]  # creation-time scope metadata survives the merge


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
        # 2026-07-29 (COLLECTOR-LINE ARTIST WIRING item 3): the name this step already loaded is
        # carried back so `_run_cohort` can resolve the card's artist-narrowing tuple in the
        # parent, off the one shared `CandidateNameIndex`, instead of in each compute worker.
        assert result.card_name == card.name

    @pytest.mark.django_db
    def test_md5_sibling_transfers_without_ever_fetching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions={key: "v1" for key in cohort_command.MANIFEST_EXTRACTOR_KEYS},
            symbol_phash=999,
        )
        stop_event = threading.Event()

        def _fail_if_called(card: Any, dpi: Optional[int] = None) -> None:
            raise AssertionError("a transfer-eligible card must never reach the fetch stage")

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", _fail_if_called)

        result = cohort_command._fetch_one_card(card_id=target.pk, stop_event=stop_event, run_id="r1", dry_run=False)

        assert result.outcome == "transferred"
        assert result.content_hash == 111
        assert result.image_bytes is None
        evidence = ImageEvidence.objects.get(card=target)
        assert evidence.transferred is True
        assert evidence.transferred_from_card_id == sibling.pk
        assert evidence.symbol_phash == 999

    @pytest.mark.django_db
    def test_a_transfer_anomaly_row_carries_this_runs_run_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """2026-07-29, from the run_id audit: `evidence_transfer.find_transfer_source` can write a
        durable `CardScanLog` anomaly row and was the one machine writer in the app stamping no
        `run_id`, making those rows invisible to `image_evidence.build_reconciliation_report`'s
        run-scoped filter. The function now takes the stamp; this pins THIS caller passing it,
        which is a separate mistake from the function forgetting to record it.

        The anomaly is an md5 pair whose `content_phash` disagrees - impossible for genuinely
        byte-identical files - so the transfer is refused and the card falls through to a fetch."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=222)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions={key: "v1" for key in cohort_command.MANIFEST_EXTRACTOR_KEYS},
        )
        stop_event = threading.Event()

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: None)

        cohort_command._fetch_one_card(card_id=target.pk, stop_event=stop_event, run_id="a-cohort-run", dry_run=False)

        log = CardScanLog.objects.get(card=target, anonymous_id="evidence-transfer-v1")
        assert log.run_id == "a-cohort-run"

    @pytest.mark.django_db
    def test_dry_run_finds_a_transfer_but_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions={key: "v1" for key in cohort_command.MANIFEST_EXTRACTOR_KEYS},
        )
        stop_event = threading.Event()

        result = cohort_command._fetch_one_card(card_id=target.pk, stop_event=stop_event, run_id="r1", dry_run=True)

        assert result.outcome == "transferred"
        assert ImageEvidence.objects.filter(card=target).count() == 0

    @pytest.mark.django_db
    def test_no_eligible_sibling_falls_through_to_a_real_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(md5_checksum="abc123", content_phash=111)  # no sibling exists at all
        stop_event = threading.Event()

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: b"raw-bytes")

        result = cohort_command._fetch_one_card(card_id=card.pk, stop_event=stop_event)

        assert result.outcome is None
        assert result.image_bytes == b"raw-bytes"
        assert ImageEvidence.objects.filter(card=card).count() == 0  # only persisted by compute


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
            card_id: int,
            content_hash: Optional[int],
            image: Any,
            fetch_latency_ms: float,
            profile: Optional[dict[str, float]] = None,
            short_circuit: Optional[bool] = None,
            known_set_codes: Optional[frozenset[str]] = None,
            artist_lexicon: Any = None,
            printing_artist_lookup: Any = None,
            card_artist_names: tuple[str, ...] = (),
            md5_checksum: Optional[str] = None,
            sha256_checksum: Optional[str] = None,
        ) -> Any:
            captured["card_id"] = card_id
            captured["content_hash"] = content_hash
            captured["image_size"] = image.size if image is not None else None
            captured["fetch_latency_ms"] = fetch_latency_ms

            class _Result:
                fields = {"fetch_ok": True}
                short_circuited = False

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        card_id, outcome, profile_dict, short_circuited = cohort_command._compute_one_card(
            card_id=7, content_hash=99, image_bytes=raw_bytes, fetch_latency_ms=12.3, dry_run=False, run_id="r"
        )

        assert card_id == 7
        assert outcome == "ok"
        assert profile_dict is None
        assert short_circuited is False
        assert captured["card_id"] == 7
        assert captured["content_hash"] == 99
        assert captured["image_size"] == (10, 10)
        assert captured["fetch_latency_ms"] == 12.3

    @pytest.mark.django_db
    def test_passes_none_image_through_for_a_failed_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _stub_compute_card_evidence(
            card_id: int,
            content_hash: Optional[int],
            image: Any,
            fetch_latency_ms: float,
            profile: Optional[dict[str, float]] = None,
            short_circuit: Optional[bool] = None,
            known_set_codes: Optional[frozenset[str]] = None,
            artist_lexicon: Any = None,
            printing_artist_lookup: Any = None,
            card_artist_names: tuple[str, ...] = (),
            md5_checksum: Optional[str] = None,
            sha256_checksum: Optional[str] = None,
        ) -> Any:
            captured["image"] = image

            class _Result:
                fields = {"fetch_ok": False}
                short_circuited = False

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        card_id, outcome, profile_dict, _short_circuited = cohort_command._compute_one_card(
            card_id=7, content_hash=None, image_bytes=None, fetch_latency_ms=0.0, dry_run=False, run_id="r"
        )

        assert captured["image"] is None
        assert outcome == "fetch_failed"
        assert profile_dict is None

    @pytest.mark.django_db
    def test_dry_run_never_calls_persist_evidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        persist_calls = []

        import cardpicker.image_evidence as image_evidence_module

        class _Result:
            fields = {"fetch_ok": True}
            short_circuited = False

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", lambda *a, **k: _Result())
        monkeypatch.setattr(
            image_evidence_module, "persist_evidence", lambda result, run_id=None: persist_calls.append(1)
        )

        cohort_command._compute_one_card(
            card_id=7, content_hash=None, image_bytes=None, fetch_latency_ms=0.0, dry_run=True, run_id="r"
        )

        assert persist_calls == []

    @pytest.mark.django_db
    def test_profile_true_forwards_a_dict_and_adds_wall_ms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """#235's diagnostic instrumentation, re-anchored to the decoupled compute stage: when
        `profile=True`, `_compute_one_card` passes a mutable dict through to
        `compute_card_evidence` (which populates fetch_ms/ocr_group_ms/etc. in place - not
        exercised here, that's `image_evidence.py`'s own test suite) and adds its own `wall_ms`
        covering this function's whole call."""
        import cardpicker.image_evidence as image_evidence_module

        captured_profile: dict[str, Any] = {}

        def _stub_compute_card_evidence(
            card_id: int,
            content_hash: Optional[int],
            image: Any,
            fetch_latency_ms: float,
            profile: Optional[dict[str, float]] = None,
            short_circuit: Optional[bool] = None,
            known_set_codes: Optional[frozenset[str]] = None,
            artist_lexicon: Any = None,
            printing_artist_lookup: Any = None,
            card_artist_names: tuple[str, ...] = (),
            md5_checksum: Optional[str] = None,
            sha256_checksum: Optional[str] = None,
        ) -> Any:
            if profile is not None:
                profile["fetch_ms"] = fetch_latency_ms
                captured_profile["seen"] = profile

            class _Result:
                fields = {"fetch_ok": True}
                short_circuited = False

            return _Result()

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        card_id, outcome, profile_dict, _short_circuited = cohort_command._compute_one_card(
            card_id=7,
            content_hash=None,
            image_bytes=None,
            fetch_latency_ms=5.0,
            dry_run=True,
            run_id="r",
            profile=True,
        )

        assert profile_dict is not None
        assert profile_dict is captured_profile["seen"]  # same dict object, populated in place
        assert profile_dict["fetch_ms"] == 5.0
        assert "wall_ms" in profile_dict
        assert profile_dict["wall_ms"] >= 0.0

    @pytest.mark.django_db
    def test_profile_false_returns_none_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import cardpicker.image_evidence as image_evidence_module

        class _Result:
            fields = {"fetch_ok": True}
            short_circuited = False

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", lambda *a, **k: _Result())
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        _card_id, _outcome, profile_dict, _short_circuited = cohort_command._compute_one_card(
            card_id=7, content_hash=None, image_bytes=None, fetch_latency_ms=0.0, dry_run=True, run_id="r"
        )

        assert profile_dict is None


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


class TestRunCohortProfileOutput:
    """`_run_cohort` is the single writer for `--profile` JSONL output (#235's diagnostic
    instrumentation, re-anchored to the decoupled driver - see `_run_cohort`'s own docstring)."""

    def test_writes_one_json_line_per_card_when_profile_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io
        import json

        def _stub_compute_with_profile(
            card_id: int,
            content_hash: Optional[int],
            image_bytes: Optional[bytes],
            fetch_latency_ms: float,
            dry_run: bool,
            run_id: str,
            profile: bool = False,
            short_circuit: Optional[bool] = None,
            known_set_codes: Optional[frozenset[str]] = None,
            md5_checksum: Optional[str] = None,
            sha256_checksum: Optional[str] = None,
            card_artist_names: tuple[str, ...] = (),
        ) -> tuple[int, str, Optional[dict[str, float]], bool]:
            profile_dict = {"fetch_ms": fetch_latency_ms, "wall_ms": 1.0} if profile else None
            return card_id, "ok", profile_dict, False

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_with_profile)

        profile_file = io.StringIO()
        (
            completed,
            fetch_failures,
            lockout_hit,
            short_circuited,
            rss_limit_hit,
            _peak_rss_mb,
        ) = cohort_command._run_cohort(
            cohort_ids=[1, 2, 3],
            fetch_threads=2,
            workers=1,
            queue_depth=2,
            dry_run=True,
            run_id="test",
            stdout_write=lambda _msg: None,
            profile=True,
            profile_file=profile_file,
        )

        assert completed == 3
        assert fetch_failures == 0
        assert lockout_hit is False
        assert short_circuited == 0
        assert rss_limit_hit is False

        lines = [json.loads(line) for line in profile_file.getvalue().splitlines()]
        assert len(lines) == 3
        assert {entry["card_id"] for entry in lines} == {1, 2, 3}
        assert all(entry["wall_ms"] == 1.0 for entry in lines)

    def test_writes_nothing_when_profile_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        profile_file = io.StringIO()
        cohort_command._run_cohort(
            cohort_ids=[1, 2],
            fetch_threads=2,
            workers=1,
            queue_depth=2,
            dry_run=True,
            run_id="test",
            stdout_write=lambda _msg: None,
            profile=False,
            profile_file=profile_file,
        )

        assert profile_file.getvalue() == ""


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

            def __init__(
                self, max_workers: Optional[int] = None, initializer: Any = None, initargs: tuple[Any, ...] = ()
            ) -> None:
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
            lambda card_id, stop_event, run_id="", dry_run=False: cohort_command._FetchOutcome(
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

        run_thread = threading.Thread(target=_run, daemon=True)
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


class TestRunCohortFetchMemoryBound:
    """Regression guard for the 2026-07-22 parent-process memory leak (command module docstring's
    "PARENT-PROCESS MEMORY LEAK" section - two production incidents: an unwatched 197k-card
    remainder run OOM-killed the whole box overnight at ~21GB parent RSS; a re-run the following
    night was caught by a watchdog at 17.3GB after 66,355 cards). The pre-fix `_run_cohort`
    submitted every `cohort_ids` entry to the fetch thread pool up front and never bounded how far
    fetch could complete ahead of compute consumption - a repro (this PR's own description)
    measured close to 100% of a synthetic cohort's raw-image-sized payloads simultaneously alive
    at peak. This test asserts the actual fixed property directly against the real `_run_cohort`,
    not just that some constant looks smaller: peak simultaneously-alive fetch-stage payloads must
    stay bounded by `queue_depth` (a small constant), never grow with cohort size."""

    def test_peak_alive_fetch_payloads_bounded_by_queue_depth_not_cohort_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import gc
        import time as _time
        import weakref
        from concurrent.futures import ThreadPoolExecutor as _RealThreadPoolExecutor

        queue_depth = 2
        cohort_size = 40  # much larger than queue_depth - the discriminating property
        live_payload_ids: set[int] = set()
        live_lock = threading.Lock()

        class _Payload:
            """Stand-in for a raw fetched image buffer - `__slots__` includes `__weakref__` so a
            `weakref.finalize` callback can tell the test exactly when each instance is actually
            collected, rather than inferring liveness from refcounts."""

            __slots__ = ("card_id", "blob", "__weakref__")

            def __init__(self, card_id: int) -> None:
                self.card_id = card_id
                self.blob = b"x" * 1024

        def _mark_dead(card_id: int) -> None:
            with live_lock:
                live_payload_ids.discard(card_id)

        def _make_payload(card_id: int) -> "_Payload":
            payload = _Payload(card_id)
            with live_lock:
                live_payload_ids.add(card_id)
            weakref.finalize(payload, _mark_dead, card_id)
            return payload

        def _stub_fetch(
            card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
        ) -> "cohort_command._FetchOutcome":
            return cohort_command._FetchOutcome(
                card_id=card_id, content_hash=1, image_bytes=_make_payload(card_id), outcome=None
            )

        constructed: list["_ManualComputePoolTrackingOnlyCardId"] = []

        class _ManualComputePoolTrackingOnlyCardId:
            """`ProcessPoolExecutor` stand-in whose `submit()` never runs `fn` - hands back a
            fresh, unresolved `Future` and records ONLY the card_id (args[0]), deliberately
            dropping the rest of `args` (which includes the fetched payload) immediately, so this
            test harness itself never becomes a second place retaining the payload beyond what a
            real `ProcessPoolExecutor` would (which pickles args across a process boundary rather
            than keeping the parent's own object reference resident) - the assertion below must
            measure the property under test, not an artifact of the stub."""

            def __init__(
                self, max_workers: Optional[int] = None, initializer: Any = None, initargs: tuple[Any, ...] = ()
            ) -> None:
                self.live: list[tuple[Future, int]] = []
                self.lock = threading.Lock()
                constructed.append(self)

            def __enter__(self) -> "_ManualComputePoolTrackingOnlyCardId":
                return self

            def __exit__(self, *exc_info: Any) -> bool:
                return False

            def submit(self, fn: Any, *args: Any) -> "Future[Any]":
                future: "Future[Any]" = Future()
                with self.lock:
                    self.live.append((future, args[0]))
                return future

        monkeypatch.setattr(cohort_command, "ThreadPoolExecutor", _RealThreadPoolExecutor)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch)
        monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _ManualComputePoolTrackingOnlyCardId)

        cohort_ids = list(range(1, cohort_size + 1))
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

        run_thread = threading.Thread(target=_run, daemon=True)
        run_thread.start()

        deadline = _time.monotonic() + 10
        while not constructed and _time.monotonic() < deadline:
            _time.sleep(0.005)
        assert constructed, "ProcessPoolExecutor was never constructed - _run_cohort didn't reach the compute stage"
        pool = constructed[0]

        peak_live = 0
        resolved = 0
        # Separate deadline: gc.collect() in the loop was ~50-100ms per call on Python 3.13
        # (full-generation collection over thousands of test objects), making the shared 10s
        # deadline flaky on slow CI runners. _Payload has __slots__ (no cycles), so CPython
        # refcount frees it immediately - no per-iteration GC needed here.
        resolution_deadline = _time.monotonic() + 30
        while resolved < cohort_size and _time.monotonic() < resolution_deadline:
            with pool.lock:
                unresolved = [(future, card_id) for future, card_id in pool.live if not future.done()]
            with live_lock:
                peak_live = max(peak_live, len(live_payload_ids))
            if unresolved:
                future, card_id = unresolved[0]
                future.set_result((card_id, "ok", None, False))
                resolved += 1
            else:
                _time.sleep(0.005)

        # One explicit collection after the loop catches any remaining objects (e.g. those held
        # in _run_cohort's stack until it exits) before the peak_live assertion below.
        gc.collect()
        with live_lock:
            peak_live = max(peak_live, len(live_payload_ids))
        run_thread.join(timeout=30)
        assert not run_thread.is_alive(), "background _run_cohort thread never finished"
        assert resolved == cohort_size
        assert result["value"][0] == cohort_size  # completed count
        assert result["value"][2] is False  # lockout_hit
        assert result["value"][4] is False  # rss_limit_hit

        # The discriminating assertion: peak simultaneously-alive fetch payloads must be bounded
        # by a small constant tied to queue_depth, NOT by cohort_size - the pre-fix code let this
        # grow toward cohort_size itself (all fetches racing ahead of consumption unbounded).
        assert peak_live <= queue_depth * 2 + 2, (
            f"peak_live={peak_live} scaled with cohort_size={cohort_size} rather than staying "
            f"bounded near queue_depth={queue_depth} - the parent-process memory leak regressed"
        )


class TestGetRssMb:
    """`_get_rss_mb` (2026-07-22) is the RSS-logging primitive both the progress line and
    `--max-rss-mb` depend on - best-effort, never raises."""

    def test_returns_a_positive_float_on_linux(self) -> None:
        rss_mb = cohort_command._get_rss_mb()
        # This test suite only runs on Linux (the pilot venv, CI) - /proc/self/status should
        # always be readable here, so a hard None would itself be a regression worth seeing fail.
        assert rss_mb is not None
        assert rss_mb > 0

    def test_never_raises_when_proc_status_is_unreadable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_oserror(*args: Any, **kwargs: Any) -> Any:
            raise OSError("no /proc here")

        monkeypatch.setattr("builtins.open", _raise_oserror)

        assert cohort_command._get_rss_mb() is None


class TestCohortStatsRssLogging:
    """`_CohortStats.record` (2026-07-22): every progress line now also logs the parent's own
    RSS, and an optional `max_rss_mb` turns crossing a threshold into a clean, observable stop."""

    def test_progress_line_includes_rss_mb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 512.0)
        lines: list[str] = []
        stats = cohort_command._CohortStats(total=1, stdout_write=lines.append)

        stats.record("ok")

        assert len(lines) == 1
        assert "rss_mb=512" in lines[0]

    def test_progress_line_shows_placeholder_when_rss_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: None)
        lines: list[str] = []
        stats = cohort_command._CohortStats(total=1, stdout_write=lines.append)

        stats.record("ok")

        assert "rss_mb=?" in lines[0]

    def test_exceeding_max_rss_mb_sets_stop_event_and_rss_limit_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 2000.0)
        stop_event = threading.Event()
        lines: list[str] = []
        stats = cohort_command._CohortStats(
            total=1, stdout_write=lines.append, stop_event=stop_event, max_rss_mb=1000.0
        )

        stats.record("ok")

        assert stats.rss_limit_hit is True
        assert stop_event.is_set()
        assert any("RSS limit exceeded" in line for line in lines)

    def test_under_max_rss_mb_never_sets_stop_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 100.0)
        stop_event = threading.Event()
        stats = cohort_command._CohortStats(
            total=1, stdout_write=lambda _msg: None, stop_event=stop_event, max_rss_mb=1000.0
        )

        stats.record("ok")

        assert stats.rss_limit_hit is False
        assert not stop_event.is_set()

    def test_max_rss_mb_none_never_checks_or_stops(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 999999.0)
        stop_event = threading.Event()
        stats = cohort_command._CohortStats(total=1, stdout_write=lambda _msg: None, stop_event=stop_event)

        stats.record("ok")

        assert stats.rss_limit_hit is False
        assert not stop_event.is_set()


class TestMaxRssGuardEndToEnd:
    """End-to-end (`call_command`) coverage for `--max-rss-mb` - the same synchronous-stub pattern
    every other command-level test in this file uses (see `_stub_pools` autouse fixture)."""

    @pytest.mark.django_db(transaction=True)
    def test_exceeding_max_rss_mb_stops_cleanly_and_exits_non_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        CardFactory(content_phash=123456789)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 2000.0)

        with pytest.raises(CommandError, match="max-rss-mb"):
            call_command(
                "run_image_evidence_cohort",
                "--limit",
                "1",
                "--workers",
                "1",
                "--run-id",
                "test-rss-exceeded",
                "--max-rss-mb",
                "1000",
                "--skip-dryrun-check",
            )

        out = capsys.readouterr().out
        assert "RSS limit exceeded" in out
        assert "rss_limit_hit=True" in out

    @pytest.mark.django_db(transaction=True)
    def test_max_rss_mb_unset_never_stops_the_run_regardless_of_rss(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        CardFactory(content_phash=123456789)

        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)
        monkeypatch.setattr(cohort_command, "_get_rss_mb", lambda: 999999.0)

        call_command(
            "run_image_evidence_cohort",
            "--limit",
            "1",
            "--workers",
            "1",
            "--run-id",
            "test-rss-unset",
            "--skip-dryrun-check",
        )

        out = capsys.readouterr().out
        assert "DONE" in out
        assert "rss_limit_hit=False" in out


class TestDryRunGuard:
    """Phase 0 rails (issues #362/#153's milestone): the forced-dry-run guard (issue #362),
    NARROWED per owner decision on PR #373's review to the targeted --card-ids-file path only -
    the routine --limit bulk-harvest path is intentionally UNGATED (its own dry-run preview pays
    the same full fetch/OCR/extraction compute cost as a real run, so the guard's cheap-preview
    rationale doesn't hold there) - see this command's own module docstring comment at the
    guard's own call site in handle()."""

    @pytest.mark.django_db(transaction=True)
    def test_limit_bulk_path_proceeds_without_any_prior_dry_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The routine --limit path is ungated - no CommandError, no matching prior dry-run
        ledger row required."""
        CardFactory(content_phash=123456789)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command("run_image_evidence_cohort", "--limit", "1", "--workers", "1", "--run-id", "guard-bulk-ungated")

        ledger = PilotRunLedger.objects.get(run_id="guard-bulk-ungated")
        assert ledger.dry_run is False
        assert ledger.status == PilotRunLedger.Status.COMPLETED

    @pytest.mark.django_db(transaction=True)
    def test_card_ids_file_path_refused_without_a_prior_matching_dry_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
    ) -> None:
        card = CardFactory(content_phash=123456789)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command(
                "run_image_evidence_cohort",
                "--card-ids-file",
                str(ids_file),
                "--workers",
                "1",
                "--run-id",
                "guard-file-no-dry-run",
            )
        assert not PilotRunLedger.objects.filter(run_id="guard-file-no-dry-run").exists()

    @pytest.mark.django_db(transaction=True)
    def test_card_ids_file_path_succeeds_after_a_matching_dry_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
    ) -> None:
        card = CardFactory(content_phash=123456789)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command(
            "run_image_evidence_cohort",
            "--card-ids-file",
            str(ids_file),
            "--workers",
            "1",
            "--run-id",
            "guard-file-dry",
            "--dry-run",
        )
        call_command(
            "run_image_evidence_cohort",
            "--card-ids-file",
            str(ids_file),
            "--workers",
            "1",
            "--run-id",
            "guard-file-write",
        )

        dry_ledger = PilotRunLedger.objects.get(run_id="guard-file-dry")
        write_ledger = PilotRunLedger.objects.get(run_id="guard-file-write")
        assert dry_ledger.dry_run is True and dry_ledger.status == PilotRunLedger.Status.COMPLETED
        assert write_ledger.dry_run is False and write_ledger.status == PilotRunLedger.Status.COMPLETED

    @pytest.mark.django_db(transaction=True)
    def test_card_ids_file_path_refused_when_the_file_scope_differs_from_the_dry_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
    ) -> None:
        card = CardFactory(content_phash=123456789)
        ids_file_a = tmp_path / "a.txt"
        ids_file_a.write_text(f"{card.pk}\n")
        ids_file_b = tmp_path / "b.txt"
        ids_file_b.write_text(f"{card.pk}\n")
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command(
            "run_image_evidence_cohort",
            "--card-ids-file",
            str(ids_file_a),
            "--workers",
            "1",
            "--run-id",
            "guard-file-a-dry",
            "--dry-run",
        )

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command(
                "run_image_evidence_cohort",
                "--card-ids-file",
                str(ids_file_b),
                "--workers",
                "1",
                "--run-id",
                "guard-file-b-write",
            )

    @pytest.mark.django_db(transaction=True)
    def test_skip_dryrun_check_bypasses_the_card_ids_file_guard_and_is_recorded(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Any
    ) -> None:
        card = CardFactory(content_phash=123456789)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(f"{card.pk}\n")
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command(
            "run_image_evidence_cohort",
            "--card-ids-file",
            str(ids_file),
            "--workers",
            "1",
            "--run-id",
            "guard-file-skip",
            "--skip-dryrun-check",
        )

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        ledger = PilotRunLedger.objects.get(run_id="guard-file-skip")
        assert ledger.counters["skip_dryrun_check_used"] is True

    @pytest.mark.django_db(transaction=True)
    def test_skip_dryrun_check_on_the_bulk_path_is_a_harmless_no_op(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """--skip-dryrun-check is meaningless on the already-ungated --limit path - passing it
        anyway must not raise, and (since the guard is never consulted for this path)
        SKIP-DRYRUN-CHECK is never printed/recorded."""
        CardFactory(content_phash=123456789)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        call_command(
            "run_image_evidence_cohort",
            "--limit",
            "1",
            "--workers",
            "1",
            "--run-id",
            "guard-bulk-skip-noop",
            "--skip-dryrun-check",
        )

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" not in printed
        ledger = PilotRunLedger.objects.get(run_id="guard-bulk-skip-noop")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert not (ledger.counters or {}).get("skip_dryrun_check_used")

    @pytest.mark.django_db(transaction=True)
    def test_broken_pipe_during_terminal_summary_does_not_flip_completed_to_failed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Production incident 2026-07-23: a client-side timeout severed stdout AFTER every write
        had already committed and the ledger row had already been saved COMPLETED - the terminal
        DONE summary print (self.stdout.write) must never be able to flip that back to FAILED.
        Uses the (now ungated) --limit bulk path - no --skip-dryrun-check needed."""
        from django.core.management.base import OutputWrapper

        CardFactory(content_phash=123456789)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        real_write = OutputWrapper.write

        def raising_write(self: OutputWrapper, msg: str = "", *args: Any, **kwargs: Any) -> None:
            if isinstance(msg, str) and msg.startswith("DONE run_id="):
                raise BrokenPipeError("stdout severed")
            return real_write(self, msg, *args, **kwargs)

        monkeypatch.setattr(OutputWrapper, "write", raising_write, raising=False)

        call_command(
            "run_image_evidence_cohort",
            "--limit",
            "1",
            "--workers",
            "1",
            "--run-id",
            "guard-broken-pipe",
        )

        ledger = PilotRunLedger.objects.get(run_id="guard-broken-pipe")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None


# ---------------------------------------------------------------------------------------------
# COLLECTOR-LINE ARTIST WIRING (2026-07-29 - see the command's own module docstring section of the
# same name). `compute_card_evidence` gained three artist-aware inputs which drive BOTH the
# collector-line escalation gate and the `artist_ocr_name` storage fallback;
# `stage_e_dispatch._run_stage_c` (the conveyor Stage C path) threaded all three from the day they
# landed and this command - the pooled path - did not, so a card extracted here stored a blank
# `artist_ocr_name` where the conveyor stored a real one. These classes pin the wiring, and the
# parity test at the end pins the ONLY claim that actually matters: the same card, the same texts,
# produces the same stored fields down either path.
# ---------------------------------------------------------------------------------------------

_ARTIST_LEXICON_NAMES = ["Alessandra Pisano", "Lindsey Look", "Ron Spears"]
# The two printings the misread/correct collector-number pair below resolve to - same fixture
# shape `test_image_evidence.TestExtractCardEvidenceCollectorLineArtistGate` uses, so a divergence
# between the two suites is a real divergence and not a fixture difference.
_PRINTING_ARTISTS = {("mom", "158"): "Alessandra Pisano", ("mom", "159"): "Lindsey Look"}


def _printing_artist_stub(set_code: Optional[str], collector_number: Optional[str]) -> Optional[str]:
    return _PRINTING_ARTISTS.get((set_code, collector_number))


def _white_card_image_bytes() -> bytes:
    """A real, decodable bleed-aspect-ratio PNG. Every OCR call in these tests is stubbed, so the
    pixels carry no text - the image exists only because `compute_card_evidence` genuinely decodes
    it and runs its geometry/phash/quality extractors over it."""
    from PIL import Image

    from cardpicker.local_fallback import BLEED_ASPECT_RATIO

    height = 1300
    image = Image.new("RGB", (round(height * BLEED_ASPECT_RATIO), height), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _install_worker_artist_context(monkeypatch: pytest.MonkeyPatch, lexicon: Any, lookup: Any = None) -> None:
    """Put a compute worker's process globals in the state `_init_worker` would have left them in,
    WITHOUT calling `_init_worker` itself.

    `_init_worker` legitimately calls `connections.close_all()` - a fork-inherited connection is
    not safe to reuse, so a real worker process must drop it. Inside a `django_db` test there is
    no fork and only one connection, the test transaction's own, and closing it detonates every
    later ORM call in that test. `_init_worker`'s own behaviour is covered directly by
    `TestInitWorkerArtistContext`; the tests below are about what `_compute_one_card` does with
    the result, so they install the result and skip the close. `monkeypatch.setattr` restores both
    globals at teardown, so nothing leaks into the rest of the session."""
    monkeypatch.setattr(cohort_command, "_WORKER_ARTIST_LEXICON", lexicon)
    monkeypatch.setattr(cohort_command, "_WORKER_PRINTING_ARTIST_LOOKUP", lookup)


class TestInitWorkerArtistContext:
    """`_init_worker` is the compute pool's `initializer=`, and the only place the two
    per-worker-process halves of the artist context are ever set."""

    @pytest.fixture(autouse=True)
    def _isolated_worker_globals(self, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
        """`_init_worker` writes PROCESS globals and closes the process's DB connections - both
        entirely correct in a freshly forked worker, both hostile in a single-process test
        session. The globals are monkeypatched (auto-restored at teardown) and `close_all` is
        replaced with a recorder the jobs test below asserts on."""
        from django.db import connections

        closed: list[bool] = []
        monkeypatch.setattr(cohort_command, "_WORKER_ARTIST_LEXICON", None)
        monkeypatch.setattr(cohort_command, "_WORKER_PRINTING_ARTIST_LOOKUP", None)
        monkeypatch.setattr(connections, "close_all", lambda: closed.append(True))
        return closed

    def test_installs_the_lexicon_and_builds_a_printing_artist_lookup(self) -> None:
        from cardpicker.collector_line_artist import (
            PrintingArtistLookup,
            build_artist_lexicon,
        )

        lexicon = build_artist_lexicon(_ARTIST_LEXICON_NAMES)

        cohort_command._init_worker(lexicon)

        assert cohort_command._WORKER_ARTIST_LEXICON is lexicon
        assert isinstance(cohort_command._WORKER_PRINTING_ARTIST_LOOKUP, PrintingArtistLookup)

    def test_no_lexicon_leaves_the_whole_gate_unwired(self) -> None:
        """The pre-2026-07-29 posture, kept reachable on purpose: a pool built without initargs
        (or a direct unit call into `_compute_one_card`) must degrade to "gate off", never to a
        half-wired read - `_parse_artist_is_contradicted` needs BOTH halves, so shipping one
        without the other would be dead weight that also reads as wired."""
        from cardpicker.collector_line_artist import build_artist_lexicon

        cohort_command._init_worker(build_artist_lexicon(_ARTIST_LEXICON_NAMES))  # install first...
        cohort_command._init_worker()  # ...then re-init the way a no-initargs pool would

        assert cohort_command._WORKER_ARTIST_LEXICON is None
        assert cohort_command._WORKER_PRINTING_ARTIST_LOOKUP is None

    def test_still_does_its_two_pre_existing_jobs(self, _isolated_worker_globals: list[bool]) -> None:
        """The artist context is job 3 - jobs 1 and 2 (OpenMP nest-oversubscription and the
        inherited-DB-connection close) are what this initializer already existed for, and adding
        job 3 must not have displaced either."""
        import os

        cohort_command._init_worker(None)

        assert os.environ["OMP_THREAD_LIMIT"] == "1"
        assert _isolated_worker_globals == [True]


class TestComputeOneCardArtistWiring:
    """`_compute_one_card` is the pooled compute work unit. It reads `artist_lexicon`/
    `printing_artist_lookup` off the process globals `_init_worker` set, and takes
    `card_artist_names` as an already-resolved tuple (never a callable - `compute_card_evidence`'s
    own docstring requires every argument crossing the pool boundary to be picklable plain data)."""

    @pytest.mark.django_db
    def test_forwards_the_worker_context_and_the_resolved_card_artist_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cardpicker.collector_line_artist import build_artist_lexicon

        lexicon = build_artist_lexicon(_ARTIST_LEXICON_NAMES)
        _install_worker_artist_context(monkeypatch, lexicon, _printing_artist_stub)

        captured: dict[str, Any] = {}

        def _stub_compute_card_evidence(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)

            class _Result:
                fields = {"fetch_ok": True}
                short_circuited = False

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        cohort_command._compute_one_card(
            card_id=7,
            content_hash=1,
            image_bytes=None,
            fetch_latency_ms=0.0,
            dry_run=True,
            run_id="r",
            card_artist_names=("Lindsey Look",),
        )

        assert captured["artist_lexicon"] is lexicon
        assert captured["printing_artist_lookup"] is cohort_command._WORKER_PRINTING_ARTIST_LOOKUP
        assert captured["printing_artist_lookup"] is not None
        assert captured["card_artist_names"] == ("Lindsey Look",)

    @pytest.mark.django_db
    def test_an_uninitialised_worker_forwards_none_rather_than_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control for the test above: no `_init_worker` call at all (a direct unit call, or a
        pool built without the initializer) leaves both `None`, which `compute_card_evidence`
        documents as "gate entirely off" - the exact pre-2026-07-29 behaviour."""
        _install_worker_artist_context(monkeypatch, None, None)

        captured: dict[str, Any] = {}

        def _stub_compute_card_evidence(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)

            class _Result:
                fields = {"fetch_ok": True}
                short_circuited = False

            return _Result()

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence)
        monkeypatch.setattr(image_evidence_module, "persist_evidence", lambda result, run_id=None: None)

        cohort_command._compute_one_card(
            card_id=7, content_hash=1, image_bytes=None, fetch_latency_ms=0.0, dry_run=True, run_id="r"
        )

        assert captured["artist_lexicon"] is None
        assert captured["printing_artist_lookup"] is None
        assert captured["card_artist_names"] == ()

    @pytest.mark.django_db
    def test_pooled_extraction_stores_a_recovered_artist_ocr_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """END TO END through the REAL `compute_card_evidence` + `persist_evidence`, with only
        tesseract stubbed: the "Illus." anchor finds nothing (as it does on 93.7% of production
        rows), the collector line plainly reads LINDSEY L, and the pooled path must now store the
        canonical `Lindsey Look`. Before this wiring it stored `""`."""
        from cardpicker.collector_line_artist import build_artist_lexicon

        card = CardFactory(content_phash=1)
        _install_worker_artist_context(monkeypatch, build_artist_lexicon(_ARTIST_LEXICON_NAMES), _printing_artist_stub)

        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_evidence_module, "run_tesseract", lambda variant, **kwargs: "")
        monkeypatch.setattr(
            image_evidence_module,
            "run_tesseract_text_and_words",
            lambda image_arg, config: ("159/281R\nMOM ¢ EN LINDSEY L", []),
        )

        cohort_command._compute_one_card(
            card_id=card.pk,
            content_hash=1,
            image_bytes=_white_card_image_bytes(),
            fetch_latency_ms=1.0,
            dry_run=False,
            run_id="r",
            known_set_codes=frozenset({"mom"}),
            card_artist_names=("Lindsey Look",),
        )

        evidence = ImageEvidence.objects.get(card=card)
        assert evidence.artist_ocr_name == "Lindsey Look"
        # The recovery fills a BLANK value only and never rewrites the artist_ocr extractor's own
        # verdict - the same invariant the conveyor path holds.
        assert evidence.illus_anchor_fired is False

    @pytest.mark.django_db
    def test_pooled_and_conveyor_paths_store_identical_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE PARITY CLAIM, and the reason this wiring is a wiring change rather than a
        behaviour change: `stage_e_dispatch._run_stage_c` calls `compute_card_evidence` with the
        three artist arguments built per batch; this command now calls it with the same three
        built per run. Same card, same texts, same stored fields - asserted over the WHOLE
        `fields` dict, not a hand-picked subset, so a future argument that only one path threads
        fails here.

        The collector texts are the misread-number sequence: attempts 1-2 read `158` (lexicon-
        valid, but that printing is by Alessandra Pisano while the line reads LINDSEY L), attempt
        3 reads the correct `159`. A path with the gate wired stores `159`; a path without it
        stores `158` and stops at attempt 1 - so this fixture separates the two paths on the
        escalation half of the feature as well as the storage half."""
        from cardpicker.collector_line_artist import build_artist_lexicon
        from cardpicker.image_evidence import compute_card_evidence

        card = CardFactory(content_phash=1)
        lexicon = build_artist_lexicon(_ARTIST_LEXICON_NAMES)
        image_bytes = _white_card_image_bytes()
        texts = [
            "158/281R\nMOM ¢ EN LINDSEY L",
            "158/281R\nMOM ¢ EN LINDSEY L",
            "159/281R\nMOM ¢ EN LINDSEY L",
        ]

        import cardpicker.image_evidence as image_evidence_module

        def _install_ocr_stubs() -> None:
            remaining = iter(texts)
            monkeypatch.setattr(image_evidence_module, "run_tesseract", lambda variant, **kwargs: "")
            monkeypatch.setattr(
                image_evidence_module,
                "run_tesseract_text_and_words",
                lambda image_arg, config: (next(remaining, texts[-1]), []),
            )

        # CONVEYOR: exactly the call `stage_e_dispatch._run_stage_c` makes.
        from PIL import Image

        _install_ocr_stubs()
        conveyor = compute_card_evidence(
            card.pk,
            1,
            Image.open(BytesIO(image_bytes)),
            fetch_latency_ms=1.0,
            short_circuit=None,
            known_set_codes=frozenset({"mom"}),
            artist_lexicon=lexicon,
            printing_artist_lookup=_printing_artist_stub,
            card_artist_names=("Lindsey Look",),
            md5_checksum=None,
            sha256_checksum=None,
        )

        # POOLED: the same card through this command's own work unit.
        _install_worker_artist_context(monkeypatch, lexicon, _printing_artist_stub)
        _install_ocr_stubs()
        cohort_command._compute_one_card(
            card_id=card.pk,
            content_hash=1,
            image_bytes=image_bytes,
            fetch_latency_ms=1.0,
            dry_run=False,
            run_id="r",
            known_set_codes=frozenset({"mom"}),
            card_artist_names=("Lindsey Look",),
        )

        evidence = ImageEvidence.objects.get(card=card)
        assert conveyor.fields["collector_line_collector_number"] == "159"  # the gate really fired
        assert conveyor.fields["artist_ocr_name"] == "Lindsey Look"
        for key, expected in conveyor.fields.items():
            assert getattr(evidence, key) == expected, f"pooled/conveyor divergence on {key}"


class TestRunCohortArtistWiring:
    """The driver's two halves of the same wiring: the lexicon reaches worker PROCESSES through
    `initargs`, and `card_artist_names` is resolved in the PARENT (one shared
    `CandidateNameIndex`) and passed per card."""

    @pytest.mark.django_db
    def test_lexicon_travels_as_initargs_and_card_artist_names_are_resolved_per_card(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cardpicker.collector_line_artist import build_artist_lexicon

        lexicon = build_artist_lexicon(_ARTIST_LEXICON_NAMES)
        constructed: list[dict[str, Any]] = []
        submitted: list[tuple[Any, ...]] = []

        class _RecordingPool(_SyncPoolStub):
            def __init__(
                self, max_workers: Optional[int] = None, initializer: Any = None, initargs: tuple[Any, ...] = ()
            ) -> None:
                constructed.append({"initializer": initializer, "initargs": initargs})

            def submit(self, fn: Any, *args: Any) -> "Future[Any]":
                submitted.append(args)
                return super().submit(fn, *args)

        monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _RecordingPool)
        monkeypatch.setattr(
            cohort_command,
            "_fetch_one_card",
            lambda card_id, stop_event, run_id="", dry_run=False: cohort_command._FetchOutcome(
                card_id=card_id,
                content_hash=1,
                image_bytes=b"x",
                fetch_latency_ms=0.0,
                outcome=None,
                card_name=f"card-{card_id}",
            ),
        )
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        cohort_command._run_cohort(
            cohort_ids=[11, 22],
            fetch_threads=1,
            workers=1,
            queue_depth=4,
            dry_run=True,
            run_id="r",
            stdout_write=lambda _msg: None,
            artist_lexicon=lexicon,
            name_artist_lookup=lambda card_name: (f"artist-for-{card_name}",),
        )

        # The compute pool - and ONLY the compute pool - is initialised with the lexicon.
        compute_pools = [pool for pool in constructed if pool["initializer"] is cohort_command._init_worker]
        assert len(compute_pools) == 1
        assert compute_pools[0]["initargs"] == (lexicon,)

        # `card_artist_names` is the last positional argument of every submission, resolved from
        # that card's own name in the parent process.
        assert sorted(args[-1] for args in submitted) == [("artist-for-card-11",), ("artist-for-card-22",)]

    @pytest.mark.django_db
    def test_no_name_lookup_passes_an_empty_narrowing_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control: `_run_cohort`'s artist arguments both default to `None`, and every caller
        that leaves them there (every pre-2026-07-29 test in this file) must keep submitting the
        empty "don't narrow" tuple rather than crashing on a `None` call."""
        submitted: list[tuple[Any, ...]] = []

        class _RecordingPool(_SyncPoolStub):
            def submit(self, fn: Any, *args: Any) -> "Future[Any]":
                submitted.append(args)
                return super().submit(fn, *args)

        monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _RecordingPool)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch_ok)
        monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute_ok)

        cohort_command._run_cohort(
            cohort_ids=[11],
            fetch_threads=1,
            workers=1,
            queue_depth=4,
            dry_run=True,
            run_id="r",
            stdout_write=lambda _msg: None,
        )

        assert [args[-1] for args in submitted] == [()]
