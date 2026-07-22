# How a card gets identified — the exact pipeline, post-#294

Plain-language companion to [`theory.md`](theory.md) — that file _proves_
the false-accept bound and soundness properties; this one _explains_ the
pipeline as the code actually runs it today, for a reader who wants the
walkthrough rather than the formal composition. See
[`theory.md`§7](theory.md#7-the-deduction-chain-as-an-explicit-composition)
for the stage-by-stage error-term treatment of the same chain, and
[`features/printing-tags.md`](features/printing-tags.md) /
[`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)
for the backend and frontend this pipeline feeds into.

**Reviewed and approved by the owner, 2026-07-21.** Written for the
pre-197k review.

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
   197k run itself validates this. Escape hatch: `--no-shortcircuit`.
4. **Parse**: set code + collector number from the collector line
   (slash-format-aware since #260); the legal band is scanned for proxy
   marking — `not for sale`, `proxy/proxies/proxied`, `playtest` variants
   (#280/#285) — setting `legal_line_proxy_marker_detected`.
5. **Persist one ImageEvidence row**: raw OCR text, parses, phashes, classes,
   the marker flag. Keyed (card, content hash) — computed once, overwritten
   only by explicit re-extraction. Signals only; nothing that can rebuild the
   image.

## Stage D — the join-key calculator (`local_calculate_verdicts`)

Eligible cards: current evidence exists, no prior vote from this machine
identity, and (safety) nothing already resolved. Then five stages per card:

- **g1 — read the stored parse.** No re-OCR, no re-parse; Stage C's fields are
  the input.
- **g2 — candidate constraint.** Candidates are only the real printings **of
  this card's name**. The parsed (set, number) must match: exactly one
  candidate → match; none → _parsed-but-no-match_ (confident no-match);
  no usable parse → _no-text_ skip; several → _ambiguous_.
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
