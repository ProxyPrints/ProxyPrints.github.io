# How a card gets identified — the exact pipeline, post-#294

Plain-language companion to [`theory.md`](theory.md) — that file _proves_
the false-accept bound and soundness properties; this one _explains_ the
pipeline as the code actually runs it today, for a reader who wants the
walkthrough rather than the formal composition. See
[`theory.md`§7](theory.md#7-the-deduction-chain-as-an-explicit-composition)
for the stage-by-stage error-term treatment of the same chain, and
[`features/printing-tags.md`](features/printing-tags.md) /
[`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)
for the backend and frontend this pipeline feeds into. The Stage D chain
this file walks through is currently gated on the pipeline-fidelity gate
(GitHub issue #154) before it's cleared to fire at full-catalog scale —
see [`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) for that
gate's current status; this file describes the mechanics, not the gate.

**Reviewed and approved by the owner, 2026-07-21.** Written for the
pre-197k review.

## FIG-1 — Pipeline flow, where a card can stop

```mermaid
flowchart TD
    IN["Card named eligible<br/>card-create · evidence-change · cron backstop sweep"]

    IN --> G1{"streaming enabled?"}
    G1 -- "no" --> X1{{"OFF<br/>STAGE_E_STREAMING_ENABLED = False<br/>no work, no ledger row"}}
    G1 -- "yes" --> G2{"envelope trip already open?"}

    G2 -- "yes" --> X2{{"HALTED · OPEN TRIP<br/>every dispatch refuses<br/>no self-resume, ever"}}
    G2 -- "no" --> G3{"fresh signal sample<br/>breaches a bar?"}

    G3 -- "yes" --> X3{{"HALTED · NEW TRIP<br/>EnvelopeTrip row persisted<br/>all dispatch stops"}}
    G3 -- "no" --> SEL["Select micro-batch<br/>size 25, seed first, backlog fill"]

    SEL --> X4{{"ALREADY PROCESSED<br/>skipped by cursor-walk verification:<br/>evidence carries every manifest key"}}
    SEL --> G4{"anything eligible?"}
    G4 -- "no" --> X5{{"EMPTY SELECTION<br/>nothing left to do"}}
    G4 -- "yes" --> G5{"concurrency slot free?"}

    G5 -- "no" --> X6{{"THROTTLED · CAP<br/>all 2 slots held<br/>deferred to the next sweep<br/>NO ledger row is written"}}
    G5 -- "yes" --> LED["Open ledger row<br/>PilotRunLedger, status running"]

    LED --> SC["STAGE C · fetch image, extract OCR evidence<br/>one card at a time"]
    SC -- "fetch fails" --> X7{{"FETCH FAILURE<br/>card skipped, counted,<br/>fed to the rolling 500-card window"}}
    SC -- "crash" --> X8{{"FAILED DISPATCH<br/>ledger row marked failed<br/>with a triage-able reason"}}
    SC --> SD["STAGE D · join-key → fallback → slow-path<br/>casts machine votes at weight 0.5"]

    SD --> CONS["Weighted consensus over every vote on the card"]
    CONS --> G6{"weight ≥ 2<br/>AND share ≥ 0.6<br/>AND at least one human-backed vote"}

    G6 -- "no" --> X9{{"CONSENSUS FLOOR<br/>nearly every card parks here<br/>machine votes alone can never clear it"}}
    G6 -- "yes" --> RES(["RESOLVED PRINTING<br/>a human vote cleared it"])

    X9 --> WTC["WTC question feed<br/>serves ≥51% of questions from cards<br/>one more human vote would resolve"]
    WTC --> HV["Human vote cast, weight 1.0"]
    HV --> CONS

    classDef halt fill:#f7768e,stroke:#8c3d4e,stroke-width:2px,color:#1a1b26
    classDef defer fill:#e0af68,stroke:#8a6a3d,stroke-width:2px,color:#1a1b26
    classDef excl fill:#7dcfff,stroke:#3f7f9c,stroke-width:2px,color:#1a1b26
    classDef work fill:#24283b,stroke:#565f89,stroke-width:1px,color:#c0caf5
    classDef gate fill:#2f3549,stroke:#ff9e64,stroke-width:2px,color:#c0caf5
    classDef done fill:#9ece6a,stroke:#5c7c3d,stroke-width:2px,color:#1a1b26

    class X2,X3,X8,X9 halt
    class X6,X7 defer
    class X1,X4,X5 excl
    class IN,SEL,LED,SC,SD,CONS,WTC,HV work
    class G1,G2,G3,G4,G5,G6 gate
    class RES done
```

Shape carries the meaning first: a hexagon is an interception (the card
stops here); a diamond is a gate being evaluated; a plain rectangle is
work actually happening; a stadium is a terminal outcome. Colour then
grades _why_ a hexagon stopped — red is a **hard halt** (a human must
act), amber is a **soft defer** (the system retries by itself on its
own), blue is a **correct exclusion** (nothing is wrong, the card just
doesn't need this pass). Every `classDef` sets both `fill:` and `color:`
so the diagram reads correctly under either a light or a dark GitHub/wiki
theme.

**Reading it:** eight of the nine interceptions are cheap and local. The
ninth — CONSENSUS FLOOR — is where the overwhelming majority of the
catalog sits by volume, and it is the only one that is not a fault. It is
the soundness property: no volume of machine votes resolves a printing,
so the pipeline's throughput is bounded by human attention on purpose.
The loop back through the WTC question feed is the actual design claim —
machines narrow the candidate set, humans close it. **Deliberately no
absolute counts in this diagram** (owner ruling, 2026-07-25, same
"shape for now, numbers once traffic starts the confirmations" posture as
FIG-2 below) — see
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md), the single
source of truth for gate status, for how many cards are currently sitting
at each stage. Absolute counts return to this diagram once real user
confirmations start accumulating in volume.

## What exists before anything runs

- A **Card row**: name, source drive, and a content phash of the image.
- The **reference set**: every real printing of every card name (CanonicalCard /
  CanonicalExpansion, from Scryfall) — set code, collector number, denominator.
- **No pixels stored, ever.** Images are fetched transiently, read, discarded.

## Stage C — evidence extraction (`run_image_evidence_cohort`)

1. **Fetch** the image from its source drive (transient, throttled).
2. **Crop** fixed regions: the collector line, the legal-line band (bottom
   ~10% of the card), the set-symbol area; compute geometry/quality signals
   (border color class, bleed class, blur, entropy, truncation).
3. **OCR, tiered**: a fast first pass; preprocessing fallback tiers
   (contrast/upscale/alternate modes) fire only when useful. NEW (#294): if
   the first pass reads text with **no digit-bearing structure**, escalation is
   skipped entirely — measured 99.7% of such cards never yield a collector line
   at any tier (customs). A `short_circuited` counter logs every skip so the
   197k run itself validates this. Escape hatch: `--no-shortcircuit`. **Set-code
   lexicon gate on acceptance (2026-07-23, issue #370):** a tier's parse only
   terminates escalation if its set code is a REAL `CanonicalExpansion` code (or
   the pre-M15 collector-number-only case, no set code parsed at all) — a live
   structural finding (issue #370) traced 94% of a lexicon-invalid-no-match
   sample to the OLD "any parse" criterion accepting tier 1's own OCR noise
   before tiers 2/3 ever got a chance to run. A `collector_number`-bearing parse
   whose set code ISN'T a real one no longer stops the loop; it's kept as the
   running best invalid candidate (first such parse, by tier order) while
   escalation continues, and only becomes the stored outcome if no later tier
   ever produces a lexicon-valid parse — the exact value pre-gate code already
   stored for that case, so this only changes the PATH there, never the result.
   Governs acceptance during escalation, not whether escalation starts (the
   digit-free short-circuit above is unaffected). The live-pilot OCR engine
   (`local_identify_printing_tags.run_ocr_for_card`) applies the same lexicon
   check at its own "parsed-but-no-match" outcome: a lexicon-invalid parse
   there abstains (`unknown-set-code`, non-rescannable) instead of casting the
   confident `is_no_match` vote it used to.
4. **Parse**: set code + collector number from the collector line
   (slash-format-aware since #260); the legal band is scanned for proxy
   marking — `not for sale`, `proxy/proxies/proxied`, `playtest` variants
   (#280/#285) — setting `legal_line_proxy_marker_detected`.
5. **Persist one ImageEvidence row**: raw OCR text, parses, phashes, classes,
   the marker flag. Keyed (card, content hash) — computed once, overwritten
   only by explicit re-extraction. Signals only; nothing that can rebuild the
   image.

**Blur variance: human-rated, not automated.** `blur_variance` (Laplacian-kernel
edge-response variance) is computed and stored in ImageEvidence but drives no
automated threshold or pipeline decision. It stays as a signal for human raters
judging upload quality. Human votes are more reliable for image quality
assessment than any single automated metric, so no threshold calibration is
planned until real rater data justifies one.

## Stage D — the join-key calculator (`local_calculate_verdicts`)

Eligible cards: current evidence exists, no prior vote from this machine
identity, and (safety) nothing already resolved. Then five stages per card:

- **g1 — read the stored parse.** No re-OCR, no re-parse; Stage C's fields are
  the input.
- **g2 — candidate constraint.** Candidates are only the real printings **of
  this card's name**. The parsed (set, number) must match: exactly one
  candidate → match; none → _parsed-but-no-match_; no usable parse →
  _no-text_ skip; several → _ambiguous_. **Set-code lexicon gate (2026-07-23):**
  a `parsed-but-no-match` outcome only casts the confident no-match
  vote below when the parsed set code is a REAL `CanonicalExpansion` code —
  a live audit found 85.5% of this outcome's parsed set codes matched no
  real expansion at all (dominated by proxy/watermark text the collector-line
  crop also caught: "proxy", "mtg", "not", "card"), un-parsed noise, not
  validated evidence. A lexicon-invalid parse abstains instead (a named,
  non-rescannable skip, routed to the slow path below exactly like
  `no-text`) - no confidence/
  OCR-quality split was separable (checked directly: in-lexicon and
  out-of-lexicon parses have near-identical tesseract confidence
  distributions), so this is gated on lexicon membership alone; a
  genuinely-custom set code on a proxy of a non-existent printing is also
  abstained by this gate, a deliberate, documented tradeoff (see
  `local_calculate_verdicts.py`'s own module docstring for the full
  reasoning and numbers).
- **g3 — tie-break.** Ambiguity only: compare the set-symbol phash against
  each candidate's rendered symbol; accept only within distance threshold AND
  a margin over the runner-up; a near-tie stays unresolved. (Fired for 2 of
  20,677 cards — the tie-break is almost never needed.)
- **g4 — agreement checks.** Cross-checks that can only _narrow or withhold_,
  never manufacture a match: border-color contradiction → withhold;
  frame-style contradiction → withhold; copyright year predating the matched
  set by >2 years → withhold; artist-OCR disagreement → match proceeds at
  lowered confidence. **Proxy marking is identification-neutral** (#294):
  catalog-required on every genuine upload, so presence proves nothing about
  which printing this is. (Until the #294 re-scan it wrongly vetoed 1,552
  validated matches — the re-scan un-blocks them.)
- **g5 — the vote, never the verdict.** A match casts one machine
  CardPrintingTag vote: weight 0.5, with an ordinal confidence label
  (0.85/0.75/0.65 — a pipeline-state rank, _not_ a probability, and verified
  to have zero effect on resolution). Resolution requires total weight ≥ 2
  **including at least one human-backed vote** — structurally, the machine can
  never resolve a card alone (verified 0 machine-only resolutions across
  12,684 gate-checked cards, spanning both the printing- and tag-consensus
  engines — see `docs/reports/2026-07-21-recovery-arc.md`). Confident
  no-matches cast a no-match vote under the same rules. **Sharpened by the
  owner-ratified 2026-07-22 vote-weight scenario matrix** (implemented in
  PR #325; raw ruling at [`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md)):
  it's no longer just "a human vote must be present" — machine weight (and
  two other non-human-backed classes added the same day: a low-weight,
  hard-capped `IMPLICIT` vote cast passively when someone picks a
  candidate under an active `/editor` filter chip, and a `FEDERATED` vote
  imported from a peer instance) is now excluded **entirely** from who
  wins and from the share math the moment there's a genuine
  human-vs-human disagreement, or the moment a human-backed winner has
  already cleared the resolution bar on its own. Practically: machine
  agreement can still help a lone human's vote resolve a previously
  undecided card (that's still allowed and intended — it's the whole
  point of the deductive backfill below), but machine or implicit
  disagreement can no longer do either of the two things it used to be
  able to do — tip an actual human-vs-human tie, or quietly flip an
  already-human-resolved card back to unresolved by diluting its share.
  That second failure mode was real and reachable at the scale this
  catalog now runs at (any 2-human-vote printing with 3+ contradicting
  machine votes), and is what the ratification specifically closed.

**Everything unresolved routes to humans**: skips and no-matches go to the
slow path — durable review-queue markers carrying the raw signals — where the
clustering backend (#265) groups them into batchable decisions, and the
question feed collects the human votes that actually resolve cards.

## Parallel detectors (same evidence, never gate identification)

- **AI-art detector**: generator names in the OCR text → "AI-Generated" tag
  votes (ordinary consensus since #292). Detect-and-tag only.
- **"Marked as proxy"** (#291, planned): marker presence → tag; **absence** →
  moderation flag, batched by source (the counterfeit-risk framing).

## Why a bad identification is hard

Candidates are name-constrained (a wrong match must be a real printing _of the
same card name_ with a colliding set+number — the parse would have to be wrong
in a way that lands exactly on a sibling printing); the tie-break demands a
margin, not just a best score; every cross-check can only withhold; and no
machine vote resolves anything without a human. Measured so far: zero false
accepts observed at every gate that can be measured, with the error terms that
remain unmeasured named as such in
[`theory.md`§7](theory.md#7-the-deduction-chain-as-an-explicit-composition)
rather than assumed.

## Reversibility

Every machine action carries a run_id and identity: votes retract by
identity+card set, evidence re-extracts by run, review routings clear by
selector. Nothing the machine does is permanent against better information —
the only permanent records are what humans decide.
