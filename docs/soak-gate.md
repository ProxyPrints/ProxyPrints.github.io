As of: 2026-07-29
What this is: the width-ramp soak gate — a machine-only evaluation
module and report command (issue #155) that computes a
PASS / FAIL / INSUFFICIENT-DATA verdict for the owner-ratified
per-width-step criteria before any widening decision. Implements the
monitoring layer only (W6 fix-batch plan): zero changes to vote logic,
consensus, weights, or resolution paths.

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

Criterion **0 — run observed** sits in front of all seven (added
2026-07-29): a `run_id` with no `ImageEvidence`, no `PilotRunLedger` row
and no `CardPrintingTag` votes was never soaked, and reports
INSUFFICIENT-DATA.

## The three verdicts

Each criterion returns one of four outcomes; the gate returns one of
three verdicts. **Only PASS permits widening.**

| Criterion outcome   | Gates? | Means                                                                     |
| ------------------- | ------ | ------------------------------------------------------------------------- |
| `PASS`              | yes    | measured, within threshold                                                |
| `FAIL`              | yes    | measured, outside threshold                                               |
| `INSUFFICIENT-DATA` | yes    | the criterion is a gate and its measurement **could not be taken**        |
| `REPORT`            | no     | no threshold **by design** — criteria 6 and 7 only; never affects verdict |

| Gate verdict        | Exit | Operator action                                                                 |
| ------------------- | ---- | ------------------------------------------------------------------------------- |
| `PASS`              | 0    | widen to the next step                                                          |
| `FAIL`              | 1    | halt; roll back with `purge_machine_votes --run-id <run_id>`, fix, re-run       |
| `INSUFFICIENT-DATA` | 2    | halt; **nothing to roll back** — find out why the step produced no data, re-run |

FAIL outranks INSUFFICIENT-DATA when both occur, so the rollback
instruction is never withheld by a co-occurring measurement gap. Any
non-zero exit halts the ramp, so an existing caller testing only
`$? -ne 0` is unaffected by the third code. This follows the same owner
ruling the Stage E dispatch driver's exit codes encode (2026-07-29, see
[`features/stage-e-operations.md`](features/stage-e-operations.md)'s
"Exit codes — the supervisor contract"): a termination that leaves the
decision unmade does not get to exit zero.

**Why three and not a boolean** (2026-07-29). The gate's first form
aggregated an `Optional[bool]` per criterion with
`all(c.passed is True for c in criteria if c.passed is not None)`. A
criterion that could not be computed was assigned `None` and was then
filtered out of its own check; separately, the criteria that "pass" by
counting zero rows pass exactly as hard for a run that never executed as
for a clean one. Evaluating a nonexistent `run_id` therefore printed
`VERDICT: PASS — safe to widen` — "we could not measure it" reading as
"it was fine", on the gate that governs whether to increase throughput
against production. INSUFFICIENT-DATA is a separate value from REPORT
precisely because an un-taken measurement and a criterion that has no
threshold by design are different states calling for different operator
actions; collapsing them is what made the gate unable to fail.

### Criterion detail

**0. Run observed.** Counts rows for the `run_id` in the three tables a
width-ramp step writes into — `ImageEvidence`, `PilotRunLedger`,
`CardPrintingTag`. All three empty → INSUFFICIENT-DATA: the run produced
no observations (a typo'd `run_id`, a step that died before its first
write, or a gate run against the wrong database). This criterion carries
the zero-observation case on its own so that criteria 2 and 4 can stay
truthful — "zero open envelope trips" genuinely _is_ a pass for a run
that actually ran, and should not be rewritten to second-guess whether
the run happened.

**1. Fetch-failure rate.** Computed from `ImageEvidence` rows whose
`run_id` matches the step's run. `fetch_ok=False` counts as a failure.
The 1% threshold matches the envelope's own fetch-failure bar
(`operating_envelope.FETCH_FAILURE_RATE_CEILING`). If no evidence rows
exist for the run, the criterion is INSUFFICIENT-DATA, **not** a pass:
a step whose fetches produced no evidence rows at all is the shape a
total fetch outage takes, and must never read as a 0% failure rate.

**2. Unacknowledged envelope trips.** Any `EnvelopeTrip` row with
`run_id` matching the step and `acknowledged_at IS NULL` is an open
trip — the HALT state documented in `models.py`'s `EnvelopeTrip`
docstring and `operating_envelope.py`'s RESUME SEMANTICS section. All
trips must be acknowledged (via `resolve_envelope_trip --acknowledge-trip <id>`) before widening.

**3. Evidence cohort count.** The number of `ImageEvidence` rows
written for the run must be within ±5% of the step's eligible cohort
count. Never hardcoded — the reference is read live off the run's own
ledger row.

The reference cohort is **derived by default**; `--step-cohort-size` is
an override, not a precondition. Resolution order:

1. `--step-cohort-size` when given (operator knows better);
2. `PilotRunLedger.counters["cohort_size"]` — written by
   `run_image_evidence_cohort` at completion;
