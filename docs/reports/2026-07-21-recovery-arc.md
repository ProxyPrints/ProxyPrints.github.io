# Recovery arc — parser-bug retraction, AI-detector write, no-text re-extraction, Stage D passes 2/3 — verification (2026-07-21)

Read-only verification of five owner-authorized runs executed directly
against prod (`mpcautofill_django`) over the course of 2026-07-21,
chained in dependency order: a parser-bug reparse/retraction, an AI-art
tag-detector write, a no-text-cohort re-extraction, and two further
Stage D join-key passes (one of which surfaced a real sequencing gap).
This session did not run any of the five — it verifies the resulting
row counts, the retraction accounting, and the machine-only-resolution
gate against what already landed, following
`docs/reports/2026-07-21-staged-write.md`'s structure and (for the
gate) `#258`'s pure-function re-derivation methodology. No writes were
made to any live database or index from this session; every figure
below comes from a `SELECT`/`count()`/pure-function re-derivation run
against the live DB, or from the five runs' own logs.

**Headline: all five runs reconcile exactly against the live DB — no
mismatch found.** Every count below either matches its own run's log
line, or explains a delta (e.g. a retraction) with the arithmetic that
produces it. Stated prominently since the task instruction asked for
this either way.

## Run parameters

| #   | run                        | `run_id` / selector                                                                           | command                      | `dry_run` | log                                                         |
| --- | -------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------- | --------- | ----------------------------------------------------------- |
| 1a  | parser-bug reparse (dry)   | `20260721T113310-3a9a95d3`, `--selector parser-bug`                                           | `reparse_collector_evidence` | True      | `~/dryruns-20260721-recovery.log`                           |
| 1b  | parser-bug reparse (write) | `20260721T115030-c75258a3`, `--selector parser-bug`                                           | `reparse_collector_evidence` | False     | (not separately captured; `PilotRunLedger` row 17 confirms) |
| 2a  | AI detector (dry)          | `20260721T113314-9d0ea678`                                                                    | `local_detect_ai_art`        | True      | `~/dryruns-20260721-recovery.log`                           |
| 2b  | AI detector (write)        | `20260721T114816-0fa65084`                                                                    | `local_detect_ai_art`        | False     | `~/writes-20260721-recovery.log`                            |
| 3   | no-text re-extraction      | `ntx-0721`                                                                                    | `run_image_evidence_cohort`  | False     | `~/writes-20260721-recovery.log`                            |
| 4   | Stage D pass 2             | `staged2-0721`                                                                                | `local_calculate_verdicts`   | False     | `~/staged2-0721.log`                                        |
| 5a  | state-clear                | `20260721T130411-c5096c6f`, `--selector no-text --stage-d-run-id staged-write-20260721T0434Z` | `reparse_collector_evidence` | False     | `~/staged3-chain.log`                                       |
| 5b  | Stage D pass 3             | `staged3-0721`                                                                                | `local_calculate_verdicts`   | False     | `~/staged3-chain.log`                                       |

All eight ledger rows are present and `status=COMPLETED`, confirmed
directly from `PilotRunLedger` (ids 12–20 span this arc, alongside the
original `staged-write-20260721T0434Z` run rows 12/13 that
`docs/reports/2026-07-21-staged-write.md` already verified):

```
14  20260721T113310-3a9a95d3  reparse_collector_evidence  completed  dry_run=True   votes_written=0
15  20260721T113314-9d0ea678  local_detect_ai_art         completed  dry_run=True   votes_written=0
16  20260721T114816-0fa65084  local_detect_ai_art         completed  dry_run=False  votes_written=1183
17  20260721T115030-c75258a3  reparse_collector_evidence  completed  dry_run=False  votes_written=100
18  staged2-0721              local_calculate_verdicts    completed  dry_run=False  votes_written=70
19  20260721T130411-c5096c6f  reparse_collector_evidence  completed  dry_run=False  votes_written=3032
20  staged3-0721              local_calculate_verdicts    completed  dry_run=False  votes_written=3010
```

One process observation, not a mismatch: no dry-run row precedes row
19 (the no-text-selector state-clear). Rows 14/17 (parser-bug selector)
and 15/16 (AI detector) both have a matching dry-run/write pair; the
no-text-selector retraction went straight to `--write`. This isn't
flagged as wrong — `--selector parser-bug`'s dry-run/write pair already
established the retraction logic's correctness on this same command,
and the state-clear step's own effect (3,032 rows retracted, all
`recorded=('skip','no-text')` → `fresh=('vote', None, True)`, i.e. "had
no prior evidence, now has some") is a narrower, more mechanical
re-check than the parser-bug selector's conclusion-comparison logic —
but it is the one place in this arc where a dry-run/write pair doesn't
exist to point at, worth naming rather than silently passing over.

