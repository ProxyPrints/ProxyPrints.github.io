"""
Bounded, owner-authorized dataset run (2026-07-20, converted to a process pool 2026-07-20 per
docs/reports/2026-07-20-pipeline-compute-profile.md's BLOCKING finding; fetch/compute decoupled
2026-07-20 per docs/features/catalog-completion-plan.md's Stage C decoupling design, #228,
confirmed by docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md, #235): drives Stage C's
per-card callable unit (`cardpicker.image_evidence.compute_card_evidence` + `persist_evidence`)
over a prioritized cohort of cards to produce the FIRST real `ImageEvidence` rows on the live
catalog. This is deliberately NOT the full-catalog harvest (that needs Stage D/E's
pipeline-fidelity + soak gates and a separate owner GO - see docs/features/catalog-completion-
plan.md's "Stage E resume contract" section) - just a simple concurrent driver, matching FINAL
POSTURE item 8a's requirement that the per-card unit stay independent of any particular
bulk-runner shape.

CONCURRENCY MODEL (2026-07-20, fetch/compute decoupling rewrite): this command previously bundled
fetch + compute into ONE per-card unit run inside a `ProcessPoolExecutor` worker. A 400-card
canary against rebuilt prod (`docs/reports/2026-07-20-canary-reprofile.md`) measured only 63.1%
parallel efficiency (4.41 of 7 workers busy on average) - idle-not-pegged, the signature of
workers stalling on I/O, not CPU contention. The confirming re-profile
(docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md, #235) measured `fetch_ms` at 36.5%
of mean per-card wall-clock, cross-validated against cgroup CPU-seconds - fetch-wait bundled into
the same worker that also does the CPU-bound OCR work was the cause. Fixed here by decoupling
fetch from compute into two concurrent stages (docs/features/catalog-completion-plan.md's Stage C
"Decoupling architecture" section):

- **Fetch stage**: a `ThreadPoolExecutor` of `--fetch-threads`/`STAGE_C_FETCH_THREADS` threads
  (default 8 - a little above `GOOGLE_IMAGE`'s own `max_concurrency=6`, so a thread is always
  queued and ready the instant a rate-limiter slot frees, per the design doc's own sizing
  rationale). Threads are the right primitive here (unlike the compute stage) because a Python
  thread releases the GIL for the duration of the blocking `requests.get` inside
  `rate_limited_get` - genuinely I/O-bound. Each fetch task (`_fetch_one_card`) calls
  `image_cdn_fetch.fetch_card_image_bytes` - the RAW, still-encoded bytes, never decoded on this
  side (see that function's own docstring) - so the only thing that crosses the fetch/compute
  process boundary is a `bytes` blob, not a decoded pixel buffer; decoding stays lazy and lands on
  the compute side, matching the design doc's own network-vs-compute core allocation.
- **Compute stage**: unchanged in spirit from the prior process-pool fix - a `ProcessPoolExecutor`
  sized to the host's USABLE compute cores (`--workers`/`STAGE_C_WORKERS`, default 7 - owner-
  confirmed hardware: 8 OCPU total, 1 pinned to network traffic), each worker forcing
  `OMP_THREAD_LIMIT=1`. The difference: a compute worker (`_compute_one_card`) now receives an
  already-fetched image buffer (raw bytes, decoded via `Image.open` right before calling
  `image_evidence.compute_card_evidence`) instead of a bare card_id it re-fetches itself - a
  compute worker's own wall-clock is 100% CPU-bound extraction, never fetch-wait. Compute workers
  never call the network and can never raise `GoogleFetchLockoutError` any more - that can only
  ever originate in the fetch stage now (design doc's "change point" #3).
- **The queue between them**: a bounded, RAM-only handoff - see `_run_cohort`'s own docstring for
  the exact windowing mechanism (`--queue-depth`/`STAGE_C_QUEUE_DEPTH`, default `workers * 2`,
  matching the design doc's "on the order of 2x the compute pool size" starting point). Memory
  budget: worst-case outstanding buffers are raw (still-JPEG-encoded) bytes, materially smaller
  than the design doc's own decoded-RGB-buffer estimate (~1.8 MiB/image) that already showed wide
  margin (well under 1 GiB even at a generous 10x that estimate) against the host's 24GB ceiling -
  this implementation is strictly cheaper than that arithmetic assumed, so the same "not RAM-bound
  at any plausible queue depth" conclusion holds a fortiori.

Two pieces of process-local state the OLD bundled-fetch design needed specifically because fetch
lived inside N compute PROCESSES no longer apply, and are gone rather than left as dead code:

1. **The Google-image rate limiter descaling.** The old `_init_worker` pre-seeded each compute
   worker's own process-local rate-limiter registry with a workers-scaled-down
   `DestinationLimiterConfig`, because N independent compute processes would otherwise each
   construct their own full-strength limiter (aggregate ceiling N times too high). Now that
   fetching lives in ONE place - the fetch stage's thread pool, all within this single command
   process - `harvest_fetch_limiter.get_limiter`'s existing process-wide singleton semantics apply
   directly to the unscaled `GOOGLE_IMAGE` config with no per-process division needed; the
   descaling hack has nothing left to compensate for. `harvest_fetch_limiter.py`/
   `image_cdn_fetch.py` are both untouched aside from the new `fetch_card_image_bytes` split (see
   that module's own docstring) - this removes complexity from THIS file only.
2. **The cross-process stop-on-lockout `Event`.** The old design used a
   `multiprocessing.Manager().Event()` because a lockout could originate inside any of N compute
   worker PROCESSES and needed to be observed by every OTHER worker process too. Since a
   `GoogleFetchLockoutError` can now only ever originate in the fetch stage - and the fetch stage
   is just a `ThreadPoolExecutor` living in THIS process, sharing memory with everything else
   here - a plain `threading.Event` covers the exact same "tell every other in-flight/not-yet-
   started task to stop" contract with no cross-process proxy needed. This is a genuine
   simplification, not a workaround: it structurally eliminates the exact bug class PR #225 fixed
   (calling a manager proxy's `is_set()` after `manager.shutdown()` had already torn the manager
   down - see `docs/reports/2026-07-20-canary-reprofile.md`'s "Bug found" section) rather than
   carefully re-ordering around it, because there is no `Manager`/`SyncManager` left to shut down
   at all. `TestExitCodeRegression`-style coverage below still asserts the observable property
   (clean exit + a correct `lockout_hit=` summary line) survives under the new architecture -
   proving the property held, not just arguing the mechanism that used to protect it is gone.

One piece of process-local state from the prior rewrite is UNCHANGED and still needed for the
compute stage specifically:

1. **DB connections.** Django DB connections are not fork-safe to share - a connection opened in
   the parent (e.g. by this command's own edhrec_rank/resume-filter queries, or by a fetch
   thread's own `Card.objects.get()` call) must not be used by a forked compute child.
   `_init_worker` (the compute pool's `initializer=`) calls `django.db.connections.close_all()`
   once per worker process, immediately after fork and before any task runs, so each compute
   worker lazily opens its own fresh connection on first query (`persist_evidence`'s writes)
   rather than touching anything inherited from the parent. Fetch threads share the parent
   process's own DB connection pool (thread-safe within one process, unlike across a fork) so no
   equivalent close-and-reopen is needed on the fetch side.

Prioritization: cards are ordered by their name's most-popular-printing `edhrec_rank` (a cheap
name-level proxy for docs/features/catalog-completion-plan.md's full harvest-priority chain -
"lands chunk -> dying-source -> queue-backing -> descending edhrec_rank -> cold tail" - not
reimplemented in full here, since the dying-source/queue-backing legs need signals this bounded
run doesn't have time to build; deviation noted in this run's own report). A NAIVE
per-Card correlated subquery against `CanonicalCard` (one lookup per card, forcing the DB to
evaluate it for all ~218k cards before an ORDER BY LIMIT can apply) was measured live and
cancelled after >2 minutes with no result - see this run's dated report. The two-step version
below avoids that: one cheap aggregate query builds a `{lowercased name: min edhrec_rank}` dict
(0.2s measured against the live catalog), then Python does the per-card lookup + sort against
however many (id, name) pairs are in scope - no per-row DB round trip.

Resume/kill-safety: `persist_evidence` is already idempotent per (card, content_hash) - a
re-run overwrites the same row rather than erroring or duplicating. This command ALSO applies a
resume filter up front (skip any card whose ImageEvidence row already carries every manifest
extractor's version key) so a re-invocation after a kill does not re-pay the fetch+OCR cost for
cards already done, matching task #147's resume-contract spirit without building its full
run-ledger machinery (explicitly out of scope for this bounded run per its own directive).
`MANIFEST_EXTRACTOR_KEYS` is kept in sync with `image_evidence.extract_card_evidence`'s own
`extractor_versions` keys (11 as of the color_profile/quality_signals extractor group) - stale
here would silently under-count "already done" and re-pay fetch+OCR cost this resume filter
exists specifically to avoid.

A `GoogleFetchLockoutError` (403 from the shared Google-bound destination) is a hard stop for
the whole run, exactly as `image_cdn_fetch.fetch_card_image`/`fetch_card_image_bytes`'s own
docstrings require every caller to treat it - this command sets a stop flag (a `threading.Event`,
see point 2 above) the moment one is observed in the fetch stage and lets already in-flight work
drain, rather than continuing to submit new fetch work into a destination that has already locked
us out.
"""

