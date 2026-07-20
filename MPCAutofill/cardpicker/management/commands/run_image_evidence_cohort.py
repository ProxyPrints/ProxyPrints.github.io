"""
Bounded, owner-authorized dataset run (2026-07-20, converted to a process pool 2026-07-20 per
docs/reports/2026-07-20-pipeline-compute-profile.md's BLOCKING finding): drives Stage C's
per-card callable unit (`cardpicker.image_evidence.extract_card_evidence` + `persist_evidence`)
over a prioritized cohort of cards to produce the FIRST real `ImageEvidence` rows on the live
catalog. This is deliberately NOT the full-catalog harvest (that needs Stage D/E's
pipeline-fidelity + soak gates and a separate owner GO - see docs/features/catalog-completion-
plan.md's "Stage E resume contract" section) - just a simple concurrent driver, matching FINAL
POSTURE item 8a's requirement that the per-card unit stay independent of any particular
bulk-runner shape.

CONCURRENCY MODEL (2026-07-20 rewrite): this command originally used a `ThreadPoolExecutor`.
The compute profile linked above measured that model at `concurrency=6` on this stage's real
workload (fetch + two Tesseract-backed extractors, ocr_group/legal_line = 58% of per-card cost)
and found it 3.25x SLOWER than sequential (`speedup_factor=0.31x`) while burning 27.7x more
CPU-seconds per card - the classic signature of CPU-bound work oversubscribing a fixed core
count, not the I/O-bound fetch case `GOOGLE_IMAGE`'s own concurrency=6 was validated for. Fixed
here with a `ProcessPoolExecutor` sized to the host's USABLE compute cores (owner-confirmed
hardware: 8 OCPU total, 1 pinned to network traffic, 7 usable for compute - `--workers`/
`STAGE_C_WORKERS` default below, env/flag-tunable since core counts vary by host) plus
`OMP_THREAD_LIMIT=1` per worker process, so N worker PROCESSES don't each ALSO spread
tesseract's own internal OpenMP threading across every core (nest-oversubscription - the same
failure mode one level down). Goal: near-linear ~7x wall-clock improvement over sequential,
matching real core count, instead of the measured 0.31x regression.

Three pieces of process-local state that were safely shared across THREADS silently stop being
shared across PROCESSES - each addressed below rather than left as a silent regression:

1. **DB connections.** Django DB connections are not fork-safe to share - a connection opened in
   the parent (e.g. by this command's own edhrec_rank/resume-filter queries before the pool
   starts) must not be used by a forked child. `_init_worker` (the pool's `initializer=`) calls
   `django.db.connections.close_all()` once per worker process, immediately after fork and before
   any task runs, so each worker lazily opens its own fresh connection on first query rather than
   touching anything inherited from the parent. `Card` objects themselves are re-fetched by pk
   inside the worker (not pickled across the process boundary) for the same reason - a card_id
   int is the only thing passed in.

2. **The stop-on-lockout flag.** The old `{"hit": False}` dict closed over by a nested function
   only worked because threads share memory - a `multiprocessing.Manager().Event()` replaces it
   here, checked at the top of `_process_one_card` (module-level, picklable, unlike the old
   closure) for every dispatched task, including ones dispatched to OTHER worker processes after
   the first one observed a lockout. Residual exposure - a task already past that check and
   mid-fetch in another process when the lockout fires - is small, bounded, one-shot per process,
   and is the same residual risk the original thread-based version already accepted (a thread
   already inside `process_one` when the flag flipped would still complete its own in-flight
   fetch too).

3. **The Google-image rate limiter.** `harvest_fetch_limiter._DestinationLimiter` is a
   `threading`-based, process-local module singleton (`get_limiter` returns one shared instance
   PER PROCESS, keyed by destination name) - it was correct under the old thread pool (one
   process, one limiter, shared by every thread) but silently wrong under a process pool: each of
   N worker processes would construct its OWN independent limiter from the unscaled `GOOGLE_IMAGE`
   config (rate_per_sec=8.0, max_concurrency=6), so the AGGREGATE ceiling across all N processes
   would become N times higher than the already owner-validated-safe level (up to 7x6=42
   concurrent fetches worst case, not 6) - see that module's own docstring for why this specific
   ceiling was chosen (a live-site-shared destination, 403 treated as a hard stop). Fixed here
   WITHOUT touching `harvest_fetch_limiter.py`/`image_cdn_fetch.py` (both otherwise untouched):
   `_init_worker` pre-seeds each worker's own process-local `_LIMITERS` registry by calling
   `get_limiter()` once with a WORKERS-SCALED-DOWN `DestinationLimiterConfig` under the exact same
   `"google_image"` name - `get_limiter` only ever constructs a new instance if that name isn't
   already registered, so `fetch_card_image`'s later (unmodified) call to
   `get_limiter(GOOGLE_IMAGE)` finds and reuses this already-registered scaled instance instead of
   building a fresh one from the unscaled constant. `max_concurrency` is floored at 1 per process
   (a worker must be able to make its own single fetch), so the true worst-case aggregate becomes
   `workers` (e.g. 7), not `workers * GOOGLE_IMAGE.max_concurrency` (42) - still technically above
   the exact validated ceiling of 6, but in practice well under it most of the time, since fetch is
   only ~39% of a worker's per-card wall-clock (the rest is CPU-bound OCR, per the compute
   profile), so rarely are all N workers fetching simultaneously. `rate_per_sec` is divided by
   `workers` so the STEADY aggregate rate across all processes approximates the original single
   ceiling. Lockout propagation is NOT handled by this scaling (a 403 observed in one process's own
   scaled-down limiter only flips that process's own `_locked_out` bool) - that's what the
   `stop_event` in point 2 above is for instead; don't confuse the two mechanisms.

`google_limiter.current_rate()` in the old progress line was a real cross-thread signal under the
threaded model; under the process model each worker has its own separate limiter instance, so a
rate read in the PARENT process is no longer meaningful (near-zero/stale, not a lie exactly, just
not the real aggregate) - dropped from the progress line rather than left in as a silently
meaningless number.

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
the whole run, exactly as `image_cdn_fetch.fetch_card_image`'s own docstring requires every
caller to treat it - this command sets a stop flag (a cross-process `Event`, see point 2 above)
the moment one is observed and lets already in-flight work drain, rather than continuing to
submit new work into a destination that has already locked us out.
"""