## 1. Parser-bug reparse — dry-run vs. write reconciliation

| metric              | dry-run | write (ledger)                                                 |
| ------------------- | ------- | -------------------------------------------------------------- |
| candidates          | 117     | — (ledger doesn't store candidate count, only `votes_written`) |
| considered          | 117     | —                                                              |
| unchanged           | 17      | —                                                              |
| changed / retracted | 100     | **100**                                                        |

`PilotRunLedger` row 17 (`votes_written=100`) matches the dry-run's
`would_retract=100` exactly — the field is literally reused for this
command's "rows this run's own write actually touched (retracted)"
count, per the command's own comment. `reparse_and_retract` deletes
`CardPrintingTag`+`CardScanLog` rows for the JOIN_KEY anonymous_id per
retracted card and re-resolves, gated by a live
`resolve_printing(card) is not None` safety check per card (never
force-retracts an already-resolved card) — confirmed by reading the
function directly, not inferred.

**Downstream vote-count effect, confirmed against the live DB**: the
original run's own `CardPrintingTag` rows under
`anonymous_id="stage-d-join-key-v1", run_id="staged-write-20260721T0434Z"`
dropped from 8,925 (3,749 match / 5,176 no-match, per `#258`) to
**8,825** (3,749 match / **5,076** no-match) — exactly −100, and the
entire delta lands in the no-match bucket, matching the dry-run's own
sample rows (all ten showed `recorded=('vote', None, True)`, i.e. a
prior no-match vote). Match-vote count (3,749) is untouched, as
expected — the parser-bug shape only ever produced false no-match
verdicts, never false matches.

## 2. AI-art detector — dry-run vs. write reconciliation

| metric                           | dry-run            | write                                                        |
| -------------------------------- | ------------------ | ------------------------------------------------------------ |
| considered (cards with evidence) | 20,800             | 20,800                                                       |
| votes cast                       | 1,183 (would_cast) | **1,183** (written, ledger row 16)                           |
| skip: no-evidence                | 197,428            | (not re-logged in write run's excerpt, same underlying pool) |
| skip: no-marker-hit              | 19,617             | —                                                            |

Arithmetic check: 1,183 + 19,617 = 20,800 (considered), and 20,800 +
197,428 = 218,228 — the full Stage C-eligible pool at this point in the
arc, consistent with `#258`'s own "20,800 distinct cards with an
`ImageEvidence` row today" figure.

**Live DB**: `CardTagVote.objects.filter(anonymous_id="ai-art-detector-v1")`
→ **1,183** rows, all under tag `AI-Generated`, all under a single
`run_id` (`20260721T114816-0fa65084`, matching the write log), 1,183
distinct `card_id`s (no duplicate voting). Matches the write log's
`total_votes=written=1183` exactly.

## 3. No-text re-extraction (`run_id=ntx-0721`)

`ImageEvidence.objects.filter(run_id="ntx-0721")`:

```
total:             9,675   (matches log's completed=9675/9675)
fetch_ok=True:     9,665
fetch_ok=False:       10   (matches log's fetch_failures=10)
```

Recovery, re-derived directly from the persisted fields rather than
trusted from a summary line:

```
parsed collector number (non-null/non-empty): 3,032   →  31.3% of 9,675
non-empty collector_line_raw_text:            7,897   →  81.6% of 9,675
```

Both match the task brief's stated figures exactly (3,032/9,675 =
31.35%, rounds to 31.3%; 7,897 gained raw text).

**Classification, not identification — tying this to the earlier
diagnostic's own framing.** `docs/features/catalog-completion-plan.md`'s
no-text-bucket diagnostic (issue #259, run
`staged-write-20260721T0434Z`'s original 9,675 `no-text` skips) already
characterized this population as skewing **garbled, not blank** (76.8%
non-empty-but-unparseable collector text) and **bottom-quartile
`blur_variance`** (blurry uploads) — i.e. a population where OCR
recovering _some_ text was always plausible, but recovering a text that
_matches a real printing_ was not implied by that diagnostic at all.
Today's actual outcome (pass 3, below: 20 printing matches vs. 2,990
no-match votes out of exactly this 3,032-card recovered cohort) is
consistent with that framing, not in tension with it: a blurry/garbled
crop recovering readable text most often means the reader is now
correctly seeing a **proxy/custom-card marker or an unofficial credit
line** (the same "NOT FOR SALE"/"PROXY"/community-credit-watermark
shapes `#151`'s and `#259`'s own motivating cases already document
elsewhere in this file) rather than a genuine, previously-illegible
Wizards collector line. The 31.3% figure is a real OCR-preprocessing
win — it recovered _readable text_ from cards that previously
contributed nothing — but it overwhelmingly resolves those cards to
"confirmed not an official printing" rather than "identified as a
specific one." That distinction is exactly what pass 3's 20-vs-2,990
split measures.

## 4. Stage D pass 2 (`run_id=staged2-0721`) — the parser-bug re-vote

Log: `considered=100 votes=written=70 no_match_votes=written=0 skip_counts={'no-evidence': 179707, 'border-mismatch': 14, 'proxy-marker-veto': 16}`. `Gate check passed: 0/70`.

**Reconciling the 100 retracted cards against pass 2's own outcome
(id-level, not just count-level)**: `local_calculate_verdicts` has no
`--card-ids` restriction — every invocation iterates the full eligible-
cards queryset (excludes cards with an existing vote or a non-
rescannable skip). The parser-bug retraction (item 1) is what made
exactly 100 cards newly eligible for this run; live DB confirms pass 2
wrote:

```
CardPrintingTag(run_id="staged2-0721"): 70 rows, all is_no_match=False, 70 distinct card_ids
CardScanLog(run_id="staged2-0721", skip_reason="border-mismatch"):     14 rows
CardScanLog(run_id="staged2-0721", skip_reason="proxy-marker-veto"):   16 rows
CardScanLog(run_id="staged2-0721", skip_reason="no-evidence"):    179,707 rows (the persistent, unrelated global no-evidence pool, re-scanned every run — not part of the 100)
```

70 votes + 14 + 16 = **100**, zero overlap between the vote set and the
two skip sets — the full retracted cohort is accounted for with no
remainder. This also confirms the recovery arc's own claim ("100
changed... 65+ printing matches vs their old false no-matches") is
actually 70, slightly above the "65+" floor stated in the brief — not a
mismatch, the brief's own number was already phrased as a lower bound.

**Gate, independently re-derived** (via
`purge_machine_votes.verify_no_machine_only_resolutions`, the same
pure, read-only check `#258` used for the printing-only case, which
also covers artist/tag resolution — see §"Gate check" below for why
that matters this time): **0/70** — matches the log exactly.

## 5. State-clear + Stage D pass 3 (`run_id=staged3-0721`)

**The sequencing lesson, stated plainly, not softened**: pass 2 (item 4) was expected to also cover the 3,032 cards the no-text re-extraction
(item 3) had just given a fresh parse to. It did not, because
`local_calculate_verdicts`'s eligibility query only rescans a card if
its _recorded_ `CardScanLog` skip reason is in
`JOIN_KEY_RESCANNABLE_SKIP_REASONS` (`{"no-evidence"}` only) — a card
still carrying a **stale `no-text` skip row** from the original
`staged-write-20260721T0434Z` run reads as already-scanned and
non-rescannable, even though its underlying `ImageEvidence` now has
real text. The runbook's state-clear step exists specifically to
retract that stale `no-text` scan-log state before a re-scan can see
the new evidence — and it was skipped ahead of pass 2 as "redundant."
It was not redundant; it was load-bearing, and pass 2's 100-card scope
(the parser-bug cohort only) is real evidence of the gap, not proof the
skip was harmless — pass 2 simply never touched the 3,032-card
recovered cohort at all, silently, until this was caught and the state-
clear step run before pass 3.

**State-clear** (`run_id=20260721T130411-c5096c6f`, `reparse_ collector_evidence --selector no-text --stage-d-run-id staged-write- 20260721T0434Z`, `votes_written=3032` per `PilotRunLedger`): retracts
the stale `no-text` `CardScanLog` row per card whose fresh state is no
longer `("skip", "no-text")`. Confirmed live: the _original_ run's own
scan-log (`anonymous_id="stage-d-join-key-v1", run_id="staged-write- 20260721T0434Z"`) now shows `no-text: 6,643` (was 9,675 per `#258`) — a
drop of exactly **3,032**, landing precisely on the recovered-cohort
size. No `CardPrintingTag` rows were touched by this step (unlike item
1's retraction) — these cards had a skip, not a vote, recorded
originally.

**Pass 3** (log: `considered=3032 votes=written=20 no_match_votes= written=2990 skip_counts={'no-evidence': 179707, 'border-mismatch': 15, 'ambiguous': 4, 'proxy-marker-veto': 3}`, `total_votes=written=3010`,
`Gate check passed: 0/3010`):

```
CardPrintingTag(anonymous_id="stage-d-join-key-v1", run_id="staged3-0721"):
  total: 3,010   is_no_match=False (printing match): 20   is_no_match=True (no-match): 2,990
```

`considered=3,032` matches the state-clear step's own `votes_written= 3032` exactly (every state-cleared card became eligible, and every
eligible card with evidence got a fresh join-key verdict this pass —
`3,010` voted + `15+4+3=22` newly skipped = `3,032`). **Gate,
independently re-derived**: **0/3,010** — matches.

## Aggregate `stage-d-join-key-v1` totals — the headline check

```
CardPrintingTag.objects.filter(anonymous_id="stage-d-join-key-v1")
  total:              11,905   ✅ matches 8,825 + 70 + 3,010 exactly
  is_no_match=True:     8,066   (5,076 + 0 + 2,990)
  is_no_match=False:    3,839   (3,749 + 70 + 20)
  distinct run_id:     ['staged-write-20260721T0434Z', 'staged2-0721', 'staged3-0721']  — no fourth/unexpected run_id present
```

Per-`run_id` breakdown, queried directly (not summed from logs):

| `run_id`                                        | total      | match     | no-match  |
| ----------------------------------------------- | ---------- | --------- | --------- |
| `staged-write-20260721T0434Z` (post-retraction) | 8,825      | 3,749     | 5,076     |
| `staged2-0721`                                  | 70         | 70        | 0         |
| `staged3-0721`                                  | 3,010      | 20        | 2,990     |
| **sum**                                         | **11,905** | **3,839** | **8,066** |

`CardScanLog` under the same `anonymous_id`, checked for completeness
(not asked for directly, but confirms no hidden vote/scan-log
mismatch): total 547,893 rows across the same three `run_id`s, with the
per-run skip-reason breakdowns summing consistently against the
original run's own numbers minus the two retractions (`no-text`
9,675 − 3,032 = 6,643; `border-mismatch` 507 + 14 + 15 = 536;
`proxy-marker-veto` 1,533 + 16 + 3 = 1,552; `ambiguous` 2 + 4 = 6;
`frame-mismatch` unchanged at 35) — every number reconciles against
`#258`'s original figures plus this arc's own deltas, with no
unexplained row anywhere.

