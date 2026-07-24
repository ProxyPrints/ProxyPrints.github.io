# Pipeline-fidelity gate — canonical status page

**GitHub issue #154** (internally referenced elsewhere as "task #151" —
a pre-board internal task-ledger number, not a second GitHub issue; issue
#154's own title cross-references both). This is the **single page**
for this gate's status, its (now-decided) owner decisions, and any
in-flight implementation gating the fire. Every
underlying fact below is linked to its source, not copied — if a number
here disagrees with its linked source, this page is wrong and should be
fixed, not the source.

**Data as of 2026-07-22T18:01Z**, re-verified live against production
Postgres for this page (`sudo docker exec mpcautofill_django python manage.py shell`, read-only queries only). §10/§11 carry a later, narrower
live re-verification (2026-07-23T00:16–00:24Z) for the #340 footprint
sizing and the Stage C run-identity note specifically — dated inline in
those sections rather than bumping this whole-page timestamp. §12
carries a further dated update (2026-07-23T01:33Z onward) for the
deploy step and the Bug-B whole-DB reparse dry-run outcome, and §9 was
amended the same day per [issue #347](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/347)'s
Tron-reviewed zeroing plan. §13 carries a further dated update
(2026-07-23T09:0x–09:3xZ) for the zeroing steps' actual execution
(B(i) write, B(ii)+B(iii) retraction) and the §9(c) Bug-A
forced-escalation sample, re-verified live at that time. §9(d) carries
a further update (2026-07-23T09:14–11:12Z) recording the 4c pilot
dry-run's own outcome, which was still in progress as of §13's own
check. §14 records the pilot `--write` and the first
`consensus_recompute --apply` (2026-07-23), after which the gate was
**fired end to end**. **§14 was extended 2026-07-24 (DB-verified live
against production Postgres)** with five further passes that ran the
same night into the next day — a lexicon-gate retraction, a marker
reparse, an artist-credit fill, a calculator re-pass, and a second
`consensus_recompute` closer — which is the sequence's actual true end
state; that update also **corrects the live resolved-printing count
from 4 to 3** (the closer flipped one card `resolved→unresolved` after
§14's original snapshot was taken) and folds in a real, verified
finding that all 218,345 cards remain `artist_vote_status=unresolved`
despite the artist-fill pass (see §14's "Artist-consensus finding").
See "Chain" below for where each number's provenance sits.

## 1. Gate definition

Stage D (`local_calculate_verdicts.py`) carries a hard precondition
before any full-catalog fire: calculators must call the existing shipped
identification code paths with `ImageEvidence`-supplied inputs, not
re-derive their logic; a stratified-sample parity replay against pilot
run `20260716T193408-6613a1a6`'s recorded outputs must show **zero
unexplained divergence**; a full knowledge-inventory sweep (every
empirically-derived constant/threshold/override/skip-reason mapped to
its home in the new pipeline, or flagged missing) must be clean. Full
precondition wording and the Stage D build it gates:
[`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)'s
"Harvest-calculate pipeline" section.

## 2. Current status

| artifact                                         | status                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Artifact 2 — knowledge-inventory sweep**       | **DONE** (2026-07-22); all 3 MISSING-constant decisions now made — see §3 below. Full constant-by-constant table: [`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md).                                                                                                                                                                                               |
| **Artifact 1 — stratified-sample parity replay** | **DONE** (2026-07-22), outcome **owner-accepted**. 83.2% OCR-channel agreement (28,456-card reproducible-channel subset); 373/41,586 (0.9%) unexplained divergences, 0/373 a wrong-printing vote — all conservative abstentions. Not literally "zero unexplained divergence," but ruled to satisfy the gate's soundness intent. Full outcome, methodology, and the owner-acceptance ruling: see §4 below. |

**Gate verdict: FIRED — §9 sequence complete end to end, true completion
2026-07-24** (the pilot `--write` + first `consensus_recompute --apply`
landed 2026-07-23; five further corrective/completion passes — lexicon-
gate retraction, marker reparse, artist-credit fill, calculator
re-pass, and a second `consensus_recompute` closer, §14 — ran the same
night into 2026-07-24 and are part of the same fire, not a new gate
question).
Every owner decision this gate needed is made (§3, §4); the deploy step
is done: master `a587000` (PR #345) went live in prod 2026-07-23T01:33Z
— migration `0078` auto-applied, and §3 items 1–2's `RESOLUTION_FLOOR_DPI`/
`EXCLUDED_RESOLVED_TAGS` constants (PR #343) verified live in the
running container (see §3, §12). Item 3 (deductive-backfill exclusion)
was separately ruled NOT restored, already merged (§3). Artifact 1 (§4)
is DONE and owner-accepted 2026-07-22 as satisfying the gate's soundness
intent, even though the literal "zero unexplained divergence" bar
wasn't hit (373 remained, all conservative abstentions; both root
causes since fixed in code by merged PR #340). Artifact 1 itself is
**closed history**, not a baseline to keep re-measuring against — see
§8 for the new-data basis ratified 2026-07-23. **The full §9 fire
sequence** (Bug-B write pass → retraction → Bug-A sample → the 4c pilot
dry-run → owner sample audit → write → `consensus_recompute --apply`),
amended 2026-07-23 per
[issue #347](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/347),
**is now COMPLETE**: the Bug-B whole-DB reparse dry-run (§12), the
zeroing steps (B(i) write, B(ii)+B(iii) retraction), the §9(c) Bug-A
forced-escalation sample, the 4c pilot dry-run (§9(d)), the owner sample
audit, the pilot `--write` (COMPLETE-BY-VERIFICATION, a documented
execution-harness artifact — see §14), and `consensus_recompute --apply` (§9(e), §14) are all **DONE**, executed and DB-verified. The
measurement of record for this fire is
[`reports/2026-07-23-4c-pilot-dry-run.md`](reports/2026-07-23-4c-pilot-dry-run.md)'s
dry-run (`pilot-dry-20260723T094518Z`) plus the write's DB-verified
counts (§14) — the write reproduced the dry-run's predicted counts
exactly on both channels. **§14 was then extended by five further
passes (2026-07-23 evening into 2026-07-24)** that are part of the same
fire, not a new gate question: a lexicon-gate retraction, a marker
reparse, an artist-credit fill, a calculator re-pass, and a second
`consensus_recompute` closer — full per-pass table and topline end-state
in §14. Two open items are carried forward past the fire: (1) the Bug-A
full re-scan, deferred to post-pilot per the owner ruling in §9(c)/§13;
(2) the pilot-era `consensus_recompute` (49,206 tag transitions,
2026-07-23T13:25:37Z) has no `PilotRunLedger` row — a structural,
pre-ledger-convention gap, not a data-quality concern — see §14's
"Pass-9 ledger gap" note.

## 3. Decision (a), resolved — the three MISSING constants

The knowledge-inventory sweep confirmed three pilot-era constants have
**no current home** in Stage C/D, by direct `grep`/read, not inference:

1. **`RESOLUTION_FLOOR_DPI = 200`** — the pilot never fetched a card
   below this empirically-validated floor (dpi≤150 measurably degrades
   OCR yield). Stage C's cohort selection has no `dpi` condition at all.
   Highest-severity of the three: no downstream signal (`ImageEvidence`
   carries no dpi field) distinguishes a low-resolution extraction later.
2. **`EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]`** — the
   pilot excluded cards already tagged custom-art/non-english (their
   printing-identification precondition is already falsified) from
   selection entirely. Stage D's `_eligible_cards_queryset` has no
   equivalent exclusion, and no other code path produces the same
   effect (checked directly against `tag_consensus.py`). Not previously
   tracked anywhere prior to this sweep — a genuinely new finding, not a
   known accepted gap.
3. **Deductive-backfill exclusion** (`.exclude(printing_tags__anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)`)
   — the pilot never re-voted a card the deductive backfill had already
   cast a vote for. Lower severity: only bites the narrow subset where
   backfill voted but the card is still UNRESOLVED (a card it fully
   _resolved_ is already excluded by Stage D's own
   `printing_tag_status=UNRESOLVED` filter). **Origin of this
   constant**: `DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"`
   in [`../MPCAutofill/cardpicker/deductive_backfill.py`](../MPCAutofill/cardpicker/deductive_backfill.py),
   run via the `deductive_backfill_printing_tags` management command.
   This is the same run that produced the 28,112 `deduction`-source
   `CardPrintingTag` votes in today's live pool (§6 below) — verified
   live: all 28,112 carry `run_id=None`, `anonymous_id="deductive-backfill-v1"`,
   `created_at` between 2026-07-14T18:21:49Z and 2026-07-14T18:22:05Z.
   See `journal/2026-07-14-deductive-printing-tag-backfill.md` (gitignored,
   machine-local) for that run's own narrative. **INTENTIONALLY NOT
   RESTORED (owner ruling, 2026-07-22)**, superseding an earlier same-day
   revision of this page that marked it "addressed in code": a read-only
   investigation of the 2026-07-14 backfill found it is pure name/metadata
   deduction (never phash/OCR — zero image inspection) whose votes check
   out sound (a 15-card sample all correct), and that excluding those
   cards would strand ~27,819 sound-but-UNRESOLVED cards outside Stage D
   for no protective benefit — re-evaluating them is safe under the
   human-backed consensus gate (agreement dedups, disagreement surfaces to
   human review). The pilot's own exclusion was a performance
   optimization (skip a card its weaker engines couldn't add to), not a
   soundness mechanism, so restoring it here would trade real coverage for
   a protection the vote-consensus layer already provides independently.
   See `local_calculate_verdicts._eligible_cards_queryset`'s own docstring
   for the in-code record of this decision. **These 28,112 `deduction`-
   source votes are NAME-based (the 2026-07-14 backfill, not phash/OCR-
   based), stay on the record as votes, and are invisible to Stage D's
   own calculation post-#341** — Stage D neither reads nor is blocked by
   them. Their consensus-layer weighting was a separate question,
   parked here as still-OPEN as of this section's earlier revisions —
   **now RESOLVED (owner ruling, 2026-07-23)**: these votes carry ZERO
   consensus weight in every resolution computation, permanently, while
   the rows themselves stay on the record forever (raw tallies/display
   paths unaffected — see `vote_consensus.DEDUCTIVE_BACKFILL_ANONYMOUS_ID`'s
   own docstring for the exact mechanism and the live-audit numbers
   behind the ruling, and [`theory.md`](theory.md)'s soundness section,
   §4, for the write-up). This is a distinct decision from the
   Stage-D-exclusion question this whole numbered item is about (whether
   Stage D re-votes a card the backfill already touched, resolved NOT-
   RESTORED above) — that ruling is unchanged by this one.

None of these three are soundness violations — the human-backed
consensus gate still applies to every vote Stage D casts regardless.

**Owner ruling (2026-07-22T23:47Z): #1 and #2 are MUST-FIX.** Sized
against live data: 28 eligible cards fall below the dpi floor (0.016%
of the 179,766-card eligible pool), 47 carry `custom-art` / 0
`non-english` (0.026%), zero overlap between the two, union 75
(0.042%) — zero live OCR votes rest on a sub-floor image. Fix: two
one-line queryset excludes in `_eligible_cards_queryset`
(`dpi__lt=200`, the custom-art/non-english tag exclusions) — **merged**
to master in [PR #343](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/343)
and **deployed** 2026-07-23T01:33Z (§9(a) done — see §12): both
constants verified live in the running container (`RESOLUTION_FLOOR_DPI = 200`, `EXCLUDED_RESOLVED_TAGS = ['custom-art', 'non-english']`). All
three items above are now decided — none remain open.

Full detail, plus 3 lower grade "open items" that are separate from
these 3 MISSING findings:
[`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md).

## 4. Artifact 1 — parity-replay methodology and outcome (resolved 2026-07-22)

**Artifact 1 was originally scoped as a live stratified-sample re-run
against dpi=250, re-extracting evidence and comparing it to the pilot's
outputs.** That scoping was wrong and was replaced by this corrected
methodology:

> Dry-run diff of new `local_calculate_verdicts` verdicts vs. the
> pilot's recorded votes; **NO Stage C re-extraction**; pass bar = the
> DOCUMENTED "zero unexplained divergence", **NOT a percentage
> threshold**.

Concretely: run Stage D's calculator in dry-run mode against the
`ImageEvidence` rows that already exist, diff its verdicts against the
`CardPrintingTag` rows the pilot run (`20260716T193408-6613a1a6`)
already cast, and account for every divergence — a match is not enough
on its own; every disagreement must be explained (a known, reasoned
architectural difference per the knowledge-inventory sweep) or the gate
fails. **No numeric pass threshold was invented or accepted anywhere in
this process** — "zero unexplained divergence" was the only documented
bar; the outcome below did not literally hit it, which is why the
owner ruling in this section exists.

### Result

**Baseline vs. method, stated explicitly.** Pilot run
`20260716T193408-6613a1a6` is the **legacy multi-channel engine** — OCR
plus the `local-phash-v1`/`local-fallback-v1` phash channels voting
concurrently (why its 43,425 votes span only 41,586 distinct cards:
some cards received votes from more than one channel). Stage D is
**OCR-only by design**. This replay is therefore a **cross-method**
verdict diff — the new OCR-only Stage D, computed against current
`ImageEvidence` from the new Stage C extractions, diffed against the
legacy multi-channel engine's recorded votes — not the new method
validated against itself. The 83.2% figure below is OCR-channel
agreement specifically; bucket d below (13,026) is exactly the
phash/fallback channels Stage D doesn't run — an explained
architectural difference, not a gap.

The replay ran 2026-07-22 as a read-only, **full-cohort** (not sampled)
comparison against that pilot run's 43,425 votes / 41,586 distinct
cards (source=ocr): each card's pilot vote was compared against what
the current Stage D join-key calculator
(`calculate_join_key_verdict`/`_resolve_candidates_for_card`, called
directly) computes from its now-persisted `ImageEvidence`, bypassing
`_eligible_cards_queryset` entirely. No writes.

**Headline**: 23,789/41,586 (57.2%) agree outright. Restricted to the
28,456 cards whose pilot vote actually used the OCR channel Stage D can
reproduce (`local-ocr-v1`), agreement is 23,689/28,456 = **83.2%**.

**Divergence buckets** (17,793 disagreements):

| bucket                                                       |  count | note                                                                                                                                      |
| ------------------------------------------------------------ | -----: | ----------------------------------------------------------------------------------------------------------------------------------------- |
| a. `RESOLUTION_FLOOR_DPI`                                    |      0 | structurally 0 in this cohort — pilot's own filter already excluded these before ever voting                                              |
| b. `EXCLUDED_RESOLVED_TAGS`                                  |      0 | same — structurally pre-filtered                                                                                                          |
| c. `DEDUCTIVE_BACKFILL` (§3 item 3)                          |      0 | same, doubly structural (deductive_backfill's own eligibility requires zero pre-existing votes)                                           |
| d. pilot engine has no Stage D analogue                      | 13,026 | pilot matched via `local-fallback-v1`/`local-phash-v1` only — both explicitly out of Stage D's scope per its own docstring/`theory.md` §7 |
| e. Stage D's new veto layer (border/copyright-year mismatch) |  4,394 | correctly withholds matches on cards whose evidence genuinely disagrees with the real printing (spot-checked, not a classifier bug)       |
| f. **UNEXPLAINED** (the gate criterion)                      |    373 | (0.9% of cohort) 2 identified root causes, **0/373 a wrong-printing vote** — every one a conservative abstention. See `theory.md` §7c.    |

Buckets a/b/c reading exactly 0 is a property of this
backward-looking cohort (the pilot's own eligibility filter already
excluded any card that would trip them), not evidence the §3 constants
don't matter going forward — that is the separate, forward-looking
question §3 answers (all three items resolved 2026-07-22, per that
section — items 1–2 MUST-FIX with a fix in flight, item 3 not
restored).

### Owner gate ruling (2026-07-22): soundness bar ACCEPTED

Not literally zero — 373 unexplained (0.9% of the 41,586-card cohort)
— but every one is a conservative abstention (0/373 voted for a wrong
printing). Ruling: the gate's **intent** (no confidently-wrong verdicts
at scale) is satisfied — zero false-accept risk. The 373 were not
treated as a fire blocker; both root causes were identified and fixed
in the same session, code-only, in merged
[PR #340](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/340):

- **155 "no-text" divergences** — the 2026-07-21 OCR short-circuit
  skipped deeper tiers whenever both tier-1 OCR attempts were
  digit-free, conflating a blank/failed tier-1 read (a read _failure_)
  with a confident "no collector number here" finding. Narrowed to
  escalate whenever tier-1 comes back blank, exactly like a
  digit-bearing-but-unparseable read already did.
- **218 `is_no_match` divergences (subset fixed)** — a glued-token OCR
  parse failure: a single language-marker character glued onto the
  tail of a set-code token, e.g. card 41559 ("Verazol, the Split
  Current") parsing `set_code="znre"` from `"znr"` + an adjacent
  language-marker token's leading `"e"`; the real set is `znr`. Same
  family as PR #260's denominator/rarity-token glued-token guard.

Separately: the three §3 constants reading 0 divergence in this
backward-looking replay is a structural artifact of the pilot's own
pre-filtering (see "Result" above), not evidence of their forward
impact — that sizing is tracked in §3, independent of this ruling.

### Scope boundary — code fix vs. live cohort

PR #340's fixes are **code-only**. Realizing the benefit on the live
373-card cohort (or any other newly-affected cards) requires a
**targeted Stage C re-extraction** of the affected `card_id`s — a
gated prod write, queued behind the post-freeze deploy, and explicitly
out of scope for / not run by PR #340. The 373-card cohort is bounded
to the pilot-vote replay's own 41,586-card comparison set, not the
full catalog — §10 sizes both root causes' actual catalog-wide
footprint (17,531 cards / 284 rows respectively), which is the scope
the re-extraction in §9(b) actually runs against.

Full source: [issue #154](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/154)'s
2026-07-22 comments (the replay result and the owner-acceptance
ruling) and [PR #340](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/340)
(the fix detail, verification, and scope-boundary note). Durable
technical distillation of what the replay showed about the OCR channel
and the conservative-abstention property: [`theory.md`](theory.md) §7c.

## 5. Why Artifact 1 is a verdict-diff, not an evidence-diff

Pilot run `20260716T193408-6613a1a6` completed 2026-07-16/17 — this
**predates** the `ImageEvidence` model entirely. Migration `0068` (the
`ImageEvidence` substrate) wasn't applied to production until
2026-07-20 (see
[`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)'s
"Migration 0068 (only) live on production" entry). There is therefore
**no `ImageEvidence` row that existed at pilot time to diff against** —
Artifact 1 can only ever compare Stage D's verdicts (computed today,
against today's `ImageEvidence`) to the pilot's recorded **votes**
(`CardPrintingTag` rows, which do predate and survive the migration).
This is the reason §4's methodology is a verdict-diff, not an
evidence-diff, and why re-extracting Stage C evidence to match the
pilot's original images would not close this gap even if it were done
(the pilot's own transient-fetch images were never persisted — see
CLAUDE.md's "Governing premise: we index, we do not store images").

## 6. Verified data snapshot (2026-07-22, live)

**Catalog**: 218,285 cards; 218,270 with a current `ImageEvidence` row.

**Vote pool** (`CardPrintingTag` / `CardTagVote` / `CardArtistVote`,
live, grows continuously):

| pool      |       total | by source                                                                     |
| --------- | ----------: | ----------------------------------------------------------------------------- |
| printing  |     101,105 | ocr 72,938 / deduction 28,112 (all `deductive_backfill`, §3 item 3) / user 55 |
| tag       |      61,334 | ocr 61,294 / user 40                                                          |
| artist    |       7,137 | ocr 7,131 / user 6                                                            |
| **total** | **169,576** |                                                                               |

**Pilot run `20260716T193408-6613a1a6`** — three distinct numbers, not
one flattened figure:

- **165,980 candidates scanned** (the pilot's own completion-log
  counter; not independently re-derivable from `CardScanLog` today — see
  [`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md)'s
  note on non-persisted run counters for why some legacy-engine
  in-memory stats can't be re-queried after the fact).
- **43,425 votes cast** (live `CardPrintingTag.objects.filter(run_id=...)`
  count — **corrected 2026-07-22** from a previously-stated 43,426 in
  `theory.md`/`catalog-completion-plan.md`; the recorded `PilotRunLedger`
  ledger row still says `votes_written=43426`, an off-by-one against the
  live count with no documented retraction explaining the difference).
- **41,586 distinct cards voted** (live `.values('card_id').distinct().count()`
  — smaller than votes-cast because a card can receive votes from
  multiple engines, e.g. OCR and phash both voting on the same card).

**Stage D run history** (`CardPrintingTag`/`PilotRunLedger`, `local_calculate_verdicts`):

| run_id                                                               |                                                                                                                                               votes written | notes                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `staged-dryrun-20260721T0423Z`                                       |                                                                                                                                                           0 | dry-run                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `staged-write-20260721T0434Z`                                        |                                                                                                                                    **0** (live, 2026-07-23) | `PilotRunLedger.votes_written` records 8,925 — the pre-retraction figure; #258's retraction (2026-07-21) brought the live count to 8,825 (already documented in [`reports/2026-07-21-recovery-arc.md`](reports/2026-07-21-recovery-arc.md)); the 2026-07-23 zeroing retraction (§13) then deleted 8,801 of those, leaving 24 — which B(i)'s write pass had already re-labeled off this `run_id` as corrected flips, so **0** remain attributed here live |
| `staged2-0721`                                                       |                                                                                                                                        0 (live, 2026-07-23) | was 70; all 70 deleted by the 2026-07-23 zeroing retraction (§13)                                                                                                                                                                                                                                                                                                                                                                                        |
| `staged3-0721`                                                       |                                                                                                                                        0 (live, 2026-07-23) | was 3,010; all 3,010 deleted by the 2026-07-23 zeroing retraction (§13)                                                                                                                                                                                                                                                                                                                                                                                  |
| `staged4-0721`                                                       |                                                                                                                                        0 (live, 2026-07-23) | was 999; all 999 deleted by the 2026-07-23 zeroing retraction (§13)                                                                                                                                                                                                                                                                                                                                                                                      |
| `interim-peek-0722`                                                  |                                                                                                                                                           0 | dry-run                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `bugb-reparse-dry-20260723T014652Z` (`PilotRunLedger` id 32)         |                                                                                                                                                           0 | dry-run, `reparse_collector_evidence` whole-DB Bug-B measurement, 197,938 considered — see §12                                                                                                                                                                                                                                                                                                                                                           |
| `bugb-reparse-scoped-dry-20260723T020508Z` (`PilotRunLedger` id 33)  |                                                                                                                                                           0 | dry-run, `reparse_collector_evidence` scoped to the 284-signature ID file — see §12                                                                                                                                                                                                                                                                                                                                                                      |
| `bugb-reparse-voted33-dry-20260723T0206Z` (`PilotRunLedger` id 34)   |                                                                                                                                                           0 | dry-run, `reparse_collector_evidence` scoped to the 33 previously-voted Bug-B cards — see §12                                                                                                                                                                                                                                                                                                                                                            |
| `bugb-write-dry-20260723T090258Z` (`PilotRunLedger` id 35)           |                                                                                                                                                           0 | dry-run, pre-write confirmation for B(i) — see §13                                                                                                                                                                                                                                                                                                                                                                                                       |
| `20260723T090331-fdf5822b` (`PilotRunLedger` id 36)                  |                                                                                                                                                           — | dry-run, `retract_stage_d_by_run_id` pre-retraction preview (12,904 votes / 7,773 skips previewed) — see §13                                                                                                                                                                                                                                                                                                                                             |
| `bugb-write-20260723T0905Z` (`PilotRunLedger` id 37)                 |                                                                                                                                                     **236** | **B(i) live write** — `reparse_collector_evidence --write`, considered 285 / fields_fixed 285 / retracted 236 / gate_refused 0 — see §13                                                                                                                                                                                                                                                                                                                 |
| `20260723T091446-35a1bde5` (`PilotRunLedger` id 38)                  |                                                                                                                                                           — | **B(ii)+B(iii) live retraction** — `retract_stage_d_by_run_id --write`: 12,880 votes deleted (+24 already flipped by B(i) = 12,904 total staged votes accounted for), 7,773 skips deleted, 20,653 cards resynced, 0 resolved-gate refusals — see §13                                                                                                                                                                                                     |
| `buga-sample-20260723T0927Z` (`PilotRunLedger` id 39)                |                                                                                                                                                           — | **§9(c) Bug-A sample** — `run_image_evidence_cohort`, live, 300-card uniform sample (seed 20260723) of the 17,531-card blank-tier-1 pool, `--no-shortcircuit` — see §13                                                                                                                                                                                                                                                                                  |
| `buga-sample-verdicts-dry-20260723T093321Z` (`PilotRunLedger` id 40) |                                                                                                                                                           0 | dry-run, `reparse_collector_evidence` verdict pass over the id-39 sample — 1 genuine match / 76 no-match / 223 skips — see §13                                                                                                                                                                                                                                                                                                                           |
| `pilot-dry-20260723T094518Z` (`PilotRunLedger` id 41, §9(d) dry-run) |                                                                                                                                                           0 | dry-run, full eligible-pool Stage D pass — join-key 39,253 match/61,247 no_match, fallback 29,710 (read-only recomputation) — see [`reports/2026-07-23-4c-pilot-dry-run.md`](reports/2026-07-23-4c-pilot-dry-run.md)                                                                                                                                                                                                                                     |
| `pilot-write-20260723T1202Z` (`PilotRunLedger` id 42, §9(d) write)   | **130,210 at write** (**48,151 join-key rows survive live**, 2026-07-24 — 52,349 retracted by the lexicon-gate retraction, §14; fallback 29,710 unaffected) | **live write** — join-key 100,500 (39,253 match/61,247 no_match) + fallback 29,710 match (still 29,710 live, never retracted), exact match to the dry-run's prediction; ledger row reads `status=failed`/`votes_written=None`, a documented execution-harness artifact (client timeout severed the executor's stdout mid-run, not the write) — see §14/[`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md)    |
| `20260724T001154-d3986cfc` (post-fire calculator re-pass write)      |                                                                                                                                                       **1** | **§14 "Five further passes" write** — `local_calculate_verdicts` re-run over the lexicon-gate-retracted pool; 52,348 `unknown-set-code` + 16 `no-evidence` skips, 117,442 `to-review` — see §14                                                                                                                                                                                                                                                          |

**Stage C run history** (`ImageEvidence.run_id`, current last-writer row
count per run — canaries first, then the main leg):

| run_id                                     | date          |    rows |
| ------------------------------------------ | ------------- | ------: |
| `stagec-canary-20260720T1659Z`             | 2026-07-20    |     223 |
| `stagec-canary-decoupled-20260720T235127Z` | 2026-07-20    |     206 |
| `ntx-0721`                                 | 2026-07-20/21 |   9,675 |
| `stagec-20k-20260721T0227Z`                | 2026-07-20/21 |  10,696 |
| `stagec-remainder-0721`                    | 2026-07-21/22 | 197,470 |

Full chain: the two decoupling canaries (Jul 20) validated the
fetch/compute-decoupled architecture at small scale, then `ntx-0721` +
`stagec-20k-20260721T0227Z` (Jul 20–21) ran a combined ~20k-card
extraction pass, then `stagec-remainder-0721` (Jul 21–22, 197,470-row
main leg) extracted the bulk of the remaining catalog. See
[`reports/2026-07-20-decoupled-canary-confirm.md`](reports/2026-07-20-decoupled-canary-confirm.md)
and [`reports/2026-07-21-stagec-20k-extraction.md`](reports/2026-07-21-stagec-20k-extraction.md)
for the canary/20k narrative detail. None of these Stage C runs have a
`PilotRunLedger` row of their own — see §11 for what that does and
doesn't affect.

**`ntx-0721` is NOT a pilot** — stated explicitly because this number
has been misremembered before: `ntx-0721` is a **Stage C extraction
run** (22,899 `CardScanLog` rows, a no-text cohort re-extraction — see
[`reports/2026-07-21-recovery-arc.md`](reports/2026-07-21-recovery-arc.md)).
Verified live: **0 votes** cast under `run_id='ntx-0721'` across all
three vote tables (`CardPrintingTag`/`CardTagVote`/`CardArtistVote`).
There is no 23,000-vote pilot; "23,111 votes" was a transient same-day
pool snapshot at some earlier point, never a pilot run of any kind, and
should not be cited as a baseline.

**`printing_tag_status`**: 218,281 unresolved, 3 resolved, 1 no_match.

**`consensus_impact_report` dry-run** (2026-07-22, `--sample-limit 20`,
zero writes): printing 92,368 pairs checked / 0 transitions; artist
7,130 pairs / 0 transitions; tag 61,328 pairs, with 49,207
`None→UNRESOLVED` materializations sized as pending a separately
owner-gated recompute pass. "Zero transitions" on printing/artist means
the ratified resolver's answer already matched every currently-persisted
status exactly, at that date. **Superseded by the real apply, and then
superseded again**: this dry-run's tag/printing sizing is now closed
history — `consensus_recompute --apply` ran 2026-07-23T13:25:37Z and
materialized 49,206 of the sized 49,207 tag transitions (organic
interim resolution accounts for the one-fewer figure) plus one
additional printing resolution (3 → 4); a **second** `consensus_recompute`
closer then ran 2026-07-24T01:14:48Z and flipped that same printing
card back (`resolved→unresolved`), so the live resolved count is **3**,
not 4 — see §14's "Five further passes" and "Pass-9 ledger gap" for the
complete before/after.

## 7. Chain — where each underlying fact actually lives

This page owns the gate's **status** and its **decisions** above; every
fact below is the linked source, not duplicated here.

- [`theory.md`](theory.md) — the formal decoding model, the false-accept
  bound, and §7's stage-by-stage Stage D composition with error terms.
  Keeps the pilot's own per-engine breakdown and calibration numbers.
- [`identification-pipeline.md`](identification-pipeline.md) —
  plain-language walkthrough of the same Stage C/D pipeline, stage by
  stage, for a reader who wants the mechanics without the formal model.
- [`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md)
  — Artifact 2's full constant-by-constant inventory table (SAME /
  CHANGED / MISSING / superseded-by-architecture / open item), the
  source for §3 above.
- [`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)
  — the six-part catalog-completion plan; the Stage D precondition
  wording (§1 above) and the Stage C/D build detail live there, not here.
- [`data/2026-07-22-pipeline-snapshot.md`](data/2026-07-22-pipeline-snapshot.md)
  (+ its [`.json`](data/2026-07-22-pipeline-snapshot.json) sibling) — the
  dated raw-data record this page's §6 numbers were re-verified against;
  re-query before trusting any live-pool number more than an hour or two
  old, per that file's own provenance notes.
- [`reports/2026-07-21-recovery-arc.md`](reports/2026-07-21-recovery-arc.md)
  — the `staged-write-20260721T0434Z` 8,925→8,825 retraction (#258) cited
  in §6's Stage D table.
- [`MPCAutofill/cardpicker/deductive_backfill.py`](../MPCAutofill/cardpicker/deductive_backfill.py)
  — the module behind the 28,112 `deduction`-source printing votes and
  §3 item 3's MISSING exclusion.
- [GitHub issue #154](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/154)
  — the artifact-1 parity-replay result and the owner-acceptance ruling
  comments (2026-07-22), the source for §4's numbers.
- [PR #340](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/340)
  (merged) — the code fix for both of §4's root causes; the live
  373-card cohort still needs the gated re-extraction described there.
- [PR #341](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/341)
  (merged) — §3 item 3's non-restoration rationale and code removal.
- [PR #343](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/343)
  (merged) — §3 items 1–2's `RESOLUTION_FLOOR_DPI`/`EXCLUDED_RESOLVED_TAGS`
  queryset-exclude fix, merged to master and deployed via PR #345.
- [PR #345](https://github.com/ProxyPrints/ProxyPrints.github.io/pull/345)
  (merged) — the §9(a) deploy commit (master `a587000`); also makes
  `run_image_evidence_cohort` self-recording via `PilotRunLedger`
  (unrelated to §9(a) itself, ledger-tracking-only, see §11).
- [issue #347](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/347)
  — the Tron-reviewed pre-pilot machine-vote zeroing plan that amended
  §9 2026-07-23 (the retraction step, the Tron corrections, the
  consensus-safety verification cited in §9/§12).
- [`reports/2026-07-23-4c-pilot-dry-run.md`](reports/2026-07-23-4c-pilot-dry-run.md)
  — the §9(d) measurement of record: the full eligible-pool Stage D
  dry-run's per-channel counters and the read-only fallback-recovery
  methodology, cited in §9(d)/§14.
- [`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md)
  — the §9(d)/§9(e) fire-sequence closing steps: the pilot `--write`'s
  DB-verified vote counts, the `status=failed` execution-harness
  artifact explanation, and `consensus_recompute --apply`'s outcome,
  the source for §14 above.
- [`data/2026-07-23-bugb-reparse-dryruns.md`](data/2026-07-23-bugb-reparse-dryruns.md)
  — the §9(b)/§12 Bug-B whole-DB reparse dry-run report + resource
  metrics, keyed by `run_id`.
- [`data/2026-07-23-zeroing-and-buga-sample.md`](data/2026-07-23-zeroing-and-buga-sample.md)
  — the §9 B(i)/B(ii)+B(iii)/(c)/§13 zeroing-execution and Bug-A sample
  report + resource metrics, keyed by `run_id`.
- [`MPCAutofill/cardpicker/management/commands/consensus_recompute.py`](../MPCAutofill/cardpicker/management/commands/consensus_recompute.py)
  (PR #336, merged) — the `--apply` command §9(e)'s materialization step
  runs (STRICTLY LAST — see §9's Tron correction).

## 8. New-data basis (owner-ratified 2026-07-23)

The 2026-07-22 full-catalog Stage C sweep (§6's `stagec-remainder-0721`
main leg, plus its two preceding canary/20k runs) is the epistemic
foundation for everything this gate measures **going forward**. Two
consequences, both ratified in-session 2026-07-23:

1. **Artifact 1 (§4)'s legacy-pilot comparison is CLOSED HISTORY.** Pilot
   run `20260716T193408-6613a1a6` served its purpose as a cross-method
   corroboration point (§4, §5, `theory.md` §7c) and stays on the record
   as that, permanently — but it does not get re-run or re-compared
   against as new data lands. It is not the baseline going forward.
2. **The new system's own pilot is DERIVED from the new data, not
   inherited from the old one.** The upcoming full-pool Stage D dry-run
   (§9 step (d), the "4c pilot") IS the pilot / measurement of record
   from this point on — its own statistics (match/no-match/abstain
   counts, per-channel join-key-vs-fallback breakdown) become the cited
   figures for any future soundness argument about this pipeline, not a
   diff back against the legacy engine.

**Scope note**: this is a basis change, not a retraction. Every legacy
(`source=ocr`, pilot-era) and deduction (`source=deduction`,
`deductive_backfill`) vote already in the DB stays exactly as-is — no
retraction, no source filter applied to either, in this ruling or any
prior one. They continue to count as live, valid votes toward
consensus; they simply stop being cited as the validation baseline for
new soundness claims.

## 9. Fire sequence (owner-ratified 2026-07-23, amended 2026-07-23 per #347)

The full gated sequence this gate's verdict (§2) is blocked on, in
order. **Amended same-day** by
[issue #347](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/347)
(Tron-reviewed pre-pilot machine-vote zeroing plan) to insert an
explicit retraction step ahead of the pilot dry-run — rationale: the
ratified new-data basis (§8) requires the 4c pilot to cast **100% of
fresh machine votes** against the corrected evidence/parser (a
new-data-basis requirement, not a data-quality complaint about the
staged votes themselves), and consensus safety for doing so was
independently verified (all 12,904 staged cards UNRESOLVED before and
after, zero resolved-card overlap, zero user-visible delta during the
no-vote window, zero ES writes from retraction).

**(a) Deploy master — DONE 2026-07-23T01:33Z.** PR #345 (master
`a587000`) put PR #343's §3 items 1–2 fix (and PR #341's item 3
non-restoration) live in prod; migration `0078` auto-applied; #343's
constants verified live in the running container (§3, §12).

**(b) Bug-B whole-DB reparse dry-run — DONE (§12).** The fixed parser
applied offline across all 197,938 stored raw texts confirmed the
existing 285-row prediction (§10) **exactly**: 284 glued-marker guard
rows plus 1 unrelated improvement (card 62354). Full detail, resource
metrics, and the scoped-33 sub-run: [`data/2026-07-23-bugb-reparse-dryruns.md`](data/2026-07-23-bugb-reparse-dryruns.md).

**B(i) Bug-B write pass — DONE 2026-07-23 (§13).** `reparse_collector_evidence --write` (run `bugb-write-20260723T0905Z`) against the
**regenerated 284-signature ID file** (the exact cohort §12's dry-run
confirmed), **NOT** the broader `parser-bug` regex selector (a 553-card
different, wider cohort — not substituted). Patch requirement (persist
corrected parse fields **unconditionally**) verified in the outcome:
considered=285, fields_fixed=285 (all 285, unconditionally — the
49-row gap is closed), retracted=236 (votes actually flipped),
gate_refused=0.

**B(ii)+B(iii) Retraction — one invocation, DONE 2026-07-23 (§13).** The
single-purpose `retract_stage_d_by_run_id` command (run
`20260723T091446-35a1bde5`), scoped to `anonymous_id=stage-d-join-key-v1`
AND the four staged run ids, deleted:

- **12,880 `CardPrintingTag` votes** (`staged-write-20260721T0434Z` /
  `staged2-0721` / `staged3-0721` / `staged4-0721`) **plus the 24 votes
  B(i) had already flipped to genuine matches within the same target
  cohort = all 12,904 originally-staged votes accounted for**,
  matching §6's table exactly (8,825 + 70 + 3,010 + 999 = 12,904; a
  pre-retraction dry-run preview, `20260723T090331-fdf5822b`, confirmed
  the full 12,904 before B(i)'s write ran). This task's own independent
  pre-flight check (2026-07-23T09:41Z, ahead of launching (d)) confirmed
  the same end state: 0 `CardPrintingTag` rows remain with
  `anonymous_id=stage-d-join-key-v1`.
- **7,773 non-rescannable `CardScanLog` stale skips** from the same
  four runs (per-run: 7,187 / 14 / 19 / 553), exactly as predicted. (The
  much larger `no-evidence` skip population from these same runs was
  deliberately **excluded** — it is rescannable via the pilot's own
  native resume-filter logic, not a retraction target.)

Per-card `resolve_printing()` safety gate applied (same conservative
card-level check as `reparse_collector_evidence`, §3 item 3's
docstring) — **0 `skipped_resolved_gate` refusals**, confirming zero
resolved-card overlap. **Verified untouched**: user votes (55),
deduction votes (28,112 — §3 item 3, still 28,112 live), legacy pilot
votes (43,425, still 43,425 live), all tag/artist votes, the 3 resolved

- 1 no_match cards (still 3 resolved live). 20,653 cards resynced via
  `resolve_and_persist_printing()` — **Tron correction** still applies:
  that function casts no votes itself, it only recomputes/persists
  printing state for the card just retracted. **Verified end-state
  (2026-07-23, live)**: `CardPrintingTag` rows with
  `anonymous_id='stage-d-join-key-v1'` = 0; non-rescannable `CardScanLog`
  skips for the 4 target runs = 0. Full run report:
  [`data/2026-07-23-zeroing-and-buga-sample.md`](data/2026-07-23-zeroing-and-buga-sample.md).

**(c) Bug-A forced-escalation SAMPLE — DONE 2026-07-23 (§13).** 300
cards uniform-randomly sampled (seed 20260723, `--no-shortcircuit`) from
the 17,531-card blank-tier-1 pool (§10), run `buga-sample-20260723T0927Z`
(extraction, 85.4s) + `buga-sample-verdicts-dry-20260723T093321Z`
(verdict dry-run). Funnel: 300 fetched → 78 non-blank OCR text (26.0%)
→ 78 parsed numbers → 65 set codes → 76 no-match votes → **1 genuine
match** (0.33%, card 122326 "Ephemerate" sketch variant → `STA` 68,
spot-checked correct) → 223 skips. Wilson 95% extrapolation to the full
17,531-card pool: **~58 genuine matches [CI 10–327]**, qualitatively
low-end likely (spot-checks show OCR noise dominating the non-blank
yield); full re-scan cost estimated ~83–104 minutes.

**Owner ruling (2026-07-23): Bug-A full re-scan DEFERRED to
post-pilot**, gap tracked not dropped: (a) the 17,531-card signature
query regenerates on demand (`fetch_ok=True`, empty collector number,
blank/whitespace raw text, excluding `ntx-0721`; 17,531 at
2026-07-23T09:19Z); (b) the pilot's own skip counters (§9(d)) will
surface the blank-evidence abstentions so the gap stays visible; (c)
**any future re-scan MUST include a state-clear step first** — this
sample's no-text skips are non-rescannable (unlike `no-evidence`
skips), so a post-pilot re-scan recipe is: re-extract with
`--no-shortcircuit` → clear stale skip state via the reparse path →
run a follow-up scoped Stage D pass to vote. Documented here as the
recipe so it is not re-derived. Full run report, funnel table, and the
recipe's full rationale:
[`data/2026-07-23-zeroing-and-buga-sample.md`](data/2026-07-23-zeroing-and-buga-sample.md).

**(d) Stage D dry-run over the full eligible pool = THE PILOT — DONE
2026-07-23** (§8), run_id `pilot-dry-20260723T094518Z`, git_sha
`42a09b3c794f7cf8aca5eb1ca2d4f6cdaa2895a6`, eligible pool 200,366 (post-
zeroing, live-verified immediately pre-run). Full statistics, the
per-channel join-key-vs-fallback breakdown, and the read-only fallback
recomputation methodology (the actual command reports fallback
considered=0/votes=0 for a **structural** reason — see below — not a
data gap): [`reports/2026-07-23-4c-pilot-dry-run.md`](reports/2026-07-23-4c-pilot-dry-run.md).
**Structural finding**: `_fallback_eligible_cards_queryset` sources its
"join-key found no confident hit" population from PERSISTED
`CardPrintingTag`/`CardScanLog` rows — which a same-invocation DRY RUN
never writes — so `local_calculate_verdicts` (no `--write`) can concretely never produce a nonzero fallback count in one pass, regardless of flags;
this is inherent to the current implementation, not fixable by a
different invocation. The fallback channel's real first-ever numbers
were recovered via a bounded, zero-write diagnostic that re-derives the
join-key no-hit population in-memory using the same production
functions, then calls the actual `calculate_fallback_verdict` per
eligible card — see the linked report for the full methodology and
results. Followed by an owner **SAMPLE AUDIT — DONE** (150 uniformly
sampled verdicts, seed `20260723150`) — sheet written machine-local only
(not committed; see the linked report for its exact path and
provenance), then **`--write` — DONE 2026-07-23** (run
`pilot-write-20260723T1202Z`, `PilotRunLedger` id 42,
COMPLETE-BY-VERIFICATION — both channels' vote counts DB-verified to
match the dry-run's prediction exactly, 130,210 total votes; full
outcome and the `status=failed` execution-harness artifact explanation:
[`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md)).

**(e) `consensus_recompute --apply` — STRICTLY LAST — DONE 2026-07-23T13:25:37Z.**
Materialized the pending `None→UNRESOLVED` tag transitions sized in
§6's `consensus_impact_report` dry-run (49,206 of the 49,207 sized
there — one fewer, organic interim resolution, not a discrepancy), via
the command in
[`consensus_recompute.py`](../MPCAutofill/cardpicker/management/commands/consensus_recompute.py)
(PR #336). Exit code 0. **Tron correction to an earlier "tag-orthogonal"
claim**: `consensus_recompute` recomputes **printing + artist + tag**
state via the real resolver paths, not tag state alone — its safety in
this sequence comes from **idempotence plus running strictly last**,
not from any orthogonality to the printing-layer steps above; it was
run strictly last here too. Printing resolution moved 3 → 4 resolved
cards (DB-verified); artist (7,130 pairs) had zero transitions. Full
outcome: [`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md).
**Note**: this command predates the `PilotRunLedger` self-recording
convention — no ledger row exists for it, a small follow-up flagged
beside the already-tracked §11 Stage C run-identity gap. **Re-confirmed
2026-07-24 by an independent DB-only audit** (exhaustive `PilotRunLedger`
scan, 64 rows, no gap-filling row found for this invocation): the gap is
real and structural, not an omission — see §14's "Pass-9 ledger gap"
note for the full corroboration attempt.

**Order was load-bearing and followed exactly**: (a) → (b)/B(i) →
B(ii)+B(iii) → (c) → (d) → sample audit → `--write` → (e)
`consensus_recompute --apply` strictly last. **The full §9 sequence
(as originally ratified) is COMPLETE.** §14 records five further
corrective/completion passes that ran after (e), extending true
completion to 2026-07-24 — not a reopening of §9's own ratified order,
which stands as executed.

Every run in this sequence gets its own report plus resource metrics
(RSS/IO/CPU, per-card cost) committed under `docs/data/`, keyed by that
run's `run_id`, and added as a new row to §6's Stage C/Stage D run
history tables (not a separate table).

## 10. #340 root-cause footprint sizing (measured 2026-07-23T00:16–00:24Z, live, read-only)

Both root causes fixed by merged PR #340 (§4) were sized against the
**full catalog**, not just the 373-card replay cohort (§4's cohort is
bounded to the pilot-vote comparison set, 41,586 cards; this sizing
covers the whole 218,285-card catalog).

**Bug A (OCR short-circuit over-skip).** 17,531 cards catalog-wide
carry the blank-tier-1 signature — a necessary-condition proxy for the
bug (matches the pattern the fix targets; not a guarantee every one
flips to a match), excluding `ntx-0721`'s cohort (already
force-escalated by that run, §6). 15,948 of the 17,531 (91%) are
Stage-D-eligible. Expected genuine-match conversion is **LOW**:
`ntx-0721`'s own base rate for this same signature is ~0.2% — the
reason §9(c) samples first rather than committing to a full re-scan.

**Bug B (glued language-marker set-code).** 284 rows carry the
signature, systemic across ≥7 distinct set codes (not one bad batch).
212 of the 284 are Stage-D-eligible; 33 already carry staged-run votes,
and **every one of those 33 is `is_no_match=True` with 0 wrong-printing
votes** — direct empirical confirmation, at this wider scale, of the
same conservative-abstention direction §4/`theory.md` §7c already
established at the 373-card replay scale. The whole-DB reparse (§9(b))
is pre-sized, not estimated: offline re-parsing all 197,938 stored raw
texts with the fixed parser diffs **exactly** 284 guard rows plus 1
unrelated improvement (card 62354).

## 11. Stage C run-identity note (verified 2026-07-23)

Stage C runs are **not** tracked in `PilotRunLedger` — verified
directly: zero rows for `run_image_evidence_cohort`. Completion-log
counters like `stagec-remainder-0721`'s (141,369 processed / 57,725
short-circuited / 492 fetch failures, §6) are log-only and not
DB-re-derivable after the fact, the same caveat §6 already states for
the older pilot's own 165,980-candidate counter. This does not affect
the evidence itself: `ImageEvidence` rows are fully persisted
regardless of ledger tracking — 197,469 current rows verified at this
check, window 2026-07-21T19:29:24Z–2026-07-22T16:45:43Z (one row's
drift against §6's 197,470 count for the same run is two snapshots
taken at different times, not a data-integrity concern — re-query
before trusting either number to the exact row). A ledger fix (Stage C
runs writing their own `PilotRunLedger` rows, closing this gap) is in
flight as a separate code PR, not yet merged as of this note.

## 12. Deploy + Bug-B whole-DB reparse dry-run outcome (2026-07-23)

**Deploy (§9(a)):** master `a587000` (PR #345) merged and deployed to
prod **2026-07-23T01:33Z**. Migration `0078` auto-applied — verified
live (`manage.py showmigrations cardpicker` shows `[X] 0078_pilotrunledger_counters`
as the last applied row). §3 items 1–2's constants verified live in the
running container: `RESOLUTION_FLOOR_DPI = 200`,
`EXCLUDED_RESOLVED_TAGS = ['custom-art', 'non-english']`.

**Bug-B whole-DB reparse dry-run (§9(b)):** three `reparse_collector_evidence`
dry-runs, `PilotRunLedger` ids 32–34 (§6's Stage D run history table),
all `dry_run=True` / `votes_written=0` — verified live against
`PilotRunLedger` directly.

- **`bugb-reparse-dry-20260723T014652Z`** (whole-DB, 197,938
  candidates): the offline 285-changed-row prediction already recorded
  in §10 verified **exactly** — 284 glued-marker guard rows plus 1
  unrelated improvement (card 62354). The command's own internal
  `changed=162,866` counter is a **different, broader** metric (see
  the command's own module docstring: it compares a fresh re-parse
  against each card's currently-RECORDED join-key verdict, not against
  the specific glued-marker signature) — arithmetic cross-check:
  `no_evidence=0 + no_prior_join_key_state=16,253 + unchanged=18,819 + changed=162,866 = 197,938`, matching `considered` exactly. The
  162,866 figure is explained as stale no-evidence skips from the
  2026-07-21 staged passes predating full Stage C evidence coverage,
  handled natively by the pilot's own rescannable-skip resume logic —
  **not** Bug-B blast radius, and explicitly **not** a write target for
  B(i)/B(ii+iii).
- **`bugb-reparse-scoped-dry-20260723T020508Z`** and
  **`bugb-reparse-voted33-dry-20260723T0206Z`**: scoped confirmation
  runs, completed in 2.94s and 1.69s respectively. The voted33 run
  found **24/33** previously-voted Bug-B cards flip
  false-no-match→genuine match under the fixed parser — ground-truth
  confirmation of those 24 is deferred to the pilot's owner sample
  audit (§9(d)), not asserted here.

Full run report, resource metrics (RSS/IO/CPU, per-card cost), and
provenance: [`data/2026-07-23-bugb-reparse-dryruns.md`](data/2026-07-23-bugb-reparse-dryruns.md).
This also doubles as the first runtime calibration for the §9(d) 4c
pilot dry-run — same verdict-computation code path.

**Fallback channel (§9(d)):** as of this section's original
2026-07-23T01:33Z-onward timestamp, verified live 0 `CardPrintingTag`
rows carried `anonymous_id='stage-d-fallback-v1'` — the fallback
channel had never cast a vote in production. §9(d)'s own entry now has
the full outcome (still zero **live votes** — the pilot is DRY-RUN
only — but the channel's own would-cast statistics are now known, via
a read-only recomputation; see that entry and its linked report).

**Remaining §9 steps as of this section's timestamp (2026-07-23T01:33Z
onward): B(i), B(ii)+B(iii), (c), (d), sample audit, `--write`, (e) were
all NOT YET RUN.** §13 below carries a later same-day update: B(i),
B(ii)+B(iii), (c), **and (d) (the 4c pilot dry-run) are now all DONE**
(§9(d)'s own entry carries the full outcome); sample audit / `--write` /
(e) remain NOT YET RUN.

## 13. Zeroing execution + Bug-A sample outcome (2026-07-23T09:0x–09:3xZ)

**B(i) Bug-B write pass — DONE.** Run `bugb-write-20260723T0905Z`
(`PilotRunLedger` id 37, preceded by dry-run confirmation id 35):
considered=285, fields_fixed=285 (all persisted unconditionally, closing
the 49-row gap), retracted=236 (votes actually flipped), gate_refused=0.

**B(ii)+B(iii) retraction — DONE.** Run `20260723T091446-35a1bde5`
(`PilotRunLedger` id 38, preceded by a dry-run preview id 36): 12,880
`CardPrintingTag` votes deleted + the 24 votes B(i) had already flipped
= all 12,904 originally-staged votes accounted for exactly; 7,773
non-rescannable `CardScanLog` skips deleted (per-run 7,187 / 14 / 19 /
553, matching the prediction exactly); `skipped_resolved_gate=0`;
20,653 cards resynced via `resolve_and_persist_printing()`. **Verified
end-state (live, this section)**: `stage-d-join-key-v1` votes = 0;
non-rescannable join-key skips (4 target runs) = 0; deduction votes =
28,112 (intact); legacy pilot votes = 43,425 (intact); resolved cards =
3 (intact); eligible Stage D pool = 200,366 (relayed, not re-queried
this pass to avoid a full-catalog scan against the concurrently-running
§9(d) pilot).

**§9(c) Bug-A forced-escalation sample — DONE.** Runs
`buga-sample-20260723T0927Z` (`PilotRunLedger` id 39, 300-card
uniform-random extraction, seed 20260723, `--no-shortcircuit`, 85.4s,
7 workers) + `buga-sample-verdicts-dry-20260723T093321Z` (`PilotRunLedger`
id 40, verdict dry-run). Funnel over the 300-card sample drawn from the
17,531-card blank-tier-1 pool (§10): 300 fetched → 78 non-blank OCR text
(26.0%) → 78 parsed numbers → 65 set codes → 76 no-match votes → **1
genuine match** (0.33%) → 223 skips. The 1 match: card 122326
("Ephemerate", Sketch Yumiko variant) → `STA` 68 — spot-checked and
confirmed correct. Wilson 95% extrapolation to the full pool: **~58
genuine matches [CI 10–327]**, qualitatively low-end likely (OCR noise
dominates the non-blank yield in spot-checks); full re-scan estimated at
~83–104 minutes.

**Owner ruling (2026-07-23): Bug-A full re-scan DEFERRED to
post-pilot.** Gap tracked, not dropped: (a) the signature query
regenerates on demand (17,531 cards at 2026-07-23T09:19Z, same
definition as §10); (b) the §9(d) pilot's own skip counters will surface
the blank-evidence abstentions, keeping the gap visible without a
separate tracker; (c) **the post-pilot re-scan procedure must include a
state-clear step** — this sample's no-text skips are non-rescannable
(unlike the `no-evidence` skip reason handled natively elsewhere in this
sequence), so the documented recipe is: re-extract with
`--no-shortcircuit` over the target cohort → clear stale skip state via
the reparse path (`reparse_collector_evidence`, same mechanism B(i)
used) → run a follow-up scoped Stage D pass (`local_calculate_verdicts`)
to actually cast votes. Recorded here as the standing recipe so it is
not re-derived next time.

**§9(d) the 4c pilot dry-run — DONE**, started immediately after (c)
above completed. Full run_id, statistics, per-channel breakdown, and the
read-only fallback-channel recovery methodology: see §9(d)'s own entry
above and [`reports/2026-07-23-4c-pilot-dry-run.md`](reports/2026-07-23-4c-pilot-dry-run.md).

Full run reports, resource metrics, and per-run `PilotRunLedger`
counters for every run in this section:
[`data/2026-07-23-zeroing-and-buga-sample.md`](data/2026-07-23-zeroing-and-buga-sample.md).

**B(i)/B(ii)+B(iii)/(c)/(d) are now all DONE** (§9's own entries carry
the live-verified detail and ledger ids); **sample audit, `--write`, and
(e) remained NOT YET RUN as of this page's edit at the time this
section was written. §14 below carries the closing update: all three
completed the same day, 2026-07-23 — the full §9 sequence is COMPLETE.**

## 14. Fire sequence complete — full outcome (2026-07-23/24)

The owner sample audit, the pilot `--write`, and the first
`consensus_recompute --apply` — the three steps §12/§13 left NOT YET
RUN — all completed 2026-07-23. **The §9 fire sequence (as originally
ratified) is COMPLETE end to end** and the gate is **FIRED** (§2). Full
detail, DB-verified counters, and the `status=failed` artifact
explanation:
[`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md).

**This section was extended 2026-07-24** with five further
corrective/completion passes that ran the same night into the next day
(a lexicon-gate retraction, a marker reparse, an artist-credit fill, a
calculator re-pass, and a second `consensus_recompute` closer) — see
"Five further passes" below, and the full per-pass table immediately
below. All figures in this extension are **DB-verified live** against
`mpcautofill_django`/Postgres, queried 2026-07-24, unless marked
"docs-sourced" or "GAP."

**Full per-pass table** (chronological, all times UTC; condensed —
dry-run rehearsals with 0 rows written are collapsed into their write
row's note where the write immediately follows):

| #   | pass                               | run_id(s)                            | dry/write          | wall time      | rows written                                                          | notes                                                 |
| --- | ---------------------------------- | ------------------------------------ | ------------------ | -------------- | --------------------------------------------------------------------- | ----------------------------------------------------- |
| 1   | Bug-B reparse write                | `bugb-write-20260723T0905Z` (id 37)  | write              | 5.4s           | 236 vote-affecting rows                                               | preceded by 3 dry rehearsals (ids 33–35), see §12/§13 |
| 1r  | Bug-B retraction                   | `20260723T091446-35a1bde5` (id 38)   | write              | 189s           | votes_deleted 12,880, cards_resynced 20,653                           | see §13                                               |
| 2   | Bug-A forced-escalation sample     | `buga-sample-20260723T0927Z`         | write (extraction) | 85.4s          | 300 sampled, 1 genuine match                                          | see §9(c)/§13                                         |
| 3   | 4c pilot dry-run                   | `pilot-dry-20260723T094518Z` (id 41) | dry                | 7m37s          | 0                                                                     | see §9(d)/§14 above                                   |
| 4   | 4c pilot write                     | `pilot-write-20260723T1202Z` (id 42) | write              | 59m23s         | 130,210 (77,861 survive live today; 52,349 later retracted by pass 5) | see §14 above                                         |
| 5   | Lexicon-gate retraction            | `20260723T184334-2260859d`           | write              | 675.8s         | retracted 52,349, unchanged 8,898                                     | see "Five further passes" below                       |
| 6   | Marker reparse write               | `20260723T184318-6e0c73d9`           | write              | 13.4s          | 2,506 fields flipped (not votes)                                      | see "Five further passes" below                       |
| 7   | Artist fill write                  | `20260723T213608-5479a0f0`           | write              | 51m2s          | 131,020 evidence fields filled                                        | see "Five further passes" below                       |
| 8   | Calculator re-pass write           | `20260724T001154-d3986cfc`           | write              | 52m41s         | 1 vote; 52,348+16 skips, 117,442 to-review                            | see "Five further passes" below                       |
| 9   | Consensus recompute #1 (pilot-era) | **no ledger row — GAP**              | —                  | not verifiable | 49,206 tag transitions (docs-sourced)                                 | see "Pass-9 ledger gap" below                         |
| 10  | Consensus recompute #2 (closer)    | `20260724T011448-32e08cc8`           | apply              | 383.9s         | 101,715 total (tag 0, artist 0, printing 1)                           | see "Five further passes" below                       |

Full per-pass detail (every dry-run rehearsal, exact considered/skip
counts, and the reconciliation arithmetic) is DB-verified but not
duplicated in full here — this table is the condensed record; the
prose subsections below carry the load-bearing detail for passes 5–10.

**Pilot `--write`** — run `pilot-write-20260723T1202Z`, `PilotRunLedger`
id 42, `started_at` 2026-07-23T12:06:53Z, `finished_at` 2026-07-23T13:06:16Z.
DB-verified vote counts match the §9(d) dry-run's prediction **exactly**
on both channels: join-key 100,500 (39,253 match / 61,247 no_match,
same as the dry-run's `would_cast` figures), fallback 29,710 match (the
fallback channel's **first production execution** — its votes did not
exist before this run). Grand total **130,210** `CardPrintingTag` rows
written.

**The `status=failed` / `votes_written=None` artifact**: the ledger row
itself reads as a failed run with no vote count. This is **NOT** a
failed or partial write — it is a documented execution-harness
artifact. The authorization executor enforced a **1800s client-side
timeout** on the launching connection; that timeout severed the
executor's own stdout stream at ~12:36Z, not the in-container process,
which kept running to completion (`finished_at` 13:06:16Z, ~30 minutes
past the timeout boundary) and hit a terminal-phase exception in its own
summary/ledger-update code, after the last vote write, not during it.
The DB-verified vote counts above — an exact match to the dry-run's
prediction on both channels — are the direct evidence the writes
themselves completed cleanly. Recorded here as
**COMPLETE-BY-VERIFICATION**, not as a failed fire, so this row is never
misread as one at a glance.

**`consensus_recompute --apply`** — executed 2026-07-23T13:25:37Z, exit
code 0. Predates the `PilotRunLedger` self-recording convention (no
ledger row exists for it — confirmed live, highest id remains 42) — this
was flagged beside the already-tracked §11 Stage C run-identity gap as a
"command predates the ledger convention" instance rather than a broken
command, and is now resolved going forward: `consensus_recompute` gained
its own self-recording ledger row (RUNNING at start, COMPLETED/FAILED at
end, per-family `pairs_checked`/`rows_written`/`transitions` counters)
as part of the command-lifecycle hardening pass, matching every other
Stage C/D pilot command's lifecycle. This specific 2026-07-23T13:25:37Z
run predates that fix and has no ledger row, immutably. Outcome: artist 7,130 pairs
checked, 0 transitions; tag 61,329 pairs checked, 49,206
`None→UNRESOLVED` materializations (one fewer than the 49,207 sized in
§6's earlier dry-run — organic interim resolution in the gap between
measurement and apply, not a discrepancy); printing resolved 3 → 4
(DB-verified at the time: `Card.printing_tag_status` distribution =
unresolved 218,309 / resolved 4 / no_match 1). **This 4 was itself
provisional** — a second closer pass the following night flipped it
back to 3; see "Five further passes" and "Topline end-state" below for
the corrected live figure.

**Pass-9 ledger gap** (re-confirmed 2026-07-24): the 49,206-transition
figure above remains **docs-sourced, not independently re-derivable**
from any ledger row — an exhaustive `PilotRunLedger` scan (64 rows, ids
1–65 minus an unrelated gap at id 10) found no row for this invocation,
and `Card.tag_vote_statuses` is a mutable JSONField overwritten by every
later recompute, not append-only, so the exact per-run delta can't be
reconstructed after the fact either. Best available corroboration (not
proof): the live `tag_vote_statuses` aggregate is 61,332 `unresolved` +
2 `resolved_apply` = 61,334 (card, tag) pairs, and the 2026-07-24 closer
pass's own dry-run rows report `pairs_checked: 61,330` for the tag
family with **zero** transitions found — consistent with a large
one-time materialization having already happened before the closer ran.
This is a structural, pre-ledger-convention gap (the command has since
been hardened to always self-record), not a data-quality concern, and
nothing further closes it.

### Five further passes (2026-07-23 evening → 2026-07-24)

Five more passes ran after the original §9 sequence closed, all
DB-verified live 2026-07-24. None of these were part of the ratified
§9 order — each addressed a downstream correction or the pilot's own
follow-on work, and none re-opens the gate question.

- **Lexicon-gate retraction** — dry `lexgate-dry-20260723T1835Z`
  (18:35:54→18:38:56, 181.9s), write `20260723T184334-2260859d` (18:43:34→18:54:50,
  675.8s, 77.5 rows/s). Scope hash `7662d0b34e17d2a6`, considered 61,247:
  **changed 52,349, retracted 52,349**, unchanged 8,898. Retracted the
  52,349 stale join-key votes the pilot `--write` (pass above) had cast
  against evidence a corrected lexicon gate has since superseded, rather
  than recasting them itself. This is the other half of the pilot
  `--write` reconciliation math already noted in §6: live join-key rows
  under `pilot-write-20260723T1202Z` today = 48,151 (down from the
  100,500 cast), and 48,151 + 52,349 = 100,500 exactly.
- **Marker reparse** — two dry rehearsals (`20260723T164303-f8e07e2b`,
  superseded, considered 132,674, would-flip 2,508; `markerdry-20260723T1844Z`,
  final, considered 133,354, would-flip 2,506 — the pool grew ~680 rows
  between them from concurrent `run_image_evidence_cohort` crash-drill
  passes), then write `20260723T184318-6e0c73d9` (18:43:18→18:43:31,
  13.4s, 186.7 flips/s): **2,506 rows flipped `legal_line_proxy_marker_detected`
  false→true**. Field-level correction, casts no votes.
- **Artist fill** — dry `20260723T204858-40e9408a` (20:48:58→21:35:07,
  46m10s), write `20260723T213608-5479a0f0` (21:36:08→22:27:10, 51m2s,
  42.8 fills/s). `backfill_modern_artist_names`, considered 202,338:
  dry `would_fill 131,020` / write **filled 131,020** — exact match.
  Fills `ImageEvidence.artist_ocr_name` only (never overwrites a
  non-blank value) — evidence, not a vote table. DB cross-check: current
  non-blank `artist_ocr_name` count 144,680 = 131,020 (this run) +
  ~13,660 pre-existing (docs figure), consistent.
- **Calculator re-pass** — two dry rehearsals (`20260723T222926-022af8ca`,
  `20260723T231506-b5c52b16`, ~43.6–43.7 min each, 0 written), then write
  `20260724T001154-d3986cfc` (00:11:54→01:04:35, 52m41s, 53.7 rows/s
  scan-log+vote total). `local_calculate_verdicts` re-run over the
  lexicon-gate-retracted pool: **1** `CardPrintingTag` vote written;
  DB-verified via `CardScanLog`, **52,348** `unknown-set-code` skips, 16
  `no-evidence` skips, **117,442** `to-review` skips (169,806 scan-log
  rows total). Nearly all of the retracted pool landed in
  abstention/review rather than a fresh resolvable vote.
- **Consensus recompute #2 ("the closer")** — dry `20260724T010750-21919b2d`
  (139.2s), dry `20260724T011030-f216fcc1` (138.7s), apply
  `20260724T011448-32e08cc8` (01:14:48→01:21:12, 383.9s, 264.9 rows/s).
  Re-materialized tag/artist/printing consensus: tag 61,330 pairs
  checked, **0** transitions; artist 7,130 pairs checked, **0**
  transitions (every one of those 7,130 checked pairs still carries only
  a single vote, below the resolution threshold — see "Artist-consensus
  finding" below); printing 94,585 pairs checked, **1** transition
  (`resolved→unresolved`) — total_written **101,715**. This is the pass
  that corrects the live `Card.printing_tag_status` resolved count from
  4 back to **3** (DB-verified: unresolved 218,341 / resolved 3 /
  no_match 1, summing to the current 218,345-card catalog).

### Artist-consensus finding (verified 2026-07-24, real, not an artifact)

Despite the artist-fill pass writing 131,020 `ImageEvidence.artist_ocr_name`
values and the closer checking 7,130 `CardArtistVote` (card, votes)
pairs, **all 218,345 cards currently read `artist_vote_status=unresolved`**
(0 resolved, 0 unknown, 0 contested); `Card.inferred_canonical_artist`
is non-null on **0** cards. Each of the 7,130 checked pairs carries only
a single machine vote, which sits below the resolution weight/share
threshold in the owner-ratified vote-weight scenario matrix — see
[`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md)
(narrated in [`theory.md`](theory.md) §4/§7a) for the resolution
mechanics; not restated here. This is expected behavior under that
ruling, not a bug: a lone machine vote never resolves anything on its
own, by design.

### Topline end-state (DB-verified live, queried 2026-07-24)

- Total `Card` rows: **218,345**.
- `printing_tag_status`: unresolved **218,341**, resolved **3**, no_match
  **1**.
- `artist_vote_status`: all 218,345 `unresolved` (see "Artist-consensus
  finding" above).
- Review queue: **134,370** distinct cards whose current
  (most-recent-per card+engine, dedup'd) `CardScanLog` row reads
  `skip_reason='to-review'` — the closest DB-backed proxy for review-queue
  size; no separate review-queue table/endpoint exists in the schema.
- `CardPrintingTag` (printing-consensus votes): **166,066** total —
  user 58, deduction 28,112, ocr 137,896 by source; by `anonymous_id`:
  `stage-d-join-key-v1` 48,152, `local-ocr-v1` 39,795,
  `stage-d-fallback-v1` 29,710, `deductive-backfill-v1` 28,112,
  `local-fallback-v1` 11,947, `local-phash-v1` 8,292, plus 7 small
  per-session user `anonymous_id`s (58 rows total). The "legacy pilot"
  43,425 figure matches run_id `20260716T193408-6613a1a6` specifically,
  not any single `anonymous_id` bucket (that run spans three engines).
- `CardArtistVote`: 7,137 total (ocr 7,131, user 6).
- `CardTagVote`: 61,336 total (ocr 61,294, user 42).

### Operational notes

- **Scryfall cache lost on every container rebuild** — [issue #402](https://github.com/ProxyPrints/ProxyPrints.github.io/issues/402),
  discovered 2026-07-23 after a deploy: `MPCAutofill/scryfall_cache/default_cards.json`
  (~2GB) lives inside the django container filesystem, not on a mounted
  volume, so a rebuild silently deletes it. `local_calculate_verdicts`
  ran with an empty back-face lookup as a result (degraded, not
  crashed — easy to miss). Fix (mount the cache dir, or fail loud on
  staleness) is tracked in the issue, not yet applied as of this
  section.
- **Border-tag seeding (7 created)** — the `seed_attribute_tags`
  management command (backing the `local_layout_class_cast` border-vote
  caster, issue #369/PR #375) was run to seed the attribute-chip
  taxonomy it depends on: Etched, Black/White/Silver Border, Old/Modern
  Border, Future Frame — 7 tags, none of which existed before. Verified
  live: `Tag` ids 24–30 are exactly this set, sequential, with nothing
  else in that id range. Idempotent (`seed_attribute_tags` is safe to
  re-run) — mentioned here as a one-time prerequisite step, not a vote
  or catalog-state change.

### What remains open

1. **Bug-A full re-scan** of the 17,531-card blank-tier-1 pool, deferred
   to post-pilot per the owner ruling in §9(c) (recipe documented there
   and in §13, not re-derived here). Still the one tracked open item
   carried forward past the fire. Owner-ratified sequencing (2026-07-24):
   the remaining tail (issue #418) is Stage E streaming's shakedown
   cohort — it does not get a further batch pass; see
   [`docs/proposals/stage-e-streaming.md`](proposals/stage-e-streaming.md)
   §6.
2. **Moderation package sizing** is now **data-ready**: the review queue
   is a DB-verified, dedup'd **134,370** cards (`to-review` skips, see
   "Topline end-state" above) — sizing work for the moderation
   package can use this figure directly rather than re-deriving it.
