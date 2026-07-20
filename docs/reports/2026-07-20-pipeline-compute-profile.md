# Pipeline compute profile — Stage C extraction + Stage D calculation (2026-07-20)

Phase 1 of the harvest-calculate compute-profiling task. Data below is
**recovered from the already-finished `pipeline-compute-profile-01`
container's logs** (`sudo docker logs pipeline-compute-profile-01`, exit 0) — the run completed cleanly before this session started and its full
JSON summary was intact, so no re-probe was needed.

## Run parameters (as launched)

- Command: `python manage.py probe_pipeline_compute --sample-size 250 --sequential-size 200 --concurrency 6`
- 250 cards selected (live catalog, read-only), 200 run sequentially,
  50 run at 6-way concurrency
- Host: `cpu_count=8`

## Per-card cost, sequential (n=200)

| Stage           | mean (ms)  | median (ms) | p95 (ms) | % of total |
| --------------- | ---------- | ----------- | -------- | ---------- |
| fetch           | 743.0      | 709.5       | 1160.3   | 38.7%      |
| geometry_bleed  | 51.6       | 50.6        | 61.2     | 2.7%       |
| crop_derivation | 0.008      | 0.007       | 0.009    | ~0%        |
| **ocr_group**   | **800.9**  | 793.2       | 993.3    | **41.7%**  |
| symbol_phash    | 1.8        | 0.8         | 0.8      | 0.1%       |
| legal_line      | 310.8      | 303.3       | 406.9    | 16.2%      |
| visual_signals  | 10.4       | 10.5        | 11.1     | 0.5%       |
| **stage_d**     | **0.18**   | 0.19        | 0.23     | **0.01%**  |
| **total**       | **1918.8** | —           | —        | 100%       |

Wall-clock: 383.8s / 200 cards. CPU: 335.3s (1.68 CPU-s/card, consistent
with mostly single-core work — `avg_cores_busy=0.87`). Peak RSS: 232 MiB.

**Stage D (`stage_d`, the calculation step) is negligible — 0.18ms/card,
0.01% of total.** It is not, and was never going to be, the bottleneck.
The entire per-card cost is Stage C extraction, and within Stage C it is
concentrated in two text-heavy sub-stages: `ocr_group` (Tesseract OCR,
41.7%) and `legal_line` (also OCR-backed, 16.2%) — together 58% of
per-card cost. `fetch` (image download, 38.7%) is the other major
component; it is a separate, already-budgeted stage (see "Fetch vs.
compute" below), not new Stage C/D cost.

## Concurrency behavior (x6, n=50)

|                         | sequential (single-thread) | concurrent (x6)                |
| ----------------------- | -------------------------- | ------------------------------ |
| cards                   | 200                        | 50                             |
| wall-clock              | 383.8s                     | 311.9s                         |
| effective per-card wall | 1.919s                     | **6.238s**                     |
| CPU-seconds             | 335.3s (1.68 CPU-s/card)   | 2324.6s (**46.49 CPU-s/card**) |
| peak RSS                | 232 MiB                    | 290 MiB                        |
| avg cores busy (of 8)   | 0.87                       | 7.45                           |
| throughput              | 0.521 cards/s              | 0.160 cards/s                  |

**Concurrency=6 makes this stage 3.25x _slower_ per card, not faster**
(measured `speedup_factor = 0.31x`), while burning **27.7x more
CPU-seconds per card** (1.68 → 46.49). `avg_cores_busy` rose from 0.87
to 7.45 out of 8 — i.e. concurrency=6 drives the host to near-total CPU
saturation, but the extra CPU goes into contention/scheduling overhead,
not useful throughput. This is the classic signature of CPU-bound work
(Tesseract subprocess/thread-pool internals, OpenCV, etc.) oversubscribing
a fixed core count: 6 concurrent OCR-heavy workers on an 8-core box thrash
each other rather than parallelizing cleanly.

This is a **materially different resource constraint than the fetch
stage's own concurrency=6 finding** (`catalog-completion-plan.md`'s Fetch
Acceleration Study, which validated concurrency=6/rate≈8.0/s as clean for
the _network-bound_ Google Drive fetch path, ceiling being Worker
p95-latency regression, not CPU). That finding does not transfer here:
this profile's bottleneck is CPU-bound compute, and the same concurrency
level that was safe for I/O-bound fetch is actively harmful for CPU-bound
extraction.

## Memory

Peak RSS 232–290 MiB across both sequential and concurrent runs — no OOM
risk at any concurrency level tested. Memory is not a constraint here;
CPU/wall-clock is.

## Projection to the full ~218k-card harvest

Tool's own extrapolation (matches independent recomputation from the
per-card means above):

| n       | single-threaded wall | at measured x6 concurrency | total CPU-seconds      |
| ------- | -------------------- | -------------------------- | ---------------------- |
| 20,000  | 10.7h                | ~34.7h                     | 33,530s (9.3 CPU-h)    |
| 218,000 | **116.2h**           | **~377.8h**                | 365,473s (101.5 CPU-h) |

