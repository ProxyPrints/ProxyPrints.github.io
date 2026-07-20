# Stage C fetch/compute timing diagnostic (2026-07-20)

Follow-up to `docs/reports/2026-07-20-canary-reprofile.md` (400-card canary,
measured 63.1% parallel efficiency / 4.41 of 7 workers busy on average) and
`docs/features/catalog-completion-plan.md`'s Stage C "fetch/compute
decoupling design" section (#228), which named the bundled per-card
fetch+compute unit as the "almost-certain cause" of the idle-core signature
but explicitly had not measured it — that design's own "Instrumentation spec
for the confirming re-profile" is what this diagnostic implements. Goal: a
small (~100–150 card), `--dry-run` cohort with a real per-card fetch-vs-
extraction timing split, plus the io.stat/network deltas the canary didn't
capture, to confirm (or rule out) fetch-wait as the dominant cause before
committing to #228's decoupling build.

## Instrumentation added

`extract_card_evidence` (`cardpicker/image_evidence.py`) gained an optional
`profile: Optional[dict[str, float]] = None` parameter — when passed a dict,
it's populated in place with a `time.monotonic()`-delta breakdown:
`fetch_ms`, `ocr_group_ms` (collector_line_ocr + artist_ocr +
collector_line_tsv, the first Tesseract-backed extractor group),
`legal_line_ms` (the second Tesseract-backed extractor), `extraction_ms`
(everything after fetch returns, i.e. every extractor combined), and
`other_ms` (`extraction_ms` minus the two OCR-group figures — geometry_bleed
/ layout_class / crop_coordinates / symbol_region / quality_signals /
color_profile combined). `None` by default — zero behavior change, negligible
overhead (a handful of extra `time.monotonic()` calls) when not requested,
and nothing new is persisted onto `ImageEvidence` (matches the design spec's
"aggregated into the run's own summary logging rather than a new persisted
ImageEvidence field").

`run_image_evidence_cohort.py` gained `--profile` (bool) and
`--profile-output PATH` (default `/tmp/stagec-profile-<run_id>.jsonl`).
`_process_one_card` now returns a 3-tuple (`card_id, outcome, profile_dict`)
instead of 2; the profile dict is built inside the worker process but
**written to the JSONL file only by the single parent process**, inside the
existing `as_completed` loop — every worker independently appending to the
same file would interleave/corrupt lines, so the parent (already the sole
consumer of `future.result()`) is the only writer. `_stub_process_one_card`
in `test_run_image_evidence_cohort.py` was updated to match the new
signature/return shape (accepts and ignores `profile`, returns a 3-tuple).

**Decision: left in as permanent, flag-gated code** (not stripped from the
diff) — `--profile` defaults off, the overhead is a few `time.monotonic()`
calls, and the parent-process-only-write design avoids any new
concurrency/correctness risk. Neither file is PROTECTED CORE (checked
against `docs/upstreaming/license-provenance.md` §2's exact list before
editing).

## Run parameters

- Command: `python manage.py run_image_evidence_cohort --limit 130 --workers 7 --dry-run --profile --run-id fetch-compute-timing-diag-20260720T2151Z -v 2`
- Invoked via `sudo docker exec mpcautofill_django ...` — code temporarily
  `docker cp`'d into the already-running, persistent prod container for the
  duration of this diagnostic, then **restored byte-for-byte to its
  pre-diagnostic state afterward** (`diff` confirmed clean) — the real code
  change ships through this PR + the normal deploy/rebuild path, not as a
  standing edit to the live container. Persistent stack was up throughout;
  no restart.
- `dry_run=True` — no `ImageEvidence`/`CardScanLog` rows written; pure timing
  measurement, resume filter untouched (400 already-fully-processed cards
  from prior runs correctly skipped, same as the canary).
- Cohort: 130 cards, prioritized by edhrec_rank (same ordering as the
  canary), process pool, 7 workers.
- Elapsed 36s, 130/130 completed, 0 fetch failures, `lockout_hit=False`,
  3.649 cards/s (canary's own 400-card run measured 3.852/s — same ballpark,
  small-cohort/cohort-position variance expected).

## Per-card timing breakdown (n=130, milliseconds)

| metric                                       | mean    | median  | p95     | stdev  | CV    |
| -------------------------------------------- | ------- | ------- | ------- | ------ | ----- |
| `fetch_ms`                                   | 680.89  | 673.58  | 1135.20 | 286.23 | 0.420 |
| `ocr_group_ms`                               | 785.72  | 757.65  | 1031.72 | 189.93 | 0.242 |
| `legal_line_ms`                              | 306.00  | 312.59  | 428.02  | 99.84  | 0.326 |
| `other_ms`                                   | 91.11   | 69.81   | 91.45   | 91.01  | 0.999 |
| `extraction_ms` (ocr_group+legal_line+other) | 1182.82 | 1149.85 | 1630.91 | 251.00 | 0.212 |
| `wall_ms` (whole `_process_one_card` call)   | 1867.08 | 1852.10 | 2460.85 | 353.75 | 0.189 |

- `fetch_ms` is **36.5% of mean wall-clock**; `extraction_ms` is **63.4%**
  (ocr_group + legal_line alone = 58.5% of wall-clock — matches the
  compute-profile report's independently-derived "58% of per-card cost"
  figure almost exactly).
- `mean(wall_ms) - mean(fetch_ms) - mean(extraction_ms) = 3.37ms` — the
  `Card.objects.get()` re-fetch-by-pk plus any other per-call overhead is
  negligible (~0.18% of wall-clock), not a meaningful per-card cost.
- `corr(fetch_ms, wall_ms) = 0.707`, `corr(extraction_ms, wall_ms) = 0.601`,
  `corr(fetch_ms, extraction_ms) = -0.141` — fetch time and extraction time
  vary independently per card (as expected: different subsystems, no shared
  bottleneck), both contribute materially and comparably to total wall-clock
  variance.
- Extraction's own CV (0.212) is lower than fetch's (0.420) — OCR cost is
  real but the "uneven per-card OCR cost" factor the canary named is a
  **secondary**, not primary, variance source; `other_ms`'s CV (0.999) is
  high in relative terms but its absolute contribution (91ms mean) is small
  next to fetch/OCR.

## Pool-dispatch overhead check

`mean(wall_ms) / 7 = 266.7ms` (the per-card wall-clock this cohort's own
per-card measurements imply at perfect back-to-back 7-way packing) vs.
**276.9ms** actually observed (36s elapsed ÷ 130 cards) — a **3.8%**
overhead, not the ~37% the canary's efficiency ratio suggested. Pool
dispatch / `ProcessPoolExecutor` scheduling overhead is real but small, and
is not the primary driver of the efficiency gap. Caveat: this 36s/130-card
denominator includes one-time pool startup (forking + `_init_worker` running
once per worker process), not excluded the way the canary's own report
separated a "400-card" figure from a "300-card slice, excludes pool warm-up"
specifically to isolate steady-state throughput. At this diagnostic's small
130-card scale, that one-time cost is folded into "per-card overhead" and
could be inflating the 3.8% figure somewhat — true steady-state dispatch
overhead is likely smaller still. Doesn't change the qualitative conclusion
(dispatch isn't the driver either way — even the unadjusted, warm-up-
inflated figure is an order of magnitude below the ~37% gap), so no rerun
was done to isolate it further.

## cgroup io.stat / network deltas (mpcautofill_django, before → after)

| metric                            | before      | after       | delta                                     |
| --------------------------------- | ----------- | ----------- | ----------------------------------------- |
| `io.stat` `rbytes` (block reads)  | 9,175,040   | 9,175,040   | **0**                                     |
| `io.stat` `wbytes` (block writes) | 3,502,080   | 3,530,752   | +28,672 (28 KiB)                          |
| `cpu.stat` `usage_usec`           | 548,409,403 | 708,695,030 | +160,285,627 (160.3 CPU-s)                |
| `memory.current`                  | 161,763,328 | 162,496,512 | +733,184                                  |
| `memory.peak`                     | 948,031,488 | 948,899,840 | +868,352 (well under host's 24GB ceiling) |
| `eth0` rx bytes                   | 315,429,137 | 425,798,426 | +110,369,289 (~105.3 MiB)                 |
| `eth0` tx bytes                   | 7,413,320   | 8,855,096   | +1,441,776 (~1.37 MiB)                    |

- **Block I/O: ~zero incremental reads, negligible (28 KiB) writes** over 130
  cards / 36s — confirms the design spec's negative-control expectation (the
  fetch path is network, not disk; no image buffer, Tesseract temp file, or
  log volume spilled to block storage in any material way) and rules out
  disk contention as an alternative explanation for idle cores.
- **CPU-seconds cross-check**: 160.3 CPU-s ÷ 130 cards = **1.233 CPU-s/card**
  — close to this run's own `extraction_ms` mean (1.183s) and to the
  canary's independently-measured **1.147 CPU-s/card**. This is the key
  cross-validation: cgroup CPU-seconds only counts time actually scheduled
  on a core, and a worker blocked on a network fetch consumes ~0 CPU during
  that block — so "CPU-s/card" was already, implicitly, measuring
  extraction-only cost all along. The canary's "63.1% efficiency" /
  "theoretical 7-way budget of 1.817 CPU-s/card" comparison assumed the
  _entire_ per-card wall-clock (fetch + extraction bundled) would need to be
  CPU-bound for 100% efficiency; since ~36.5% of it structurally isn't
  (fetch is I/O-wait), the "missing" ~37% and the measured 36.5% fetch
  fraction are the same number within measurement noise. Not two
  independent findings — one directly explains the other.
- **Network**: 105.3 MiB received / 1.37 MiB transmitted over 130 dry-run
  cards ≈ 828 KiB/card received. Reported with an explicit caveat, not as a
  clean fetch-only isolate: `eth0` is this container's only network
  interface, so it also carries all Postgres/Elasticsearch container-to-
  container traffic (DB queries for the edhrec-rank map, resume filter, and
  130 `Card.objects.get()` calls) plus any concurrent live-API traffic
  during the 36s window — not exclusively the Google image fetch. Directly
  comparing this to the design doc's own derived ~1.8 MiB _decoded RGB
  buffer_ estimate isn't apples-to-apples either (that figure is
  post-decode memory size, not compressed wire size) — the design doc
  itself frames that arithmetic as a memory-budget check, not a network
  isolate. Treat this number as directional (order-of-magnitude consistent
  with fetching card images at `DEFAULT_FETCH_DPI=250`), not as a precise
  per-image byte count.