import json
import logging
import math
import os
import threading
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import dataclass
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Min

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.models import CanonicalCard, Card, ImageEvidence

logger = logging.getLogger(__name__)

# The full Stage C manifest as of 2026-07-20 (fetch_health + geometry-bleed + geometry-group +
# OCR-group + symbol-region + legal-line + quality-signals/color-profile) - matches
# image_evidence.extract_card_evidence's own extractor_versions keys exactly. Keep this set in
# sync with that function whenever a new extractor group lands (see module docstring).
MANIFEST_EXTRACTOR_KEYS = frozenset(
    {
        "fetch_health",
        "geometry_bleed",
        "layout_class",
        "crop_coordinates",
        "collector_line_ocr",
        "artist_ocr",
        "collector_line_tsv",
        "symbol_region",
        "legal_line",
        "quality_signals",
        "color_profile",
    }
)

DEFAULT_LIMIT = 3000
# Usable compute OCPUs (owner-confirmed hardware, 2026-07-20): 8 OCPU total, 1 pinned to network
# traffic, 7 usable for compute - matches the process pool's own sizing rationale in the module
# docstring above. Env-tunable (STAGE_C_WORKERS) since core counts vary by host; the CLI flag
# below takes precedence over both when passed explicitly.
DEFAULT_WORKERS = int(os.environ.get("STAGE_C_WORKERS", "7"))
# Fetch-thread count: a little above GOOGLE_IMAGE's own max_concurrency=6 (module docstring's
# fetch-stage section) - the limiter's own semaphore is the real concurrency ceiling regardless
# of thread count, extra threads beyond 6 just keep a request queued and ready.
DEFAULT_FETCH_THREADS = int(os.environ.get("STAGE_C_FETCH_THREADS", "8"))
# Queue depth between the fetch and compute stages - "on the order of 2x the compute pool size"
# per the design doc's own starting point; a CLI-passed --workers changes this default too (see
# handle() below), STAGE_C_QUEUE_DEPTH/--queue-depth override it directly.
DEFAULT_QUEUE_DEPTH_MULTIPLIER = 2
PROGRESS_EVERY = 25


