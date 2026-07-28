As of: 2026-07-28
What this is: the width-ramp soak gate — a machine-only evaluation
module and report command (issue #155) that computes PASS/FAIL for the
owner-ratified per-width-step criteria before any widening decision.
Implements the monitoring layer only (W6 fix-batch plan): zero changes
to vote logic, consensus, weights, or resolution paths.

---

## The width ramp

The Bug-A canary is re-queried live at GO (step 0), then the ramp
widens through three steps:

| Step       | Approx. size | Description                         |
| ---------- | ------------ | ----------------------------------- |
| 0 (canary) | ~400         | Bug-A canary, re-queried live at GO |
| 1          | ~25k         | First real bulk step                |
| 2          | ~60k         | Second bulk step                    |
| 3          | remainder    | All remaining unresolved cards      |

Sizes are recomputed from the live queue each time — never hardcoded.
The DB grows between runs; all cohort counts come from live queries.

## The seven criteria

| #   | Criterion                     | Threshold                 | Source                                                                                                    |
| --- | ----------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------- |
| 1   | Fetch-failure rate            | ≤ 1%                      | `ImageEvidence.fetch_ok` rows scoped to `run_id`; mirrors `operating_envelope.FETCH_FAILURE_RATE_CEILING` |
| 2   | Unacknowledged envelope trips | 0                         | `EnvelopeTrip.objects.filter(run_id=…, acknowledged_at__isnull=True)`                                     |
| 3   | Evidence cohort count         | within ±5% of cohort      | `ImageEvidence` rows for `run_id` vs step's eligible cohort count (live)                                  |
| 4   | Machine-only resolutions      | 0 cards                   | Mirrors `deductive_backfill.verify_zero_resolutions` pattern (see that module's own docstring)            |
| 5   | Ledger heartbeat              | no gap > 1h               | `PilotRunLedger.started_at`/`finished_at` timestamps for `run_id`                                         |
| 6   | Crash-drill reminder          | manual (canary step only) | The gate does NOT automate this; the report prints a reminder line                                        |
| 7   | Vote yield                    | reported only             | `PilotRunLedger.counters` — votes cast / cards considered; no threshold in v1                             |

### Criterion detail

**1. Fetch-failure rate.** Computed from `ImageEvidence` rows whose
`run_id` matches the step's run. `fetch_ok=False` counts as a failure.
The 1% threshold matches the envelope's own fetch-failure bar
(`operating_envelope.FETCH_FAILURE_RATE_CEILING`). If no evidence rows
exist for the run, the criterion is reported as informational (no
verdict).

**2. Unacknowledged envelope trips.** Any `EnvelopeTrip` row with
`run_id` matching the step and `acknowledged_at IS NULL` is an open
trip — the HALT state documented in `models.py`'s `EnvelopeTrip`
docstring and `operating_envelope.py`'s RESUME SEMANTICS section. All
trips must be acknowledged (via `resolve_envelope_trip --acknowledge-trip <id>`) before widening.

**3. Evidence cohort count.** The number of `ImageEvidence` rows
written for the run must be within ±5% of the step's eligible cohort
count. The cohort count is either passed via `--step-cohort-size` or
computed live from `PilotRunLedger.counters["cohort_size"]`. Never
hardcoded.

**4. Zero machine-only resolutions.** Mirrors the
`deductive_backfill.verify_zero_resolutions` pattern: for each card
that received a machine vote in this run (`CardPrintingTag` rows with
matching `run_id`), the pure `resolve_printing` is re-checked against
current DB state. Any card that resolves to a printing is a violation.
The rationale (from `deductive_backfill`'s own docstring): "should
structurally never happen" is exactly what an operational gate verifies
against real data.

**5. Ledger heartbeat.** No gap > 1h between consecutive
`PilotRunLedger` activity timestamps (started_at always counts;
finished_at counts if set). A single-row or zero-row ledger is
trivially OK. Uses `started_at`/`finished_at` because those are the
schema's actual activity timestamps.

**6. Crash-drill reminder.** Canary-step only (manual). The gate does
NOT automate this; the report prints a reminder line that step 1
requires a DRILL-PASS before widening.

**7. Vote yield.** Reported only — votes cast / cards considered, from
`PilotRunLedger.counters` including the illustration counters #511
added. No threshold in v1. The measured values appear in the report
for the operator's own assessment.

## The runbook

After each width-ramp step completes:

1. Run the soak gate:

   ```
   python manage.py soak_gate_report --run-id <run_id> --step-cohort-size <size>
   ```

   For canary step 0, add `--canary-step`.

2. Interpret the output:

   - **All PASS** (exit code 0): safe to widen to the next step.
   - **Any FAIL** (exit code 1): halt, no widening.

3. On FAIL, the rollback is:

   ```
   python manage.py purge_machine_votes --run-id <run_id>
   ```

4. Fix the failed criterion, re-run the gate, widen only on exit 0.

## Standing rules

- **`rejudge_fallback_channel --write` never runs while streaming is
  enabled.** This is a standing rule from the streaming design brief
  (`docs/proposals/stage-e-streaming.md`).
- **Pre-bulk Scryfall bulk-data freshness step.** Before any bulk
  step: download the latest bulk-data file, checksum it against the
  last import, and re-import if changed. This ensures the canonical
  card set is current.
- **All counts come from live queries.** The DB grows between runs;
  never hardcode cohort sizes or evidence counts.
- **This is the widen/halt decision artifact.** FAIL → halt, no
  widening. The rollback command is `purge_machine_votes --run-id`.

## Implementation

- `cardpicker/soak_gate.py` — pure evaluation module (zero writes)
- `cardpicker/management/commands/soak_gate_report.py` — CLI wrapper
- `cardpicker/tests/test_soak_gate.py` — test suite