### Fetch vs. compute, and the ~6.2h reference budget

The ~6.2h figure the task asks to extrapolate against comes from
`catalog-completion-plan.md`'s Fetch Acceleration Study — it is the
_fetch-only_ wall-clock budget for the 181,483 deduped fetch targets at
the validated `concurrency=6`/`rate≈8.0/s` config, and was never meant to
include Stage C/D compute cost. This profile's own per-card unit bundles
fetch + all Stage C extractors + Stage D into a single measured pipeline
(matching how the actual bulk driver, `run_image_evidence_cohort`, is
documented to work: "fetch → extract → evidence → calculate → discard"
as one per-card unit), so the honest comparison is the whole-unit number
above, not a compute-only subset. Both are given for completeness:

- **Whole per-card unit** (fetch+extract+calculate), 218k cards:
  116.2h single-threaded / 377.8h at x6 concurrency vs. the 6.2h
  reference — **18.7x / 60.9x over budget**.
- **Compute-only** (excluding fetch, which has its own already-separately-
  budgeted 6.2h number and shouldn't double-count): 1175.7ms/card ×
  218,000 = 71.2h single-threaded alone — still **11.5x over the 6.2h
  reference budget**, before concurrency's negative scaling is even
  applied.

Either framing lands in the same place: this is not a "somewhat over"
result, it's an order-of-magnitude-plus miss, made worse rather than
better by the concurrency level that was safe for the unrelated fetch
stage.

## BOTTLENECK VERDICT: BLOCKING

Two independent, each-individually-sufficient findings:

1. **Per-card compute cost, at any concurrency, projects to 71–378h for
   the full 218k-card harvest against a 6.2h reference budget** (11.5x–
   61x over). Stage D itself is negligible (0.18ms/card) — the cost is
   entirely Stage C extraction, concentrated in the two OCR-backed
   sub-stages (`ocr_group` 41.7%, `legal_line` 16.2%).
2. **Concurrency does not help and actively hurts**: x6 concurrency (the
   level already validated for the _fetch_ stage) makes this _compute_
   stage 3.25x slower per card and burns 27.7x more CPU-seconds per card,
   because it's CPU-bound OCR work oversubscribing an 8-core host, not
   I/O-bound network fetch. There is no concurrency dial to turn here
   without first addressing the CPU-bound bottleneck itself (e.g.
   capping concurrency well below core count for OCR-heavy stages,
   batching/optimizing Tesseract invocation, or reducing OCR's per-card
   cost directly).

Memory is not a factor (232–290 MiB peak, no OOM risk).

Per the task's gate: this is a genuine BLOCKING bottleneck (per-card
compute cost makes the full 218k harvest infeasible within any budget in
the current implementation, and concurrency scaling actively backfires).
**Phase 2 (the 20k-cohort Stage C extraction + Stage D dry-run test) was
NOT run.**

## Additional findings surfaced while investigating (not part of the

gate reasoning, reported separately per advisor guidance)

- **The task's literal Phase 2 target command (`extract_card_evidence`)
  does not exist as an invokable `manage.py` command in any current
  branch.** `extract_card_evidence` is a pure Python function
  (`cardpicker/image_evidence.py`) per the plan doc's own spec — not a
  bulk-runner command. The actual bulk drivers are `run_image_evidence_cohort`
  (Stage C — present only in worktree `agent-acae3e89f4ba8d761`, commit
  `91444fb0`, unmerged anywhere else) and `local_calculate_verdicts`
  (Stage D — present in several in-flight worktrees including this one,
  dry-run-by-default matching the task's Phase 2 spec, still unmerged to
  `master`). Neither exists in `master` nor in the currently-running prod
  containers.
- **The persistent prod `mpcautofill_django`/`mpcautofill_worker`
  containers are running an older image** (`fd1e2b20...`, built
  2026-07-19T14:35Z) that has none of the Stage C/D commands at all —
  confirmed via `docker exec mpcautofill_django python manage.py --help`.
  Untouched throughout this session; prod stayed up and unmodified the
  entire time (confirmed 200s from both `api.proxyprints.ca` and
  `proxyprints.ca` at the end of this task).
- **The `mpcautofill_django` image tag itself has been overwritten** by a
  one-off build from an unmerged worktree branch (image `ea809c73...`,
  built 2026-07-20T14:43:22Z, immediately before the profile container
  ran) — the tag now points at code well ahead of and divergent from
  `master`. This predates this session and this session took no build/
  deploy action, but it's a live hazard: any future `docker compose up -d --build`/`--force-recreate` on the persistent stack would deploy this
  untested, unmerged snapshot instead of reviewed `master` code. Flagged
  for the owner; not corrected here (outside this task's scope, touches
  deploy state).
- No active `deploy-freeze-active` label found (`gh issue list -R ProxyPrints/ProxyPrints.github.io --label deploy-freeze-active --state all` returned empty) and `WORKERS.md` had no active rows at task start.