def _init_worker() -> None:
    """Compute pool `initializer=` - runs once per worker PROCESS, immediately after it starts
    (fork on Linux), before that worker executes its first task. Two jobs (down from three - see
    module docstring for why the rate-limiter descaling job is gone entirely under the decoupled
    design):
    """
    # 1. tesseract's LSTM engine can multi-thread itself internally via OpenMP - without this, N
    # worker PROCESSES (not just N threads within one process) would each ALSO spread across
    # every core, nest-oversubscribing well past the pool's own --workers sizing. Same fix
    # local_identify_printing_tags.py's own concurrent path already applies.
    os.environ["OMP_THREAD_LIMIT"] = "1"

    # 2. A DB connection inherited via fork is not safe to reuse - force this worker to open its
    # own fresh connection lazily on its own first query instead (persist_evidence's writes).
    from django.db import connections

    connections.close_all()


@dataclass(frozen=True)
class _FetchOutcome:
    """Result of one fetch-stage task (`_fetch_one_card`, runs on a fetch THREAD - shares memory
    with the rest of this process, so this need not be picklable). `outcome` is `None` when the
    fetch step completed (successfully or with an ordinary, non-lockout failure) and this card
    should proceed to the compute stage; any other value is a terminal outcome that bypasses
    compute entirely (matching the old bundled design's own "skipped-lockout"/"dropped"
    conventions, replicated here so the final summary counts are unchanged)."""

    card_id: int
    content_hash: Optional[int] = None
    image_bytes: Optional[bytes] = None
    fetch_latency_ms: float = 0.0
    outcome: Optional[str] = None