3. `PilotRunLedger.counters["batch_size"]` — written by
   `stage_e_dispatch` at ledger **creation**, alongside `trigger_reason`.
   Creation-time matters: it is on the row from the start, so a run that
   crashed halfway — the case this criterion most needs to catch — still
   has a reference. It is also the only intent counter the streaming
   Stage E dispatcher records, so without it criterion 3 would need a
   flag for the very runs the width ramp is made of.

**What the reference may never be derived from.** Only counters
recording what the run _set out_ to do are eligible. Achievement
counters (`completed`, `stage_c_completed`, …) and the `ImageEvidence`
count itself are excluded on purpose: a reference computed from the
outcome agrees with the outcome by construction, so the criterion would
compare the run against itself and could never fail. A step that
silently processed half its cohort writes half the evidence _and_ half
the completions — they agree perfectly, and the gate would certify it.
Buying flag-free operation that way would re-introduce an unfailable
gate, which is a worse trade than the flag it removes.

If no intent counter is present the criterion is INSUFFICIENT-DATA and
the message **names `--step-cohort-size`**, so a first-time instance
maintainer can act on it.

**While the run is still RUNNING** the criterion is INSUFFICIENT-DATA
regardless of where the reference came from: `batch_size` is on the row
from creation, so an in-flight dispatch has its full intent recorded
while its evidence is still accumulating, and comparing the two reports
a shortfall that is merely work not done _yet_. A FAIL there would be
wrong twice — it accuses a healthy run, and its rollback advice would
send an operator to `purge_machine_votes` against a live one. The ramp
still halts (never widen off an in-flight step), and a run stuck
RUNNING is caught by criterion 5 once it goes stale.

**4. Zero machine-only resolutions.** Mirrors the
`deductive_backfill.verify_zero_resolutions` pattern: for each card
that received a machine vote in this run (`CardPrintingTag` rows with
matching `run_id`), the pure `resolve_printing` is re-checked against
current DB state. Any card that resolves to a printing is a violation.
The rationale (from `deductive_backfill`'s own docstring): "should
structurally never happen" is exactly what an operational gate verifies
against real data.

**5. Ledger heartbeat.** `PilotRunLedger.run_id` is unique, so this
checks the run's own liveness rather than gaps between rows: a RUNNING
row (no `finished_at`) must have `started_at` within 1h or the run
appears stalled; a COMPLETED/FAILED row is trivially OK. Uses
`started_at`/`finished_at` because those are the schema's actual
activity timestamps. **No ledger row at all is INSUFFICIENT-DATA, not a
pass** (changed 2026-07-29): the row is this criterion's only
instrument, so its absence means liveness was not measured — the old
"trivially OK" reading let a run that never started report a healthy
heartbeat.

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
   python manage.py soak_gate_report
   ```

   **No flags are required.** A bare invocation evaluates the most
   recently started ledger run — reporting which run it picked and the
   ledger row it came from — and derives criterion 3's cohort from that
   run's own counters. This is the owner directive "default the default
   things, disable them with flags" (2026-07-29): an instance owner must
   get a real verdict without knowing which flags to pass.

   Every flag narrows or overrides that default; none is a precondition:

   ```
   python manage.py soak_gate_report --run-id <run_id>
   python manage.py soak_gate_report --run-id <run_id> --step-cohort-size <size>
   python manage.py soak_gate_report --run-id <run_id> --canary-step
   ```

   Pin `--run-id` when evaluating a specific run: `stage_e_dispatch`
   writes one ledger row **per micro-batch**, so the auto-selected
   default is one batch of a multi-batch step. For canary step 0, add
   `--canary-step` — it only adds a manual crash-drill reminder and
   never affects the verdict. With an empty ledger there is nothing to
   default to, and the command errors naming `--run-id`.

2. Interpret the output (see "The three verdicts" above):

   - **`VERDICT: PASS`** (exit 0): safe to widen to the next step.
   - **`VERDICT: FAIL`** (exit 1): halt, no widening.
   - **`VERDICT: INSUFFICIENT-DATA`** (exit 2): halt, no widening. The
     gate could not observe this run, so it cannot certify it.

3. On FAIL, the rollback is:

   ```
   python manage.py purge_machine_votes --run-id <run_id>
   ```

4. On INSUFFICIENT-DATA there is **nothing to roll back** — no rollback
   command is printed. Establish why the step produced no data (wrong
   `run_id`? step never executed? wrong database?), then re-run the gate.

5. Fix the failed or unmeasurable criterion, re-run the gate, widen only
   on exit 0.

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
- **This is the widen/halt decision artifact.** Only `VERDICT: PASS`
  (exit 0) permits widening. FAIL → halt, rollback with
  `purge_machine_votes --run-id`. INSUFFICIENT-DATA → halt, investigate;
  an unmeasured soak is never a widen.

## Implementation

- `cardpicker/soak_gate.py` — pure evaluation module (zero writes)
- `cardpicker/management/commands/soak_gate_report.py` — CLI wrapper
- `cardpicker/tests/test_soak_gate.py` — test suite