## Cross-validation summary

Two independent signals agree: (1) the direct per-card timing split shows
fetch is 36.5% of wall-clock, extraction 63.4%, with pool-dispatch overhead
measured at only ~3.8% and per-task DB-reconnect-adjacent cost at ~0.18%;
(2) the cgroup CPU-seconds/card figure (both this run's 1.233 and the
canary's 1.147) closely matches the direct `extraction_ms` measurement,
which is exactly what you'd see if I/O-wait (not CPU contention, not
scheduling overhead) is what's missing from "CPU-s/card" relative to
"wall/card". Both point at the same cause.

## VERDICT

**The 37% efficiency gap is primarily fetch-wait**, confirming the Stage C
decoupling design's (#228) central hypothesis directly rather than by
inference. Pool-dispatch overhead (~3.8%), per-task DB-reconnect-adjacent
cost (~0.18%), and uneven-OCR-cost (real, secondary — extraction's CV is
lower than fetch's, and it's not large enough to explain a 37% gap on its
own) are all measured and are NOT the dominant cause. Implementing #228's
fetch/compute decoupling design **as specified** is the correct next step —
no different fix is indicated.

**Expected-speedup cross-check**: `1 / (1 - fetch_fraction) = 1 / (1 - 0.365) ≈ 1.574x`. Applied to the canary's own ~15.7–16.0h full-pool projection,
that lands at **~10.0–10.2h** — matching #228's own expected-outcome section
(71.2h compute-only ÷ 7 ≈ 10.2h) to within rounding. This diagnostic's
independently-derived speedup factor and the design doc's own projection
converge on the same number from two different directions (measured
fetch-fraction vs. the compute-profile report's total-compute-hours figure),
which is strong corroborating evidence, not just a plausibility check.

## Prod safety

Persistent stack stayed up throughout (`mpcautofill_django`,
`mpcautofill_worker`, `mpcautofill_postgres`, `mpcautofill_elasticsearch`,
`mpcautofill_nginx` all `Up` before/during/after, no restart). `--dry-run`
used throughout — zero `ImageEvidence`/`CardScanLog` rows written, nothing
to clean up. `https://api.proxyprints.ca/2/sources/` and
`https://proxyprints.ca/` both `200` immediately before and after the run.
Index-not-store posture unaffected (timing measurement only; the JSONL
profile file contains card IDs and millisecond floats, no image data, and
was deleted from the container after being copied out for analysis).
Instrumented code was `docker cp`'d into the running container for the
diagnostic and restored to its exact pre-diagnostic bytes afterward
(`diff`-verified) — the real change ships via this PR's normal review/merge
/deploy path, not as a standing live-container edit.

## Deviations from the task's own scope

- Unit test suite (`pytest`) could not be run inside the persistent prod
  container: `cardpicker/tests/conftest.py`'s session-scoped `autouse`
  `elasticsearch` fixture depends on `testcontainers`, which needs a Docker
  socket the running webserver container doesn't have (and shouldn't be
  given, for prod-safety reasons). Verified correctness instead via (1)
  `ast.parse` syntax check, (2) careful manual review of the diff against
  the existing extractor control flow, and (3) two live, real dry-run
  invocations against prod (a 3-card smoke test, then the 130-card
  diagnostic itself) — the second of these is a more meaningful integration
  check than the mocked unit test would have been anyway, since it exercises
  the real ORM, real fetch, real Tesseract calls, and the real
  `ProcessPoolExecutor`/`Manager` machinery end-to-end. Existing
  `test_run_image_evidence_cohort.py` was updated to match the new
  `_process_one_card` signature/return shape so it stays correct for CI
  (which does have a working test-container setup), but was not itself
  executed in this session.
- `WORKERS.md` row could not be added: this session is sandboxed to a
  worktree checkout and its edit tooling refuses writes to the shared,
  machine-local `WORKERS.md` at the main checkout path (by design, per the
  "worktree absolute path trap" lesson). Confirmed before starting that no
  other session had an active row and no `deploy-freeze-active` label was
  set; the diagnostic run itself was small (130 cards, 36s) and is already
  complete, so the coordination window has closed without incident, but a
  genuinely long-running or larger future run from a worktree session should
  get this fixed (or have the owning session's row added by a session that
  can reach the real `WORKERS.md`).