def _fetch_one_card(card_id: int, stop_event: threading.Event) -> _FetchOutcome:
    """Fetch-stage step (thread, not process) - I/O-bound network fetch only, per the decoupling
    design. Returns the RAW fetched bytes (never decoded here - see
    `image_cdn_fetch.fetch_card_image_bytes`'s own docstring for why), never runs any extractor.
    `stop_event` is checked FIRST so a task dispatched after another fetch thread already observed
    a lockout never calls `fetch_card_image_bytes` (and so never fetches) at all."""
    if stop_event.is_set():
        return _FetchOutcome(card_id=card_id, outcome="skipped-lockout")

    try:
        card = Card.objects.select_related("source").get(pk=card_id)
    except Card.DoesNotExist:
        return _FetchOutcome(card_id=card_id, outcome="dropped")

    from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image_bytes

    fetch_started_at = time.monotonic()
    try:
        image_bytes = fetch_card_image_bytes(card, dpi=DEFAULT_FETCH_DPI)
    except GoogleFetchLockoutError:
        stop_event.set()
        logger.error("GoogleFetchLockoutError observed - stopping the run, no further fetches submitted")
        # Matches the old design's "raise, caller treats as a no-op skip" observable behaviour
        # without actually raising through a Future - see module docstring point 2 and this
        # command's own test suite for the exact count this must NOT contribute to.
        return _FetchOutcome(card_id=card_id, outcome="lockout")
    fetch_latency_ms = (time.monotonic() - fetch_started_at) * 1000

    return _FetchOutcome(
        card_id=card_id,
        content_hash=card.content_phash,
        image_bytes=image_bytes,
        fetch_latency_ms=fetch_latency_ms,
        outcome=None,
    )


def _compute_one_card(
    card_id: int,
    content_hash: Optional[int],
    image_bytes: Optional[bytes],
    fetch_latency_ms: float,
    dry_run: bool,
    run_id: str,
    profile: bool = False,
) -> tuple[int, str, Optional[dict[str, float]]]:
    """Module-level (picklable) compute-only work unit for the process pool - takes plain,
    already-fetched data (never a `Card`/`Image` instance re-fetched or re-decoded elsewhere), and
    does the actual pixel decode (`Image.open`, lazy - real decode happens on first access inside
    `compute_card_evidence`'s extractors) plus every CPU-bound extractor. Never touches the
    network and can never raise `GoogleFetchLockoutError` - that can only originate in the fetch
    stage now (see module docstring point 2).

    `profile` (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md): when
    True, a per-card timing dict (`compute_card_evidence`'s own `fetch_ms`/`ocr_group_ms`/
    `legal_line_ms`/`extraction_ms`/`other_ms` breakdown, plus this function's own `wall_ms`
    covering decode + every extractor + `persist_evidence` - i.e. this compute worker's entire
    slice of the work, no fetch/DB-refetch included any more since neither happens here under the
    decoupled design) is built and returned as the third tuple element, exactly as
    `_run_cohort`'s single-writer discipline (see its own docstring) expects - the compute pool's
    OWN worker processes never write the JSONL file directly, only the caller collecting results
    back in the parent process does."""
    from cardpicker.image_evidence import compute_card_evidence, persist_evidence

    wall_started_at = time.monotonic() if profile else None

    image = None
    if image_bytes is not None:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(image_bytes))

    profile_dict: Optional[dict[str, float]] = {} if profile else None
    result = compute_card_evidence(card_id, content_hash, image, fetch_latency_ms, profile=profile_dict)
    if not dry_run:
        persist_evidence(result, run_id=run_id)
    if profile_dict is not None and wall_started_at is not None:
        profile_dict["wall_ms"] = (time.monotonic() - wall_started_at) * 1000
    outcome = "fetch_failed" if result.fields.get("fetch_ok") is False else "ok"
    return card_id, outcome, profile_dict