## Gate check — re-derived across all touched cards, all engines

The task asked for the machine-only-resolution gate re-derived "over
all touched cards," which this arc actually spans two different
consensus mechanisms, not one: printing votes (`printing_consensus.py`,
via `CardPrintingTag`) from the four `local_calculate_verdicts` runs,
and tag votes (`tag_consensus.py`, via `CardTagVote`) from the AI-art
detector. `purge_machine_votes.verify_no_machine_only_resolutions` (the
same function `local_detect_ai_art`'s own docstring says it reuses
rather than re-deriving an equivalent check) checks **all three**
resolution types per card — printing, artist, and tag — in one pass,
so it's the correct single pure function for this, not
`resolve_printing` alone (which only covers the join-key runs and would
silently miss a tag-consensus violation).

```
touched by stage-d-join-key-v1 (3 run_ids, union):  11,905 cards
touched by ai-art-detector-v1:                       1,183 cards
overlap (touched by both engines):                     404 cards
union — all cards touched by this arc:              12,684 cards

verify_no_machine_only_resolutions(union) → 0 violations   ✅ 0/12,684
```

Also re-derived per individual run, matching each run's own logged
claim exactly:

| run                                                          | gate (re-derived) | gate (log)                                                                               |
| ------------------------------------------------------------ | ----------------- | ---------------------------------------------------------------------------------------- |
| `staged-write-20260721T0434Z` (post-retraction, 8,825 cards) | 0/8,825           | 0/8,925 pre-retraction (`#258`) — expected to differ only in denominator, not in outcome |
| `staged2-0721`                                               | 0/70              | 0/70                                                                                     |
| `staged3-0721`                                               | 0/3,010           | 0/3,010                                                                                  |
| `ai-art-detector-v1`                                         | 0/1,183           | 0/1,183                                                                                  |

