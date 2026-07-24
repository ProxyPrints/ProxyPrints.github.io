As of: 2026-07-24
What this is: the admin-facing operational truth for Stage E's envelope
enforcement primitive (Phase 1 of
[`docs/proposals/stage-e-streaming.md`](../proposals/stage-e-streaming.md),
issue [#153](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/153)).
That brief is the design authority (still **HOLD**, owner review pending on
§3-§5 as a whole) and is not restated here — this doc covers what an
operator actually does: the two operating modes, what the envelope bars
mean, and the trip/resume runbook. See
[`docs/theory.md`](../theory.md)'s new "Streaming and continuous operation"
section for why none of this changes the soundness model.

Phase 1 ships the envelope PRIMITIVE only (`cardpicker/operating_envelope.py`,
the `EnvelopeTrip` model, and the `resolve_envelope_trip` management command)
— nothing in the codebase calls `check_envelope` yet. There is no streaming
dispatch loop today; this doc describes the mechanism a Phase 2 dispatcher
will consume, written now so the runbook exists before the first real trip
does, not after.

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

## What Phase 2/3 will add

This page describes Phase 1 (the primitive) only. Not yet built, and not
promised on any particular timeline — see `stage-e-streaming.md` itself for
the full design (still HOLD pending owner review of §3-§5):

- **Phase 2**: the actual streaming dispatch loop — the event-driven
  qcluster trigger (`stage-e-streaming.md` §3 decision (1)), micro-batch
  sizing derived from the Bug-A shakedown cohort measurement (§10(c)), and
  the wiring that calls `check_envelope`/`current_trip` before every
  dispatch (this primitive has no caller yet).
- **Phase 3** (informal shorthand, not a brief-defined phase number): the
  dispatcher-kill acceptance test (`stage-e-streaming.md` §7) and the
  `CardScanLog` retention tripwire mechanism (§10(b)) — both specced in the
  brief, neither built in this change.

## See also

- [`docs/proposals/stage-e-streaming.md`](../proposals/stage-e-streaming.md)
  — the full design brief this page implements Phase 1 of; the design
  authority for every number and decision cited above.
- [`docs/theory.md`](../theory.md) — "Streaming and continuous operation":
  why moving from batch to streaming (and this envelope's pause/resume
  mechanism) changes nothing about the pipeline's soundness model.
- [`docs/pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) — the
  existing "note-prominently"/kill RSS bars and the 7.0 load-average
  escalation threshold this envelope reuses, in their original BULK-mode
  context.
