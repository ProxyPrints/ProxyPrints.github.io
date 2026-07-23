# Zeroing execution + Bug-A forced-escalation sample — 2026-07-23

Run report + resource metrics for the
[`pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) §9 B(i)/
B(ii)+B(iii) zeroing steps and the §9(c) Bug-A forced-escalation sample
step, keyed by `run_id` — same convention
[`2026-07-23-bugb-reparse-dryruns.md`](2026-07-23-bugb-reparse-dryruns.md)
established, filed under `docs/data/` per §9's own "every run in this
sequence gets its own report ... committed under `docs/data/`" note
rather than `docs/reports/`.

All `PilotRunLedger` rows below (ids 35–40) verified live (`id`,
`run_id`, `command`, `dry_run`, `status`, `votes_written`,
`started_at`/`finished_at`, and `counters` where populated) — DB-verified
2026-07-23, read-only, single-row/indexed lookups only (the concurrent
§9(d) 4c pilot dry-run was in flight at query time; no bulk/full-table
scan run against it). Where a command has no `counters` JSONField
payload wired up (`reparse_collector_evidence`, `run_image_evidence_cohort`'s
own per-card OCR-funnel breakdown), the finer figures are relayed by the
owner from that run's stdout, not independently DB-re-derivable after
the fact — same caveat already established in
[`2026-07-23-bugb-reparse-dryruns.md`](2026-07-23-bugb-reparse-dryruns.md).

## B(i) — Bug-B write pass

### `bugb-write-dry-20260723T090258Z` — pre-write dry confirmation

`PilotRunLedger` id 35. `command=reparse_collector_evidence`,
`dry_run=True`. `started_at` 2026-07-23T09:03:02.581298Z, `finished_at`
2026-07-23T09:03:05.534876Z (DB-verified) — **2.95s**. `votes_written=0`
(dry). Confirmation pass against the regenerated 284-signature ID file
immediately ahead of the live write below — not a resource-profiling
target in its own right at this scale.

### `bugb-write-20260723T0905Z` — live write

`PilotRunLedger` id 37. `command=reparse_collector_evidence`,
`dry_run=False`. `started_at` 2026-07-23T09:12:39.354789Z, `finished_at`
2026-07-23T09:12:44.765051Z (DB-verified) — **5.41s**. `votes_written=236`
(DB-verified field).

**Counters** (stdout, relayed): `considered=285`, `fields_fixed=285`,
`retracted=236`, `gate_refused=0`.

Internal cross-check: `fields_fixed=285` matches §10/§12's pre-sized
"whole-DB reparse diffs exactly 284 guard rows plus 1 unrelated
improvement (card 62354)" cohort exactly (284 + 1 = 285) — this run is
that cohort, written. `retracted=236` is the subset of the 285 whose
**vote** actually changed (a wrong/no-match verdict flipped to a
corrected one); the remaining `285 − 236 = 49` are exactly the "49-row
gap where only verdict-changed cards get fields saved" the fire
sequence's B(i) patch requirement (§9) closes — those 49 got their
`collector_line_*` fields corrected unconditionally with no
accompanying vote change (their prior vote was already right, or they
carried no vote to begin with). `gate_refused=0` — the per-card
`resolve_printing()` safety gate never blocked a write in this run.

## B(ii)+B(iii) — retraction (`retract_stage_d_by_run_id`)

### `20260723T090331-fdf5822b` — pre-retraction dry-run

`PilotRunLedger` id 36. `command=retract_stage_d_by_run_id`,
`dry_run=True`. `started_at` 2026-07-23T09:03:31.871873Z, `finished_at`
2026-07-23T09:04:43.225765Z (DB-verified) — **71.35s**.

**Counters** (DB `counters` JSONField, verified):

| metric                  |  total | staged-write-20260721T0434Z | staged2-0721 | staged3-0721 | staged4-0721 |
| ----------------------- | -----: | --------------------------: | -----------: | -----------: | -----------: |
| `votes_deleted`         | 12,904 |                       8,825 |           70 |        3,010 |          999 |
| `skips_deleted`         |  7,773 |                       7,187 |           14 |           19 |          553 |
| `cards_resynced`        |      0 |                           0 |            0 |            0 |            0 |
| `skipped_resolved_gate` |      0 |                           0 |            0 |            0 |            0 |

`cards_resynced=0` here is expected — this is the dry-run, no resync
happens without `--write`. Ran **before** B(i)'s live write (09:03:31 vs.
09:12:39), so this preview reflects the full pre-flip 12,904-vote staged
cohort exactly as §6/§9 already documented it.

### `20260723T091446-35a1bde5` — live retraction

`PilotRunLedger` id 38. `command=retract_stage_d_by_run_id`,
`dry_run=False`. `started_at` 2026-07-23T09:14:46.516102Z, `finished_at`
2026-07-23T09:17:55.097389Z (DB-verified) — **188.58s (3m8.6s)**.

**Counters** (DB `counters` JSONField, verified):

| metric                  |  total | staged-write-20260721T0434Z | staged2-0721 | staged3-0721 | staged4-0721 |
| ----------------------- | -----: | --------------------------: | -----------: | -----------: | -----------: |
| `votes_deleted`         | 12,880 |                       8,801 |           70 |        3,010 |          999 |
| `skips_deleted`         |  7,773 |                       7,187 |           14 |           19 |          553 |
| `cards_resynced`        | 20,653 |                      15,988 |           84 |        3,029 |        1,552 |
| `skipped_resolved_gate` |      0 |                           0 |            0 |            0 |            0 |

Ran **after** B(i)'s live write (09:14:46 vs. 09:12:39), so
`votes_deleted` reads 24 lower than the pre-write dry-run above
(12,904 − 24 = 12,880) — those 24 are exactly the B(i) write's
false-no-match→genuine-match flips within the retraction's own
`staged-write-20260721T0434Z` target cohort (8,825 − 8,801 = 24): once
corrected, they were no longer eligible retraction targets. **Every one
of the original 12,904 staged votes is accounted for**: 12,880 deleted +
24 corrected-and-kept by B(i) = 12,904. `skips_deleted=7,773` matches
the dry-run exactly (per-run 7,187/14/19/553, unaffected by B(i)'s
scope). `skipped_resolved_gate=0` both runs — the per-card
`resolve_printing()` safety gate never blocked a retraction; zero
resolved-card overlap, as required.

### Verified end-state (DB-verified, post-retraction, read-only)

| check                                                                      |                                                                                                                                          value |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------: |
| `CardPrintingTag` rows, `anonymous_id='stage-d-join-key-v1'`               |                                                                                                                                              0 |
| non-rescannable `CardScanLog` skips, the 4 target run_ids                  |                                                                                                                                              0 |
| `CardPrintingTag` rows, `source='deduction'`                               |                                                                                                                                         28,112 |
| `CardPrintingTag` rows, `run_id='20260716T193408-6613a1a6'` (legacy pilot) |                                                                                                                                         43,425 |
| `Card` rows, `printing_tag_status='resolved'`                              |                                                                                                                                              3 |
| eligible pool (`local_calculate_verdicts` cohort)                          | 200,366 (relayed by owner — not independently re-queried this pass, to avoid a full-catalog scan against the concurrently-running §9(d) pilot) |

All rows above except the eligible-pool figure are direct DB counts run
this pass. The join-key-vote/non-rescannable-skip zeroes, the intact
deduction/legacy/resolved counts, confirm the retraction hit exactly its
intended target and nothing else — no user vote (55), deduction vote
(28,112), legacy pilot vote (43,425), or resolved card (3) was touched,
matching §9's "must never touch" list exactly.

## §9(c) — Bug-A forced-escalation sample

### `buga-sample-20260723T0927Z` — sample extraction

`PilotRunLedger` id 39. `command=run_image_evidence_cohort`,
`dry_run=False`. `started_at` 2026-07-23T09:28:54.658887Z, `finished_at`
2026-07-23T09:30:20.071563Z (DB-verified) — **85.41s**, matching the
relayed 85.4s figure exactly.

**Counters** (DB `counters` JSONField, verified): `completed=300`,
`cohort_size=300`, `lockout_hit=False`, `rss_limit_hit=False`,
`fetch_failures=0`, `short_circuited=0`. `--no-shortcircuit`,
`workers=7` are run-invocation parameters relayed by the owner (not a
`counters` field). 300-card uniform-random sample (seed 20260723) drawn
from the 17,531-card blank-tier-1 signature pool sized in §10, excluding
`ntx-0721`'s already-force-escalated cohort.

### `buga-sample-verdicts-dry-20260723T093321Z` — verdict dry-run over the sample

`PilotRunLedger` id 40. `command=reparse_collector_evidence`,
`dry_run=True`. `started_at` 2026-07-23T09:33:23.576790Z, `finished_at`
2026-07-23T09:33:26.302553Z (DB-verified) — **2.73s**. `votes_written=0`
(dry). `counters=NULL` (this command carries no `counters` JSONField, as
already established) — the funnel breakdown below is relayed from
stdout, not independently DB-re-derivable after the fact.

**Funnel** (relayed, 300-card sample):

| stage                | count | % of 300 |
| -------------------- | ----: | -------: |
| fetched              |   300 |     100% |
| non-blank OCR text   |    78 |    26.0% |
| parsed a number      |    78 |    26.0% |
| resolved a set code  |    65 |    21.7% |
| cast a no-match vote |    76 |    25.3% |
| genuine match        |     1 |     0.3% |
| skipped              |   223 |    74.3% |

Arithmetic check: `76 + 1 + 223 = 300`, matching `completed` exactly.

**The one genuine match**: card 122326 ("Ephemerate", Sketch Yumiko
variant) → Strixhaven Mystical Archive (`STA`) collector number 68 —
spot-checked and confirmed correct by the owner. `ImageEvidence` for
this card (run `buga-sample-20260723T0927Z`, DB-verified) carries raw
OCR text `'{ . .\nNiseenpesinninoensire\n~ YUMIKO-68 a'` — noisy, but the
`~ YUMIKO-68` fragment carried enough signal for the parser to resolve
the correct printing once tier-1 was force-escalated past.

**Wilson 95% CI extrapolation to the full 17,531-card pool**: ~58
genuine matches [CI 10–327]. Qualitatively low-end likely — spot-checks
of the non-blank yield show OCR noise dominating rather than clean,
parseable collector lines. Estimated full re-scan cost at this sample's
observed throughput: ~83–104 minutes.

## Owner ruling (2026-07-23) — Bug-A full re-scan DEFERRED

Full re-scan of the 17,531-card pool is **deferred to post-pilot**. The
gap is tracked, not dropped:

1. **The signature query regenerates on demand** — `fetch_ok=True`,
   empty collector number, blank/whitespace raw text, excluding
   `ntx-0721`. 17,531 cards at query time 2026-07-23T09:19Z (the same
   figure §10 already sized; this ruling re-confirms it's still live and
   re-derivable, not a frozen snapshot).
2. **The 4c pilot's own skip counters surface the blank-evidence
   abstentions** — the pilot dry-run (§9(d)) will itself report how many
   of its no-match/skip verdicts are blank-tier-1 cards, so the Bug-A gap
   stays visible in the pilot's own output rather than needing a
   separate tracking mechanism.
3. **Post-pilot re-scan procedure — documented here so it is not
   re-derived**: any future full re-scan of the 17,531-card (or
   then-current) blank-tier-1 pool MUST include a **state-clear step**
   first. This sample's 223 no-text skips are recorded as
   `CardScanLog` rows with a **non-rescannable** skip reason (no text
   found) — unlike the `no-evidence` skip reason (§12), these do NOT
   self-clear via the pilot's native resume-filter logic. The recipe:
   (a) re-run Stage C extraction (`run_image_evidence_cohort`) with
   `--no-shortcircuit` over the target cohort to force past tier-1 and
   produce fresh `ImageEvidence`; (b) clear the stale skip state for that
   cohort via the reparse path (`reparse_collector_evidence`, same
   mechanism B(i) used); (c) run a follow-up scoped Stage D pass
   (`local_calculate_verdicts`) to actually cast votes from the new
   evidence. Skipping step (b) would leave the cohort's stale
   non-rescannable skip rows in place and silently exclude it from any
   later Stage D run that filters on rescannability.

## Relationship to the pipeline-fidelity gate

This file is the §9 B(i)/B(ii)+B(iii)/(c) data source for
[`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md), which is
the gate's canonical status page and single source of truth for its
verdict and open decisions — this file stays the raw, dated
run-report/resource-metric record; the gate doc owns the status.