The human-backed consensus gate held throughout every run in this arc,
individually and in aggregate — no card anywhere in the 12,684-card
touched set resolved (printing, artist, or tag) from machine-sourced
votes alone.

## Reversibility

Every run in this arc is independently purgeable via
`purge_machine_votes --run-id <id>`, scoped by the exact `run_id`s
above:

- `staged-write-20260721T0434Z` (join-key votes, now 8,825 rows post-retraction) + its own scan-log.
- `20260721T115030-c75258a3` (the parser-bug retraction itself — reversing this purge does not restore the retracted votes; it only removes this run's own ledger row. Restoring the pre-retraction state would mean re-running the original join-key calculator's stale logic, which no longer exists in code — the retraction is a one-way correction, not a reversible vote-cast, and should be read that way).
- `20260721T114816-0fa65084` (1,183 `CardTagVote` rows, `AI-Generated` tag).
- `20260721T130411-c5096c6f` (the state-clear retraction — same one-way caveat as above).
- `staged2-0721` (70 join-key votes).
- `staged3-0721` (3,010 join-key votes).

Purging any of the three vote-casting runs (`staged-write-...`,
`staged2-0721`, `staged3-0721`, `20260721T114816-0fa65084`) reverts its
votes and re-resolves affected cards' cached status via
`resolve_and_persist_printing`/`resolve_and_persist_tag_votes`. Purging
either retraction run is not meaningful in the same sense — those runs
deleted rows rather than casting new ones, so there is nothing for
`purge_machine_votes` to remove from them beyond the ledger row itself.