class _CohortStats:
    """Thread-safe accumulator for the same completed/fetch_failures/progress-line bookkeeping
    the old single-loop design did inline - pulled into its own small class since the decoupled
    driver now records outcomes from two different call sites (the fetch stage's own terminal
    outcomes, and the compute stage's `as_completed`/windowed-wait results) rather than one."""

    def __init__(self, total: int, stdout_write: Any) -> None:
        self._lock = threading.Lock()
        self._total = total
        self._stdout_write = stdout_write
        self.completed = 0
        self.fetch_failures = 0
        self._run_start = time.monotonic()

    def record(self, outcome: str) -> None:
        # "lockout" mirrors the old design's `except GoogleFetchLockoutError: continue` - the one
        # card whose OWN fetch triggered the lockout is not counted at all, matching the exact
        # observable behaviour of the prior raise-and-catch mechanism (see module docstring
        # point 2) without needing an actual exception to propagate through a Future.
        if outcome == "lockout":
            return
        with self._lock:
            self.completed += 1
            if outcome in ("fetch_failed", "dropped"):
                self.fetch_failures += 1
            completed = self.completed
            elapsed = time.monotonic() - self._run_start
        if completed % PROGRESS_EVERY == 0 or completed == self._total:
            rate = completed / elapsed if elapsed > 0 else 0.0
            self._stdout_write(
                f"[{completed}/{self._total}] elapsed={elapsed:.0f}s rate={rate:.3f}/s fetch_failures={self.fetch_failures}"
            )


def _run_cohort(
    cohort_ids: list[int],
    fetch_threads: int,
    workers: int,
    queue_depth: int,
    dry_run: bool,
    run_id: str,
    stdout_write: Any,
    profile: bool = False,
    profile_file: Any = None,
) -> tuple[int, int, bool]:
    """
    The decoupled fetch/compute driver itself. Two concurrent executors:

    - `fetch_pool` (`ThreadPoolExecutor`, I/O-bound) - every `cohort_ids` entry is submitted as
      its own fetch task up front. This is safe to do unconditionally (unlike compute submission
      below) because an unstarted `Future` sitting in a `ThreadPoolExecutor`'s internal queue
      costs a card_id int, not an image buffer - no buffer exists until that thread actually runs
      `_fetch_one_card`, and actual concurrent execution is already bounded to `fetch_threads` by
      the executor itself. This mirrors the old design's own already-accepted pattern of
      submitting an entire cohort's worth of futures to one executor at once.
    - `compute_pool` (`ProcessPoolExecutor`, CPU-bound) - NOT submitted to unconditionally: a
      sliding window (`pending`, capped at `queue_depth`) bounds how many fetched-but-not-yet-
      computed buffers can be outstanding (submitted to the compute pool and not yet complete) at
      once - this is the design doc's own "a bounded number of outstanding fetched-but-not-yet-
      computed buffers... enforced however the implementation chooses to gate submission" (its own
      cited example: "a counting semaphore around handoff to the compute pool" - `wait(...,
      FIRST_COMPLETED)` below is the equivalent windowing primitive for this shape). Once
      `len(pending) >= queue_depth`, this loop blocks on `wait()` until at least one compute task
      finishes before submitting the next fetched buffer - so the fetch stage's OWN
      `as_completed(fetch_futures)` iteration (and therefore the fetch threads feeding it) can
      only run as far ahead of compute as `queue_depth` allows, which is exactly the backpressure
      property the design calls for.

    `profile`/`profile_file` (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md):
    when `profile` is True, each completed compute future's own per-card timing dict (see
    `_compute_one_card`'s docstring) is written as one JSON line to `profile_file` - this function
    is the single writer (every result flows back through `_drain_one_pending` in THIS thread, the
    same single-parent-process discipline the original bundled design's instrumentation used, just
    re-anchored to the decoupled driver instead of the old `as_completed` loop directly in
    `handle()`).

    Returns `(completed, fetch_failures, lockout_hit)` - the same three figures the old single-
    loop design printed in its final summary line.
    """
    stop_event = threading.Event()
    stats = _CohortStats(total=len(cohort_ids), stdout_write=stdout_write)

    with ThreadPoolExecutor(max_workers=fetch_threads) as fetch_pool, ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker
    ) as compute_pool:
        fetch_futures = {fetch_pool.submit(_fetch_one_card, card_id, stop_event): card_id for card_id in cohort_ids}
        pending: "dict[Future[Any], int]" = {}

        def _drain_one_pending() -> None:
            done, _ = wait(set(pending.keys()), return_when=FIRST_COMPLETED)
            for done_future in done:
                card_id = pending.pop(done_future)
                card_profile: Optional[dict[str, float]] = None
                try:
                    _, outcome, card_profile = done_future.result()
                except Exception:
                    logger.exception("Dropped card (uncaught exception in compute stage)")
                    outcome = "dropped"
                stats.record(outcome)
                if profile_file is not None and card_profile is not None:
                    profile_file.write(json.dumps({"card_id": card_id, **card_profile}) + "\n")
                    profile_file.flush()

        for fetch_future in as_completed(fetch_futures):
            fetch_result = fetch_future.result()
            if fetch_result.outcome is not None:
                stats.record(fetch_result.outcome)
                continue

            if len(pending) >= queue_depth:
                _drain_one_pending()

            compute_future = compute_pool.submit(
                _compute_one_card,
                fetch_result.card_id,
                fetch_result.content_hash,
                fetch_result.image_bytes,
                fetch_result.fetch_latency_ms,
                dry_run,
                run_id,
                profile,
            )
            pending[compute_future] = fetch_result.card_id

        while pending:
            _drain_one_pending()

    return stats.completed, stats.fetch_failures, stop_event.is_set()


