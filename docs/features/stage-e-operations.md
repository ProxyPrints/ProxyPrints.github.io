As of: 2026-07-24
What this is: the admin-facing operational truth for Stage E's envelope
enforcement primitive (Phase 1) and streaming dispatch loop (Phase 2), both
implementing [`docs/proposals/stage-e-streaming.md`](../proposals/stage-e-streaming.md)
(issue [#153](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/153)).
That brief is the design authority (still **HOLD**, owner review pending on
§3-§5 as a whole) and is not restated here — this doc covers what an
operator actually does: the two operating modes, what the envelope bars
mean, the trip/resume runbook, and (new in Phase 2) the dispatch loop itself
— its trigger, batching, and observability. See
[`docs/theory.md`](../theory.md)'s new "Streaming and continuous operation"
section for why none of this changes the soundness model.

Phase 1 shipped the envelope PRIMITIVE (`cardpicker/operating_envelope.py`,
the `EnvelopeTrip` model, and the `resolve_envelope_trip` management command).
Phase 2 (this update) is the first CALLER of that primitive: the streaming
dispatch loop itself (`cardpicker/stage_e_dispatch.py`) — see "Phase 2 — the
streaming dispatch loop" below. **Both phases ship default-OFF**
(`settings.STAGE_E_STREAMING_ENABLED = False`) — turning streaming on against
production is the phase-3 shakedown's own polled owner action, not something
either phase does by merging.

---

## The two operating modes

Stage E ratified a two-mode split (`stage-e-streaming.md` §10(a)) rather
than a single cards/hour ceiling:

- **PASSIVE mode** — continuous operation against submitted drives and
  newly-created cards (Phase 2's eventual event-driven trigger). Load-
  governed, not rate-governed: no cards/hour cap at all. This is the mode
  the envelope primitive on this page governs.
- **BULK mode** — backfill work, unchanged from today's discipline: polled
  per-batch at max throughput, gated by `pilot_run_lifecycle.py`'s forced
  dry-run-before-write check (issue #362/PR #373), one human poll per
  batch — exactly how every fire-sequence pass in
  [`docs/pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) already
  ran. **`operating_envelope.py` does not apply to BULK mode at all** — a
  BULK invocation (`run_image_evidence_cohort`, `local_calculate_verdicts`,
  etc.) is governed by the existing dry-run-guard/ledger machinery those
  commands already have, not by this primitive.

If you're running a `--limit`/`--card-ids-file` batch command today, you are
in BULK mode and this page's envelope/trip mechanism does not gate you.
This page is entirely about the PASSIVE-mode mechanism a future streaming
daemon will use.

## The envelope model

A PASSIVE-mode dispatcher is expected to sample four live signals before
every micro-batch dispatch and refuse to dispatch (HALT) the instant any one
of them crosses its bar. The four ratified bars
(`stage-e-streaming.md` §10(a)), in the priority order
`operating_envelope._bar_breach` checks them:

| bar                  | ceiling                                 | source                                                                            |
| -------------------- | --------------------------------------- | --------------------------------------------------------------------------------- |
| Google fetch lockout | any occurrence — **instant** pause      | the existing `GoogleFetchLockoutError`/`lockout_hit` signal, unchanged            |
| Host load average    | **> 7.0**                               | the existing escalation threshold (`docs/reports/2026-07-23-4c-pilot-dry-run.md`) |
| RSS per worker       | **> 512MB**                             | `stage-e-streaming.md` §10(a), a new, streaming-specific per-worker bar           |
| Fetch-failure rate   | **> 1%** over a rolling 500-card window | `stage-e-streaming.md` §10(a)                                                     |

None of these numbers are invented on this page or in `operating_envelope.py`
itself — every one is cited to the ratifying brief section in that module's
own docstring, which is the place to check if a bar's exact value is ever in
question.

**HALT is not a soft slowdown.** The moment any bar is breached, the
primitive persists an `EnvelopeTrip` row (`bar`, the observed `detail`
values, `tripped_at`, an optional `run_id`) and the dispatcher is expected
to stop issuing new micro-batches entirely — in-flight work already
dispatched is allowed to drain (matching the existing kill-test/resume-
contract's own "in-flight work drains, nothing new starts" discipline), but
no NEW batch goes out while a trip is open.

## Resume requires a fresh owner action — always

**There is no self-resume, in any case, for any bar.** This is a hard
ratified rule (`stage-e-streaming.md` §3 decision (5)/§10(a)), not a default
that happens to be conservative — matching the same posture PR #373's
`--skip-dryrun-check` already established elsewhere in this pipeline: an
override is allowed, but it is always explicit and always logged, never
automatic. A PASSIVE-mode dispatcher must never clear its own trip, no
matter how quickly the underlying condition (load, RSS, failure rate)
recovers.

### Runbook: investigating and clearing a trip

1. **Find the open trip.** Either from the streaming daemon's own halt
   message (once Phase 2 exists), or directly:
   ```python
   from cardpicker.operating_envelope import current_trip
   current_trip()  # None if nothing is open
   ```
   or via the Django admin (`EnvelopeTrip` is registered, read-only —
   `trip_id`/`bar`/`run_id`/`tripped_at`/`acknowledged_at` are all listed
   and searchable there; the admin form cannot itself acknowledge a trip —
   see "Why the admin can't resume a trip" below).
2. **Understand why it tripped.** `EnvelopeTrip.detail` carries the exact
   observed values against the ceiling (e.g.
   `{"load_avg": 8.2, "ceiling": 7.0}`) — this is the whole investigation
   payload; there is nothing else to correlate for a single trip beyond
   whatever host-level diagnosis (`top`, `docker stats`, the fetch-failure
   log) the bar itself suggests.
3. **Fix or confirm the underlying condition**, exactly as you would for any
   of the pre-existing "note-prominently"/kill RSS bars or the 7.0 load
   escalation threshold this reuses — nothing about diagnosis changes just
   because the signal now also persists a trip row.
4. **Acknowledge the trip**, once you're satisfied it's safe to resume:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm django \
     python manage.py resolve_envelope_trip \
     --acknowledge-trip <trip-id> \
     --note "host load confirmed back under 3.0, checked via top"
   ```
   `--note` is mandatory and non-empty — an acknowledgement always carries a
   human-readable reason, durably, on the trip row itself (not just in a
   terminal that may never be read again). A trip that's already
   acknowledged, or a `trip_id` that doesn't exist, raises a `CommandError`
   rather than silently doing nothing.
5. **Nothing dispatches automatically on acknowledgement.** Clearing a trip
   only removes it from `current_trip()`'s result — a Phase 2 dispatcher's
   own poll loop is what actually resumes issuing micro-batches, the next
   time it checks and finds the envelope clear.

### Why the admin can't resume a trip

`EnvelopeTrip`'s Django admin registration is entirely read-only (every
field, including `acknowledged_at`/`acknowledged_note`) — `resolve_envelope_trip`
is the ONLY code path permitted to set those fields
(`operating_envelope.acknowledge_trip`'s own docstring). This is deliberate,
not an oversight: the admin is a monitoring surface for finding a `trip_id`
to hand to the command, not a second, less-visible resume path that could
bypass the mandatory `--note` and the CLI's own audit trail.

## Phase 2 — the streaming dispatch loop

Built 2026-07-24, per the owner-approved Phase 2 implementation task for
`stage-e-streaming.md` §3-§5 (still HOLD as a brief — this is the
owner-pre-approved implementation of what it already specced, the same
posture Phase 1 shipped under). Ships **default-OFF**
(`settings.STAGE_E_STREAMING_ENABLED = False`) — every mechanism below is
live code, wired unconditionally, but every entry point checks the flag
first and is a no-op while it's False. Flipping it to `True` is the ONLY
action the phase-3 shakedown needs to take to go live; no redeploy of this
code is required.

### What it is

`cardpicker/stage_e_dispatch.py`'s `dispatch_micro_batch` is the CONVEYOR —
the first real caller of Phase 1's `check_envelope`/`current_trip` primitive.
It is a DISPATCH LOOP only: it never reimplements Stage C extraction, Stage D
calculator decode logic, or consensus resolution — every actual accept/reject
decision still happens inside the same `cardpicker.image_evidence`/
`cardpicker.local_calculate_verdicts`/`cardpicker.printing_consensus` code
BULK mode already uses, called via their existing entry points. BULK-mode
commands (`run_image_evidence_cohort`, `local_calculate_verdicts`,
`reparse_collector_evidence`, `consensus_recompute`, etc.) are byte-identical
to before this change — none of their own call sites pass the new optional
`card_ids` scoping parameter `local_calculate_verdicts.py`'s three calculator
entry points (`run_join_key_calculator`/`run_fallback_calculator`/
`run_slow_path_calculator`) gained for this module's benefit.

### Ordering, every dispatch call

1. **Default-off gate** — `settings.STAGE_E_STREAMING_ENABLED` must be `True`,
   or the call is a no-op (`status="disabled"`).
2. **No-self-resume gate** — `operating_envelope.current_trip()` must be
   `None`, or the call refuses outright (`status="halted-open-trip"`) with
   zero DB writes beyond the lookup itself. This is the binding rule from
   Phase 1's own review: no code path in `stage_e_dispatch.py` ever calls
   `acknowledge_trip` — resume is always `resolve_envelope_trip`'s own
   command, a fresh, explicit owner action (see the runbook above).
3. **Fresh envelope sample** — live host load (`os.getloadavg()`), this
   worker process's own RSS (`cardpicker.process_metrics.get_process_rss_mb`),
   and a rolling fetch-outcome window feed `check_envelope`. If THIS sample
   breaches a bar, a new trip is recorded and the call halts
   (`status="halted-new-trip"`) before touching Stage C/D at all.
4. **Micro-batch selection** — `_select_micro_batch` builds the card-id list:
   the triggering event's own card first (if any), filled up to
   `settings.STAGE_E_MICRO_BATCH_SIZE` from the Stage C backlog (cards
   lacking a full-manifest `ImageEvidence` row — the same shape
   `run_image_evidence_cohort.py`'s own resume filter uses, imported, not
   reimplemented).
5. **Stage C** (sequential, per-card, not pooled — a micro-batch is far too
   small for BULK mode's process-pool concurrency to help) — the same
   `compute_card_evidence`/`persist_evidence` unit `run_image_evidence_cohort.py`
   drives, one card at a time. A `GoogleFetchLockoutError` stops Stage C for
   this batch immediately and records a fresh trip (instant-pause bar) —
   in-flight, already-committed work stays committed; Stage D below still
   runs against whatever was reached ("in-flight work drains, nothing NEW
   starts").
6. **Stage D** — `run_join_key_calculator`/`run_fallback_calculator`/
   `run_slow_path_calculator`, called AS-IS with the new `card_ids` scope, in
   the same escalation order every BULK-mode invocation already uses. Each of
   these already calls `resolve_and_persist_printing` internally for every
   card it touches — this is what satisfies §3 decision (4)'s "scoped
   incremental per-touch consensus recompute" with no separate consensus step
   in the dispatcher at all.
7. **Ledger write** — one `PilotRunLedger` row per micro-batch (see
   "Observability" below).

### Trigger: event-driven, plus a cron backstop (§3 decision (1))

- **Event-driven** (`cardpicker/stage_e_signals.py`, wired in
  `cardpicker.apps.CardpickerConfig.ready()`): a `post_save` receiver on
  `Card` (only `created=True` — "card-create") and on `ImageEvidence` (every
  save — "evidence-change") queues `dispatch_for_card` via django-q2's
  `async_task`, never inline. Both receivers check
  `STAGE_E_STREAMING_ENABLED` before doing anything, including before
  importing `django_q.tasks` — connecting the receivers themselves is always
  cheap and side-effect-free, only the flag gates real work.
- **Cron backstop** (`manage.py stream_backstop_sweep`): re-runs the same
  eligibility selectors against the Stage C backlog, then (once that's empty)
  the Stage D join-key-eligible backlog, dispatching micro-batches until both
  are exhausted, the envelope trips, or `--max-batches` is reached. Catches
  anything a lost/never-fired django-q dispatch missed (django-q2's own
  delivery guarantee is at-least-once-attempted, not exactly-once-delivered).
  **Not scheduled anywhere by this change** — no django-q `Schedule` row is
  created; wiring an actual cadence is a phase-3/live-deploy action, not a
  code change.

### Micro-batch sizing (§3 decision (2), sharpened by §10(c))

`settings.STAGE_E_MICRO_BATCH_SIZE` (default `25`, env-tunable, no code
change needed to adjust) is a **placeholder**, not a considered answer —
§10(c) ratifies that the real number ships as a MEASURED OUTPUT of the Bug-A
tail shakedown's own instrumentation (phase 3, not yet run). The default
sits inside the brief's own "roughly 10-100 cards per batch" sanity range as
a conservative starting point pending that measurement.

### Observability: the streaming-run ledger convention

Every micro-batch — from either trigger — writes one `PilotRunLedger` row:
`command="stage_e_streaming_dispatch"`, `dry_run=False` (PASSIVE mode has no
per-batch dry-run leg — see `stage-e-streaming.md` §3 decision (5)), and
`counters` carrying `trigger_reason` (`"card-create"`/`"evidence-change"`/
`"backstop-sweep"`/`"backstop-sweep-stage-d"`), `batch_size`,
`stage_c_completed`, `stage_c_fetch_failures`, `stage_d_join_key_votes`,
`stage_d_fallback_votes`, `stage_d_slow_path_routed`, `elapsed_s`,
`peak_rss_mb` (via the same `process_metrics.get_process_rss_mb` Phase 1
wired in), and `lockout_trip_id` (non-null only when a Google lockout tripped
mid-batch). A halted call (`disabled`/`halted-open-trip`/`halted-new-trip`)
writes NO ledger row at all — a halted dispatch never partially starts, so
there's nothing to record beyond the `EnvelopeTrip` row `check_envelope`
itself already persists. A crashed batch (any other exception) is marked
`FAILED` with `counters["failure_reason"]` via the same
`pilot_run_lifecycle.mark_ledger_failed` rail every BULK-mode command uses —
no new failure-handling mechanism.

### Resume contract, extended to a streamed micro-batch

Each card's own `persist_evidence` call is its own transaction — a crash
mid-batch leaves every already-persisted card durably written and nothing
partially written for the card the crash interrupted. A re-invocation over
the same (or an overlapping) card-id set is idempotent: Stage C's resume
filter skips cards already fully processed, and Stage D's own
anonymous_id-exclusion eligibility queries skip cards already voted on — the
same "truthful ledger, idempotent re-entry, zero manual cleanup" property the
batch kill-test (`scripts/ops/crash_drill.sh`) already proves for BULK mode,
now covered for the streamed path by `cardpicker/tests/test_stage_e_dispatch.py`'s
`TestKillSafetyResumeContract` (a mid-batch exception, a truthful `FAILED`
ledger row, and an idempotent re-invocation, at unit-test granularity). The
LIVE, host-level dispatcher-kill drill `stage-e-streaming.md` §7(b) specs
(killing the dispatcher PROCESS itself, not a simulated exception) is still
open — see that section for why it's sequenced into the phase-3 shakedown,
not this change.

## Phase 3 (not yet built)

Informal shorthand, not a brief-defined phase number — see
`stage-e-streaming.md` for the full design (still HOLD pending owner review
of §3-§5 as a whole):

- **Turning `STAGE_E_STREAMING_ENABLED` on** against production — the
  phase-3 shakedown's own polled owner action, explicitly not done by either
  Phase 1 or Phase 2 landing.
- **The live, host-level dispatcher-kill acceptance test** (`stage-e-streaming.md`
  §7(b)) — killing the dispatcher process itself mid-stream, not a simulated
  exception.
- **The `CardScanLog` retention tripwire mechanism** (§10(b)) — specced in
  the brief, not built in this change.
- **The Bug-A tail shakedown itself** (§6 item 1, issue #418) — the cohort
  that measures the real `STAGE_E_MICRO_BATCH_SIZE` (§10(c)).

## See also

- [`docs/proposals/stage-e-streaming.md`](../proposals/stage-e-streaming.md)
  — the full design brief this page implements Phase 1 and Phase 2 of; the
  design authority for every number and decision cited above.
- [`docs/theory.md`](../theory.md) — "Streaming and continuous operation":
  why moving from batch to streaming (and this envelope's pause/resume
  mechanism) changes nothing about the pipeline's soundness model.
- [`docs/pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) — the
  existing "note-prominently"/kill RSS bars and the 7.0 load-average
  escalation threshold this envelope reuses, in their original BULK-mode
  context.
