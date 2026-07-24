As of: 2026-07-24
What this is: design brief for Stage E ("streaming assembly + resume
contract + kill-test," GitHub issue
[#153](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/153)).
**HOLD — owner review pending.** Every number below is cited to a
committed doc, a merged/open PR, or a live, read-only `PilotRunLedger`/
table query run while writing this brief (2026-07-24) — where a figure
in the originating task brief could not be independently verified, that
is stated explicitly rather than restated as fact (rulings-travel-with-
citation discipline, per this repo's reporting convention). See
[`docs/pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) for the
pipeline's current live state (single source of truth, not restated
here) and [`docs/theory.md`](../theory.md) for the soundness model every
recommendation below is checked against.

Companion issues: [#418](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/418)
(Bug-A re-scan tail — this brief's owner-ratified shakedown cohort, §7)
and [#278](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/278)
(AI-art-detector rescan-on-evidence-change — this brief's second
consumer, §7).

**Phase 1 built 2026-07-24** (observability + envelope-enforcement
primitives only, per the owner-pre-approved implementation task for this
brief's §3 decision (6) gaps and §3 decision (5)/§10(a)'s ratified
PASSIVE-mode bars) - `cardpicker/operating_envelope.py`, the
`EnvelopeTrip` model, and `resolve_envelope_trip` (the resume command);
see [`docs/features/stage-e-operations.md`](../features/stage-e-operations.md)
for the operator-facing runbook and [`docs/theory.md`](../theory.md)'s
new §10 for the soundness note. **This does not lift the HOLD above** -
no streaming dispatch loop exists yet, and §3-§5 as a whole still need
owner review before Phase 2 (the loop that actually consumes this
primitive) is built.

**Phase 2 built 2026-07-24** (the streaming dispatch loop itself, per the
owner-approved implementation task for this brief's §3-§5 as specced) -
`cardpicker/stage_e_dispatch.py` (the conveyor: default-off gate, the
no-self-resume check against Phase 1's `current_trip`, a fresh
`check_envelope` sample, micro-batch selection, sequential Stage C, scoped
Stage D via the new `card_ids` parameter `local_calculate_verdicts.py`'s
three calculator entry points gained, and the per-batch `PilotRunLedger`
row), `cardpicker/stage_e_signals.py` (the event-driven card-create/
evidence-change trigger, §3 decision (1)), and
`manage.py stream_backstop_sweep` (the cron backstop, same decision). Ships
**default-OFF** (`settings.STAGE_E_STREAMING_ENABLED = False`) - see
[`docs/features/stage-e-operations.md`](../features/stage-e-operations.md)'s
new "Phase 2" section for the full operator-facing detail (trigger, batching,
observability, resume contract). **This does not lift the HOLD above either** -
turning streaming on in production, the live host-level dispatcher-kill drill
(§7(b)), the `CardScanLog` retention tripwire (§10(b)), and the Bug-A tail
shakedown that measures the real micro-batch size (§10(c)) are all still
open, tracked as "Phase 3" in the ops doc.

**§10 update (2026-07-24, owner):** four of §9's open items are now
ratified — the rate-control/authorization-envelope question (§9 item 1)
and the `CardScanLog` retention question (§9 item 2) are RESOLVED, and
the micro-batch-size and 2026-07-24-IO-audit points are sharpened. See
§10 for the full ratification text; the overall HOLD status above is
unchanged by it.

---

## 0. What Stage E actually has to satisfy

Issue #153's own text (quoted in full, nothing added): kill-and-restart
at any point with zero manual cleanup proven via a blocking `kill -9`
mid-batch acceptance test; resume filter = cards lacking an
`ImageEvidence` row for this extractor-version set; one-transaction
batch commit (or explicit evidence-first statement); a durable run
ledger (likely extending `PilotRunLedger`). This is the same four-piece
contract `docs/features/catalog-completion-plan.md`'s "Stage E resume
contract" paragraph already specifies (owner directive, 2026-07-19,
still the canonical spec — not re-derived here, only extended below to
a continuous/streaming operating mode instead of a discrete batch run).

---

## 1. Measured envelope (verified 2026-07-24)

All per-card rates below are **compute-stage** throughput on the box
described in §8 — a shared 8-OCPU aarch64 host also running the live
Django/Postgres/ES/nginx stack. None of these assume dedicated
hardware; §8 makes that assumption explicit and states its consequence
for rate control.

| regime                                                                                                      | rate                                        | source                                                                                                           |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Stage C, pre-multi-pass baseline                                                                            | **5.37 cards/s** (5.367 measured)           | `docs/features/catalog-completion-plan.md` ~line 2075, citing `docs/reports/2026-07-21-stagec-20k-extraction.md` |
| Stage C, decoupled fetch/compute, 400-card basis                                                            | **5.542 cards/s**                           | `docs/reports/2026-07-20-decoupled-canary-confirm.md`                                                            |
| Stage C, decoupled, 300-card steady-state slice (excl. warm-up)                                             | **5.769 cards/s**                           | same report                                                                                                      |
| Stage C, multi-pass-heavy (100%-escalation cohort)                                                          | **3.5 cards/s** (3.492 measured)            | `catalog-completion-plan.md` line 2078, citing `ntx-0721` run                                                    |
| Stage C, blended projection (46.8% no-text split)                                                           | **≈4.29 cards/s**                           | `catalog-completion-plan.md` line 2090 (derived, not a direct measurement)                                       |
| Stage C, worst-case floor, blank-tier-1 pool, `--no-shortcircuit`, dry-run                                  | **3.252 cards/s** (10,437 cards / 3,209.6s) | live `PilotRunLedger` id 70, `run_id=rescan-wave1-dry-20260724`, queried 2026-07-24 (see below)                  |
| Stage C, same cohort, real write                                                                            | **3.351 cards/s** (10,437 cards / 3,115.1s) | live `PilotRunLedger` id 75, `run_id=rescan-wave1b-20260724`                                                     |
| Stage D, join-key dry-run (evidence already extracted)                                                      | **~438 cards/s** (2.28ms/card)              | `docs/reports/2026-07-23-4c-pilot-dry-run.md` line 164                                                           |
| Stage D, fallback-channel dry-run                                                                           | **~93 cards/s** (10.75ms/card)              | same report, line 176                                                                                            |
| Stage D, real vote-cast write (130,210 rows, 59m23s)                                                        | **~27ms/row**                               | `docs/pipeline-fidelity-gate.md` line 878                                                                        |
| Stage D, in-process compute only (excl. DB I/O)                                                             | **0.18ms/card**                             | `docs/reports/2026-07-20-pipeline-compute-profile.md` line 32                                                    |
| `consensus_recompute --apply`, full DB (163,045 pairs checked: 94,585 printing + 7,130 artist + 61,330 tag) | **383.9s** (~264.9 rows/s)                  | `docs/pipeline-fidelity-gate.md` line 995                                                                        |

**On "Stage D ~4–5ms/card DB-only"** (as stated in the task brief that
produced this section): this specific figure does not appear anywhere
in the written record and is **not restated as fact here**. The closest
verified numbers span a much wider range depending on what "DB-only"
is taken to mean — 0.18ms/card for in-memory compute alone (no DB I/O
at all), 2.28ms/card for a full dry-run pass including reads but no
writes, up to ~27ms/row for a real pass that also casts votes. The
brief below uses the verified range, not a single collapsed figure.

**On the 2026-07-24 wave-1 worst-case floor**: the task brief's
"3.25-3.35 cards/s ... flat ~190MB RSS ... 0 fetch failures" claim was
checked directly against the live `PilotRunLedger` table
(`mpcautofill_django` container, read-only query, 2026-07-24). Confirmed
exactly: `rescan-wave1-dry-20260724` (id 70) — 10,437 cards, 3,209.6s,
**0** fetch failures, no lockout, no RSS-limit hit; `rescan-wave1b-20260724`
(id 75) — 10,437 cards, 3,115.1s, **1** fetch failure (not 0 — the
dry-run had 0, the real write had 1; the brief's "0 fetch failures"
claim only holds for the dry-run half). **Not confirmed**: the
"~190MB RSS" figure. `PilotRunLedger.counters` for both rows records
`scope`/`completed`/`elapsed_s`/`cohort_size`/`lockout_hit`/
`rss_limit_hit`/`fetch_failures`/`short_circuited` — no memory-usage
field at all, and no report file or journal entry for either run_id
exists in `docs/` to cross-check against. This is a real observability
gap, not a contested number — see §5's observability section, which
treats "the streaming ledger should record what the batch ledger
didn't" as a design requirement rather than working around the gap.

`run_id=rescan-wave1-20260724` (id 71) exists as a `failed` row with an
empty `counters` dict, started and finished within 3ms 2026-07-24T09:20:51Z
— consistent with a fast pre-flight rejection (e.g. a guard failing
before any work started), superseded by the successful `rescan-wave1b`
run four hours later. Not investigated further here; irrelevant to the
throughput numbers above.

---

## 2. Proven primitives to build on

Stage E does not start from zero. Four pieces of exactly the discipline
it needs already exist and are cited here rather than redesigned:

1. **The resume contract's kill-test, already demonstrated.** The
   `catalog-completion-plan.md` "Stage E resume contract" paragraph
   (owner directive, 2026-07-19) is on `master` today. Its acceptance
   test — kill-and-restart at an arbitrary mid-batch point, a truthful
   interrupted-run ledger, idempotent recovery with zero manual cleanup
   — first passed in production 2026-07-23 (kill at 105/1000 committed,
   `DRILL-PASS 2026-07-23T18:31:39Z`) and is referenced in passing on
   `master` at `docs/pipeline-fidelity-gate.md` line 972 ("concurrent
   `run_image_evidence_cohort` crash-drill passes" growing the marker
   reparse pool by ~680 rows between two dry rehearsals). **The
   re-runnable script and its full write-up are not yet on `master`** —
   they exist on open PR [#405](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/405)
   ("Graduate crash-drill script..."), which copies `crash_drill.sh` to
   `scripts/ops/crash_drill.sh` and documents it in the resume-contract
   section (its one edit-point per run is the seeded cohort query,
   currently a 1,000-card slice of the blank-collector-text pool). This
   brief treats #405 as **pending merge, not yet authoritative** — §7's
   kill-test acceptance section for the streaming path should be
   sequenced after #405 lands, extending the same script rather than
   writing a second one. This partially satisfies #153's own title
   already: the resume contract and a working kill-test both exist for
   the **batch** driver; what's still open is making the same guarantee
   hold for a **continuous** one (§3).
2. **Vote-collision skip-if-exists guard** — PR #411 ("Fix
   local_lands_identify write-path vote collision and dry-run
   would_cast=0"), merged, closes #407/#408. Establishes the pattern a
   streaming per-card write path needs: a write attempt against a card
   that already carries a vote from the same `anonymous_id` must be a
   documented no-op, not a duplicate/error, so a re-triggered streaming
   job is naturally idempotent at the vote layer.
3. **Reparse retract-and-recast** — `reparse_collector_evidence.py`
   (`MPCAutofill/cardpicker/management/commands/reparse_collector_evidence.py`),
   documented at `docs/troubleshooting.md` line 987 and exercised
   repeatedly in the fire sequence (`docs/pipeline-fidelity-gate.md`
   §14, e.g. the lexicon-gate retraction pass, 52,349 rows retracted).
   Establishes the pattern for a streaming re-entry: when evidence
   changes under an already-voted card, retract the stale vote and
   recast rather than leaving it stale — never accumulate contradictory
   votes silently.
4. **Forced-dry-run gates + ledger self-recording** — PR #373
   ("Command-lifecycle hardening for Stage C/D pilot commands"), merged.
   `pilot_run_lifecycle.py` requires a matching recent dry-run before
   `--write`/`--apply` (overridable via `--skip-dryrun-check`, always
   logged), and saves `COMPLETED`-with-counters before terminal output
   so a severed stdout can never flip a completed run to `FAILED` — the
   exact bug class `docs/pipeline-fidelity-gate.md` line 918's "Pass-9
   ledger gap" describes as pre-dating this hardening. Also self-records
   a `PilotRunLedger` row for `consensus_recompute`, previously absent.
5. **Evidence-first reads** — PR #391 ("Read stored ImageEvidence first
   in the lands identifier"). `local_lands_identify` now consumes a
   card's current `ImageEvidence` row when one exists, skipping
   fetch+OCR entirely, falling back to a live fetch only when no current
   evidence exists — the exact "don't refetch what's already extracted"
   discipline a continuous streaming trigger needs to avoid re-doing
   Stage C work on every touch.
6. **scryfall-cache fail-loud guard** — PR #412 ("Persist scryfall_cache
   volume + fail-loud missing-cache guard"). A streaming daemon that
   runs indefinitely must fail loudly and immediately on a missing
   dependency rather than degrading silently over a long uptime; this
   PR is the existing precedent for that posture on the canonical-data
   side.

---

## 3. Design decisions

### (1) Trigger: qcluster job on card-create/evidence-change, vs. periodic cron sweep

**Recommendation: event-driven (qcluster job dispatched on card-create
and on evidence-change), with a low-frequency cron sweep as a
correctness backstop, not the primary path.**

Issue #278 ("AI-art detector: rescan-on-evidence-change tool") already
establishes the consumer-side framing this decision has to match: its
selector is explicitly evidence-change-shaped — "cards holding a
`CardScanLog(anonymous_id='ai-art-detector-v1', skip_reason='no-marker-hit')`
whose current `ImageEvidence.updated_at` postdates the scan-log row."
A periodic full-table sweep can express that same query, but pays for a
table scan every cycle regardless of how few cards actually changed; an
event-driven dispatch fires exactly once per actual state transition
(new card, or the specific evidence row that changed) and needs no scan
at all. Given Stage D's own per-card DB-read-only cost is in the
low-single-digit-ms range (§1) — cheap enough that a burst of qcluster
jobs is not a per-job concern — the event trigger's downside is
bounded, while a cron sweep's downside (redundant full-table work on
every tick, worse as the catalog grows) is not.

The cron sweep still earns a place as a backstop: `django-q`'s own
job-delivery guarantees are at-least-once-attempted, not
exactly-once-delivered, and this repo does not currently have an
audited "no dispatch was ever silently dropped" property. A low-
frequency (e.g. daily) sweep re-running the same evidence-change
selector against the full table catches anything a lost dispatch missed
— cheap relative to Stage C compute cost, since it is a Stage-D-shaped
DB query, not a re-extraction.

### (2) Work granularity: per-card jobs vs. micro-batches

**Recommendation: micro-batches (a bounded card-id list per job), not
per-card jobs, with the batch size set by measured per-card cost, not a
fixed constant.**

A `PilotRunLedger` row currently represents one _run_ (a whole
management-command invocation) — 78 rows exist for the entire pipeline's
history to date (live count, 2026-07-24). A per-card streaming job would
turn this into one ledger row per card: at the current 218,345-card
catalog, that is a >2,800x multiplication of ledger volume for the
existing backlog alone, before any future growth. `PilotRunLedger`'s own
table is tiny today (104 kB, live query) specifically because it's
batch-shaped; per-card semantics would change its growth curve
entirely and it would need the same retention thinking §8 gives
`CardScanLog`.

Micro-batches (recommended size: enough cards that one batch's wall-
clock cost stays in the few-seconds-to-low-tens-of-seconds range at the
Stage C worst-case floor of 3.25 cards/s — roughly 10-100 cards per
batch, tuned against live host load per decision (3) rather than fixed
here) keep ledger-row growth proportional to _dispatch_ volume, not
_catalog_ volume, while still being small enough that a `kill -9`
mid-batch loses at most one batch's uncommitted work — the same
tolerance the existing kill-test already demonstrated at 105/1000
(§2 item 1), just at a smaller N. A batch-per-job ledger row can carry
the exact same `counters` shape (`scope`, `completed`, `elapsed_s`,
`fetch_failures`, etc.) the batch driver already uses, so no new ledger
schema is needed — only a new _dispatch_ shape sitting on top of the
existing per-run row semantics.

### (3) Backpressure / rate control

**Recommendation: derive concurrency and dispatch rate from measured,
live host load (CPU/RSS), not a fixed worker count — the measured
envelope in §1 already shows fixed concurrency assumptions failing on
this exact host.**

The OCR-heavy concurrency probe (`docs/reports/2026-07-20-pipeline-compute-profile.md`)
measured `ThreadPoolExecutor(concurrency=6)` running **3.25x SLOWER**
per card than sequential on this box (`speedup_factor = 0.31x`) while
burning 27.7x more CPU-seconds/card — CPU-bound Tesseract work
oversubscribing a fixed 8-core count, not scaling with added
concurrency. The decoupled fetch/compute architecture (§1, PRs #228/
#237) already fixes the specific failure mode that measurement found
(fetch-wait no longer blocks compute threads), but the underlying
constraint — a fixed core count shared with the rest of the live stack
— doesn't go away, it only moves to whatever concurrency the compute
side itself runs at. This host's shared-CPU sensitivity shows up
independently in the frontend test suite too: `docs/troubleshooting.md`
documents Jest tests flaking under full-parallelism CPU contention
(line ~611: "this sandbox's CPU is shared across as many parallel Jest
worker processes as `npx jest` defaults to spawning") and a Playwright
spec failing intermittently specifically under `--workers=4` "parallel
Playwright workers contending for CPU with the dev server's own
on-demand compilation" (line ~1633) — different subsystem, same
underlying lesson: this box's throughput under concurrency is a
measured, not assumed, property.

Concretely: a streaming dispatcher should read current host load
(`load average`, container RSS — both already sampled in existing
resource-profile reports, e.g. `docs/reports/2026-07-23-4c-pilot-dry-run.md`'s
"Host load average peaked at 1.09 (well under the 7.0 escalation
threshold)") before issuing the next micro-batch, and hold or shrink
dispatch when load crosses a threshold, rather than issuing batches on
a fixed timer/fixed worker-pool size irrespective of what else the box
is doing at that moment (the live stack, ES, Postgres, and — per
WORKERS.md's currently active row — an in-flight 197k-card Stage C
remainder run sharing the same host). The 7.0 escalation threshold and
the RSS "note-prominently"/kill bars already established in the pilot
reports (`2026-07-23-4c-pilot-dry-run.md`) are the existing reference
points to reuse, not new ones to invent.

### (4) Where consensus recompute fits

**Recommendation: per-touch incremental recompute for the specific
(card, tag) pairs a streaming job just wrote to, not a scheduled
full-DB sweep as the steady-state default.**

`consensus_recompute --apply`'s full-DB pass is fast in absolute terms
(383.9s for 163,045 pairs, §1) but that cost scales with catalog size
and pair count, not with how many cards actually changed in a given
window — under continuous per-card/micro-batch writes, most of a full
sweep's work would be re-checking pairs nothing touched. A streaming
write path should call the same consensus-recompute machinery scoped to
just the touched `(card, tag)` pairs immediately after a batch commits
(the existing `local_calculate_verdicts`/`vote_consensus` call shape
already supports a scoped query, per the fire sequence's own per-pass
`considered`/`changed` counters). The full-DB sweep remains valuable as
a periodic correctness backstop (the same at-least-once-not-exactly-once
reasoning as decision (1)'s cron sweep) — e.g. weekly — to catch drift
from any write path that bypassed the incremental hook, but should not
be the primary mechanism once streaming is live, since its cost curve
is wrong for a continuous system.

### (5) The human-backed gate and dry-run-guard conventions in a continuous world

**Recommendation: replace the per-batch owner dry-run poll with a
standing, owner-ratified authorization envelope — explicit bounds the
owner sets once, that the streaming daemon self-enforces and can never
exceed without a fresh owner action.**

The per-card resolution false-accept rate is 0 "by construction and
measured 0" (`docs/theory.md` §7b) because the human-backed gate
(`vote_consensus.resolve_weighted_consensus`, the owner-ratified
vote-weight scenario matrix) structurally prevents machine-sourced
votes from ever alone clearing the resolution threshold — this
invariant is untouched by moving from batch to streaming, since it
lives in the vote-weight/consensus layer, not the dispatch layer, and
nothing in this brief proposes touching it. What genuinely doesn't
transfer is the _operational_ per-batch pattern this pipeline has used
throughout the fire sequence: `pilot_run_lifecycle.py`'s forced
dry-run-before-write gate (#373) and the owner polling each batch's dry
run before authorizing its write. A continuous daemon issuing
micro-batches every few seconds cannot have a human review each one —
that's the "per-card polls are absurd" problem the task brief names
correctly.

The proposed replacement: the owner ratifies a standing envelope once
per meaningful change in scope — cohort/source, extractor-version set,
and numeric bounds (e.g. max cards/hour, max fetch-failure rate before
auto-pause, max RSS before auto-pause, mirroring the existing "note-
prominently"/kill RSS bars and the 7.0 load-average escalation
threshold already in use) — and the streaming daemon self-enforces
those bounds exactly the way the forced-dry-run guard self-enforces
"no write without a preceding dry run" today: an out-of-envelope
condition halts dispatch and requires a fresh owner action to resume,
the same posture #373's `--skip-dryrun-check` override already
establishes (allowed, but always logged, never silent). The dry-run
convention itself doesn't disappear — it moves from "one dry run per
batch, polled by a human" to "one dry run per _envelope change_,"
matching the cadence a human can actually review. This is a genuinely
new mechanism, not yet built anywhere in this codebase, and needs an
explicit owner ruling on the envelope's exact bounds before
implementation — flagged as an open item in §9.

### (6) Observability: the ledger's streaming equivalent

**Recommendation: extend `PilotRunLedger`'s counters shape rather than
inventing a parallel model, but close the two real gaps this brief's
own verification pass just found.**

§1's live-DB check surfaced two concrete gaps worth fixing before
streaming, not after: (a) `PilotRunLedger.counters` has no RSS/memory
field — the "flat ~190MB RSS" claim in the originating task brief could
not be verified against anything, batch or streaming, because nothing
records it durably today (resource-profile reports capture RSS
separately, by hand, per investigation — not as a ledger field); (b) a
`failed` ledger row (id 71, `rescan-wave1-20260724`) persists with an
empty `counters` dict and no error detail, which is exactly the kind of
row a streaming daemon issuing many small jobs per hour cannot afford —
at per-card/micro-batch granularity, an unattributed failure needs a
recorded reason to be triage-able at all. A streaming-era ledger row
should carry: the existing counters shape (`scope`, `completed`,
`elapsed_s`, `fetch_failures`, `lockout_hit`, `rss_limit_hit`,
`short_circuited`), plus a sampled RSS field and a required
`failure_reason` string whenever `status=failed`. Aggregation for a
human-readable "is streaming healthy right now" view is a dashboard
query over these rows (cards/hour, failure rate, current envelope
bounds vs. current load) — not a new persisted model.

---

## 4. Efficiency candidates

Each candidate below is checked against `docs/theory.md`'s soundness
model: the decode-or-abstain rule (§1, "accept iff exactly one
candidate survives within the evidence ball; abstain otherwise") and
the measured/structural resolution false-accept bound of 0 (§7b, "the
_resolution_ false-accept rate is 0 by construction and measured 0").
**No candidate below is permitted to weaken either property.** Where
one would, it is marked REJECTED and the reasoning is stated, not
smoothed over.

### 1. Escalation-tier reordering by measured yield

PR #392's own body states the measured cost: the old lexicon-invalid
population paid ~216ms/card at ~1.15 attempts (near-baseline), while a
comparable near-full-escalation population paid ~909ms/card at ~7.06
attempts (`docs/reports/2026-07-23-ocr-preprocessing-probe.md` line 47
and `-probe-2.md` line 46 are the underlying per-variant measurements
PR #392's body derives its summary from). If tiers were reordered so
the highest-yield tier ran first, average attempts-per-card would drop
for the population that currently pays full escalation.

**Attribution check (verified 2026-07-24)**: this cannot be built today
without a new counter. `ImageEvidence.extractor_versions` records only
that an extractor ran and its version string (`image_evidence.py` line
786 etc.) — it does not record _which tier_ produced the accepted
parse. `CardScanLog` records `anonymous_id`/`skip_reason`/`run_id`, not
per-tier attempt data either. The tier/variant loop itself
(`_collector_line_ocr_attempts`, `image_evidence.py` ~line 294) is a
lazy generator yielding `(variant, config, tier)` — the tier number
exists in-memory during the loop but is discarded once a winning parse
is found; nothing persists it.

**Recommendation**: build the streaming-era counter first (record which
tier produced the accepted parse — a small addition to
`extractor_versions` or a sibling field, not a new table), let it
accumulate real distribution data across the streaming path's first
weeks, then reorder tiers once there's a real hit-rate to reorder by.
Reordering tiers before that is prioritizing a guess over the same
"measure before optimizing" discipline this whole pipeline was built
on. **Soundness**: unaffected either way — tier order only changes
_when_ a lexicon-valid parse is found, never _whether_ an invalid one
is accepted (PR #392's own lexicon gate is the actual soundness
backstop here, independent of tier ordering). Not rejected, sequenced
behind its own prerequisite.

### 2. Cheap-first deduction ordering for new cards

Stage D's cheapest signals — name-index narrowing (`CandidateNameIndex`,
built once per run today, see item 5 below), singleton detection, and
source metadata — cost low-single-digit milliseconds (§1's Stage D
range) against Stage C's OCR-heavy ~300ms+/card. Running them first,
before the expensive fetch+OCR pass, is attractive purely on cost.

**What evidence standard this would rest on, checked against theory.md**:
the existing precedent for exactly this shape is `local_lands_identify.py`'s
own SINGLETON case (§2's pipeline docstring, lines 32-34): artist-OCR
narrows a name's candidate set to exactly one, but that narrowing
_alone_ never casts a vote — a phash comparison against that singleton
must still independently clear `find_best_match`'s standard acceptance
distance before a vote is cast (confidence 0.85, "two channels
independently arrive at the same answer" — the docstring's own words).
The Part 4 HOLD-B sample (`docs/reports/2026-07-18-part4-hold-b.md`
line 26) measured exactly 3/300 (1.0%) of a real sample landing in this
singleton path, and even that 3-card fraction cleared it via phash
confirmation, not narrowing alone. This is the working example of
"cheap signal narrows, image evidence still confirms" already live in
this codebase.

**Recommendation**: cheap Stage D signals may **prioritize** — reorder
the streaming work queue so singleton-shaped or high-confidence-prior
cards get processed first, or route a card's Stage C job with a hint
about which candidate to check first — but must **never resolve** a
card in place of the OCR/phash evidence channels. This is a scheduling
optimization, not a new evidence path, and needs no change to the
decode-or-abstain rule or the vote-weight gate. A version of this that
DID skip OCR/phash on cheap-signal narrowing alone would be a genuine
soundness regression (an unconfirmed vote reaching the resolution gate
on non-image evidence) — **that version is explicitly REJECTED**, not
proposed.

### 3. Decoupled fetch/OCR pipelining as the streaming default

**Recommendation: adopt, unconditionally.** §1's numbers already make
this a clean call: the decoupled architecture (PRs #228/#237) measured
5.542-5.769 cards/s in production (95.2%-99.1% parallel efficiency,
`docs/reports/2026-07-20-decoupled-canary-confirm.md`) against the
coupled architecture's 3.852-3.797 cards/s on the exact same host and
cohort shape — a ~1.44-1.52x wall-clock speedup, already shipped and
production-proven, not a proposal. There is no coupled-vs-decoupled
tradeoff left to make for a new streaming worker: decoupled is strictly
better on every measured axis (throughput, CPU efficiency) and carries
no soundness implication at all — it changes _how_ the existing
extraction code is scheduled across threads, not what it computes. The
streaming daemon's compute stage should be built on the decoupled
model from the start, not the older coupled `ThreadPoolExecutor`
pattern the OCR-concurrency probe (§3, decision (3)) already showed
losing to sequential execution under contention.

### 4. Skip-reason-aware re-entry

**Recommendation: codify the taxonomy explicitly — most skip reasons
are terminal for a given evidence version; only an evidence-change event
re-opens a card to re-scan, never an elapsed-time trigger.**

This is already issue #278's own selector, verbatim: a card holding a
non-rescannable skip (`CardScanLog(anonymous_id=..., skip_reason='no-marker-hit')`)
re-enters eligibility only when "current `ImageEvidence.updated_at`
postdates the scan-log row" — never on a periodic timer, never by
default. `CardScanLog`'s own model docstring (`models.py` ~line 1256)
states the same generalization independently: "the resume query only
cares whether ANY non-re-scannable row exists" — i.e. a skip reason is
non-rescannable _by default_ unless the specific engine's own resume
query says otherwise. The streaming design should make this the
explicit, generic re-entry contract for every engine, not a per-engine
ad hoc convention re-derived each time a new detector is built: **a
skip row is a terminal state for its evidence version; the only valid
re-entry trigger is that evidence version changing under it** — the
same "resume filter = cards lacking an ImageEvidence row for this
extractor-version set" shape issue #153 already specifies for the
crash-recovery case, generalized to cover the ongoing-operation case
too. No soundness implication — this governs _scheduling triggers_
only, not vote/gate semantics.

### 5. Amortized loading

**Recommendation: yes, and the existing pattern already shows the gap
precisely.** `known_set_codes()` (PR #392's own body: "built once per
run (one DB query) and threaded through explicitly... before forking
the compute pool") and `CandidateNameIndex()` (constructed once per
management-command invocation across every caller — confirmed at
`local_identify_printing_tags.py` line 1086, `local_residual_classify.py`
line 221, `local_lands_identify.py` line 546, `harvest_probe.py` line
73 — always built fresh at the top of each `handle()`, never cached
across invocations) are both already amortized **per batch run**, never
rebuilt per-card within a run. `local_phash.py` has no caching layer at
all today (confirmed by inspection — no `cache`/`lru_cache` usage in
the file) — each canonical-hash lookup is a fresh computation or a
fresh evidence-row read.

The gap: "per run" stops being a meaningful unit once there is no
discrete run boundary — a long-lived streaming worker process has no
natural point to rebuild these at, unlike a `management command`
invocation that starts and ends. The lexicon and name-index should be
built **once per worker process lifetime** instead, with an explicit
invalidation event (a new `CanonicalExpansion`/`CanonicalCard` row
landing) rather than a per-batch rebuild — the same "evidence-change
event triggers refresh" shape as decision (4)'s incremental consensus
recompute. This is a pure performance change with no soundness
implication: both structures are read-only lookups feeding into the
existing decode-or-abstain evidence channels, never a vote source
themselves.

---

## 5. Hardware envelope & federated scalability

### This box, concretely

Measured 2026-07-19, `docs/infrastructure.md` line 27: **8 OCPU
(aarch64, Neoverse-N1 — Oracle's "Ampere" tier), 23Gi total RAM**,
running the full production Docker stack (django/worker/postgres/
elasticsearch/nginx) continuously, plus whatever pilot/backfill job is
active at any given time (WORKERS.md's currently-active row: an
in-flight 197k-card Stage C remainder run, started 2026-07-21T19:30Z,
holding a backend deploy freeze for its duration). **Every rate in §1
was measured on this exact box, under this exact co-tenancy** — not a
dedicated benchmark environment. The OCR-concurrency probe's 3.25x
slowdown under `concurrency=6` (§1, §3 decision (3)) and the frontend
test suite's documented CPU-contention flakiness
(`docs/troubleshooting.md`, Jest full-parallelism and Playwright
`--workers=4` entries cited in decision (3)) are two independent,
already-measured demonstrations that this host's throughput under
concurrency is not a fixed property — it degrades under contention with
its own other tenants. Decision (3)'s "derive rate control from live
host load, not a fixed worker count" recommendation follows directly
from this, not from caution alone.

### Scale-down requirement

This pipeline is part of the federation pitch
(`docs/federation-v1.md`, `docs/federation/public-export-v1.md`) — the
design must run correctly, if slowly, on a materially weaker
mpc-autofill-lineage instance, not just scale up on ours. Consequences
this brief specs explicitly:

- **Every concurrency/batch knob should default from a declared
  resource envelope (cores/RAM the operator states), not a hardcoded
  constant** — the same shape decision (3)'s live-load-derived rate
  control already needs, extended to a one-time declared floor at
  startup for instances too small to usefully sample live load moment-
  to-moment.
- **A single-worker, single-core floor mode must be correct, just
  slow — never a degraded/unsound mode.** Projected throughput at that
  floor: the measured single-process worst-case is 3.25 cards/s
  (§1, `rescan-wave1-dry-20260724`, itself already single-process on a
  shared host) — under real co-tenancy on a smaller box this could
  reasonably run at some fraction of that; even taken at face value,
  3.25 cards/s × 86,400s = **~280,800 cards/day**, comfortably above
  any single federated instance's realistic daily new-card volume. The
  point of this mode is not speed, it's that it never trades soundness
  for throughput at the floor — every decode-or-abstain/human-gate
  property in §4 holds identically regardless of worker count.
- **Bounded memory independent of catalog size** is the actual target
  property the task brief's (unverified, §1) "~190MB RSS" figure was
  gesturing at — the two live wave-1 ledger rows at least confirm
  `rss_limit_hit: false` held across a 10,437-card run (`PilotRunLedger`
  ids 70/75), consistent with a bounded-not-catalog-scaling footprint,
  even though the exact RSS number itself isn't recorded (§3 decision
  (6) specs fixing that). This is the property a streaming worker
  should preserve by construction (stream cards through, never hold the
  whole cohort in memory) — not a number to hit, a shape to keep.
- **Graceful pause/resume under pressure should be an explicit,
  advertised feature, not an incidental side effect.** The resume
  contract (§2 item 1) already makes an arbitrary kill free — zero
  manual cleanup, idempotent restart. A streaming daemon should expose
  the same property as a deliberate operator action ("pause," not just
  "survive a crash"), so a low-resource instance can run the pipeline
  in short bursts between other work without any special handling.

### Disk

The governing premise (`CLAUDE.md`: "we index, we do not store images")
is the hard constraint this design inherits unmodified — no proposal in
this brief stores image pixels beyond transient fetch/decode, and
nothing here revisits that posture. What _does_ grow under continuous
operation is evidence/scan-log/ledger rows, not pixels. Live table
sizes queried 2026-07-24 (218,345 cards):

| table                        | rows      | total size | per-card                                                            |
| ---------------------------- | --------- | ---------- | ------------------------------------------------------------------- |
| `cardpicker_imageevidence`   | 218,269   | 460 MB     | ~2.1 KB/card                                                        |
| `cardpicker_cardscanlog`     | 2,090,159 | 451 MB     | ~9.6 rows/card, ~2.1 KB/card                                        |
| `cardpicker_cardprintingtag` | 168,783   | 63 MB      | —                                                                   |
| `cardpicker_pilotrunledger`  | 78        | 104 kB     | negligible today, see §3 decision (2) on why streaming changes this |

`CardScanLog` is the one to watch: it is explicitly append-only by
design ("older rows for the same pair are historical... not deduplicated
away," model docstring), and a streaming system doing continuous
evidence-change re-entry (§4 item 4) will write scan-log rows at a
materially higher rate than the current batch-run cadence. This brief
does not spec a pruning policy — the model's own append-only rationale
(a durable audit trail, mirroring how vote tables work) argues against
naive deletion — but flags retention/pruning of superseded
(non-current) scan-log rows as an open item for whoever builds this
(§9), not a decision made here.

### Federation seam

Streaming's eventual outputs (verdicts/votes cast by the streaming
path) should slot into the `public-export-v1` signed-JSONL shape
(`docs/federation/public-export-v1.md`, "one JSON object per resolved
verdict, newline-delimited," human-confirmed-only in v1) the same way
any other verdict-producing pass's output would — no design work here,
since that spec itself is HOLD pending owner review. Noted as the seam
that exists, not designed further.

### Sibling instances sharing compute (forward-looking, not designed)

A federated mpc-autofill-lineage instance cooperating with another on
pipeline work — e.g. a stronger instance running Stage C extraction for
a weaker sibling's cards, or splitting work by source across instances
— is a real future direction worth naming, not designing:

1. **Work-unit shape**: the card-ids-file + run-ledger contract this
   pipeline already uses (`--card-ids-file`, per-run `PilotRunLedger`
   row) is already a serializable, instance-agnostic work unit — a list
   of card identifiers plus a scope hash is exactly what a cross-
   instance handoff would need to describe "do this work," with no
   redesign required to make it expressible that way.
2. **Hard constraint**: the index-not-store posture and the federation
   pitch's "card artwork never crosses the wire" claim
   (`CLAUDE.md`'s governing premise) apply to inter-instance traffic
   exactly as strictly as to our own disk. A sibling computing evidence
   for another instance's cards would have to fetch the source image
   directly from its origin (Drive/etc.), never receive pixels from the
   requesting instance — only evidence/verdict rows (the
   `public-export-v1` JSONL shape) may cross between instances. This is
   not a new rule for this brief to invent; it's the existing governing
   premise applied to a network boundary that doesn't exist yet.
3. **Trust implications**: machine votes produced by a sibling's
   compute need attributable weight/provenance per originating
   instance — `anonymous_id` namespacing per instance/engine is the
   existing primitive for this (every engine already has its own stable
   `anonymous_id`; extending that to include an instance identifier is
   a natural, not novel, extension). Sybil/multi-actor trust weighting
   belongs to `docs/theory.md`'s Dawid-Skene addendum (§6, "Sybil/bad-
   actor unification — future work, nothing built") — cited, not
   restated, since that section already owns this problem.
4. **Cost/benefit, honestly**: this box's own single-instance decoupled
   throughput is 5.542-5.769 cards/s (§1) — 86,400s × that range is
   **~478,900-498,500 cards/day**; the blended-regime estimate (§1,
   ≈4.29 cards/s) is **~370,700 cards/day**. Even the low end of that
   range is large relative to any one federated instance's realistic
   catalog growth rate (this fork's own full catalog is 218,345 cards
   total, accumulated over the project's whole lifetime, not per day).
   **Recommendation: not yet.** The coordination complexity of a
   cross-instance work-handoff protocol is not justified by a
   throughput gap that doesn't exist at realistic federated scale — a
   single instance's own compute floor comfortably outpaces plausible
   demand. The work-unit shape in item 1 keeps the door open cheaply
   (it costs nothing to note that the existing contract already
   generalizes) without spending design effort on a protocol nothing
   currently needs.

---

## 6. Sequencing (owner-ratified)

1. **The ~6,535-card Bug-A tail (issue #418) is streaming's shakedown
   cohort — it does not get a batch pass.** Issue #418's own body states
   the pool: 16,972 total blank-tier-1 cards, wave 1 = top 4 sources
   (10,437 cards, already measured at the §1 worst-case floor), leaving
   16,972 - 10,437 = **6,535** as the tail this issue tracks. Note for
   whoever implements this: `docs/pipeline-fidelity-gate.md`'s "What
   remains open" item 1 references a **17,531**-card current pool for
   the same Bug-A re-scan — 559 cards larger than #418's snapshot,
   consistent with the ongoing 197k-card Stage C remainder still adding
   to this pool (WORKERS.md's active row). **The exact tail count should
   be re-derived fresh via #418's own DB query at streaming-cutover
   time, not hardcoded from either number in this brief** — both are
   real, dated snapshots, neither is current by construction.
2. **The AI-art-detector pass (issue #278) is the second consumer.**
   Its own selector (§3 decision (1), §4 item 4) is already shaped
   exactly like the streaming re-entry contract this brief specs —
   building #278 against the streaming path, second, exercises the
   evidence-change re-entry machinery on a real, already-scoped
   workload before any third consumer is asked to trust it.

---

## 7. Kill-test acceptance for the streaming path

Extending the existing drill (§2 item 1) rather than writing a new one:
the batch kill-test (kill -9 mid-batch, truthful ledger, idempotent
resume, zero manual cleanup — production-proven 2026-07-23,
`scripts/ops/crash_drill.sh` pending merge on PR #405) needs one
additional acceptance property to cover the streaming path: **killing
the streaming _dispatcher_ process (not a single batch job) must leave
every already-committed micro-batch intact and every in-flight batch
resumable exactly as the existing kill-test already proves for a single
run** — i.e. the streaming daemon is not a new failure surface, it's
the existing resume contract applied to "many small runs" instead of
"one big run." Concretely, before streaming is considered production-
ready: (a) run `crash_drill.sh` (once graduated via #405) against a
micro-batch-sized cohort to confirm the existing drill's guarantees
hold at the smaller granularity decision (2) proposes; (b) a second
drill killing the _dispatcher_ itself (not a worker job) mid-stream,
confirming no batch is double-dispatched or silently dropped on
dispatcher restart — this is new, since the batch driver has no
dispatcher-vs-worker split to test. Both should fold into the same soak
gate #153 already names (task #156), not become a separate gate.

---

## 8. Review

Per the owner's standing mandate on this brief: the implementation PR
that eventually builds any of §3-§5 gets a Tron pass with an explicit
**efficiency + soundness** mandate — reviewing not just "does this
work" but "does this preserve every property §4 checked against
`docs/theory.md`" — before owner review, not instead of it.

---

## 9. Open items / decisions needed

1. **§3 decision (5)'s standing authorization envelope** (bounds for
   cards/hour, max fetch-failure rate, max RSS before auto-pause) needs
   an explicit owner ruling on its numeric bounds before implementation
   — this brief proposes the mechanism, not the numbers. **RESOLVED
   2026-07-24 — see §10(a)**: replaced with a two-mode (PASSIVE/BULK)
   split rather than a single cards/hour figure.
2. **§5's `CardScanLog` retention/pruning policy** under continuous
   evidence-change re-entry is flagged, not decided — the append-only
   design rationale argues against naive deletion, but no retention
   policy exists today and streaming will grow this table faster than
   the current batch cadence does. **RESOLVED 2026-07-24 — see
   §10(b)**: a 10M-row/5GB tripwire, pruned via a dry-run-gated
   management command.
3. **§4 item 1's per-tier attribution counter** should land before any
   escalation-tier reordering is attempted — sequencing note, not an
   open question, but worth stating so the reordering isn't attempted
   out of order.
4. **§6 item 1's exact Bug-A tail count** should be re-queried fresh at
   streaming-cutover time (16,972-10,437=6,535 per issue #418's own
   snapshot vs. the pipeline-fidelity-gate.md's later, larger
   17,531-card pool) — not a design decision, a data freshness note.
5. **PR #405's merge status** — this brief treats the crash-drill script
   as pending, not yet on `master` (still open, unmerged, as of
   2026-07-24); §7's kill-test extension should be sequenced after it
   lands.

## 10. Ratified amendments (2026-07-24, owner)

The owner ratified two of §9's open items outright and sharpened two
further points this brief had otherwise left to design-time judgment.
**The brief's overall HOLD status is unchanged by this section** — §3-§5's
implementation still needs its own owner review before it's built; what's
resolved here is four specific open questions within it, not the HOLD
itself.

### (a) Two-mode operation replaces §9 item 1's cards/hour ceiling

**Ratified: no fixed cards/hour ceiling, in either mode.** §3 decision
(5) proposed a standing authorization envelope with numeric bounds
including a max-cards/hour figure; the owner's ruling replaces that
single number with an operating-mode split instead:

- **PASSIVE mode** — continuous operation against submitted drives and
  newly-created cards (the steady-state trigger §3 decision (1) already
  specs). Load-governed, not rate-governed: no artificial cards/hour cap
  at all. Dispatch is bounded entirely by live bars, matching §3
  decision (3)'s "derive rate control from live host load" recommendation
  with the actual numbers now attached:
  - pause dispatch above host load average **7.0** (the existing
    escalation threshold, §3 decision (3)/§1, reused unchanged);
  - RSS ceiling **512MB per worker**;
  - fetch-failure rate **>1% over a rolling 500-card window**;
  - **instant pause** on any Google lockout signal (the existing
    `lockout_hit` bar, §1, reused unchanged);
  - **resume requires a fresh owner action** in every case above — no
    self-resume, matching #373's `--skip-dryrun-check` posture (an
    override is allowed, but never silent/automatic).
- **BULK mode** — backfill work, unchanged from today's discipline:
  polled per-batch at max throughput, gated by `pilot_run_lifecycle.py`'s
  forced dry-run-before-write check (#373), one human poll per batch —
  exactly the operating pattern every fire-sequence pass in
  [`docs/pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) already
  used, not revised by this ratification.

§3 decision (5)'s mechanism (the daemon self-enforces bounds, halts
out-of-envelope, requires fresh owner action to resume) stands
unchanged; only the numeric shape of the envelope was open, and is now
closed for PASSIVE mode. §9 item 1 is **RESOLVED**.

### (b) `CardScanLog` retention tripwire (§9 item 2)

**Ratified: stays append-only under normal operation** — §5's own
"durable audit trail" rationale against naive deletion is unchanged —
**but a concrete tripwire now exists** instead of an open-ended "flagged,
not decided":

- **Trigger**: 10M rows OR 5GB table size, whichever comes first (live
  size at the time of writing: 2,090,159 rows / 451MB, §5 — comfortably
  under both bars today; no immediate action needed).
- **Prune rule**: keep latest-per-`(card, anonymous_id)` plus every row
  under 12 months old; anything older AND superseded by a later row for
  the same pair becomes eligible for deletion.
- **Mechanism**: a new management command, gated by the same
  dry-run-then-poll discipline every other pilot command uses (#373's
  forced dry-run-before-write pattern) — never a bare delete.

§9 item 2 is **RESOLVED**.

### (c) Micro-batch size is measured, not chosen (§3 decision (2))

**Ratified: no pre-chosen constant.** §3 decision (2)'s own text already
hedged this ("roughly 10-100 cards per batch, tuned against live host
load per decision (3) rather than fixed here") — the owner's ruling makes
that non-negotiable: the actual batch size ships as a **measured output**
of §7's kill-test/tail-shakedown instrumentation (the ~6,535-card Bug-A
tail, issue #418, §6 item 1), not a value decided in this brief or
hand-picked at implementation time. Whoever builds §7's shakedown
instruments batch wall-clock cost directly against live host load and
derives the size from that data; this brief's 10-100 range is a sizing
sanity check on the result, not the answer.

### (d) 2026-07-24 IO audit outcomes feed §4

Two follow-ups to §4's efficiency candidates, from the same-day IO/
throughput audit of the Stage C pipeline:

- **PR [#424](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/424)**
  ("Fix three small IO findings from the 2026-07-24 audit"), merged:
  `requests.Session` reuse per `_DestinationLimiter` (~80-90ms/request
  eliminated once warmed, ~4-5% of pipeline wall-clock net of
  `GOOGLE_IMAGE`'s pacing governor), `CardScanLog.bulk_create()`
  replacing per-row `.create()` calls in `persist_evidence` (matching
  every other calculator's existing `bulk_create` convention), and a
  missing `.iterator()` on `run_image_evidence_cohort`'s resume-filter
  query (flagged against that exact command's own documented
  2026-07-22 parent-process OOM history, §1). All three land as §4's
  efficiency work continuing into the streaming build, not new
  candidates for this brief to re-evaluate.
- **Issue [#423](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/423)**
  ("tesserocr A/B spike"), open: replacing per-call `pytesseract`
  process spawn (~98ms fixed floor inside every ~195-205ms OCR call,
  paid up to 8x/card under escalation) with a persistent in-process
  `tesserocr` binding, estimated at 20-25% of total per-card wall-clock
  — the single largest efficiency candidate identified against §1's
  measured envelope, gated on an ARM64 wheel-availability check and a
  byte-identical A/B parity spike before any code change (a PROTECTED
  CORE substrate-swap under an unchanged public API, per
  [`docs/upstreaming/license-provenance.md`](../upstreaming/license-provenance.md)'s
  absorption discipline). Not yet built; tracked as the audit's largest
  open finding, not folded into §4's numbered list above since it needs
  its own spike before a recommendation can be made either way.
