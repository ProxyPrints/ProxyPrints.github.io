# Pipeline-fidelity gate — canonical status page

**GitHub issue #154** (internally referenced elsewhere as "task #151" —
a pre-board internal task-ledger number, not a second GitHub issue; issue
#154's own title cross-references both). This is the **single page**
for this gate's status and its open owner decisions. Every
underlying fact below is linked to its source, not copied — if a number
here disagrees with its linked source, this page is wrong and should be
fixed, not the source.

**Data as of 2026-07-22T18:01Z**, re-verified live against production
Postgres for this page (`sudo docker exec mpcautofill_django python manage.py shell`, read-only queries only). See "Chain" below for where
each number's provenance sits.

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
| **Artifact 2 — knowledge-inventory sweep**       | **DONE** (2026-07-22), but **NOT clean** as originally worded — see §3 below. Full constant-by-constant table: [`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md).                                                                                                                                                                                                  |
| **Artifact 1 — stratified-sample parity replay** | **DONE** (2026-07-22), outcome **owner-accepted**. 83.2% OCR-channel agreement (28,456-card reproducible-channel subset); 373/41,586 (0.9%) unexplained divergences, 0/373 a wrong-printing vote — all conservative abstentions. Not literally "zero unexplained divergence," but ruled to satisfy the gate's soundness intent. Full outcome, methodology, and the owner-acceptance ruling: see §4 below. |

**Gate verdict: NOT YET clean.** Full-catalog fire stays blocked on
Open decision (a)'s items 1–2 (`RESOLUTION_FLOOR_DPI`,
`EXCLUDED_RESOLVED_TAGS`) — item 3 (deductive-backfill exclusion) was
separately resolved 2026-07-22, ruled NOT restored (§3). Artifact 1
(§4) is now DONE and its outcome was owner-accepted 2026-07-22 as
satisfying the gate's soundness intent, even though the literal "zero
unexplained divergence" bar wasn't hit (373 remained, all conservative
abstentions; both root causes since fixed in code by merged PR #340 —
a gated re-extraction of the affected live cohort is still queued, see
§4).

## 3. Open decision (a) — the three MISSING constants

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
   for the in-code record of this decision.

None of these three are soundness violations — the human-backed
consensus gate still applies to every vote Stage D casts regardless.
**Owner ruling still needed on #1/#2** (item #3 above is now resolved —
deliberately not restored, per the ruling above): are the remaining two
must-fix-before-fire, or an accepted gap the gate can clear without them?
Full detail, plus 3 lower grade "open items" that are separate from these
3 MISSING findings:
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

The replay ran 2026-07-22 as a read-only, **full-cohort** (not sampled)
comparison against pilot run `20260716T193408-6613a1a6` (43,425 votes /
41,586 distinct cards, source=ocr): each card's pilot vote was compared
against what the current Stage D join-key calculator
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
question §3 answers (item 3 resolved 2026-07-22; items 1–2 still open).

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
out of scope for / not run by PR #340.

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

| run_id                         |    votes written | notes                                                                                                                                                                                                                                                     |
| ------------------------------ | ---------------: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `staged-dryrun-20260721T0423Z` |                0 | dry-run                                                                                                                                                                                                                                                   |
| `staged-write-20260721T0434Z`  | **8,825** (live) | `PilotRunLedger.votes_written` records 8,925 — this is the pre-retraction figure; #258's retraction brought the live count to 8,825 (already documented in [`reports/2026-07-21-recovery-arc.md`](reports/2026-07-21-recovery-arc.md), not a new finding) |
| `staged2-0721`                 |               70 |                                                                                                                                                                                                                                                           |
| `staged3-0721`                 |            3,010 |                                                                                                                                                                                                                                                           |
| `staged4-0721`                 |              999 |                                                                                                                                                                                                                                                           |
| `interim-peek-0722`            |                0 | dry-run                                                                                                                                                                                                                                                   |

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
for the canary/20k narrative detail.

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

**`consensus_impact_report` dry-run** (today, `--sample-limit 20`, zero
writes): printing 92,368 pairs checked / 0 transitions; artist 7,130
pairs / 0 transitions; tag 61,328 pairs, with 49,207 `None→UNRESOLVED`
materializations still pending a separately owner-gated recompute pass.
"Zero transitions" on printing/artist means the ratified resolver's
answer already matches every currently-persisted status exactly.

## 7. Chain — where each underlying fact actually lives

This page owns the gate's **status** and its **open decisions** above;
every fact below is the linked source, not duplicated here.

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
  (open) — §3 item 3's non-restoration rationale and code removal.
