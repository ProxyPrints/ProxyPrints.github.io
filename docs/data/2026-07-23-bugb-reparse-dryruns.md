# Bug-B whole-DB reparse dry-runs — 2026-07-23

Run report + resource metrics for the [`pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md)
§9(b)/§12 Bug-B whole-DB reparse dry-run step, keyed by `run_id` — same
convention [`2026-07-20-pipeline-compute-profile.md`](../reports/2026-07-20-pipeline-compute-profile.md)
established for resource-metric reports, filed under `docs/data/` per
§9's own "every run in this sequence gets its own report ... committed
under `docs/data/`" note rather than `docs/reports/`.

**Command**: `reparse_collector_evidence` (module docstring:
[`../../MPCAutofill/cardpicker/management/commands/reparse_collector_evidence.py`](../../MPCAutofill/cardpicker/management/commands/reparse_collector_evidence.py)) —
re-parses `ImageEvidence.collector_line_raw_text` with the current
`local_ocr.parse_collector_line`, re-derives the join-key calculator's
conclusion via the existing, unmodified `calculate_join_key_verdict`,
and compares against each card's currently RECORDED verdict/skip. Zero
image fetches. All three runs below ran dry (`--write` not passed): no
`CardPrintingTag`/`CardScanLog` writes, `ImageEvidence` field
refreshes computed in-memory only, not persisted.

All three `PilotRunLedger` rows verified live (`run_id`, `command`,
`dry_run`, `status`, `votes_written`, `started_at`/`finished_at`) —
`counters` is `NULL` on all three: this command has no `counters`
JSONField payload wired up (unlike `run_image_evidence_cohort`'s own
`_CohortStats`), so its `considered`/`no_evidence`/
`no_prior_join_key_state`/`unchanged`/`changed` breakdown and the
resource-usage figures below are taken from that run's own stdout/host
measurement as relayed by the owner, not independently DB-re-derivable
after the fact — same caveat already established for
`run_image_evidence_cohort`'s completion-log counters in
[`2026-07-22-pipeline-snapshot.md`](2026-07-22-pipeline-snapshot.md)'s
`extraction-run-stagec-remainder-0721` group.

## `bugb-reparse-dry-20260723T014652Z` — whole-DB run

`PilotRunLedger` id 32. `started_at` 2026-07-23T01:47:47.637432Z,
`finished_at` 2026-07-23T02:02:06.496708Z (both DB-verified) — **858.86s
wall (14m18.9s)**, matching the DB-derived duration exactly.

**Counters** (stdout, relayed):

| counter                 |   count |
| ----------------------- | ------: |
| considered              | 197,938 |
| no_evidence             |       0 |
| no_prior_join_key_state |  16,253 |
| unchanged               |  18,819 |
| changed                 | 162,866 |

Arithmetic check: `0 + 16,253 + 18,819 + 162,866 = 197,938 = considered`
exactly.

**Outcome vs. the pre-existing §10 prediction**: the offline
285-changed-row prediction already recorded in
[`pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md)'s §10
("offline re-parsing all 197,938 stored raw texts with the fixed parser
diffs exactly 284 guard rows plus 1 unrelated improvement, card 62354")
verified **exactly** against this run. The `changed=162,866` counter
above is a **different, broader** metric than that 285-row figure — it
compares a fresh re-parse against each card's currently RECORDED
join-key verdict (module docstring's own "compare against the RECORDED
verdict, not the stored parse" design choice), not against the specific
glued-marker signature. Explained as stale `no-evidence` skips from the
2026-07-21 staged runs (`staged-write-20260721T0434Z`/`staged2`/
`staged3`/`staged4-0721`) predating full Stage C evidence coverage —
those cards had no `ImageEvidence` at staging time, so their recorded
skip state trivially differs from a fresh verdict now that
`stagec-remainder-0721` gave them evidence. Handled natively by the
pilot's own rescannable-skip resume logic (the `no-evidence` skip
reason is not in the retraction target list — see the gate doc's §9
B(ii)+B(iii) step). **Not** Bug-B blast radius, and explicitly **not**
a write target for this fire-sequence step.

**Resource metrics** (host measurement over the run window):

| metric                                    | value                                      |
| ----------------------------------------- | ------------------------------------------ |
| wall time                                 | 858.86s (14m18.9s)                         |
| sustained CPU, django                     | ~0.7 core                                  |
| sustained CPU, postgres                   | ~0.3 core                                  |
| total core-seconds (approx.)              | ~893 core-s                                |
| peak django RSS                           | 329 MiB (+186 MiB over a 143 MiB baseline) |
| postgres RSS                              | flat, ~182–194 MiB                         |
| host disk, read ops (delta)               | +5,465                                     |
| host disk, bytes written (delta, approx.) | ~132 MB                                    |

No OOM risk observed (peak RSS well under container limits, matching
the "memory is not a constraint" finding in
[`2026-07-20-pipeline-compute-profile.md`](../reports/2026-07-20-pipeline-compute-profile.md)
for the unrelated Stage C/D compute profile).

**Calibration note**: this run executes the same verdict-computation
code path (`calculate_join_key_verdict`/`_resolve_candidates_for_card`)
the §9(d) 4c full-pool pilot dry-run will run — it is therefore also the
**first runtime calibration point** for that upcoming, much larger run
(197,938 cards here vs. the full eligible pool there), not just a
Bug-B-specific measurement.

## `bugb-reparse-scoped-dry-20260723T020508Z` — scoped to the

284-signature ID file

`PilotRunLedger` id 33. `started_at` 2026-07-23T02:05:15.210240Z,
`finished_at` 2026-07-23T02:05:18.154734Z (DB-verified) — **2.94s**.
Scoped to the regenerated 284-signature ID file (the same cohort §9(b)
above confirms) — a fast confirmation pass, not a resource-profiling
target in its own right at this scale.

## `bugb-reparse-voted33-dry-20260723T0206Z` — scoped to the 33

previously-voted Bug-B cards

`PilotRunLedger` id 34. `started_at` 2026-07-23T02:05:59.905730Z,
`finished_at` 2026-07-23T02:06:01.596422Z (DB-verified) — **1.69s**.
Scoped to the 33 cards that already carry staged-run votes among the
284 (§10: "33 already carry staged-run votes, and every one of those 33
is `is_no_match=True` with 0 wrong-printing votes"). **24/33** flip
false-no-match → genuine match under the fixed parser. Ground-truth
confirmation of those 24 flips is deferred to the §9(d) owner sample
audit — not asserted as confirmed-correct here, only as the fixed
parser's own fresh conclusion.

## Relationship to the pipeline-fidelity gate

This file is the §9(b)/§12 data source for
[`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md), which
is the gate's canonical status page and single source of truth for its
verdict and open decisions — this file stays the raw, dated
run-report/resource-metric record; the gate doc owns the status.
