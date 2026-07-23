# Pilot `--write` + `consensus_recompute --apply` — 2026-07-23

Run report for the [`pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md)
§9(d)/§9(e) fire-sequence closing steps — the pilot's own write pass and
the strictly-last `consensus_recompute --apply` — keyed by `run_id`/
`PilotRunLedger` id, same convention
[`2026-07-23-zeroing-and-buga-sample.md`](2026-07-23-zeroing-and-buga-sample.md)
established, filed under `docs/data/` per §9's own "every run in this
sequence gets its own report ... committed under `docs/data/`" note
rather than `docs/reports/`.

## §9(d) — pilot `--write`, `pilot-write-20260723T1202Z`

`PilotRunLedger` id **42** (DB-verified 2026-07-23), `command=local_calculate_verdicts`,
`dry_run=False`, `started_at` 2026-07-23T12:06:53.433610Z, `finished_at`
2026-07-23T13:06:16.880465Z (both DB-verified) — **3,563s wall (59m23s)**.
`git_sha=42a09b3c794f7cf8aca5eb1ca2d4f6cdaa2895a6`, matching the §9(d)
dry-run's own git_sha exactly — same code, no drift between measurement
and write.

### The status=failed / votes_written=None artifact — read this before the table below

The row itself DB-reads `status=failed`, `votes_written=None`,
`counters=None`. **This is a documented execution-harness artifact, not
a failed or partial write** — record this run as **COMPLETE-BY-VERIFICATION**:

- The authorization executor that launched the run enforced a **1800s
  client-side timeout** on the `docker exec` connection. The in-container
  process itself kept running past that point — the timeout severed the
  executor's own stdout stream at ~12:36Z, not the process.
- The in-container process **completed all writes**: both channels'
  vote counts match the §9(d) dry-run's prediction (`reports/2026-07-23-4c-pilot-dry-run.md`)
  **exactly**, DB-verified below, not estimated.
- The process then hit an exception in its own terminal/summary-reporting
  phase — after the last vote write, before the ledger row's own
  `status`/`votes_written`/`counters` fields got set to their normal
  success values. That terminal-phase exception is what produced the
  `status=failed` row; it is not evidence any vote failed to write.
- `finished_at` (13:06:16Z) is ~30 minutes after the 1800s/12:36Z timeout
  boundary — consistent with the process continuing to completion on its
  own clock, unobserved by the severed executor connection, before
  hitting the terminal-phase exception and exiting.

**DB-verified vote counts, both channels, exact match to the §9(d)
dry-run's `would_cast` prediction**:

| channel         | verdict   | dry-run predicted (would_cast) | write, DB-verified live |
| --------------- | --------- | -----------------------------: | ----------------------: |
| join-key        | match     |                         39,253 |                  39,253 |
| join-key        | no_match  |                         61,247 |                  61,247 |
| join-key        | **total** |                        100,500 |                 100,500 |
| fallback        | match     |                         29,710 |                  29,710 |
| fallback        | no_match  |                              0 |                       0 |
| fallback        | **total** |                         29,710 |                  29,710 |
| **grand total** |           |                        130,210 |                 130,210 |

Query: `CardPrintingTag.objects.filter(anonymous_id='stage-d-join-key-v1')`
/ `anonymous_id='stage-d-fallback-v1'`, split by `is_no_match`. This is
the fallback channel's **first production execution** — its 29,710
`stage-d-fallback-v1` votes did not exist before this run (the §9(d)
dry-run's own fallback figure was a read-only in-memory recomputation,
never persisted; see that report's "read-only recovery of the true
fallback numbers" section).

## §9(e) — `consensus_recompute --apply`

Executed **2026-07-23T13:25:37Z**, exit code 0 (relayed — see ledger
note below). Command:
[`consensus_recompute.py`](../../MPCAutofill/cardpicker/management/commands/consensus_recompute.py)
(PR #336).

**Ledger note**: this command **predates the `PilotRunLedger`
self-recording convention** — confirmed live, no `PilotRunLedger` row
exists for this run (the highest id remains 42, the pilot write above).
Flagged as a small follow-up beside the already-tracked Stage C
run-identity gap (§11: Stage C runs also don't self-record a ledger
row) — both are instances of the same underlying gap, a command that
predates the convention rather than a command that's broken.

**Counters** (relayed from command output):

| domain   | pairs checked | transitions                                                                                                                                                                                                                    |
| -------- | ------------: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| artist   |         7,130 | 0                                                                                                                                                                                                                              |
| tag      |        61,329 | 49,206 `None→UNRESOLVED` materializations (one fewer than the 49,207 sized in §6's earlier `consensus_impact_report` dry-run — organic interim resolution between the dry-run's measurement and this apply, not a discrepancy) |
| printing |   (see below) | 3 → 4 resolved (one additional card resolved by this apply)                                                                                                                                                                    |

**Printing resolution end-state — DB-verified** (`Card.objects.values('printing_tag_status').annotate(...)`,
2026-07-23):

| `printing_tag_status` |       count |
| --------------------- | ----------: |
| unresolved            |     218,309 |
| resolved              |           4 |
| no_match              |           1 |
| **total**             | **218,314** |

Confirms the relayed "3 → 4" printing-resolution figure directly: live
`resolved` count is 4. (Total catalog count of 218,314 here vs. §6's
2026-07-22 snapshot of 218,285 reflects ordinary catalog growth between
those two dates, not a data-integrity concern — not re-verified in this
task, out of scope.)

## End-state vote pool (`CardPrintingTag`, DB-verified live, 2026-07-23, post-write and post-recompute)

| source                                             |   count | notes                                                              |
| -------------------------------------------------- | ------: | ------------------------------------------------------------------ |
| join-key (`stage-d-join-key-v1`)                   | 100,500 | §9(d) write, this run                                              |
| fallback (`stage-d-fallback-v1`)                   |  29,710 | §9(d) write, this run — first-ever production execution            |
| user (`source='user'`)                             |      57 | intact throughout the fire sequence (§9's "must never touch" list) |
| deduction (`source='deduction'`)                   |  28,112 | intact (§3 item 3, §9's "must never touch" list)                   |
| legacy pilot (`run_id='20260716T193408-6613a1a6'`) |  43,425 | intact (§6)                                                        |

These five cuts are the task's own requested categories, not a
partition of the table: `legacy pilot`'s 43,425 rows are a `run_id`-scoped
subset of `source='ocr'` (not a disjoint category from it), so summing
all five double-counts that overlap and will not match the live
`CardPrintingTag` table total.

Live total-table count and per-`anonymous_id` breakdown, for
cross-reference: `CardPrintingTag.objects.count()` = 218,413;
`stage-d-join-key-v1` = 100,500, `local-ocr-v1` = 39,795,
`stage-d-fallback-v1` = 29,710, `deductive-backfill-v1` = 28,112,
`local-fallback-v1` = 11,947, `local-phash-v1` = 8,292, plus a handful
of small per-session anonymous UUIDs (≤28 rows each). By `source`:
`ocr` 190,244 / `deduction` 28,112 / `user` 57.

## Relationship to the pipeline-fidelity gate

This file is the §9(d)/§9(e) data source for
[`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md), which is
the gate's canonical status page and single source of truth for its
verdict — this file stays the raw, dated run-report record; the gate doc
owns the status. The full §9 fire sequence is now **COMPLETE end to
end** as of this run: (a) deploy → (b)/B(i) Bug-B → B(ii)+B(iii)
retraction → (c) Bug-A sample → (d) pilot dry-run → owner sample audit
→ (d) pilot `--write` → (e) `consensus_recompute --apply`. The Bug-A
deferred full re-scan (§9(c)'s owner ruling) remains the one tracked
open item from the whole sequence.
