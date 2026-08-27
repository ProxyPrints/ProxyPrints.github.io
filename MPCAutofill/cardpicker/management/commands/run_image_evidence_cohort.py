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
  at any plausible queue depth" conclusion holds a fortiori - PROVIDED fetch submission is itself
  windowed. It was not, until the fix documented immediately below - see that note before trusting
  the arithmetic above against a real multi-day run.

**PARENT-PROCESS MEMORY LEAK - found and fixed 2026-07-22** (two production incidents against the
197,428-card remainder run: an unwatched run OOM-killed the whole box overnight at ~21GB parent
RSS; a re-run the following night was caught and stopped cleanly by a watchdog at 17.3GB after
66,355 cards, ~250-350KB retained per card - the size of one raw fetched image buffer).
Root-caused by a synthetic repro (a throwaway harness reproducing `_run_cohort`'s own loop shape
with tracked, weakref-observable payloads instead of real network/DB calls - see this PR's own
description for the exact numbers, and `test_run_image_evidence_cohort.py`'s
`TestRunCohortFetchMemoryBound` for the same property turned into a permanent regression guard
against the real `_run_cohort`), NOT by re-running the real 197k cohort:

1. **Primary cause (~95% of the effect): fetch submission was never windowed.** The pre-fix
   `_run_cohort` submitted every `cohort_ids` entry to the fetch thread pool UP FRONT
   (`fetch_futures = {fetch_pool.submit(...): card_id for card_id in cohort_ids}`), then only
   gated COMPUTE submission behind `queue_depth` (the `pending` dict below). The design doc's own
   memory-budget arithmetic ("worst-case buffers alive at once ~= fetch threads in flight + queue
   depth + one per compute worker ~= 31") silently assumed fetch completion was ALSO bounded by
   that same window - the implementation never enforced that assumption. Since fetch (I/O-bound,
   paced by `GOOGLE_IMAGE`'s 6-way concurrency limiter) completes cards materially faster than
   compute (CPU-bound OCR across 7 processes) consumes them, fetch raced arbitrarily far ahead of
   the point where its results were used - a repro measured 400/400 synthetic cards' worth of
   raw-image-sized payloads simultaneously alive at peak with the un-windowed submission pattern,
   vs. 22/400 (bounded by `queue_depth`) once fetch submission was ALSO windowed to match. **Fix**:
   `cohort_ids` are now drip-fed into the fetch pool via `_submit_more_fetch()`, capped so total
   outstanding fetch-stage work (in flight + completed-but-not-yet-consumed) never exceeds
   `queue_depth` - the same knob already documented as "the backpressure knob between the fetch
   and compute stages," now actually enforced on both sides of that boundary rather than one.
2. **Secondary cause (~1% of the effect, real but minor - fixed in the same change): the
   `fetch_futures` dict/set was never pruned as futures were consumed.** Even a `Future` whose
   `.result()` has already been read remains reachable (and its retained result - here, a
   `_FetchOutcome` including the full raw image bytes - stays alive) for as long as anything still
   references the `Future` object itself. The old code built `fetch_futures` once and iterated it
   via `as_completed()` without ever removing entries, so every consumed future (not just
   unconsumed ones) stayed resident until the whole cohort finished. **Fix**: entries are discarded
   from the tracking set the instant their result is read, in every code path (including the
   fetch-side terminal-outcome `continue` path).

Ruled out as contributors (checked directly, not assumed): `_CohortStats` holds only integer
counters, never a list/row per card; the live prod container confirmed `DEBUG=False` (so Django's
`connection.queries` per-query growth, which only fires under `DEBUG=True`, cannot be the cause);
`--profile`'s JSONL output is written and flushed per-line, never buffered in memory; the
`already_done_ids` resume-filter set holds bare ints (bytes/card as expected, not the ~250-350KB/
card the incidents showed).

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
resume filter up front so a re-invocation after a kill does not re-pay the fetch+OCR cost for
cards already done, matching task #147's resume-contract spirit without building its full
run-ledger machinery (explicitly out of scope for this bounded run per its own directive).
SINCE 2026-07-30 THAT FILTER IS RUN-SCOPED: it skips cards THIS `run_id` already finished, not
cards SOME run once finished, so a plain invocation redoes the catalogue from scratch and a
resume is `--run-id <the killed run's id>`. `--only-never-extracted` narrows back to the old
identity-scoped predicate. See `already_extracted_card_ids`' own docstring for the full argument
and for the `bleed_diff_mm` case that made the old predicate a permanent blind spot.
    `MANIFEST_EXTRACTOR_KEYS` and `MANIFEST_EXTRACTOR_CURRENT_VERSIONS` are kept in sync with
    `image_evidence.compute_card_evidence`'s own `extractor_versions` assignments (12 keys as of
    pinline_inset's addition, see below) - stale here would silently under-count "already done"
    and re-pay fetch+OCR cost this resume filter exists specifically to avoid.

That sync is now ENFORCED, not merely requested: `.github/scripts/check_extractor_manifest_sync.py`
derives {key: version} from image_evidence.py by AST and fails CI if either constant below
disagrees with it. Two things this prose itself had wrong are the argument for a tether rather
than a sterner comment - it said "12" when the manifest carried 11 keys, and it named
`extract_card_evidence` when the assignments actually live in `compute_card_evidence`. A
hand-written anchor drifts exactly like a hand-written list.

    `artbox_phash` (issue #480, added 2026-07-25) has the same "adding a manifest key stales every
    row's `has_keys` check" consequence every prior manifest addition has had, deliberately - see
    that issue's own binding sequencing comment: this key merges into the manifest, but the resulting
    whole-catalog Stage C pass it makes eligible does NOT run until the owner schedules it (riding
    `#473`/`#472`'s own deploy first, per that comment) - never a standalone `artbox_phash`-only
    backfill, which would duplicate ~218k fetches the combined pass already needs to make anyway.

    `pinline_inset` (added alongside the pinline-inset measurement, 2026-08-14) has the identical
    consequence: every one of the ~220k existing `ImageEvidence` rows now fails `has_keys` for
    lacking this key and becomes eligible for re-extraction, and the resulting whole-catalog Stage C
    pass does not run until the owner schedules it - same posture as `artbox_phash` above, not a
    standalone `pinline_inset`-only backfill.

EVIDENCE TRANSFER (2026-07-25, issue #473 PR-2, folded with issue #472): `_fetch_one_card` checks
`evidence_transfer.find_transfer_source(card)` BEFORE the network fetch call below - a card with a
known `Card.md5_checksum` and an eligible md5-sibling's own CURRENT full-manifest `ImageEvidence`
row gets its own row created via `evidence_transfer.transfer_evidence` instead of paying for a
real fetch+OCR pass over byte-identical content. Terminal outcome `"transferred"` (new, alongside
the pre-existing `"skipped-lockout"`/`"dropped"`) bypasses the compute pool entirely, same as those
- see `_fetch_one_card`'s own docstring for the exact mechanism and `evidence_transfer.py`'s own
module docstring for the pairing/staleness rules that keep this safe.

A `GoogleFetchLockoutError` (403 from the shared Google-bound destination) is a hard stop for
the whole run, exactly as `image_cdn_fetch.fetch_card_image`/`fetch_card_image_bytes`'s own
docstrings require every caller to treat it - this command sets a stop flag (a `threading.Event`,
see point 2 above) the moment one is observed in the fetch stage and lets already in-flight work
drain, rather than continuing to submit new fetch work into a destination that has already locked
us out.

**LEDGER RSS OBSERVABILITY (2026-07-24, docs/proposals/stage-e-streaming.md §3 decision (6)/§1)**:
this command's own `_get_rss_mb` (2026-07-22) already logged RSS to stdout on every progress line,
but never durably - the brief's own live-`PilotRunLedger` verification pass found the task brief's
"flat ~190MB RSS" wave-1 claim unverifiable against anything, since nothing recorded RSS onto a
ledger row. `_CohortStats.peak_rss_mb` now tracks the running max of the same samples the progress
line already takes (no extra `/proc` reads), and `handle()` writes it onto
`ledger.counters["peak_rss_mb"]` alongside the run's other completion counters, closing that gap
for this command. `PilotRunLedger.counters` (a `JSONField`) is extended, not migrated - per the
brief's own recommendation to prefer the existing free-form counters convention over a schema
change where the data fits.

**COLLECTOR-LINE ARTIST WIRING (2026-07-29)**: `compute_card_evidence` grew three artist-aware
inputs (`artist_lexicon`, `printing_artist_lookup`, `card_artist_names`) which drive both the
collector-line escalation gate AND the `artist_ocr_name` storage fallback - see that function's
own `artist_lexicon` docstring paragraph. `stage_e_dispatch._run_stage_c` (the CONVEYOR Stage C
path) threaded all three from the day they landed; THIS command - the POOLED path, and the faster
of the two by 5.5x-9.3x per card - did not, so a card extracted here got none of it and stored a
blank `artist_ocr_name` where the conveyor would have stored a real one. Wiring them here is a
pure parity change: the same card now produces the same stored values down either path.

Each of the three is threaded by whichever mechanism suits a PROCESS pool (the conveyor is
sequential and in-process, so it simply builds all three as locals - none of those options
transfer across a fork):

  1. `artist_lexicon` (~2.5k `CanonicalArtist.name`s, 98 KB pickled) - built ONCE per run in the
     parent (`handle()`, one query, next to `known_set_codes()`) and handed to each worker
     PROCESS exactly once via `ProcessPoolExecutor(initargs=...)`/`_init_worker`, which parks it
     in a module global the compute unit reads. Deliberately NOT a per-submit argument the way
     `known_set_codes` is: a frozenset of ~800 short codes is cheap to re-pickle per card, a
     98 KB lexicon measures at 1.36 ms of pickle round-trip per card (~1.2% of the 109 ms/card
     compute budget) for a value that cannot vary within a run.
  2. `printing_artist_lookup` - constructed per worker process in `_init_worker` (construction
     issues no query of its own; it loads one expansion's `{collector number: artist}` map on
     first touch and answers from memory thereafter, bounded at 64 expansions). Built in the
     WORKER rather than the parent because it is the one of the three that must issue queries at
     CALL time, and a pooled compute worker already holds its own DB connection for
     `persist_evidence`. Its cache therefore spans that worker's whole lifetime rather than the
     conveyor's one batch - strictly better locality, and the only observable difference is that
     a `CanonicalCard.artist` edited mid-run is picked up on the next run rather than the next
     batch.
  3. `card_artist_names` - resolved on the PARENT side, per card, from one
     `collector_line_artist.build_name_artist_lookup()` built once per run, and passed to the
     compute unit as an already-resolved `tuple[str, ...]` (a handful of short strings). That is
     the shape `compute_card_evidence` documents as mandatory - resolved plain data, never a
     callable, so it stays picklable across the pool boundary. Resolving it parent-side is also
     the answer to whether `local_calculate_verdicts._get_cached_candidate_name_index()` is the
     right sharing mechanism here: that cache is per-PROCESS, so letting each of 7 compute workers
     reach for it would build 7 independent copies of the 113k-row `CandidateNameIndex` (measured:
     1.6 s and ~100 MB each) instead of the single one the parent builds. Measured cost of the
     parent-side call: 0.053 ms/card, against a driver loop with ~15.6 ms/card of throughput
     headroom at 7 workers.
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
    wait,
)
from dataclasses import dataclass
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Min
from django.utils import timezone

from cardpicker.collector_line_artist import (
    ArtistLexicon,
    NameArtistLookup,
    PrintingArtistLookup,
    build_name_artist_lookup,
    build_printing_artist_lookup,
    load_artist_lexicon,
)
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.local_calculate_verdicts import known_set_codes
from cardpicker.models import CanonicalCard, Card, ImageEvidence, PilotRunLedger
from cardpicker.modern_artist_credit import LexiconIndex, load_lexicon_index
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)
from cardpicker.utils import get_baked_git_sha, read_card_ids_file

logger = logging.getLogger(__name__)

# The full Stage C manifest as of 2026-08-14 (fetch_health + geometry-bleed + geometry-group +
# OCR-group + artbox-phash + symbol-region + legal-line + quality-signals + pinline-inset;
# color_profile retired 2026-07-27, never consumed downstream) - matches
# image_evidence.compute_card_evidence's own extractor_versions keys exactly. Keep this set in
# sync with that function whenever a new extractor group lands (see module docstring) - and note
# that "keep in sync" is now CHECKED by .github/scripts/check_extractor_manifest_sync.py, so a
# drift fails CI rather than waiting to be noticed.
MANIFEST_EXTRACTOR_KEYS = frozenset(
    {
        "fetch_health",
        "geometry_bleed",
        "layout_class",
        "crop_coordinates",
        "art_edge",
        "collector_line_ocr",
        "artist_ocr",
        "collector_line_tsv",
        "artbox_phash",
        "symbol_region",
        "legal_line",
        "quality_signals",
        "pinline_inset",
    }
)

# Single-source version map (2026-07-28, issue #509): maps each manifest extractor key to the
# CURRENT expected version string from image_evidence.py's per-extractor version constants.
# Used by the version-aware resume filter (below) to reject stale rows whose keys are present
# but whose values still carry an old version tag - e.g. a card with
# "collector_line_ocr": "collector-line-ocr-v1" has the KEY but not the CURRENT VALUE, so it
# should be re-processed, not skipped. Imported by stage_e_dispatch._stage_c_manifest_versions()
# for the streaming filter (same "imported, never reimplemented" posture as MANIFEST_EXTRACTOR_KEYS
# itself). Keep this dict's values in sync with image_evidence.py's version constants whenever a
# version bump lands - ENFORCED by .github/scripts/check_extractor_manifest_sync.py, which
# derives the expected map from image_evidence.py by AST and fails CI on any disagreement.
MANIFEST_EXTRACTOR_CURRENT_VERSIONS: dict[str, str] = {
    "fetch_health": "fetch-health-v2",
    "geometry_bleed": "geometry-bleed-v1",
    "layout_class": "layout-class-v1",
    "crop_coordinates": "crop-coordinates-v1",
    "art_edge": "art-edge-v1",
    "collector_line_ocr": "collector-line-ocr-v3",
    "artist_ocr": "artist-ocr-v4",
    "collector_line_tsv": "collector-line-tsv-v3",
    "artbox_phash": "artbox-phash-v2",
    "symbol_region": "symbol-region-v1",
    "legal_line": "legal-line-v2",
    "quality_signals": "quality-signals-v1",
    "pinline_inset": "pinline-inset-v1",
}


def already_extracted_card_ids(run_id: str, only_never_extracted: bool = False) -> set[int]:
    """
    RUN-SCOPED RESUME (2026-07-30 owner directive: "a bulk run redoes everything from scratch;
    flags tell it to narrow" / "prior runs cannot pollute, but the current run can be resumed").
    This is `local_calculate_verdicts._eligible_cards_queryset`'s run-scoping (PR #604) applied one
    layer up, to Stage C. Read that function's docstring first - the argument is the same one and
    is not restated in full here.

    THE DEFAULT (`only_never_extracted=False`) SCOPES TO `run_id`. A card counts as done only when
    its `ImageEvidence` row carries every `MANIFEST_EXTRACTOR_CURRENT_VERSIONS` entry AND was last
    written by THIS run (`ImageEvidence.run_id`, which `image_evidence.persist_evidence` and
    `evidence_transfer.transfer_evidence` both stamp unconditionally on every write). Since
    `--run-id` defaults to a fresh timestamp, a plain invocation finds nothing already done and
    redoes the catalogue from scratch; re-invoking with the SAME `--run-id` skips exactly the cards
    that run already completed. That is the whole mechanism, and it is what "within-run resume must
    keep working" reduces to: a killed 220k-card run resumes with `--run-id <its own id>`.

    WHAT THIS FIXES, beyond the from-scratch ruling. The previous predicate was IDENTITY-scoped -
    "has this card ever been extracted at these versions" - which made a FIELD ADDED WITHOUT A
    VERSION BUMP permanently unreachable. `ImageEvidence.bleed_diff_mm` is the measured case: NULL
    on 215,921 of 220,579 rows (97.9%), 213,131 of those on rows whose `bleed_class` is a confident
    `bleed` (so `compute_bleed_diff_mm`'s abstain path did not apply). Every row carries the one
    and only `geometry_bleed` version, `geometry-bleed-v1`, so a v1 manifest written BEFORE the
    field existed is indistinguishable from a v1 manifest written after, reads as current, and is
    skipped forever. Run-scoping removes the "forever": the next from-scratch run re-extracts it.

    `only_never_extracted=True` restores the pre-2026-07-30 identity-scoped predicate verbatim, as
    a NARROWING flag - the direction the owner's rule requires ("default the default things,
    disable them with flags"). Note the stale-v1 trap above still applies under that flag, and a
    version bump is still the correct tool for it there; run-scoping only takes the trap off the
    DEFAULT path.

    Scoped in SQL rather than in Python (`ImageEvidence.run_id` is `db_index=True`) so the default
    path no longer streams all 220,579 `extractor_versions` blobs through this process just to
    discard them - `.iterator()` is kept for the `only_never_extracted` path, which still must.
    """
    rows = ImageEvidence.objects.all()
    if not only_never_extracted:
        rows = rows.filter(run_id=run_id)
    return {
        card_id
        for card_id, extractor_versions in rows.values_list("card_id", "extractor_versions").iterator()
        if MANIFEST_EXTRACTOR_CURRENT_VERSIONS.items() <= extractor_versions.items()
    }


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


# COLLECTOR-LINE ARTIST WIRING (2026-07-29, module docstring's own section): the two per-WORKER-
# PROCESS halves of the artist context. Both are set exactly once, by `_init_worker` below, and
# read (never reassigned) by `_compute_one_card`. `None` in either means "the gate and the
# `artist_ocr_name` storage fallback are both off for this process", which is precisely the
# pre-2026-07-29 behaviour of this command - so a caller that constructs a pool WITHOUT this
# initializer degrades to exactly what it used to do rather than crashing, and `_run_cohort` (the
# only production constructor) always passes it.
_WORKER_ARTIST_LEXICON: Optional[ArtistLexicon] = None
_WORKER_PRINTING_ARTIST_LOOKUP: Optional[PrintingArtistLookup] = None
_WORKER_MODERN_ARTIST_LEXICON: Optional[LexiconIndex] = None


def _init_worker(
    artist_lexicon: Optional[ArtistLexicon] = None,
    modern_artist_lexicon: Optional[LexiconIndex] = None,
) -> None:
    """Compute pool `initializer=` - runs once per worker PROCESS, immediately after it starts
    (fork on Linux), before that worker executes its first task. Three jobs (the rate-limiter
    descaling job is gone entirely under the decoupled design - see module docstring):

    `artist_lexicon` (2026-07-29) is `handle()`'s own single per-run `load_artist_lexicon()`
    result, delivered here through `ProcessPoolExecutor(initargs=...)` so it crosses the fork
    boundary ONCE per worker instead of once per card. See the module docstring's COLLECTOR-LINE
    ARTIST WIRING section for why this one travels by initializer while `known_set_codes` travels
    per submit, and why `printing_artist_lookup` is built here rather than shipped from the
    parent.

    `modern_artist_lexicon` (2026-08-04) is `handle()`'s own `load_lexicon_index()` result,
    delivered the same way for the same reason - see `compute_card_evidence`'s own
    `modern_artist_lexicon` docstring paragraph for what it feeds, the ARTIST-CROP FALLBACK.
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

    # 3. Park this process's artist context. `build_printing_artist_lookup()` issues no query at
    # construction (its per-expansion maps load lazily on first touch), so this runs safely on
    # BOTH sides of the `close_all()` above; it is placed after it deliberately, so the resolver
    # can only ever open a connection this worker owns. Skipped entirely when no lexicon was
    # supplied - a `PrintingArtistLookup` with no lexicon alongside it can never be consulted
    # (`_parse_artist_is_contradicted` requires both), so building one would be pure waste.
    global _WORKER_ARTIST_LEXICON, _WORKER_PRINTING_ARTIST_LOOKUP, _WORKER_MODERN_ARTIST_LEXICON
    _WORKER_ARTIST_LEXICON = artist_lexicon
    _WORKER_PRINTING_ARTIST_LOOKUP = None if artist_lexicon is None else build_printing_artist_lookup()
    _WORKER_MODERN_ARTIST_LEXICON = modern_artist_lexicon


def _get_rss_mb() -> Optional[float]:
    """Best-effort PARENT-process resident set size in MB, read from `/proc/self/status`
    (2026-07-22, added after the two OOM incidents this module docstring's "PARENT-PROCESS MEMORY
    LEAK" section describes - see that section for the full mechanism). Deliberately never raises:
    this is a diagnostic/safety add-on, not something a run should fail over just because it's
    running somewhere `/proc` isn't readable (a non-Linux dev box, a locked-down sandbox) - returns
    `None` in that case, and every caller treats `None` as "skip the RSS-dependent behaviour this
    time," never as an error."""
    try:
        with open("/proc/self/status") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


@dataclass(frozen=True)
class _FetchOutcome:
    """Result of one fetch-stage task (`_fetch_one_card`, runs on a fetch THREAD - shares memory
    with the rest of this process, so this need not be picklable). `outcome` is `None` when the
    fetch step completed (successfully or with an ordinary, non-lockout failure) and this card
    should proceed to the compute stage; any other value is a terminal outcome that bypasses
    compute entirely (matching the old bundled design's own "skipped-lockout"/"dropped"
    conventions, replicated here so the final summary counts are unchanged - plus `"transferred"`,
    2026-07-25, issue #473 PR-2's own new terminal outcome, see `_fetch_one_card`'s own docstring).
    `md5_checksum`/`sha256_checksum` (also issue #473 PR-2) are the card's own live values at fetch
    time, carried across to the compute stage for stamping onto the resulting `ImageEvidence` row -
    see `_compute_one_card`'s own docstring.

    `card_name` (2026-07-29, module docstring's COLLECTOR-LINE ARTIST WIRING item 3) is the same
    `Card.name` this fetch step already loaded, carried back so `_run_cohort` can resolve the
    card's `card_artist_names` narrowing tuple in the PARENT process (one shared
    `CandidateNameIndex`) rather than in each compute worker (seven of them). Empty string for
    every terminal outcome that never reaches the compute stage.

    `stale_extractor_keys`/`stored_evidence_fields` (2026-08-19, perf/per-extractor-reextraction):
    read here on the fetch thread (a plain DB read, not itself fetch-bound work) from this card's
    own `current_evidence_queryset` row, if one exists, and carried across so the compute stage
    can carry forward every non-stale extractor's already-stored values rather than recomputing
    them - see `image_evidence.compute_card_evidence`'s own docstring for the mechanism. `None`/
    `None` (a card with no current row yet - e.g. its content_hash just changed, or this is its
    first-ever pass) means "nothing to carry forward," which `compute_card_evidence` already
    treats as "every key is stale" via its own `stored_extractor_versions` absence check."""

    card_id: int
    content_hash: Optional[int] = None
    md5_checksum: Optional[str] = None
    sha256_checksum: Optional[str] = None
    image_bytes: Optional[bytes] = None
    fetch_latency_ms: float = 0.0
    outcome: Optional[str] = None
    card_name: str = ""
    stale_extractor_keys: Optional[frozenset[str]] = None
    stored_evidence_fields: Optional[dict[str, Any]] = None
    stored_extractor_versions: Optional[dict[str, Any]] = None


def _stale_extractor_keys_and_stored_fields(
    card: Card,
) -> "tuple[Optional[frozenset[str]], Optional[dict[str, Any]], Optional[dict[str, Any]]]":
    """PER-EXTRACTOR RE-EXTRACTION (2026-08-19, perf/per-extractor-reextraction): reads this
    card's own CURRENT `ImageEvidence` row (`image_evidence.current_evidence_queryset` - the same
    content_hash+md5 currency rule every other reader of stored evidence uses, imported not
    reimplemented), diffs its `extractor_versions` against `MANIFEST_EXTRACTOR_CURRENT_VERSIONS`,
    and returns `(stale_keys, stored_fields, stored_extractor_versions)` for
    `compute_card_evidence`'s own carry-forward parameters. `(None, None, None)` when there is no
    current row yet (first-ever pass, or the card's content_hash just changed) -
    `compute_card_evidence` already treats an absent `stored_extractor_versions` as "every key is
    stale," so this is the correct "nothing to carry forward" signal, not a special case here.

    Runs on the FETCH thread (a plain DB read, not network I/O, but this function already shares
    the fetch stage's own thread pool and DB connection - no new connection, no new thread)."""
    from cardpicker.image_evidence import (
        EXTRACTOR_OWNED_FIELDS,
        current_evidence_queryset,
    )

    owned_field_names = [name for names in EXTRACTOR_OWNED_FIELDS.values() for name in names]
    row = current_evidence_queryset(card).values("extractor_versions", *owned_field_names).first()
    if row is None:
        return None, None, None
    stored_extractor_versions: dict[str, str] = row.pop("extractor_versions") or {}
    stale_keys = frozenset(
        key
        for key, current_version in MANIFEST_EXTRACTOR_CURRENT_VERSIONS.items()
        if stored_extractor_versions.get(key) != current_version
    )
    return stale_keys, row, stored_extractor_versions


def _fetch_one_card(
    card_id: int, stop_event: threading.Event, run_id: str = "", dry_run: bool = False
) -> _FetchOutcome:
    """Fetch-stage step (thread, not process) - I/O-bound network fetch only, per the decoupling
    design. Returns the RAW fetched bytes (never decoded here - see
    `image_cdn_fetch.fetch_card_image_bytes`'s own docstring for why), never runs any extractor.
    `stop_event` is checked FIRST so a task dispatched after another fetch thread already observed
    a lockout never calls `fetch_card_image_bytes` (and so never fetches) at all.

    EVIDENCE TRANSFER (2026-07-25, issue #473 PR-2's own "BULK resume-filter seam... find where a
    card is about to be fetched" scope item): checked here, BEFORE the network fetch call below -
    `evidence_transfer.find_transfer_source(card)` looks for an md5-sibling's own CURRENT
    full-manifest `ImageEvidence` row; if found, this card's own row is written via
    `evidence_transfer.transfer_evidence` (skipped entirely under `dry_run`, matching
    `_compute_one_card`'s own `dry_run` convention for its real-extraction persist call) and this
    function returns immediately with `outcome="transferred"` - `_run_cohort`'s own main loop
    already treats any non-`None` `outcome` as "record it, never submit to the compute pool" (see
    that function's own `if fetch_result.outcome is not None: ...` branch, unchanged), so this new
    outcome value needs no new branch there. `run_id` is threaded through from `_run_cohort` (an
    otherwise-unused parameter added to this function purely to carry it here)."""
    if stop_event.is_set():
        return _FetchOutcome(card_id=card_id, outcome="skipped-lockout")

    try:
        card = Card.objects.select_related("source").get(pk=card_id)
    except Card.DoesNotExist:
        return _FetchOutcome(card_id=card_id, outcome="dropped")

    from cardpicker.evidence_transfer import find_transfer_source, transfer_evidence

    # `run_id=run_id` - see `evidence_transfer._record_transfer_anomaly`'s own docstring: this
    # call can write a durable anomaly CardScanLog row, which was previously unstamped.
    transfer_source = find_transfer_source(card, run_id=run_id)
    if transfer_source is not None:
        if not dry_run:
            transfer_evidence(card, transfer_source, run_id=run_id)
        return _FetchOutcome(
            card_id=card_id,
            content_hash=card.content_phash,
            md5_checksum=card.md5_checksum,
            sha256_checksum=card.sha256_checksum,
            outcome="transferred",
        )

    from cardpicker.harvest_fetch_limiter import DestinationThrottledError
    from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image_bytes

    stale_extractor_keys, stored_evidence_fields, stored_extractor_versions = _stale_extractor_keys_and_stored_fields(
        card
    )

    fetch_started_at = time.monotonic()
    try:
        image_bytes = fetch_card_image_bytes(card, dpi=DEFAULT_FETCH_DPI)
    except DestinationThrottledError:
        # 2026-07-30 owner rate ruling: `fetch_card_image_bytes` now raises this instead of
        # returning None on a 429/503, so the Stage E dispatcher can tell rate pressure apart from
        # a genuine fetch failure and DEGRADE rather than trip its operating envelope. THIS command
        # is BULK mode, which `operating_envelope.py` explicitly does not govern at all - there is
        # no envelope here to spare, so the distinction buys nothing, and the only thing that
        # matters is that this must not escape through the Future and kill the fetch pool.
        # Deliberately reported as an ordinary un-fetched card (`image_bytes=None`), which is
        # EXACTLY the shape a 429 produced here before this change: bit-for-bit unchanged
        # behaviour for this command. The limiter has still widened its own pacing interval, which
        # is the half that actually protects the destination.
        logger.warning("Throttled fetching card %s - deferring it; the limiter has slowed the pace", card_id)
        return _FetchOutcome(
            card_id=card_id,
            content_hash=card.content_phash,
            md5_checksum=card.md5_checksum,
            sha256_checksum=card.sha256_checksum,
            image_bytes=None,
            fetch_latency_ms=(time.monotonic() - fetch_started_at) * 1000,
            outcome=None,
            card_name=card.name,
            stale_extractor_keys=stale_extractor_keys,
            stored_evidence_fields=stored_evidence_fields,
            stored_extractor_versions=stored_extractor_versions,
        )
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
        md5_checksum=card.md5_checksum,
        sha256_checksum=card.sha256_checksum,
        image_bytes=image_bytes,
        fetch_latency_ms=fetch_latency_ms,
        outcome=None,
        card_name=card.name,
        stale_extractor_keys=stale_extractor_keys,
        stored_evidence_fields=stored_evidence_fields,
        stored_extractor_versions=stored_extractor_versions,
    )


def _compute_one_card(
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
    stale_extractor_keys: Optional[frozenset[str]] = None,
    stored_evidence_fields: Optional[dict[str, Any]] = None,
    stored_extractor_versions: Optional[dict[str, Any]] = None,
) -> tuple[int, str, Optional[dict[str, float]], bool]:
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
    back in the parent process does.

    `short_circuit` (2026-07-21, docs/features/catalog-completion-plan.md's "Recovery-arc lessons"
    item 1): forwarded straight through to `compute_card_evidence` - `None` (the default) resolves
    to that function's own `STAGE_C_NO_SHORTCIRCUIT` env-var default, an explicit `False` is this
    command's own `--no-shortcircuit` escape hatch. The fourth return value, `short_circuited`, is
    `result.short_circuited` verbatim - a per-card diagnostic count `_CohortStats` aggregates into
    the run's own final summary line (never persisted onto `ImageEvidence`), which is how the
    197k-card remainder run itself produces the plan's own "open verification gap" measurement.

    `known_set_codes` (2026-07-23, issue #370's own recorded follow-up): the SET-CODE LEXICON GATE
    `local_calculate_verdicts.known_set_codes()` produces, built ONCE by `handle()` below (one DB
    query in the parent process, not per-card) and forwarded straight through - see
    `compute_card_evidence`'s own docstring for the escalation-loop acceptance criterion this
    controls. Picklable (a plain `frozenset[str]`), so passing it into each `compute_pool.submit`
    call below costs one IPC serialization per card, not a query.

    `md5_checksum`/`sha256_checksum` (2026-07-25, issue #473 PR-2): the card's own live values,
    already read by `_fetch_one_card` (no second query here) and carried across via
    `_FetchOutcome` - forwarded straight through to `compute_card_evidence` for stamping onto the
    resulting `ImageEvidence` row, same as `stage_e_dispatch._run_stage_c`'s own compute step.

    `card_artist_names` (2026-07-29, module docstring's COLLECTOR-LINE ARTIST WIRING item 3): the
    artists who illustrated a printing of THIS card's own name, already resolved to a plain tuple
    by `_run_cohort` in the parent process - never a callable, so this work unit's whole argument
    list stays picklable exactly as `compute_card_evidence`'s own docstring requires. `()` (the
    default) means "don't narrow", byte-identical to the pre-2026-07-29 behaviour.

    `stale_extractor_keys`/`stored_evidence_fields`/`stored_extractor_versions` (2026-08-19,
    perf/per-extractor-reextraction): resolved on the fetch thread by
    `_stale_extractor_keys_and_stored_fields` and forwarded straight through to
    `compute_card_evidence`'s own parameters of the same names - see that function's own docstring
    for the carry-forward mechanism this drives. All three `None` (a card with no current stored
    row) means "nothing to carry forward," which `compute_card_evidence` already resolves to
    "every extractor is stale," i.e. today's full-recompute behaviour.

    THE OTHER ARTIST INPUTS ARE PROCESS STATE, NOT ARGUMENTS. `artist_lexicon`,
    `printing_artist_lookup`, and (2026-08-04) `modern_artist_lexicon` are read off
    `_WORKER_ARTIST_LEXICON`/`_WORKER_PRINTING_ARTIST_LOOKUP`/`_WORKER_MODERN_ARTIST_LEXICON`,
    which `_init_worker` set once when this worker process started - see the module docstring for
    why each travels the way it does. All being `None` (an un-initialised process: a direct unit
    call, a pool built without the initializer) disables the escalation gate and both
    `artist_ocr_name` storage fallbacks entirely, which is exactly what this command did before
    2026-07-29/2026-08-04 - never an error, and never a partially-wired read."""
    from cardpicker.image_evidence import compute_card_evidence, persist_evidence

    wall_started_at = time.monotonic() if profile else None

    image = None
    if image_bytes is not None:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(image_bytes))

    profile_dict: Optional[dict[str, float]] = {} if profile else None
    result = compute_card_evidence(
        card_id,
        content_hash,
        image,
        fetch_latency_ms,
        profile=profile_dict,
        short_circuit=short_circuit,
        known_set_codes=known_set_codes,
        artist_lexicon=_WORKER_ARTIST_LEXICON,
        printing_artist_lookup=_WORKER_PRINTING_ARTIST_LOOKUP,
        card_artist_names=card_artist_names,
        modern_artist_lexicon=_WORKER_MODERN_ARTIST_LEXICON,
        md5_checksum=md5_checksum,
        sha256_checksum=sha256_checksum,
        stale_extractor_keys=stale_extractor_keys,
        stored_evidence_fields=stored_evidence_fields,
        stored_extractor_versions=stored_extractor_versions,
    )
    if not dry_run:
        persist_evidence(result, run_id=run_id)
    if profile_dict is not None and wall_started_at is not None:
        profile_dict["wall_ms"] = (time.monotonic() - wall_started_at) * 1000
    outcome = "fetch_failed" if result.fields.get("fetch_ok") is False else "ok"
    return card_id, outcome, profile_dict, result.short_circuited


class _CohortStats:
    """Thread-safe accumulator for the same completed/fetch_failures/progress-line bookkeeping
    the old single-loop design did inline - pulled into its own small class since the decoupled
    driver now records outcomes from two different call sites (the fetch stage's own terminal
    outcomes, and the compute stage's `as_completed`/windowed-wait results) rather than one.

    `stop_event`/`max_rss_mb` (2026-07-22, the parent-process memory-leak fix - see module
    docstring): every progress line now also logs the parent's own RSS (cheap - one `/proc` read
    per `PROGRESS_EVERY` cards, see `_get_rss_mb`'s own docstring), so the NEXT time this
    accumulates unexpectedly the log itself shows it climbing, rather than only surfacing at an
    OOM or a watchdog kill. `max_rss_mb`, when set (`--max-rss-mb`, default off), makes this a
    self-limiting safety net rather than a passive log line: crossing the threshold sets
    `stop_event` (the SAME stop-on-lockout event the fetch stage already checks, so it drains
    exactly like a lockout does - no new stop mechanism) and records `rss_limit_hit` for
    `handle()` to turn into a nonzero exit. This is deliberately a clean stop, not a hard kill -
    the resume filter (module docstring's "Resume/kill-safety" section) already makes a
    re-invocation after ANY stop safe, so self-limiting before the box's own OOM killer intervenes
    is strictly better than the two incidents this fix responds to."""

    def __init__(
        self,
        total: int,
        stdout_write: Any,
        stop_event: Optional[threading.Event] = None,
        max_rss_mb: Optional[float] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._total = total
        self._stdout_write = stdout_write
        self._stop_event = stop_event
        self._max_rss_mb = max_rss_mb
        self.completed = 0
        self.fetch_failures = 0
        # Recovery-arc lessons item 1 (2026-07-21) - count, don't just enable, the
        # pre-classification short-circuit's own real-world hit rate, so a real run (the 197k
        # remainder in particular) produces the plan's own "open verification gap" measurement
        # data rather than only the 20k-cohort's retrospective estimate.
        self.short_circuited = 0
        # Evidence transfer (2026-07-25, issue #473 PR-2) - a card whose row was created via
        # `evidence_transfer.transfer_evidence` (an md5-sibling's own current row, copied) rather
        # than a real fetch+extraction pass. Counted the same way short_circuited is (a real
        # completion, never a fetch_failures/dropped case), never subtracted from `completed`.
        self.transferred = 0
        self.rss_limit_hit = False
        # peak parent-process RSS observed across this run's own progress-line samples (2026-07-24,
        # docs/proposals/stage-e-streaming.md §3 decision (6)/§1's own "this is a real observability
        # gap" finding - the "flat ~190MB RSS" claim in wave-1's task brief could not be verified
        # against PilotRunLedger.counters because nothing recorded it durably). Sampled at the same
        # PROGRESS_EVERY cadence _get_rss_mb already logs at below - no extra /proc reads, just a
        # running max of a value already being read. None until the first sample lands (mirrors
        # _get_rss_mb's own "None means unavailable/not yet known" convention).
        self.peak_rss_mb: Optional[float] = None
        self._run_start = time.monotonic()

    def record(self, outcome: str, short_circuited: bool = False) -> None:
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
            if outcome == "transferred":
                self.transferred += 1
            if short_circuited:
                self.short_circuited += 1
            completed = self.completed
            elapsed = time.monotonic() - self._run_start
        if completed % PROGRESS_EVERY == 0 or completed == self._total:
            rate = completed / elapsed if elapsed > 0 else 0.0
            rss_mb = _get_rss_mb()
            if rss_mb is not None:
                with self._lock:
                    self.peak_rss_mb = rss_mb if self.peak_rss_mb is None else max(self.peak_rss_mb, rss_mb)
            rss_display = f"{rss_mb:.0f}" if rss_mb is not None else "?"
            self._stdout_write(
                f"[{completed}/{self._total}] elapsed={elapsed:.0f}s rate={rate:.3f}/s "
                f"fetch_failures={self.fetch_failures} short_circuited={self.short_circuited} "
                f"transferred={self.transferred} rss_mb={rss_display}"
            )
            if (
                self._max_rss_mb is not None
                and rss_mb is not None
                and rss_mb >= self._max_rss_mb
                and self._stop_event is not None
                and not self._stop_event.is_set()
            ):
                self.rss_limit_hit = True
                self._stop_event.set()
                self._stdout_write(
                    f"RSS limit exceeded ({rss_mb:.0f}MB >= --max-rss-mb {self._max_rss_mb:.0f}MB) "
                    "- stopping the run cleanly once in-flight work drains; the resume filter "
                    "makes a re-invocation pick up exactly where this one stopped"
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
    short_circuit: Optional[bool] = None,
    max_rss_mb: Optional[float] = None,
    known_set_codes: Optional[frozenset[str]] = None,
    artist_lexicon: Optional[ArtistLexicon] = None,
    name_artist_lookup: Optional[NameArtistLookup] = None,
    modern_artist_lexicon: Optional[LexiconIndex] = None,
) -> tuple[int, int, bool, int, bool, Optional[float]]:
    """
    The decoupled fetch/compute driver itself. Two concurrent executors:

    - `fetch_pool` (`ThreadPoolExecutor`, I/O-bound) - `cohort_ids` are drip-fed into it via
      `_submit_more_fetch()`, NOT all submitted up front (2026-07-22 fix - see module docstring's
      "PARENT-PROCESS MEMORY LEAK" section for the two production incidents this responds to and
      the repro evidence behind it). Submitting the whole cohort at once was previously reasoned
      to be safe because "an unstarted `Future` costs a card_id int, not an image buffer" - true,
      but that reasoning only covers futures that HAVEN'T completed yet; it says nothing about
      futures that HAVE completed but haven't been consumed by this loop yet, each of which DOES
      hold a real fetched-image buffer. Since fetch (paced by `GOOGLE_IMAGE`'s 6-way concurrency
      limiter) completes cards faster than the 7-process CPU-bound compute stage consumes them,
      unbounded upfront submission let fetch race arbitrarily far ahead, accumulating raw image
      buffers for the entire remaining cohort. `outstanding_fetch` now bounds TOTAL outstanding
      fetch-stage work (in flight + completed-but-not-yet-consumed) to `queue_depth` - the same
      knob already documented as "the backpressure knob between the fetch and compute stages," now
      actually enforced on the fetch side too, not just the compute side below.
    - `compute_pool` (`ProcessPoolExecutor`, CPU-bound) - unchanged: a sliding window (`pending`,
      capped at `queue_depth`) bounds how many fetched-but-not-yet-computed buffers can be
      outstanding (submitted to the compute pool and not yet complete) at once - the design doc's
      own "a bounded number of outstanding fetched-but-not-yet-computed buffers... enforced however
      the implementation chooses to gate submission" (its own cited example: "a counting semaphore
      around handoff to the compute pool" - `wait(..., FIRST_COMPLETED)` below is the equivalent
      windowing primitive for this shape).

    `profile`/`profile_file` (2026-07-20, docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md):
    when `profile` is True, each completed compute future's own per-card timing dict (see
    `_compute_one_card`'s docstring) is written as one JSON line to `profile_file` - this function
    is the single writer (every result flows back through `_drain_one_pending` in THIS thread, the
    same single-parent-process discipline the original bundled design's instrumentation used, just
    re-anchored to the decoupled driver instead of the old `as_completed` loop directly in
    `handle()`).

    `short_circuit` (2026-07-21, docs/features/catalog-completion-plan.md's "Recovery-arc lessons"
    item 1): forwarded to every `_compute_one_card` submission - see that function's own docstring.

    `max_rss_mb` (2026-07-22): forwarded to `_CohortStats` - see its own docstring for the
    checkpoint-and-stop mechanism this drives.

    `known_set_codes` (2026-07-23, issue #370's own recorded follow-up): built ONCE by `handle()`
    below and forwarded to every `_compute_one_card` submission - see that function's own
    docstring and `compute_card_evidence`'s own docstring for the mechanism this controls.

    `artist_lexicon`/`name_artist_lookup` (2026-07-29, module docstring's COLLECTOR-LINE ARTIST
    WIRING section): both built ONCE by `handle()` below, and consumed here by two DIFFERENT
    routes because they have two different lifetimes. `artist_lexicon` is handed to the compute
    pool's `initializer=` as `initargs`, so it crosses the fork boundary once per worker PROCESS;
    `name_artist_lookup` never crosses it at all - it is called HERE, on the parent's own driver
    thread, once per card about to be submitted, and only its tiny resolved tuple travels. Both
    `None` (the default, and every test that doesn't thread them) leaves the artist gate and the
    `artist_ocr_name` storage fallback off, exactly as before 2026-07-29.

    `modern_artist_lexicon` (2026-08-04): built ONCE by `handle()` below and handed to the compute
    pool's `initializer=` alongside `artist_lexicon` - same lifetime, same route. `None` (the
    default) leaves the ARTIST-CROP FALLBACK off - see `compute_card_evidence`'s own docstring.

    Returns `(completed, fetch_failures, lockout_hit, short_circuited, rss_limit_hit, peak_rss_mb)`
    - the same three figures the old single-loop design printed in its final summary line, plus the
    short-circuit counter (item 1's own "count it during the real run" ask), the RSS-limit flag, and
    (2026-07-24, docs/proposals/stage-e-streaming.md §3 decision (6)) the peak parent-process RSS
    sampled across the run - `_CohortStats.peak_rss_mb`'s own final value, `None` iff `/proc/self/
    status` was never readable for the whole run (matches `_get_rss_mb`'s own convention).
    """
    stop_event = threading.Event()
    stats = _CohortStats(total=len(cohort_ids), stdout_write=stdout_write, stop_event=stop_event, max_rss_mb=max_rss_mb)

    with ThreadPoolExecutor(max_workers=fetch_threads) as fetch_pool, ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(artist_lexicon, modern_artist_lexicon)
    ) as compute_pool:
        cohort_iter = iter(cohort_ids)
        outstanding_fetch: "set[Future[Any]]" = set()
        pending: "dict[Future[Any], int]" = {}

        def _submit_more_fetch() -> None:
            # Refill outstanding_fetch up to queue_depth from whatever cohort_ids remain - the
            # actual fix for the primary leak (see this function's own docstring above). Called
            # both before the loop starts and after each batch of fetch results is drained, so
            # outstanding_fetch never holds more than queue_depth completed-or-in-flight buffers
            # at once, regardless of how far ahead fetch could otherwise race.
            while len(outstanding_fetch) < queue_depth:
                try:
                    card_id = next(cohort_iter)
                except StopIteration:
                    return
                outstanding_fetch.add(fetch_pool.submit(_fetch_one_card, card_id, stop_event, run_id, dry_run))

        def _drain_one_pending() -> None:
            done, _ = wait(set(pending.keys()), return_when=FIRST_COMPLETED)
            for done_future in done:
                card_id = pending.pop(done_future)
                card_profile: Optional[dict[str, float]] = None
                short_circuited = False
                try:
                    _, outcome, card_profile, short_circuited = done_future.result()
                except Exception:
                    logger.exception("Dropped card (uncaught exception in compute stage)")
                    outcome = "dropped"
                stats.record(outcome, short_circuited=short_circuited)
                if profile_file is not None and card_profile is not None:
                    profile_file.write(json.dumps({"card_id": card_id, **card_profile}) + "\n")
                    profile_file.flush()

        _submit_more_fetch()
        while outstanding_fetch:
            done, _ = wait(outstanding_fetch, return_when=FIRST_COMPLETED)
            for fetch_future in done:
                # Discard as soon as consumed (2026-07-22 fix, the secondary leak - see module
                # docstring) - a completed Future retains its own result (here, a _FetchOutcome
                # including the raw image bytes) for as long as anything still references the
                # Future itself, so this must happen for EVERY outcome, not just the ones that go
                # on to compute.
                outstanding_fetch.discard(fetch_future)
                fetch_result = fetch_future.result()
                if fetch_result.outcome is not None:
                    stats.record(fetch_result.outcome)
                    continue

                if len(pending) >= queue_depth:
                    _drain_one_pending()

                # CARD-NAME NARROWING resolved HERE, in the parent (2026-07-29 - module
                # docstring's COLLECTOR-LINE ARTIST WIRING item 3): one shared
                # `CandidateNameIndex` answers every card, and only the resolved tuple is
                # pickled into the worker. Measured at 0.053 ms/card, so doing it on this
                # single-threaded driver loop costs nothing against the pool's own throughput.
                card_artist_names = () if name_artist_lookup is None else name_artist_lookup(fetch_result.card_name)

                compute_future = compute_pool.submit(
                    _compute_one_card,
                    fetch_result.card_id,
                    fetch_result.content_hash,
                    fetch_result.image_bytes,
                    fetch_result.fetch_latency_ms,
                    dry_run,
                    run_id,
                    profile,
                    short_circuit,
                    known_set_codes,
                    fetch_result.md5_checksum,
                    fetch_result.sha256_checksum,
                    card_artist_names,
                    fetch_result.stale_extractor_keys,
                    fetch_result.stored_evidence_fields,
                    fetch_result.stored_extractor_versions,
                )
                pending[compute_future] = fetch_result.card_id
            _submit_more_fetch()

        while pending:
            _drain_one_pending()

    return (
        stats.completed,
        stats.fetch_failures,
        stop_event.is_set(),
        stats.short_circuited,
        stats.rss_limit_hit,
        stats.peak_rss_mb,
    )


class Command(BaseCommand):
    help = (
        "Bounded dataset run (2026-07-20): drives compute_card_evidence + persist_evidence over "
        "a prioritized (edhrec_rank-ordered) cohort of cards via a decoupled fetch-thread-pool + "
        "compute-process-pool pipeline (Stage C fetch/compute decoupling design, #228). NOT the "
        "full-catalog harvest - see this command's own module docstring. Write mode is the "
        "DEFAULT (pass --dry-run to preview). The forced-dry-run guard (issue #362) applies ONLY "
        "to the targeted --card-ids-file path - it requires a matching COMPLETED dry-run of the "
        "SAME --card-ids-file within --dry-run-window-hours (see --skip-dryrun-check to override). "
        "The routine --limit bulk-harvest path is intentionally UNGATED: unlike the targeted path, "
        "its own dry-run preview pays the same full fetch/OCR/extraction compute cost as a real "
        "run, so the guard's cheap-preview rationale doesn't hold there (owner decision, PR #373)."
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
            "writes, and on this run's own PilotRunLedger row (self-recorded per the same "
            "start/complete lifecycle local_calculate_verdicts already follows). Default: "
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
        parser.add_argument(
            "--card-ids-file",
            type=str,
            default=None,
            help="Path to a newline-separated file of explicit card pks to (re-)extract - "
            "issue #259's targeted re-extraction path (reparse_collector_evidence's own "
            "--selector no-text runbook calls for this to refresh a specific no-text cohort's "
            "OCR read with improved preprocessing). When given, the edhrec_rank priority ordering "
            "is bypassed and --limit is ignored. Since 2026-07-30 this flag is PURELY a scope "
            "narrowing: forcing re-extraction is now the DEFAULT for every path (see "
            "--only-never-extracted), so this no longer needs its own bypass of the resume "
            "filter - the run-scoped filter applies here too, which is a strict gain (a killed "
            "targeted re-extraction now resumes instead of restarting).",
        )
        parser.add_argument(
            "--only-never-extracted",
            action="store_true",
            default=False,
            help="NARROW the cohort to cards NO run has ever extracted at the current manifest "
            "versions - the pre-2026-07-30 identity-scoped resume filter, now opt-in. The default "
            "is run-scoped: a fresh --run-id redoes the catalogue from scratch, and re-invoking "
            "with the SAME --run-id resumes exactly where the previous invocation stopped (owner "
            "ruling: 'a bulk run redoes everything from scratch; flags tell it to narrow'). Use "
            "this to top up coverage cheaply when you are confident no field or classifier "
            "changed under a fixed extractor version - see already_extracted_card_ids' own "
            "docstring for the bleed_diff_mm case where that confidence was misplaced.",
        )
        parser.add_argument(
            "--no-shortcircuit",
            action="store_true",
            default=False,
            help="Disable the collector_line_ocr pre-classification short-circuit (2026-07-21, "
            "docs/features/catalog-completion-plan.md's 'Recovery-arc lessons' item 1) - forces "
            "every card to pay for the full multi-tier escalation even when tier 1 found no "
            "digit character, matching this build's pre-item-1 behavior. For a measurement run "
            "only (e.g. gathering the plan's own 'would a zero-digit tier-1 card ever have "
            "recovered at a later tier' validation data) - the default (short-circuit ON) is the "
            "one the 197k-card remainder run should use. Overrides the STAGE_C_NO_SHORTCIRCUIT "
            "env var when passed; when NOT passed, that env var still applies (checked inside "
            "image_evidence.compute_card_evidence itself).",
        )
        parser.add_argument(
            "--max-rss-mb",
            type=float,
            default=None,
            help="Self-limiting safety net (2026-07-22, added after two production OOM/near-OOM "
            "incidents on the 197k-card remainder run - see module docstring's 'PARENT-PROCESS "
            "MEMORY LEAK' section): when the parent process's own RSS (logged every progress line "
            "regardless of this flag) reaches or exceeds this many MB, the run stops cleanly once "
            "in-flight work drains and exits non-zero, instead of running until the OS OOM-killer "
            "intervenes. Off by default (no ceiling) - the underlying leak this guards against is "
            "fixed in this same change, so this is defense-in-depth, not the primary fix. Safe to "
            "set because a re-invocation CARRYING THIS RUN'S --run-id picks up exactly where the "
            "stopped run left off (the resume filter is run-scoped since 2026-07-30 - see module "
            "docstring's 'Resume/kill-safety' section; the run prints its own resume line at "
            "startup). A re-invocation WITHOUT --run-id starts the cohort over, by design.",
        )
        # Forced-dry-run guard (issue #362, Phase 0 rails, narrowed per owner decision on PR #373's
        # review - see the guard's own call site in handle() for the full reasoning): applies ONLY
        # to a --card-ids-file write, never to the routine --limit bulk-harvest path.
        add_dry_run_guard_arguments(parser, write_flag="a --card-ids-file write")

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
        max_rss_mb: Optional[float] = options["max_rss_mb"]
        run_id: str = options["run_id"] or f"stagec-cohort-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        profile: bool = options["profile"]
        profile_output: str = options["profile_output"] or f"/tmp/stagec-profile-{run_id}.jsonl"
        profile_file = open(profile_output, "w") if profile else None
        # --no-shortcircuit explicitly disables (False); otherwise None defers to
        # image_evidence.compute_card_evidence's own STAGE_C_NO_SHORTCIRCUIT env-var default
        # (short-circuit ON unless that env var is set) - see this flag's own --help.
        short_circuit: Optional[bool] = False if options["no_shortcircuit"] else None
        only_never_extracted: bool = options["only_never_extracted"]

        self.stdout.write(
            f"run_id={run_id} limit={limit} workers={workers} fetch_threads={fetch_threads} "
            f"queue_depth={queue_depth} dry_run={dry_run} profile={profile} "
            f"no_shortcircuit={options['no_shortcircuit']} max_rss_mb={max_rss_mb} "
            f"only_never_extracted={only_never_extracted} "
            "(decoupled fetch/compute pipeline)"
        )
        # The resume filter is run-scoped by default (see already_extracted_card_ids), so a
        # re-invocation must carry this run_id back or it starts over. Printed up front, where an
        # operator watching a run that is about to be killed can still copy it.
        self.stdout.write(f"To resume this run after a stop: --run-id {run_id}")
        if profile:
            self.stdout.write(f"Profile JSONL: {profile_output}")

        # Forced-dry-run guard scope (issue #362, narrowed per owner decision on PR #373's review):
        # the guard applies ONLY to the targeted --card-ids-file path - the closest analogue to the
        # other four commands' own retroactive-fix cohorts, and cheap to preview (a small explicit
        # id list). The routine --limit bulk-harvest path is intentionally UNGATED: write_mode below
        # is forced False whenever no --card-ids-file is given, regardless of --dry-run, so
        # enforce_dry_run_precondition is a guaranteed no-op (no CommandError, no ledger-row
        # precondition) for that path - a --limit run's own "dry-run" still pays full fetch/OCR/
        # extraction compute cost (there is no cheap bulk preview), so the guard's cheap-preview
        # rationale doesn't hold there, and gating it would force every routine harvest invocation
        # to either find a matching recent dry-run of the same --limit or pass --skip-dryrun-check
        # every time. `scope` itself is still computed/recorded for BOTH paths (cheap, and useful
        # audit-trail context even when the guard doesn't consult it for --limit).
        card_ids_file_for_scope: Optional[str] = options["card_ids_file"]
        scope = (
            scope_hash("card_ids_file", card_ids_file_for_scope)
            if card_ids_file_for_scope
            else scope_hash("cohort_limit", limit)
        )
        skip_used = enforce_dry_run_precondition(
            command="run_image_evidence_cohort",
            write_mode=(not dry_run) and bool(card_ids_file_for_scope),
            skip_check=options["skip_dryrun_check"],
            window_hours=options["dry_run_window_hours"],
            scope=scope,
        )

        # Self-recording (2026-07-23): one PilotRunLedger row per invocation, written RUNNING here
        # and updated to COMPLETED/FAILED once the run's aggregate counters are known - the same
        # start/complete lifecycle local_calculate_verdicts already follows, so this command's own
        # completion counters (previously log-only, see this command's prior --run-id help text)
        # are durably queryable by run_id like every other Stage C/D pilot command's are.
        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="run_image_evidence_cohort",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(scope=scope, skip_dryrun_check_used=skip_used),
        )

        try:
            # Resume filter, computed for BOTH selection paths (2026-07-30). It used to be built
            # only inside the --limit branch, so --card-ids-file carried its own hardcoded "force
            # a re-run" bypass. Under run-scoping that bypass is redundant - forcing re-extraction
            # is what the DEFAULT does now - and keeping it would have left the targeted path the
            # one path that cannot resume after a kill. One predicate, both paths.
            already_done_ids = already_extracted_card_ids(run_id, only_never_extracted=only_never_extracted)
            if already_done_ids:
                self.stdout.write(
                    f"Resume filter ({'never-extracted-by-any-run' if only_never_extracted else f'run_id={run_id}'}): "
                    f"skipping {len(already_done_ids)} already-fully-processed cards"
                )

            card_ids_file: Optional[str] = options["card_ids_file"]
            if card_ids_file:
                # Targeted re-extraction path (issue #259) - explicit ids, priority ordering
                # bypassed (see this flag's own --help).
                cohort_ids = [
                    card_id for card_id in read_card_ids_file(card_ids_file) if card_id not in already_done_ids
                ]
                self.stdout.write(
                    f"--card-ids-file given: {len(cohort_ids)} explicit card ids after the resume filter "
                    "(priority ordering bypassed)"
                )
            else:
                # Step 1: cheap name -> min(edhrec_rank) map - see module docstring for why this
                # replaces a per-row correlated subquery.
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
                self.stdout.write(
                    f"Built name->edhrec_rank map ({len(name_rank)} names) in {time.monotonic() - t0:.2f}s"
                )

                # Step 2 (the resume filter) is now computed above, once, for both selection
                # paths - see already_extracted_card_ids.

                # Step 3: candidate (id, name) pairs, cheapest possible shape for the Python-side sort.
                candidates = (
                    Card.objects.filter(content_phash__isnull=False)
                    .exclude(id__in=already_done_ids)
                    .values_list("id", "name")
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
                ledger.status = PilotRunLedger.Status.COMPLETED
                ledger.finished_at = timezone.now()
                ledger.counters = merge_counters(
                    ledger.counters,
                    {
                        "cohort_size": 0,
                        "completed": 0,
                        "fetch_failures": 0,
                        "short_circuited": 0,
                        "lockout_hit": False,
                        "rss_limit_hit": False,
                        # 2026-07-24 (stage-e-streaming.md §3 decision (6)): a single point sample -
                        # there was no batch to sample a peak across, but recording SOMETHING here
                        # keeps this counters shape uniform with the real-cohort path below rather
                        # than silently omitting the key for the empty case.
                        "peak_rss_mb": _get_rss_mb(),
                    },
                )
                ledger.save(update_fields=["status", "finished_at", "counters"])
                with resilient_terminal_output():
                    self.stdout.write("Nothing to do.")
                return

            # Set-code lexicon (2026-07-23, issue #370's own recorded follow-up): built ONCE here
            # (one DB query in the parent process, before the pool forks) and threaded through to
            # every compute worker via `_run_cohort`/`_compute_one_card` - see
            # `compute_card_evidence`'s own docstring for the escalation-loop acceptance criterion
            # this feeds. Same "query once, pass through explicitly" convention step 1/2 above
            # already use for name_rank/already_done_ids.
            lexicon = known_set_codes()

            # COLLECTOR-LINE ARTIST WIRING (2026-07-29 - see the module docstring's own section
            # for the full rationale and the measurements behind each choice). Both built ONCE
            # here, in the parent, on the same "query once, pass through explicitly" convention
            # `lexicon` immediately above already uses - and, like it, built only AFTER the
            # "Nothing to do" early return above, so a run whose cohort is empty never pays for
            # either. That laziness matters most for `build_name_artist_lookup()`: it is backed by
            # `local_calculate_verdicts._get_cached_candidate_name_index()`, the single
            # process-cached entry point that module requires every batch-reachable caller to use,
            # and building its 113k-row `CandidateNameIndex` measures at 1.6 s / ~100 MB - the
            # same "only once there is really work to do" posture `_run_stage_c` and
            # `run_join_key_calculator` already practise.
            artist_lexicon = load_artist_lexicon()
            name_artist_lookup = build_name_artist_lookup()
            # ARTIST-CROP FALLBACK (2026-08-04): same "query once, pass through explicitly"
            # convention as the two lookups immediately above - see `compute_card_evidence`'s own
            # `modern_artist_lexicon` docstring paragraph.
            modern_artist_lexicon = load_lexicon_index()

            # Close the parent's own DB connection(s) before forking the compute pool - belt-and-
            # braces alongside each compute worker's own _init_worker close_all() call, so the
            # connection this command's own step 1/2/3 queries above used is never inherited by any
            # child either. Fetch threads keep using this same parent-process connection pool (safe -
            # threads within one process, unlike a fork).
            from django.db import connections as _parent_connections

            _parent_connections.close_all()

            run_start = time.monotonic()
            try:
                completed, fetch_failures, lockout_hit, short_circuited, rss_limit_hit, peak_rss_mb = _run_cohort(
                    cohort_ids=cohort_ids,
                    fetch_threads=fetch_threads,
                    workers=workers,
                    queue_depth=queue_depth,
                    dry_run=dry_run,
                    run_id=run_id,
                    stdout_write=self.stdout.write,
                    profile=profile,
                    profile_file=profile_file,
                    short_circuit=short_circuit,
                    max_rss_mb=max_rss_mb,
                    known_set_codes=lexicon,
                    artist_lexicon=artist_lexicon,
                    name_artist_lookup=name_artist_lookup,
                    modern_artist_lexicon=modern_artist_lexicon,
                )
            finally:
                if profile_file is not None:
                    profile_file.close()

            elapsed = time.monotonic() - run_start
            rate = completed / elapsed if elapsed > 0 else 0.0
            final_rss_mb = _get_rss_mb()
            # A tiny cohort (fewer cards than PROGRESS_EVERY) never trips _CohortStats.record's own
            # sampling cadence, so peak_rss_mb could still be None even though _get_rss_mb itself
            # works fine on this host - fold in this post-run sample too, so "no peak recorded" only
            # ever means "/proc/self/status was genuinely unreadable for this whole run", matching
            # _get_rss_mb's own documented None convention, not "the cohort happened to be small".
            if final_rss_mb is not None:
                peak_rss_mb = final_rss_mb if peak_rss_mb is None else max(peak_rss_mb, final_rss_mb)

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the DONE summary print below - a BrokenPipeError on a
            # severed stdout while printing that summary must never look like this run failed.
            # Written COMPLETED (not FAILED) even when --max-rss-mb is about to force a nonzero
            # exit below - the run itself drained cleanly and every write up to this point already
            # committed (module docstring's "this is a checkpoint, not a failure to recover from"),
            # so the ledger's own status should say the same thing the docstring already argues.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(
                ledger.counters,
                {
                    "cohort_size": len(cohort_ids),
                    "completed": completed,
                    "fetch_failures": fetch_failures,
                    "short_circuited": short_circuited,
                    "lockout_hit": lockout_hit,
                    "rss_limit_hit": rss_limit_hit,
                    "elapsed_s": round(elapsed, 1),
                    "peak_rss_mb": peak_rss_mb,
                },
            )
            ledger.save(update_fields=["status", "finished_at", "counters"])

            with resilient_terminal_output():
                self.stdout.write(
                    f"DONE run_id={run_id} completed={completed}/{len(cohort_ids)} elapsed={elapsed:.0f}s "
                    f"rate={rate:.3f}/s fetch_failures={fetch_failures} lockout_hit={lockout_hit} "
                    f"short_circuited={short_circuited} rss_limit_hit={rss_limit_hit} "
                    f"rss_mb={f'{final_rss_mb:.0f}' if final_rss_mb is not None else '?'} "
                    f"peak_rss_mb={f'{peak_rss_mb:.0f}' if peak_rss_mb is not None else '?'}"
                )

            if rss_limit_hit:
                # Nonzero exit (2026-07-22, item 3's own "cleanly checkpoints+exits nonzero" ask) -
                # every persist_evidence write up to this point already committed and the resume
                # filter (module docstring's "Resume/kill-safety" section) makes a re-invocation safe,
                # so this is a checkpoint, not a failure to recover from.
                raise CommandError(
                    f"--max-rss-mb={max_rss_mb:.0f} exceeded - run stopped cleanly at "
                    f"completed={completed}/{len(cohort_ids)}; re-invoke the same command to resume "
                    "(the resume filter skips everything already fully processed)."
                )
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed,
            # docs/proposals/stage-e-streaming.md §3 decision (6)/§10) - a no-op for a genuine
            # mid-run failure ONLY when the ledger row is still RUNNING; the --max-rss-mb
            # CommandError above already moved the row to COMPLETED with its counters filled in
            # before raising, so this call is a no-op for that path (matching
            # local_calculate_verdicts's own convention, scoped to not overwrite a completion this
            # run genuinely reached). When it DOES apply, records a triage-able
            # counters["failure_reason"] alongside FAILED, closing the "empty-failed-row" gap
            # (PilotRunLedger id 71, `run_id=rescan-wave1-20260724`) mark_ledger_failed's own
            # docstring cites.
            mark_ledger_failed(ledger, exc)
            raise
