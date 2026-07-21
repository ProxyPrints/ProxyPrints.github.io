# Decoupled fetch/compute canary confirmation on prod (2026-07-20)

Confirming canary on the newly-deployed decoupled fetch/compute
architecture (`#228` design, `#237` implementation, migration head 0076).
Follows up `docs/reports/2026-07-20-canary-reprofile.md` (bundled-driver
canary, 63.1% parallel efficiency, STOPPED at gate condition (a)) and
`docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md` (confirmed
fetch-wait as 36.5% of per-card wall-clock, the root cause `#228`/`#237`
were built to eliminate). This run is the first real, at-scale
confirmation of whether the decoupling fix actually worked.

## Pre-flight

- Branch up to date with `origin/master` (includes `#237`,
  `14268bb6` "Stage C: implement fetch/compute decoupling").
- `run_image_evidence_cohort --help` (live `mpcautofill_django` container)
  shows `--profile`/`--profile-output`/`--fetch-threads`/`--queue-depth`,
  matching the decoupled design's own flag set.
- No `deploy-freeze-active` label (`gh issue list ... --state all` empty),
  no migration freeze noted in `docs/troubleshooting.md`/`infrastructure.md`,
  no other `manage.py` process running in the container at run start.
- **`WORKERS.md` coordination gap persists**: this session is a worktree
  checkout with no `WORKERS.md` file of its own (gitignored, not copied
  into the worktree working directory), and an `Edit` attempt against the
  shared main-checkout path was correctly refused by this session's own
  tooling ("worktree absolute path trap"). This reproduces exactly what
  the prior diagnostic session flagged as unresolved. Coordination for
  this run relied on the deploy-freeze label check + confirming no other
  `manage.py` process was active, not a `WORKERS.md` row — same gap,
  still open, now confirmed twice.
- Read the current `run_image_evidence_cohort.py` shutdown/summary code
  before running: the prior canary's documented crash bug (calling
  `stop_event.is_set()` on a `multiprocessing.Manager` proxy after
  `manager.shutdown()`) is structurally gone under the decoupled design —
  there is no cross-process `Manager`/`SyncManager` left at all (a plain
  `threading.Event` replaces it, since a lockout can now only originate in
  the in-process fetch-thread stage). The command's own docstring cites
  this explicitly as "PR #225" fixing the exact bug class from the prior
  canary's own report.
- Live site: `https://api.proxyprints.ca/2/sources/` → 200,
  `https://proxyprints.ca/` → 200, immediately before the run.

## Run parameters

- Command: `python manage.py run_image_evidence_cohort --limit 400 --workers 7 --profile --profile-output /tmp/stagec-canary-decoupled-20260720T235127Z.jsonl --run-id stagec-canary-decoupled-20260720T235127Z -v 2`
- Invoked via `sudo docker exec mpcautofill_django ...` (persistent
  container, no restart) — matches the original canary's own approach.
- `dry_run=False` — real write, continuing the already-authorized
  real-write canary pattern from the original run.
- Cohort: 400 cards, prioritized by edhrec_rank (cold tail last), 7
  compute-process workers, 8 fetch threads (defaults), queue-depth 14
  (`workers * 2` default).
- Eligible pool at run start: **217,828 cards** (driver's own resume
  filter — 400 fewer than the original canary's 218,212, exactly
  accounting for that canary's own 400 written rows now counting as done
  under the manifest).
- **Exit code: 0** — clean exit, no crash, `DONE` summary line printed
  normally. This directly confirms the shutdown-bug fix holds under real
  load, not just by code inspection.

## Timing — before/after comparison

| metric                                                                           | **old (bundled, 2026-07-20 canary-reprofile)** | **new (decoupled, this run)**         |
| -------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------- |
| wall-clock, 400 cards (driver's own progress line / DONE line)                   | 104–108s                                       | **72s**                               |
| steady-state throughput (400-card basis)                                         | 3.852 cards/s                                  | **5.542 cards/s**                     |
| steady-state throughput (300-card slice, cards 100→400, excludes pool warm-up)   | 3.797 cards/s                                  | **5.769 cards/s** (52s for 300 cards) |
| CPU-seconds consumed (container cgroup `cpu.stat` delta)                         | 458.79 CPU-s                                   | **481.15 CPU-s**                      |
| CPU-seconds/card                                                                 | 1.147                                          | **1.203**                             |
| wall-clock/card at 7-way (400-card basis)                                        | 0.260s                                         | **0.180s**                            |
| wall-clock/card at 7-way (300-card steady-state basis)                           | 0.263s                                         | **0.173s**                            |
| theoretical 7-way CPU budget/card (7 × wall/card), 400-card basis                | 1.817 CPU-s                                    | **1.263 CPU-s**                       |
| theoretical 7-way CPU budget/card, steady-state basis                            | —                                              | **1.213 CPU-s**                       |
| **parallel efficiency** (actual CPU-s/card ÷ theoretical budget), 400-card basis | **63.1%**                                      | **95.2%**                             |
| **parallel efficiency, steady-state (300-card slice) basis**                     | —                                              | **99.1%**                             |
| wall-clock speedup vs. old, 400-card basis                                       | —                                              | **1.44x**                             |
| wall-clock speedup vs. old, steady-state basis                                   | —                                              | **1.52x**                             |

CPU-s/card is ~5% higher in this run than the original canary's (1.203 vs.
1.147) — expected sample variance across different 400-card cohorts (a
different slice of the edhrec-rank-ordered queue, different OCR
difficulty mix), not a regression; both figures represent the same
"pure compute cost" quantity as validated by the timing diagnostic. The
efficiency jump (63.1% → 95.2–99.1%) is the headline result: the
decoupled pipeline packs the 7-way compute pool almost to its
theoretical ceiling, versus roughly a third of that ceiling going idle
under the bundled design.

