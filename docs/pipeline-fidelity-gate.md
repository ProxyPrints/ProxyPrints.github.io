# Pipeline-fidelity gate — canonical status page

**GitHub issue #154** (internally referenced elsewhere as "task #151" —
a pre-board internal task-ledger number, not a second GitHub issue; issue
#154's own title cross-references both). This is the **single page**
for this gate's status and its two open owner decisions. Every
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

| artifact                                         | status                                                                                                                                                                                                   |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Artifact 2 — knowledge-inventory sweep**       | **DONE** (2026-07-22), but **NOT clean** as originally worded — see §3 below. Full constant-by-constant table: [`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md). |
| **Artifact 1 — stratified-sample parity replay** | **PENDING**, queued behind extraction. Methodology corrected 2026-07-22 — see §4 below (the originally-scoped methodology was wrong and has been replaced, not merely clarified).                        |

**Gate verdict: NOT clean.** Full-catalog fire stays blocked until the
owner rules on the two open decisions in §3 and §4, and Artifact 1 is
run and comes back clean under the corrected methodology.

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
   machine-local) for that run's own narrative.

None of these three are soundness violations — the human-backed
consensus gate still applies to every vote Stage D casts regardless.
**Owner ruling needed**: are these three must-fix-before-fire, or an
accepted gap the gate can clear without them? Full detail, plus 3 lower
grade "open items" that are separate from these 3 MISSING findings:
[`reports/2026-07-22-knowledge-inventory.md`](reports/2026-07-22-knowledge-inventory.md).

## 4. Open decision (b) — the corrected parity-replay methodology

**Artifact 1 was originally scoped as a live stratified-sample re-run
against dpi=250, re-extracting evidence and comparing it to the pilot's
outputs.** That scoping is wrong and is replaced by this corrected
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
fails. **Do not invent or accept a numeric pass threshold anywhere in
this process** — "zero unexplained divergence" is the only documented
bar, and no percentage is a substitute for it, regardless of how high.
**Owner ruling needed**: sign off on this replacement methodology
(rather than the original re-extraction scoping) before Artifact 1 is
run.

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

This page owns the gate's **status** and the **two open decisions**
above; every fact below is the linked source, not duplicated here.

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