## Next-step options

1. **The 197,428-card Stage C remainder is still open** — unchanged by
   this arc (this arc operated entirely on cards Stage C had already
   extracted evidence for, plus the no-text cohort's targeted
   re-extraction). A full-catalog Stage C harvest of the remainder
   still needs its own separate owner GO per Stage E's resume-contract
   gate, same as `docs/reports/2026-07-21-stagec-20k-extraction.md`
   and `docs/reports/2026-07-21-staged-write.md` both already noted.
2. **The 2,990 no-match votes from pass 3 feed the review-cluster
   work — correcting the task brief's own framing here.** The brief
   that opened this verification cited "clustering #262/#265"; checked
   directly (`docs/features/moderation.md`'s "Known gaps / follow-ups"
   section, current on this branch): **#265 is not a separate frontend
   follow-up issue** — it's the PR number of the review-cluster
   _backend_ itself (`b6c95a70`, "Add review-queue clustering + batch
   no-match confirmation API (#262) (#265)", merged 2026-07-21 07:30:31
   ET, hours before this arc's first run at 11:33), which implements
   issue #262. The one remaining tracked follow-up is "Review-cluster
   frontend UI (issue #262)" itself — same issue number, no distinct
   successor issue exists in the docs today. Substantively: these 2,990
   cards are now `is_no_match=True` under `stage-d-join-key-v1` — per
   the review-clusters section, a card only enters that clustering
   population once it carries the slow-path `to-review` routing marker
   AND is still `UNRESOLVED`; a single machine no-match vote does not
   resolve a card on its own (confirmed above: 0/12,684 gate
   violations), so these 2,990 cards remain eligible for slow-path
   routing and, from there, the _already-shipped_ exact-signal
   clustering/batch-confirm backend (#265) — not resolved by this
   verification, a real next step for whichever pass runs the slow-path
   calculator over them, feeding a backend that's ready today.
3. Not part of this task, but worth surfacing given the process-gap
   findings above: the _only_ place in the arc's runbook where a
   dry-run/write pair doesn't exist (the no-text-selector state-clear,
   item 5a) is also the one step whose omission-before-pass-2 already
   caused a real, silent scope gap. Adding a mandatory dry-run to that
   specific selector's runbook step (mirroring what `--selector parser-bug` already does) would have caught the skipped-step problem
   before pass 2, not after — a candidate process fix, not something
   this read-only verification session should decide unilaterally.

## Live API

Not independently re-checked in this verification session (read-only,
DB/log queries only) — the owner's authorized run channel already
covered live-API health as part of executing all five runs; this
session did not restart or touch any container beyond issuing
read-only Django-shell queries against the already-running
`mpcautofill_django` container.