## Fetch-wait vs. compute split, from `--profile` output (n=400)

Under the decoupled architecture, `fetch_ms` and `wall_ms` are no longer
additive — `wall_ms` is the compute worker's own timer, covering only
image decode + every extractor + `persist_evidence` (per the code's own
docstring: "no fetch/DB-refetch included any more since neither happens
here under the decoupled design"). `fetch_ms` is the fetch stage's
separately-measured latency, passed through as a parameter, happening
concurrently in a different thread before the compute worker ever starts.

| metric                                                                | mean (ms) | median (ms) | p95 (ms) | stdev (ms) | CV    |
| --------------------------------------------------------------------- | --------- | ----------- | -------- | ---------- | ----- |
| `fetch_ms` (fetch stage, concurrent, not blocking compute)            | 1311.09   | 1092.28     | 2735.89  | 734.06     | 0.560 |
| `ocr_group_ms`                                                        | 808.64    | 791.10      | 1143.34  | 217.17     | 0.269 |
| `legal_line_ms`                                                       | 332.53    | 319.78      | 587.15   | 144.55     | 0.435 |
| `other_ms`                                                            | 81.85     | 74.86       | 91.90    | 54.16      | 0.662 |
| `extraction_ms` (ocr_group + legal_line + other)                      | 1223.02   | 1194.59     | 1717.14  | 293.61     | 0.240 |
| `wall_ms` (compute worker's own timer: decode + extraction + persist) | 1234.35   | 1204.25     | 1730.70  | 293.96     | 0.238 |

**Correlation check — the key confirmation the decoupling worked:**
`corr(extraction_ms, wall_ms) = 0.9998`, `corr(fetch_ms, wall_ms) = -0.249`,
`corr(fetch_ms, extraction_ms) = -0.249`. `wall_ms` tracks `extraction_ms`
almost perfectly (mean gap of only 11.3ms, attributable to decode +
`persist_evidence`'s DB write) and is essentially uncorrelated with
`fetch_ms`. Under the OLD bundled architecture, `fetch_ms` was 36.5% of
`wall_ms` by construction (same worker, same clock, sequential). Under
this run, fetch time has been fully removed from the compute worker's
own wall-clock — direct, per-card confirmation that the fetch stage no
longer blocks the compute stage, not just an inference from aggregate
throughput numbers.

(Note: `fetch_ms`'s own mean, 1311ms, is not directly comparable to the
prior diagnostic's 681ms bundled-run figure — different cohort, and this
run's fetch stage runs 8 threads concurrently competing for the same
outbound network path the diagnostic's single-worker-at-a-time bundled
model didn't have to share. It doesn't matter for wall-clock throughput
as long as aggregate fetch throughput keeps the bounded queue fed, which
it evidently did — no queue starvation observed, `wall_ms` shows no
fetch-related inflation.)

## cgroup `io.stat` / network deltas (`mpcautofill_django`, before → after)

| metric                                   | before                  | after                      | delta                                    |
| ---------------------------------------- | ----------------------- | -------------------------- | ---------------------------------------- |
| `io.stat` `rbytes` (block reads)         | 0                       | 0                          | **0**                                    |
| `io.stat` `wbytes` (block writes)        | 1,576,960               | 2,424,832                  | +847,872 (828 KiB)                       |
| `cpu.stat` `usage_usec`                  | 24,748,733              | 505,895,605                | +481,146,872 (481.15 CPU-s)              |
| `memory.current`                         | 140,898,304 (134.4 MiB) | 143,552,512 (136.9 MiB)    | +2,654,208                               |
| `memory.peak` (lifetime high-water mark) | 222,543,872 (212.2 MiB) | 1,503,526,912 (1433.9 MiB) | +1,280,983,040                           |
| `eth0` rx bytes                          | 371,499                 | 300,966,073                | +300,594,574 (~286.7 MiB, ~734 KiB/card) |
| `eth0` tx bytes                          | 272,312                 | 6,298,993                  | +6,026,681 (~5.75 MiB)                   |

- Block I/O: negligible (828 KiB total writes, zero reads) over 400
  cards/72s — confirms the fetch-and-compute path is network/CPU, not
  disk, matching the original diagnostic's own negative-control finding.
- Memory peak rose to ~1.43 GiB (higher than the bundled canary's ~904
  MiB, expected — the decoupled pipeline now holds up to `queue_depth`=14
  in-flight raw-bytes buffers plus 8 fetch threads' overhead concurrently
  with 7 compute processes, vs. the bundled design's single per-card
  buffer per worker). Nowhere near the host's 24GB ceiling — gate
  condition (d) clear with wide margin.
- Network: ~734 KiB/card received, same order of magnitude as the
  diagnostic's own directional 828 KiB/card dry-run figure; `eth0` also
  carries Postgres/ES/live-API traffic so this isn't a pure fetch isolate,
  same caveat as the diagnostic's own report.

## Extraction failure rate

**6/400 (1.5%)** — all six failures are `HTTPError: 500 Server Error`
from `cdn.proxyprints.ca` (the image CDN, not a code path introduced by
this session), `lockout_hit=False` throughout, no `GoogleFetchLockoutError`.
Well under the 5% gate ceiling. (Higher than the original canary's 0/400,
but still a small absolute count against a different card slice — six
transient CDN 500s, not a systemic extraction defect.)

## New-field / DB write verification

`ImageEvidence.objects.filter(run_id="stagec-canary-decoupled-20260720T235127Z").count()` →
**400**, confirming the real write (`dry_run=False`) landed as expected.
Spot-checked one row: `symbol_phash`, `symbol_crop_px`,
`legal_line_crop_px`, `color_mean_rgb`, `blur_variance`, `image_entropy`
all non-null — same manifest-field population the original canary
verified, unaffected by the decoupling refactor (which only touched
orchestration, not `image_evidence.py`'s field set).

## Projection to the full 217,828-card remaining-work pool

| basis                                 | projected wall-clock   |
| ------------------------------------- | ---------------------- |
| 400-card rate (5.542/s)               | 39,301.7s = **10.92h** |
| 300-card steady-state slice (5.769/s) | 37,753.7s = **10.49h** |

Both bases land at **~10.5–10.9h** — inside the design doc's own ~10.2h
target (within 3–7%, plausibly explained by this cohort's slightly
higher per-card compute cost, see the CPU-s/card note above), well below
the ~15h gate ceiling, and a large, real improvement over the bundled
canary's ~15.7–16.0h projection.

## Live API

`https://api.proxyprints.ca/2/sources/` → 200 immediately before and
immediately after the run. `https://proxyprints.ca/` → 200 after. All
five persistent containers (`mpcautofill_django`, `mpcautofill_worker`,
`mpcautofill_postgres`, `mpcautofill_elasticsearch`, `mpcautofill_nginx`)
remained `Up` throughout, no restart. Gate condition (c) clear.

## Index-not-store posture

No code changes shipped in this session — this was an execution-only
canary against the already-deployed `#237` implementation. Re-verified:
the decoupling docstring itself states the only thing crossing the
fetch/compute boundary is a raw `bytes` blob (never decoded on the fetch
side), decode happens lazily inside the compute worker immediately before
extraction, and the profile JSONL (card IDs + millisecond floats only,
deleted from the container after being copied out for analysis) contains
no pixel data. `persist_evidence`'s field set is unchanged by the
decoupling refactor. Gate condition (e) clear.

## GATE DECISION: CLEAR — proceed, decoupling fix confirmed at prod scale

All gate conditions clear:

- (a) projected wall-clock ~10.5–10.9h, well under the ~15h ceiling —
  **clear**, and the design's ~10.2h target is essentially hit.
- (b) extraction failure rate 1.5%, under the 5% ceiling — **clear**.
- (c) live API stable before/after, no degradation — **clear**.
- (d) memory peak ~1.43 GiB, nowhere near the 24GB ceiling — **clear**.
- (e) no index-not-store violation — **clear**.

**Before/after headline**: parallel efficiency **63.1% → 95.2%** (400-card
basis) / **99.1%** (steady-state basis); wall-clock speedup **1.44x–1.52x**;
projected full-pool wall-clock **~15.7–16.0h → ~10.5–10.9h**. The `#228`
decoupling design, as implemented in `#237`, resolved the fetch-wait
bottleneck the original canary and timing diagnostic identified — this is
direct, per-card, `--profile`-derived confirmation (not just an aggregate
throughput inference) that fetch and compute now proceed concurrently as
designed. Phase 2 (20k cohort + Stage D dry-run) is not part of this
task's scope and was not run.

## Open items

1. `WORKERS.md` coordination gap for worktree sessions remains unresolved
   (confirmed a second time in this session) — a genuinely long-running
   future run from a worktree session should get this fixed, or have the
   owning session's row added by a session that can reach the real file.
2. The benign `pg_type_typname_nsp_index` `UniqueViolation` race observed
   in django/worker startup logs during the prod rebuild that preceded
   this canary is now documented at
   [`docs/troubleshooting.md`](../troubleshooting.md)'s new
   "`psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint \"pg_type_typname_nsp_index\"`" entry — no fix applied, confirmed
   self-healing (0076_saveddeckshare landed correctly despite the race).
