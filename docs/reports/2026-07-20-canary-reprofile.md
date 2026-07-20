# Stage C canary re-profile on prod (2026-07-20)

Phase 1 (canary) of the payload run authorized against rebuilt prod
(master, DB at migration 0075, `run_image_evidence_cohort` +
`local_calculate_verdicts` present in `mpcautofill_django`). This
follows up `docs/reports/2026-07-20-pipeline-compute-profile.md`
(BLOCKING verdict at x6 thread-pool concurrency, later fixed by
converting the driver to a `ProcessPoolExecutor` — see that command's
own module docstring) with a REAL run against the live catalog to
confirm the fix holds at prod scale, before any 20k/full-harvest
commitment.

## Run parameters

- Command: `python manage.py run_image_evidence_cohort --limit 400 --workers 7 --run-id stagec-canary-20260720T1659Z -v 2`
- Invoked via `sudo docker exec mpcautofill_django ...` from
  `/home/ubuntu/ProxyPrints.github.io/docker`
- Cohort: 400 cards, prioritized by edhrec_rank (cold tail last),
  process pool, 7 workers (host: 8 OCPU, 1 pinned to network per the
  driver's own docstring)
- `dry_run=False` — this is a real, owner-authorized write of fresh
  full-signal `ImageEvidence` rows
- Eligible pool at time of run: 218,212 cards (the driver's own resume
  filter found **zero** cards already carrying every manifest key — the
  pre-existing 18,072-row baseline, see below, does not count as "done"
  under the current 11-key manifest, so this 218,212 is the honest
  remaining-work denominator for both this canary and any future run)

## Timing

| metric                                                                         | value                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| wall-clock, 400 cards (pool's own progress line)                               | 104s                                                                                                                                                                                                                                                                                                                                                                |
| wall-clock, full `docker exec` (incl. crash overhead, see below)               | 108s                                                                                                                                                                                                                                                                                                                                                                |
| steady-state throughput (400-card progress line)                               | 3.852 cards/s                                                                                                                                                                                                                                                                                                                                                       |
| steady-state throughput (300-card slice, cards 100→400, excludes pool warm-up) | 3.797 cards/s                                                                                                                                                                                                                                                                                                                                                       |
| CPU-seconds consumed (container cgroup `cpu.stat` delta)                       | 458.79 CPU-s                                                                                                                                                                                                                                                                                                                                                        |
| CPU-seconds/card                                                               | 1.147                                                                                                                                                                                                                                                                                                                                                               |
| wall-clock/card at 7-way                                                       | 0.260s (3.852/s) – 0.263s (3.797/s)                                                                                                                                                                                                                                                                                                                                 |
| theoretical 7-way CPU budget/card (7 × wall/card)                              | 1.817 CPU-s                                                                                                                                                                                                                                                                                                                                                         |
| **parallel efficiency** (actual CPU-s/card ÷ theoretical budget)               | **63.1%** — well short of the "near-linear ~7x" the process-pool fix targeted; some real speedup held (this is NOT a regression back to the old 0.31x/27.7x-CPU blowup), but overhead (pool dispatch, per-task DB connection setup in `_init_worker`, GIL-adjacent contention, uneven per-card OCR cost) is eating roughly a third of the theoretical parallel gain |

### Projection to the full 218,212-card remaining-work pool

| basis                                                        | projected wall-clock |
| ------------------------------------------------------------ | -------------------- |
| 400-card steady rate (3.852/s)                               | 56,649s = **15.74h** |
| conservative 300-card slice (3.797/s, excludes pool warm-up) | 57,470s = **15.96h** |

Both bases land at **~15.7–16.0h**, above this task's own "~10–12h
post-fix expectation" (a 31–60% overshoot from that range's low/high
ends respectively) and **above the gate's ~15h ceiling** — this is
gate condition (a), triggered, not a near-miss rounding artifact. The
process-pool rewrite genuinely fixed the prior BLOCKING result (x6
thread-pool concurrency projected 377.8h/compute-only 71.2h single-
threaded against a 6.2h reference — see the linked compute-profile
report) but the fix does not fully hold at the "near-linear ~7x" level
its own docstring targets once measured against a real, unmocked prod
workload at 400-card scale rather than the smaller/synthetic sample the
original compute-profile used.

## Extraction failure rate

**0/400 (0%)** — `fetch_failures=0` throughout every progress line, no
`GoogleFetchLockoutError`, no dropped cards. Well under the 5% gate
ceiling.

## New-field population (0069–0075 manifest additions)

Confirmed via DB read against the 400 rows this run wrote
(`run_id=stagec-canary-20260720T1659Z`), compared against the
pre-existing 18,072-row baseline (all runs predating this canary,
`run_id` in `{stagec-cohort-20260720-full, stagec-cohort-calibration}`,
`created_at` 2026-07-20 03:38–10:28 UTC):

| field                                          | old 18,072-row baseline | canary (400 rows)                                                                                                        |
| ---------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `symbol_phash` non-null                        | 0                       | 400/400                                                                                                                  |
| `symbol_crop_px` non-null                      | 0                       | 400/400                                                                                                                  |
| `legal_line_crop_px` non-null                  | 0                       | 400/400                                                                                                                  |
| `legal_line_raw_text` non-blank                | 0                       | 366/400 (34 blank = genuine "nothing found," a real outcome per the model's own null-vs-blank convention, not a failure) |
| `legal_line_proxy_marker_detected` non-null    | 0                       | 400/400                                                                                                                  |
| `color_mean_rgb` / `color_stddev_rgb` non-null | 0                       | 400/400                                                                                                                  |
| `blur_variance` / `image_entropy` non-null     | 0                       | 400/400                                                                                                                  |

All 11 manifest extractor keys present on every canary row
(`fetch_health, geometry_bleed, layout_class, crop_coordinates, collector_line_ocr, artist_ocr, collector_line_tsv, symbol_region, legal_line, quality_signals, color_profile`). The old 18k rows are
confirmed pre-0069–0075 (symbol/legal-line/visual-signal fields
genuinely never computed, not a query artifact) and are NOT
double-counted as "done" by the resume filter — they'll need
reprocessing in any full run, which is already reflected in the
218,212-card remaining-work denominator above.

## Memory

Container (`mpcautofill_django`) cgroup v2 memory, read directly from
`/sys/fs/cgroup/system.slice/docker-<id>.scope/memory.{current,peak}`
before/after (host: 23Gi total per `free -h`):

|                                                                                           | before                | after                 |
| ----------------------------------------------------------------------------------------- | --------------------- | --------------------- |
| `memory.current`                                                                          | 130,494,464 (124 MiB) | 133,025,792 (127 MiB) |
| `memory.peak` (lifetime-of-cgroup high-water mark, not resettable on this kernel — 6.8.0) | 233,934,848 (223 MiB) | 948,031,488 (904 MiB) |

Peak rose to ~904 MiB during the run (7 worker processes + Django +
Tesseract subprocess overhead) — nowhere near the 24GB host ceiling;
gate condition (d) clear.

## Live API

`https://api.proxyprints.ca/2/sources/` → 200 immediately before and
immediately after the run. `https://proxyprints.ca/` → 200 after. No
degradation observed; gate condition (c) clear. (Canary window was
short — 108s — so this is a light check, not a sustained-load test;
Phase 2 §1's own instructions call for periodic polling under a larger,
longer cohort for exactly this reason, which did not run — see below.)

## Index-not-store posture

Confirmed via code read (`cardpicker/image_evidence.py`) before running:
every `*_crop_px` field is coordinates only (`_crop_box_to_pixels`,
explicit docstring: "crop COORDINATES only, never crop pixels");
`symbol_phash` is `imagehash.phash` output (an int) of a region that is
"discarded the moment" it's hashed; `color_mean_rgb`/`color_stddev_rgb`
are aggregate statistics ("store the math, not the strip"). No pixel
buffer, file, or blob is written anywhere in the extraction or persist
path. Gate condition (e) clear.

## Bug found (not fixed — out of this session's scope)

`run_image_evidence_cohort.py` lines 354–361: `manager.shutdown()` is
called, then the final summary `self.stdout.write(...)` on the next
line calls `stop_event.is_set()` — a method on the now-shut-down
`multiprocessing.Manager`'s proxy object. This is a **deterministic,
100%-reproducing crash** (`AttributeError` inside
`multiprocessing.managers`, surfaced as
`FileNotFoundError: [Errno 2] No such file or directory` when the proxy
tries to reconnect to the manager's now-closed socket), independent of
run size or lockout state. Confirmed in this canary's own traceback.

**Does not affect data integrity** — every `persist_evidence` write
happens inside worker processes before the `with ProcessPoolExecutor`
block exits, i.e. before `manager.shutdown()` runs; all 400 rows were
DB-verified present and fully populated regardless of the crash.
Effects are limited to: (1) the final `"DONE run_id=... lockout_hit=..."`
summary line never prints, and (2) `manage.py` (and therefore
`docker exec`) exits non-zero, which would break any automation keyed
on exit code.

Proposed one-line fix (not applied — this session's scope is execution

- reporting, not code changes): capture
  `lockout_hit = stop_event.is_set()` into a local variable _before_
  `manager.shutdown()` is called, then reference that local in the final
  f-string instead of calling the proxy method after shutdown. `run_image_evidence_cohort.py` is not on the PROTECTED CORE list.

## GATE DECISION: STOPPED — condition (a) triggered

Per the owner's "no surprises" gate: projected 218,212-card
compute-only wall-clock at 7-way is **~15.7–16.0h**, above the ~15h
ceiling and above the task's own 10–12h post-fix expectation. All other
gate conditions are clear (0% failure rate, RSS nowhere near the 24GB
ceiling, live API stable, no index-not-store violation), but (a) alone
is sufficient to stop. **Phase 2 (20k cohort + Stage D dry-run) was NOT
run.**

This is not a return to the prior BLOCKING result — the process-pool
fix produced a real, large improvement (from a projected 377.8h at x6
thread-pool concurrency down to ~15.7–16h at 7-way process-pool
concurrency, per the linked compute-profile report) — but it lands
short of the "near-linear ~7x"/10–12h target the fix's own docstring
claims, at 63.1% measured parallel efficiency rather than ~100%. The
gap is real and worth a decision before committing further compute:
either accept ~16h as the working number for the full run, or
investigate the ~37% efficiency loss (pool-dispatch/DB-reconnect
overhead per `_init_worker`, uneven per-card OCR cost, or something
else) before scaling up.