class Command(BaseCommand):
    help = (
        "Bounded dataset run (2026-07-20): drives compute_card_evidence + persist_evidence over "
        "a prioritized (edhrec_rank-ordered) cohort of cards via a decoupled fetch-thread-pool + "
        "compute-process-pool pipeline (Stage C fetch/compute decoupling design, #228). NOT the "
        "full-catalog harvest - see this command's own module docstring."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Cohort size. Default: {DEFAULT_LIMIT}.")
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_WORKERS,
            help="Compute process pool size - size this to the host's USABLE compute cores (leave "
            "any core pinned to network traffic out of this number), not total core count. "
            f"Overrides the STAGE_C_WORKERS env var if both are set. Default: {DEFAULT_WORKERS} "
            "(owner-confirmed hardware as of 2026-07-20: 8 OCPU total, 1 pinned to network, 7 "
            "usable for compute).",
        )
        parser.add_argument(
            "--fetch-threads",
            type=int,
            default=DEFAULT_FETCH_THREADS,
            help="Fetch-stage thread pool size - I/O-bound, sized a little above "
            "harvest_fetch_limiter.GOOGLE_IMAGE's own max_concurrency=6. Overrides the "
            f"STAGE_C_FETCH_THREADS env var if both are set. Default: {DEFAULT_FETCH_THREADS}.",
        )
        parser.add_argument(
            "--queue-depth",
            type=int,
            default=None,
            help="Bounded number of fetched-but-not-yet-computed buffers allowed outstanding at "
            "once (the backpressure knob between the fetch and compute stages). Overrides the "
            "STAGE_C_QUEUE_DEPTH env var if both are set. Default: workers * "
            f"{DEFAULT_QUEUE_DEPTH_MULTIPLIER} (the design doc's own 'on the order of 2x the "
            "compute pool size' starting point) - a tuning knob for the confirming re-profile, "
            "not a value fixed by the design.",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Free-text run identifier stored on each ImageEvidence/CardScanLog row this run "
            "writes (no PilotRunLedger row - out of scope for this bounded run). Default: "
            "auto-generated from the current UTC timestamp.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Extract but do not persist anything - for timing/sampling only.",
        )
        parser.add_argument(
            "--profile",
            action="store_true",
            default=False,
            help="Diagnostic-only (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-"
            "diagnostic.md): capture a per-card fetch-vs-extraction timing breakdown "
            "(fetch_ms/ocr_group_ms/legal_line_ms/other_ms/extraction_ms/wall_ms) and write one "
            "JSON line per card to --profile-output. Adds a handful of time.monotonic() calls "
            "per card - negligible overhead. Does not persist anything new onto ImageEvidence.",
        )
        parser.add_argument(
            "--profile-output",
            type=str,
            default=None,
            help="Path (inside the container) to write the --profile JSONL to. Default: "
            "/tmp/stagec-profile-<run_id>.jsonl.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        limit: int = options["limit"]
        workers: int = max(1, options["workers"])
        fetch_threads: int = max(1, options["fetch_threads"])
        queue_depth: int = max(
            1,
            options["queue_depth"]
            if options["queue_depth"] is not None
            else int(os.environ.get("STAGE_C_QUEUE_DEPTH", str(workers * DEFAULT_QUEUE_DEPTH_MULTIPLIER))),
        )
        dry_run: bool = options["dry_run"]
        run_id: str = options["run_id"] or f"stagec-cohort-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        profile: bool = options["profile"]
        profile_output: str = options["profile_output"] or f"/tmp/stagec-profile-{run_id}.jsonl"
        profile_file = open(profile_output, "w") if profile else None

        self.stdout.write(
            f"run_id={run_id} limit={limit} workers={workers} fetch_threads={fetch_threads} "
            f"queue_depth={queue_depth} dry_run={dry_run} profile={profile} (decoupled fetch/compute pipeline)"
        )
        if profile:
            self.stdout.write(f"Profile JSONL: {profile_output}")

        # Step 1: cheap name -> min(edhrec_rank) map - see module docstring for why this replaces
        # a per-row correlated subquery.
        t0 = time.monotonic()
        name_rank: dict[str, int] = {}
        rank_rows = (
            CanonicalCard.objects.filter(printing_metadata__edhrec_rank__isnull=False)
            .values("name")
            .annotate(min_rank=Min("printing_metadata__edhrec_rank"))
        )
        for row in rank_rows.iterator():
            key = row["name"].lower()
            existing = name_rank.get(key)
            if existing is None or row["min_rank"] < existing:
                name_rank[key] = row["min_rank"]
        self.stdout.write(f"Built name->edhrec_rank map ({len(name_rank)} names) in {time.monotonic() - t0:.2f}s")

        # Step 2: resume filter - cards whose ImageEvidence row already has every manifest key.
        already_done_ids: set[int] = set()
        for card_id, extractor_versions in ImageEvidence.objects.values_list("card_id", "extractor_versions"):
            if MANIFEST_EXTRACTOR_KEYS.issubset(extractor_versions.keys()):
                already_done_ids.add(card_id)
        if already_done_ids:
            self.stdout.write(f"Resume filter: skipping {len(already_done_ids)} already-fully-processed cards")

        # Step 3: candidate (id, name) pairs, cheapest possible shape for the Python-side sort.
        candidates = (
            Card.objects.filter(content_phash__isnull=False).exclude(id__in=already_done_ids).values_list("id", "name")
        )
        id_name_pairs = list(candidates)
        self.stdout.write(f"{len(id_name_pairs)} eligible cards before cohort slicing")

        def priority_key(pair: tuple[int, str]) -> tuple[float, int]:
            card_id, name = pair
            rank = name_rank.get(name.lower())
            return (rank if rank is not None else math.inf, card_id)

        id_name_pairs.sort(key=priority_key)
        cohort_ids = [card_id for card_id, _name in id_name_pairs[:limit]]
        self.stdout.write(f"Cohort: {len(cohort_ids)} cards (prioritized by edhrec_rank, cold tail last)")

        if not cohort_ids:
            self.stdout.write("Nothing to do.")
            return

        # Close the parent's own DB connection(s) before forking the compute pool - belt-and-
        # braces alongside each compute worker's own _init_worker close_all() call, so the
        # connection this command's own step 1/2/3 queries above used is never inherited by any
        # child either. Fetch threads keep using this same parent-process connection pool (safe -
        # threads within one process, unlike a fork).
        from django.db import connections as _parent_connections

        _parent_connections.close_all()

        run_start = time.monotonic()
        try:
            completed, fetch_failures, lockout_hit = _run_cohort(
                cohort_ids=cohort_ids,
                fetch_threads=fetch_threads,
                workers=workers,
                queue_depth=queue_depth,
                dry_run=dry_run,
                run_id=run_id,
                stdout_write=self.stdout.write,
                profile=profile,
                profile_file=profile_file,
            )
        finally:
            if profile_file is not None:
                profile_file.close()

        elapsed = time.monotonic() - run_start
        rate = completed / elapsed if elapsed > 0 else 0.0
        self.stdout.write(
            f"DONE run_id={run_id} completed={completed}/{len(cohort_ids)} elapsed={elapsed:.0f}s "
            f"rate={rate:.3f}/s fetch_failures={fetch_failures} lockout_hit={lockout_hit}"
        )