import json
import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager
from multiprocessing.managers import SyncManager
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Min

from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    DestinationLimiterConfig,
    GoogleFetchLockoutError,
    get_limiter,
)
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
PROGRESS_EVERY = 25


def _init_worker() -> None:
    """Pool `initializer=` - runs once per worker PROCESS, immediately after it starts (fork on
    Linux), before that worker executes its first task. Three jobs, each fixing one piece of
    process-local state that was safely shared under the old thread pool and silently isn't
    under a process pool - see module docstring's numbered list for the full rationale on each.
    """
    # 1. tesseract's LSTM engine can multi-thread itself internally via OpenMP - without this, N
    # worker PROCESSES (not just N threads within one process) would each ALSO spread across
    # every core, nest-oversubscribing well past the pool's own --workers sizing. Same fix
    # local_identify_printing_tags.py's own concurrent path already applies.
    os.environ["OMP_THREAD_LIMIT"] = "1"

    # 2. A DB connection inherited via fork is not safe to reuse - force this worker to open its
    # own fresh connection lazily on its own first query instead.
    from django.db import connections

    connections.close_all()

    # 3. Pre-seed this worker's own process-local rate-limiter registry with a workers-scaled-down
    # config under the SAME destination name, so fetch_card_image's later (unmodified) lookup
    # finds and reuses this instance rather than constructing a fresh one from the unscaled
    # GOOGLE_IMAGE constant - see module docstring point 3 for the full rationale.
    workers = max(1, int(os.environ.get("STAGE_C_ACTIVE_WORKERS", str(DEFAULT_WORKERS))))
    scaled_config = DestinationLimiterConfig(
        name=GOOGLE_IMAGE.name,
        rate_per_sec=GOOGLE_IMAGE.rate_per_sec / workers,
        max_concurrency=max(1, GOOGLE_IMAGE.max_concurrency // workers),
        lockout_status_codes=GOOGLE_IMAGE.lockout_status_codes,
        backoff_status_codes=GOOGLE_IMAGE.backoff_status_codes,
    )
    get_limiter(scaled_config)


def _process_one_card(
    card_id: int, dry_run: bool, run_id: str, stop_event: Any, profile: bool = False
) -> tuple[int, str, Optional[dict[str, float]]]:
    """Module-level (picklable) per-card work unit for the process pool - takes a plain card_id,
    not a `Card` instance, and re-fetches it inside the worker (see module docstring point 1).
    `stop_event` is a `multiprocessing.Manager().Event()` proxy, checked FIRST so a task
    dispatched to this worker after another worker already observed a lockout never calls
    `extract_card_evidence` (and so never fetches) at all.

    `profile` (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md): when
    True, a per-card timing dict (`extract_card_evidence`'s own `fetch_ms`/`ocr_group_ms`/
    `legal_line_ms`/`extraction_ms`/`other_ms` breakdown, plus this function's own `wall_ms`
    covering the whole call including the `Card.objects.get` re-fetch) is built and returned as
    the third tuple element rather than written from inside the worker process - each worker
    writing independently to a shared JSONL file would interleave/corrupt lines; the single
    parent process (the `as_completed` loop below) is the only writer instead."""
    if stop_event.is_set():
        return card_id, "skipped-lockout", None

    # Imported here (not just at module level) so this stays trivially callable/picklable
    # regardless of worker start method - cheap, already-imported-by-Django-app-registry modules.
    from cardpicker.image_evidence import extract_card_evidence, persist_evidence

    wall_started_at = time.monotonic() if profile else None

    try:
        card = Card.objects.select_related("source").get(pk=card_id)
    except Card.DoesNotExist:
        return card_id, "dropped", None

    profile_dict: Optional[dict[str, float]] = {} if profile else None
    try:
        result = extract_card_evidence(card, profile=profile_dict)
    except GoogleFetchLockoutError:
        stop_event.set()
        logger.error("GoogleFetchLockoutError observed - stopping the run, no further work submitted")
        raise
    if not dry_run:
        persist_evidence(result, run_id=run_id)
    if profile_dict is not None and wall_started_at is not None:
        profile_dict["wall_ms"] = (time.monotonic() - wall_started_at) * 1000
    outcome = "fetch_failed" if result.fields.get("fetch_ok") is False else "ok"
    return card_id, outcome, profile_dict


class Command(BaseCommand):
    help = (
        "Bounded dataset run (2026-07-20): drives extract_card_evidence + persist_evidence over "
        "a prioritized (edhrec_rank-ordered) cohort of cards via a process pool sized to the "
        "host's usable compute cores. NOT the full-catalog harvest - see this command's own "
        "module docstring."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Cohort size. Default: {DEFAULT_LIMIT}.")
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_WORKERS,
            help="Process pool size - size this to the host's USABLE compute cores (leave any "
            "core pinned to network traffic out of this number), not total core count. Overrides "
            f"the STAGE_C_WORKERS env var if both are set. Default: {DEFAULT_WORKERS} "
            "(owner-confirmed hardware as of 2026-07-20: 8 OCPU total, 1 pinned to network, 7 "
            "usable for compute).",
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
        dry_run: bool = options["dry_run"]
        run_id: str = options["run_id"] or f"stagec-cohort-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        profile: bool = options["profile"]
        profile_output: str = options["profile_output"] or f"/tmp/stagec-profile-{run_id}.jsonl"
        profile_file = open(profile_output, "w") if profile else None

        # Read by _init_worker in each forked child (env is inherited at fork time) to scale the
        # rate limiter to the ACTUAL worker count this invocation used, not just the module
        # default - see _init_worker's own point 3.
        os.environ["STAGE_C_ACTIVE_WORKERS"] = str(workers)

        self.stdout.write(
            f"run_id={run_id} limit={limit} workers={workers} dry_run={dry_run} profile={profile} " "(process pool)"
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

        completed = 0
        fetch_failures = 0
        run_start = time.monotonic()

        # Close the parent's own DB connection(s) before forking the pool - belt-and-braces
        # alongside each worker's own _init_worker close_all() call, so the connection this
        # command's own step 1/2/3 queries above used is never inherited by any child either.
        from django.db import connections as _parent_connections

        _parent_connections.close_all()

        manager: SyncManager = Manager()
        stop_event = manager.Event()

        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
                futures = {
                    pool.submit(_process_one_card, card_id, dry_run, run_id, stop_event, profile): card_id
                    for card_id in cohort_ids
                }
                for future in as_completed(futures):
                    card_id = futures[future]
                    card_profile: Optional[dict[str, float]] = None
                    try:
                        _, outcome, card_profile = future.result()
                    except GoogleFetchLockoutError:
                        continue
                    except Exception:
                        logger.exception("Dropped card %s (uncaught exception)", card_id)
                        outcome = "dropped"
                    completed += 1
                    if outcome in ("fetch_failed", "dropped"):
                        fetch_failures += 1
                    if profile_file is not None and card_profile is not None:
                        profile_file.write(json.dumps({"card_id": card_id, **card_profile}) + "\n")
                        profile_file.flush()
                    if completed % PROGRESS_EVERY == 0 or completed == len(cohort_ids):
                        elapsed = time.monotonic() - run_start
                        rate = completed / elapsed if elapsed > 0 else 0.0
                        self.stdout.write(
                            f"[{completed}/{len(cohort_ids)}] elapsed={elapsed:.0f}s rate={rate:.3f}/s "
                            f"fetch_failures={fetch_failures}"
                        )
                        self.stdout.flush()
        finally:
            if profile_file is not None:
                profile_file.close()

        # Read stop_event's state BEFORE manager.shutdown() tears down the manager process - the
        # proxy's is_set() call needs a live manager to talk to, and calling it after shutdown()
        # unconditionally raised (every invocation, regardless of cohort size or lockout state -
        # see docs/reports/2026-07-20-canary-reprofile.md's "Bug found" section for the traceback
        # this produced against a real 400-card prod canary).
        lockout_hit = stop_event.is_set()
        manager.shutdown()

        elapsed = time.monotonic() - run_start
        rate = completed / elapsed if elapsed > 0 else 0.0
        self.stdout.write(
            f"DONE run_id={run_id} completed={completed}/{len(cohort_ids)} elapsed={elapsed:.0f}s "
            f"rate={rate:.3f}/s fetch_failures={fetch_failures} lockout_hit={lockout_hit}"
        )
