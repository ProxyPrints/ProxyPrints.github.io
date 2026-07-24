# Theory note: the printing-identification pipeline as candidate-constrained decoding

**STATUS: Reviewed and approved by the owner, 2026-07-17.** Written per
the catalog-completion plan's Part 6, gated on the full-catalog run's
final report existing. Written for an external reader — this also
doubles as the technical annex for a future federation pitch (see
`docs/federation-v1.md`), so it avoids repo-internal jargon where a
general term exists. For a plain-language walkthrough of the same
pipeline without the formal decoding model, see
[`identification-pipeline.md`](identification-pipeline.md). For the
pipeline-fidelity gate (GitHub issue #154, internally task #151) that
governs whether §7's Stage D chain is cleared to fire at full-catalog
scale, see the canonical status page,
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) — this file
keeps the formal method and the pilot's own measured numbers, the gate's
status/decisions live only on that page.

## 1. The model: decoding over a closed codebook

A community member uploads an image under a self-reported card name `n`
(the Google Drive filename, loosely parsed). The catalog already knows,
for almost every name, the finite set of legal printings that name could
be — `C(n)`, the candidate set, drawn from a canonical card database
(Scryfall via this fork's own `CanonicalCard`/`CanonicalPrintingMetadata`
tables). This is the load-bearing structural fact the whole design
leans on: **the search space per card is not open-world.** We are never
asking "what card is this, out of everything that could exist" — we are
asking "which member of this already-known, usually-small set does this
evidence point to." That reframing is what turns an otherwise-intractable
visual/text recognition problem into something closer to classical
**channel decoding**: a codebook of known codewords (printings), a noisy
channel (the scan/photo and its filename), and a decoding rule that
either outputs one codeword or abstains.

A note on scope, before the channels: this section formalizes the
**original pilot architecture** — three independent channels (OCR,
phash, fallback), each modeled separately below. The **production**
deduction chain, formalized in §7, is a narrower composition of the
same primitives into a single join-key calculator; the closed-codebook
model and the decode-or-abstain rule are common to both.

Three independent noisy channels feed the decoder, each modeled
separately rather than fused into one score:

- **OCR** reads the collector-number line (set code + collector number)
  printed on the card itself, off the SAME image the uploader supplied —
  a noisy string channel. Failure modes are illegible text (glyph noise),
  parser bugs (see the autopsy below — two real ones found and fixed),
  and a genuinely unrecoverable source in a small minority of cases.
- **phash** (`imagehash.phash`, 64-bit, `hash_size=8`) treats the image
  itself as a noisy 64-bit channel against every candidate's own
  reference image, decoded via nearest-Hamming-distance with a
  disagreement/no-clear-winner abstention rule rather than a forced
  pick.
- **fallback** (attribute-elimination) is a categorical channel:
  border color, frame style, and other observable attributes narrow the
  candidate set by elimination when name+OCR+phash alone don't converge
  on exactly one.

The decoding rule across all three is the same shape: **accept iff
exactly one candidate survives within the evidence ball; abstain
otherwise.** Nothing here ever forces a decision under ambiguity — every
engine's skip-reason vocabulary (`no-clear-winner`,
`too-many-candidates`, `parsed-but-no-match`, `ambiguous`, `no-evidence`,
…) exists specifically to make "the evidence didn't uniquely decode"
distinguishable from "the evidence decoded to X," both in the code path
and, since 2026-07-16, in a persisted `CardScanLog` row — abstention is a
first-class, durable outcome, not a silently-dropped case.

## 2. False-accept bound, calibrated from real data

Any decoder like this can fail in exactly one dangerous direction: it
converges on a candidate that's _wrong_, not just abstains. §2a and §2c
below are direct, measured evidence bounding how often that actually
happens in this system, from smallest to largest scale. §2b is a
different but related property — that the pipeline's abstentions are
themselves genuine (the engine isn't quietly discarding evidence it
could have used), not a false-accept measurement in its own right.

**a. The 300+300 harvested-pair validation** (`docs/features/printing-tags.md`,
"Validation against real production data") — 300 real pairs of distinct
`Card` rows the live run's own engines voted for the _same_ printing,
plus 300 pairs voted for _different_ printings (the false-merge check),
harvested via a read-only query against the live production DB. The
same-printing pairs were further partitioned by an independent ground
truth (full-resolution phash distance, which is a stricter, orthogonal
check than "voted the same"): 79 were true duplicate uploads (100%
correctly landed within the clustering distance threshold, zero false
splits); 162 were different photos of the genuinely same printing
(correctly did not cluster as "same upload" in the large majority —
11.7% coincidentally landed within threshold anyway, but since the
underlying printing really is the same, this degrades precision of a
_secondary_ clustering heuristic, not correctness of the printing vote
itself). Of the different-printing pairs, 269 were analyzed: **zero**
landed within the clustering threshold — minimum observed distance 6,
clear of the cutoff.

_(Note for review, checked against source data before writing this,
not inferred: the doc's own 79+162 partition accounts for 241 of the
300 same-printing pairs (59 unaccounted), and its 269 accounts for the
300 different-printing pairs (31 unaccounted) — the same shortfall
pattern in both categories, which is itself a clue (a shared filtering
step — e.g. a pair where one card lacked a computable full-resolution
hash — dropped some fraction of both harvests before analysis), but
neither `docs/features/printing-tags.md` nor the same-day journal entry
(`journal/2026-07-16-hash-at-ingest.md`) states what that step was or
which pairs it dropped. Checked both sources directly rather than
guessing. The false-accept-bound conclusions above are calibrated only
on the accounted-for cases (241 and 269 respectively), consistent with
that — but the reconciliation itself is still open and belongs on the
owner's desk, not resolved by assumption here.)_

**b. The no-match autopsy verifies abstentions are genuine, not a
false-accept measurement** (`docs/features/printing-tags.md`, "No-match
autopsy") — this sample is conditioned on abstention by construction:
all 176 cases are ones where OCR already declined to answer, so by
definition none of them can be a false accept (the engine confidently
converging on the wrong candidate) — that failure mode can only show up
in a sample of cases where the engine _did_ commit to an answer, which
is what §2a and §2c measure. What this sample verifies instead: that
the abstentions were the right call, not evidence quietly discarded.
The full partition of the 176 real OCR `parsed-but-no-match` cases:
47/176 (26.7%) were parser-bug-recoverable — two real, since-fixed
parsing bugs (see the autopsy's build history), the fix behind the
pilot's 25.7%→41.3% projected OCR yield improvement. Of the remaining
129, 2/176 (1.1% of the full 176) were genuinely-missing printings (no
`CanonicalCard` row exists at all for the parsed set+number), and
127/176 (72.2%) were true unsalvageable OCR garbage with no recoverable
signal. The pipeline's actual false-accept evidence is §2a's 269
different-printing pairs (zero within the clustering threshold, minimum
observed distance 6) and §2c's structural gate below.

**c. The full-catalog run's own gate**, at the scale that matters most:
**every one of the 43,425 machine votes cast (165,980 candidates
processed, 26.2% invocation hit rate) was verified, after the fact,
against `verify_zero_resolutions` — 0/43,425 affected cards were ever
resolved by machine evidence alone.** (Corrected 2026-07-22 from a
previously-stated 43,426 — an off-by-one against the live
`CardPrintingTag` count for this `run_id`, unreconciled to any
documented retraction; see
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) for the full
candidates-scanned/votes-cast/distinct-cards-voted breakdown, which are
three different numbers, not one flattened figure.) This is not a
sampled estimate; it is the literal count. It's a soundness property,
not an accuracy one (see §4) — but it means that even in the
counterfactual worst case where every one of those 43,425 votes were
wrong, **not one of them was ever
capable of independently producing an incorrect resolution**, by
construction, at this observed scale.

Per-engine breakdown, this run (`run_id=20260716T193408-6613a1a6`):

| engine   | votes written | dominant abstention reason                                  |
| -------- | ------------: | ----------------------------------------------------------- |
| OCR      |        28,461 | `no-text` (72,682), `parsed-but-no-match` (47,787)          |
| phash    |         6,218 | `no-clear-winner` (116,912), `too-many-candidates` (39,278) |
| fallback |         8,747 | `ambiguous` (90,278), `no-evidence` (23,431)                |

Plus attribute channels, run cumulatively across all 165,980 candidates:
border votes `{borderless: 51,503, black: 106,212, white: 7,136, silver: 398}` (ground truth override applied to 41,516 of these); frame votes
`{modern: 88,680, old: 8,370}` (ground truth: 41,515), with 68,912 frame
abstentions and 6,379 **frame mismatches** — cases where OCR/phash
converged on a printing but the observed frame style contradicted the
matched candidate's known frame, so the _printing_ vote itself is
withheld rather than trusted past a contradiction (this is Part 3's
dual-yield recovery source: the withheld printing vote still carries a
correctly-matched `CanonicalCard`, salvageable for an artist vote even
though the printing claim itself is discarded). Bleed votes `{bleed: 163,685, trimmed: 2,259}`, 18 abstentions.

## 3. Comparison to prior art

**Fellegi-Sunter record linkage** (the classical statistical framework
for "are these two records the same real-world entity") frames a match
decision as a likelihood-ratio test: compare the probability of the
observed agreement pattern under "same entity" vs. "different entity,"
accept if the ratio clears a threshold calibrated against known
false-positive/false-negative costs. This pipeline's decode-or-abstain
rule is a **special case** of that same shape, with two structural
simplifications that make it both easier to reason about and less
general: (1) the "different entity" class isn't diffuse — it's the
finite, enumerable rest of `C(n)`, so the likelihood ratio collapses to
"is there exactly one candidate whose evidence beats every other
candidate's, by a margin," not a continuous probability estimate over an
open population; (2) each channel runs independently rather than being
fused into one joint score — closer to an ensemble of independent
decoders than a single Fellegi-Sunter linkage score. This is not an
exclusive-or between the channels: multiple engines converging on the
same candidate is redundant confirmation, not a conflict to arbitrate,
and when engines genuinely contradict each other (the frame-mismatch
case above) the response is to withhold the vote, not to force a pick
between them.

**tmikonen's population-relative threshold** (`docs/features/printing-tags.md`,
"Prior-art read") is the closer visual-hashing precedent: rather than a
fixed Hamming-distance cutoff, accept the best-match candidate only if
its distance is >4 standard deviations below the mean distance to every
_other_ candidate for that query — a per-query statistical outlier test,
not a global threshold. This pipeline's own two-threshold clustering
(d=0 exact-match entailment, 0<d<=2 narrowing-only prior) is a **fixed,
not population-relative** cutoff, chosen instead through direct
calibration against the harvested 300+300 ground-truth pairs above
(§2a) rather than a per-query statistical model. tmikonen's approach is
more principled where hash population size and structure vary
meaningfully per query; this pipeline's fixed thresholds are simpler and
were judged sufficient once validated directly against real production
outcomes rather than requiring a per-query background distribution to be
computed. Both are, structurally, likelihood-ratio-test approximations
under a closed or effectively-closed candidate set — the shared idea
neither project invented independently of the other, but both converged
on: **validate a distance decision against the actual population's own
distance distribution, don't pick a cutoff in isolation.**

## 4. Soundness mechanisms

Two structural properties keep this decoder safe to run unattended at
catalog scale, independent of how accurate any single engine's evidence
turns out to be:

1. **The two-threshold split** (d=0 propagates a vote as sound
   entailment — literally the same uploaded image, transitively true;
   0<d<=2 only narrows the _candidate set_ for a fresh independent
   compute, never auto-votes on its own). This bounds the blast radius
   of a hash-collision-driven error to "one wasted compute," never "one
   silently-wrong vote."
2. **The human-backed gate, sharpened by the owner-ratified 2026-07-22
   vote-weight scenario matrix** (`vote_consensus.resolve_weighted_consensus`,
   `is_human_backed_source`, implemented in PR #325; the ratification
   artifact itself is [`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md)):
   machine-sourced votes (`VoteSource.OCR`, `VoteSource.DEDUCTION`, weight
   0.5 by default) can never _alone_ clear the resolution threshold
   (`PRINTING_TAG_MIN_VOTES=2`) — at least one human vote (weight 1.0) or
   admin vote (weight 5.0) must be present in the winning tally for a card
   to actually resolve. The ratification replaces a plain boolean-presence
   check with a stronger invariant: **machine and implicit weight are
   excluded from both winner selection and the quorum/share gate whenever
   any outcome group already holds human-backed weight `>= min_weight`, or
   a live human-vs-human contest exists** (two or more groups each
   carrying some human-backed weight) — the matrix's [no-machine-tipping
   and machine-dissent-never-de-resolves
   mechanisms](features/printing-tags.md#human-contest-machine-weight-drop).
   Concretely: machine/implicit agreement may still _reinforce_ an
   already-human-backed side (a lone human vote plus agreeing machine
   weight can still promote a previously-unresolved card — the matrix's
   promotion-stays ruling, unaffected by the two mechanisms above), but
   machine or implicit dissent can neither tip a genuine
   human-vs-human contest (the [no-machine-tipping
   mechanism](features/printing-tags.md#human-contest-machine-weight-drop))
   nor drag an already-quorum-valid human
   winner's share back below `min_share` to silently de-resolve it (the
   [machine-dissent-never-de-resolves
   mechanism](features/printing-tags.md#machine-dissent-never-de-resolves) —
   at 28k+ deduction-vote scale, this used to be reachable on any
   thin-margin 2-human-vote card before the ratification). A new passive
   evidence class, `VoteSource.IMPLICIT` (weight 0.25, `PRINTING_TAG_IMPLICIT_WEIGHT`,
   cast when a person picks a candidate card while an `/editor` filter chip
   is active), is symmetric to machine weight under this gate: never
   human-backed, and its summed weight per (card, tag) outcome group is
   additionally hard-capped at `PRINTING_TAG_IMPLICIT_CAP=1.0`, strictly
   below `min_weight` — a pile of implicit votes cannot form quorum on its
   own even before the human-backed check applies. Implicit weight is
   also excluded entirely from the questionFeed's suggestedness/confidence-fill
   computation (`get_tag_net_polarity`, the matrix's
   [suggestedness-excludes-implicit
   mechanism](features/printing-tags.md#suggestedness-excludes-implicit)) — a passive
   selection by-product must never color a chip's fill or let a person's
   own earlier pick "explain itself" back to them, which would otherwise
   be a self-seeding loop (evidence created by the UI reinforcing the same
   UI's own suggestion of itself). `VoteSource.FEDERATED` (weight 1.0,
   `VOTE_FEDERATED_WEIGHT`, pinned at 1.0 per the matrix's own FEDERATED-weight ruling —
   see [`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md))
   sits in the same
   non-human-backed bucket as machine/implicit weight for gate purposes —
   despite carrying full USER-equivalent weight toward quorum and share,
   an imported federated verdict is a **suggestion**, never itself
   sufficient to clear `g₅`, and is subject to the same exclusion as
   machine/implicit weight the moment a human-backed contest or
   already-quorum-valid human winner is in play. Machine evidence narrows
   and prioritizes what a human is asked to confirm; it never substitutes
   for that confirmation, and — as of this ratification — never dilutes
   or overturns one either. This is the property §2c's 0/43,425 result is
   actually verifying — not "43,425 correct decisions," but "43,425
   decisions that were structurally incapable of resolving anything on
   their own."

Together these mean the system's worst-case failure mode, even under a
badly miscalibrated engine, is a wasted human review cycle (a bad
suggestion surfaced for confirmation) — never a silent wrong answer
committed to the catalog, and, since 2026-07-22, never a silently
_reverted_ right answer either: passive/machine/federated evidence can
now neither form nor overturn a human-backed quorum on its own.

A further, narrower tightening landed 2026-07-23 and only concerns one
specific historical cohort: the 28,112 `CardPrintingTag` votes cast by
the 2026-07-14 deductive-name-backfill run (`source="deduction"`,
`anonymous_id="deductive-backfill-v1"` — pure logical inference from
already-trusted catalog metadata, zero image inspection; see
`cardpicker.deductive_backfill`'s own module docstring). A live audit
of that cohort at ratification time found 60% of the 28,112 were
already redundant with an agreeing image-derived (OCR/phash/fallback)
vote on the same card, 17% were opposed by an explicit human no-match
vote, 66 were directly contradicted by a later human vote for a
different printing, and only 459 were unopposed yet unverifiable
against any independent evidence. The deduction premise itself also
decays with time, independent of any per-vote error: 56 of the 66
contradicted votes are explained by the printing registry having grown
since the 2026-07-14 backfill — a name that matched exactly one
`CanonicalCard` then can match several now, so a vote sound at cast
time can become wrong later purely because the catalog around it
changed, not because the original inference was flawed. Given that
mix, the owner ruled these
votes now carry zero weight in every consensus computation — winner
selection, the quorum/share gate math above, and every downstream
suggestion or prioritization scalar built on vote weight — permanently,
regardless of how any future recompute or code change might otherwise
treat `VoteSource.DEDUCTION`. The rows themselves are never deleted or
hidden: they remain visible in raw vote tallies and every display
surface (e.g. the `/whatsthat` per-outcome tally, the questionFeed
tier-1 "confirm suggestion" surface, and `Card.suggestedCanonicalCard`)
exactly as before — only their contribution to the resolution math is
removed. This is a strictly tightening change to the pipeline's
soundness posture, not a new mechanism: resolution now rests on
image-derived machine evidence (OCR/phash/fallback) plus human votes
only, with the one cohort of purely name-derived machine votes reduced
to a historical record that a human reviewer can still see and act on,
but that can no longer itself move, reinforce, or protect a resolved
outcome. See `cardpicker.vote_consensus.DEDUCTIVE_BACKFILL_ANONYMOUS_ID`
and `resolve_vote_weight`'s own docstrings for the exact mechanism, and
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md)'s §3 item 3 for
how this relates to (and is distinct from) the separate, already-settled
question of whether Stage D re-votes a card this same backfill cohort
already touched.

## 5. Honest novelty statement

Nothing in this pipeline is individually new: OCR, perceptual hashing,
categorical elimination, weighted multi-source voting, and human-gated
consensus are all standard, well-understood components, most already
well precedented in Fellegi-Sunter-style record linkage and in
crowdsourced-consensus systems generally. The composition is the
contribution: three independent noisy channels over a **closed,
per-record candidate set** (not an open-world search), each with an
explicit abstention path rather than a forced decision, feeding into a
consensus layer with a **structural** (not just statistical) guarantee
that machine evidence alone can never resolve anything. (In production
these same primitives are composed into the single join-key calculator
of §7 rather than run as three parallel channels; the contribution is
the composition and its structural guarantee, not the particular
channel arrangement.)

The transferable pattern is: **user-submitted media identified against a
canonical registry, using multiple independent weak-evidence channels,
gated by a human-backed consensus threshold that machine evidence
structurally cannot clear alone.** This generalizes wherever (a) a
closed or near-closed reference catalog exists, (b) user submissions are
noisy and self-labeled, and (c) wrong silent resolutions are more costly
than a slower, human-reviewed one. Candidate domains beyond MTG proxy
cards:

- **Stamp/coin/trading-card cataloging generally** — any collectibles
  community where a canonical catalog (Scott numbers, a mint registry, a
  set list) already exists and users upload photos of physical items
  against it.
- **Music/media fingerprinting against a known catalog** (e.g. matching
  a user-uploaded clip against a licensed catalog, not an open "what
  song is this" search) — the same closed-candidate-set structure, audio
  hash as the noisy channel in place of phash.
- **Museum/archive digitization triage** — volunteers photograph items
  from a collection with a known accession catalog; OCR of labels/plates
  plus visual matching against catalog records, human-gated before
  updating the authoritative record.

## 6. Sybil/bad-actor unification (future work — nothing built)

**Readiness re-checked 2026-07-18: still not ready.** Total vote rows
now exceed 155,000, but that's almost entirely machine throughput from
this pipeline's own trusted engines (`ocr`/`deduction`); real human
participation is 4 distinct voters (largest single contribution: 22
votes). The trigger below needs human-population volume or an observed
attack, neither of which this represents — see
`docs/reports/2026-07-18-dawid-skene-readiness-recheck.md` for the full
numbers and reasoning. One exception: the cluster-consistency detector
(third bullet below) isn't actually gated by human volume and could be
built independently.

Added as an addendum, not a build item: the identification machinery
above already treats every vote — human or machine — as **noisy
evidence to be weighed, never ground truth to be trusted outright**. That
framing is directly reusable as an integrity layer against bad actors,
because the same abstract question ("how much should I trust this
evidence source") applies whether the noise is honest OCR error or
deliberate manipulation. Nothing below is built; these are
report-only detectors, explicitly never automatic enforcement, until
there's an observed real attack or meaningful resolution volume to
justify it:

- **Machine evidence as an independent witness**: a per-`anonymous_id`
  disagreement-rate detector against _validated_ machine evidence (the
  same evidence this doc calibrates against in §2), surfacing a
  human voter whose submissions systematically contradict
  high-confidence machine signal — without touching the resolution path
  itself, purely a report.
- **Cluster consistency as a free contradiction detector**: `d=0`
  cluster members (by definition, the same uploaded image) that somehow
  resolve to _different_ printings are an internal contradiction with
  zero new machinery required — just a report over
  `local_clustering`'s existing output.
- **Cohort revocation generalizes beyond `run_id`**: Part 1's
  `purge_machine_votes` pattern (delete a cohort's votes, re-resolve
  every affected card via the persisting resolvers, assert no
  card is left resolved on machine-only survivors) scopes today by
  `run_id`. The identical mechanism and the identical post-purge
  invariant apply to a suspect _human_ cohort scoped by a
  `created_at`/`anonymous_id` window instead — same code shape, a
  different scoping dimension, not a new subsystem.
- **Trust tiers, if ever needed, are one more vote-tuple dimension**
  (`is_established`) alongside source and confidence in the existing
  weighted-vote model — not a parallel trust system bolted on
  separately.

### Relation to Dawid-Skene reliability estimation

The voter-as-noisy-channel framing this whole pipeline already uses —
treat every source (human or machine) as having some unknown, per-source
reliability, and estimate the _true_ label jointly with each source's
reliability, rather than trusting any single source's raw output — is
exactly the **Dawid-Skene** model from crowdsourced-label aggregation.
This pipeline currently uses _fixed_, hand-set per-source weights
(`PRINTING_TAG_AI_WEIGHT` (a legacy name — it weights machine-derived
sources: OCR and deduction; no generative AI is involved) `=0.5` — now
`PRINTING_TAG_MACHINE_WEIGHT` in settings.py, with the old name kept as a
backward-compatible env-var fallback so an existing deployment's config
can't silently break — human `1.0`, admin `5.0`,
`VOTE_FEDERATED_WEIGHT=1.0` — non-human-backed (the matrix's own
FEDERATED-weight ruling, [`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md)),
despite matching a
human vote's raw weight — and, added by the 2026-07-22 vote-weight
ratification, implicit `0.25` (`PRINTING_TAG_IMPLICIT_WEIGHT`, summed and
capped per (card, tag) at `PRINTING_TAG_IMPLICIT_CAP=1.0`, also
non-human-backed) rather than weights estimated from the data
itself — a simplification, not an oversight, appropriate while per-source
volume is still low enough that a hand-set prior is more stable than a
data-estimated one would be. The Dawid-Skene connection is the basis for
a shared framework covering three distinct noise sources this system
already has to reason about separately today — **OCR/phash channel
noise** (§1-2), **honest human error** (why the resolution threshold
requires >1 vote, not blind trust in the first human), and **deliberate
manipulation** (this section) — under one estimation model instead of
three ad hoc ones. It is also the natural basis for federation's own
per-peer reliability measurement against shared `content_hash`es (see
`docs/federation-v1.md`): a federation peer is, in this framing, just
another noisy source whose reliability can be estimated the same way a
human or machine voter's can, rather than needing a bespoke trust
protocol.

## 7. The deduction chain as an explicit composition

§§1–2 give the model and its measured false-accept bound at the level
of "the decoder as a whole." This section writes the decoder out as an
explicit composition of stages, each a function with its own error
term, so a federation peer (or a reviewer) can see exactly where the
bound comes from and, crucially, which factors are **measured** versus
which are only **a-priori-bounded** or frankly **unmeasured**. The
chain formalized here is the one the code actually runs today: Stage
D's join-key calculator (`cardpicker/local_calculate_verdicts.py`),
not the older three-independent-channel live pilot §1 describes.

**A note on which pipeline this is, stated plainly rather than
smoothed over.** §1's "three independent noisy channels (OCR, phash,
fallback), each modeled separately" describes the live-pilot engines
(`local_identify_printing_tags.py`) that produced §2c's
`run_id=20260716T193408-6613a1a6` numbers. The current deduction chain
is architecturally narrower and is a **single composed calculator**,
not three parallel decoders: collector-line OCR **and** set-symbol
phash are treated as **one near-unique join key** into Scryfall data
(`calculate_join_key_verdict`), followed by an agreement/veto layer,
followed by human-review routing for everything that doesn't uniquely
decode. Full-image phash as an independent matching channel is **not**
part of this chain — Stage D's symbol phash is used **only** as a
tie-break inside the ambiguous branch (below), and general
image-phash matching was deferred to user-submitted phash (issue #203,
not built). So §1's phash-channel description is the live pilot's, not
this composition's; the two share the closed-codebook framing and the
decode-or-abstain rule, but not the channel structure. The soundness
property (§2c/§4) is identical across both, and is re-verified on this
chain below.

### 7a. The stages, as functions with error terms

For a card uploaded under name `n` with (unknown) true printing
`p* ∈ C(n)`, the chain is a composition `g = g₅ ∘ g₄ ∘ g₃ ∘ g₂ ∘ g₁`
whose output is one of: a printing `p̂`, a genuine `no_match`, or an
abstention (a named skip). A **false accept** is the event
`p̂ ∉ {p*, no_match, abstain}` — the decoder commits to a _wrong_
printing.

- **`g₁` — join-key parse.** Reconstructs an `OcrParseResult` from the
  already-persisted `collector_line_set_code`/`collector_line_collector_number`
  fields (produced in Stage C by `local_ocr.parse_collector_line`; Stage
  D builds the `OcrParseResult` from the persisted values — no re-OCR
  and no re-parse). Output: a token `t = (ŝ, ĉ)` or `∅`. Error term
  `ε₁ = P(t is a confusable misread — syntactically valid, but not the true (s*, c*))`. **Unmeasured** as a rate; structurally bounded
  because `t` must clear the parser's own shape constraints (`_SET_CODE_RE`
  = 3–5 alnum, `_COLLECTOR_NUMBER_RE` = 1–4 digits + optional letter)
  and the number is normalized (`_normalize_collector_number`) before
  any comparison.
- **`g₂` — candidate constraint.** `validate_against_candidates(t, C(n))`
  accepts iff `t` matches **exactly one** candidate in the card's own
  name-scoped set `C(n)`; otherwise it returns `parsed-but-no-match`,
  `ambiguous`, or `no-text`. This is the load-bearing stage: a false
  accept here requires `t` to coincide **not merely with a wrong token
  but with another _valid_ candidate `p' ∈ C(n), p' ≠ p*`** — the
  misread must land inside the same name's own small candidate set.
  Error term `ε₂ = P(a misread token equals some p' ∈ C(n)\{p*})`,
  bounded above by `|C(n)|` (usually small) and by the per-`CanonicalCard`
  uniqueness of `(expansion, collector_number)`. **Partially
  measured**: the rate at which the constraint even _admits_ more than
  one candidate (the `ambiguous` escape — collector-number-only match
  across sets) is **2 / 20,677 ≈ 9.7×10⁻⁵** of considered cards on the
  2026-07-21 run (`staged-write-20260721T0434Z`,
  `docs/reports/2026-07-21-staged-write.md`). That is a direct
  measurement of how rarely the closed-set constraint fails to isolate
  a single candidate on its own.
- **`g₃` — symbol-phash tie-break (conditional).** Runs **only** on
  the `ambiguous` branch (`_symbol_phash_tiebreak`): the card's stored
  `symbol_phash` is compared by Hamming distance against each ambiguous
  candidate's rendered keyrune set-symbol glyph
  (`local_fallback.render_set_symbol`), accepting the nearest **iff**
  it clears `SYMBOL_DISTANCE_THRESHOLD` **and** beats its runner-up by
  `SYMBOL_MARGIN`; a tie abstains (`None`). Error term
  `ε₃ = P(the true card's symbol phash lands within threshold-and-margin of a *wrong* expansion's glyph)`. **Unmeasured** directly. The
  nearest empirical evidence is §2a's orthogonal result — 269
  different-printing pairs, minimum observed **full-image**-phash
  distance 6 — but note that is full-image phash, not the set-symbol
  phash `g₃` uses, so it is suggestive of clean hash-space separation,
  not a measurement of this stage.
- **`g₄` — agreement/veto layer.** Applied to **every** would-be match
  (`_apply_agreement_checks`), whether from `g₂` directly or via `g₃`.
  A sequence of orthogonal cross-checks, each of which can only
  **withhold** a match (convert accept → skip), never manufacture one:
  truncated-image veto, border agreement (`layout_class` vs.
  `CanonicalPrintingMetadata.border_color`), frame agreement
  (`classify_frame_style` vs. `.frame`), copyright-year era check
  (parsed `©` year predating the printing's `released_at` by more than
  `COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS = 2` withholds), and
  artist-OCR corroboration (a disagreement _weakens confidence_ rather
  than vetoing). `legal_line_proxy_marker_detected` is READ here but no
  longer withholds or weakens anything as of a 2026-07-21 owner-ruled
  correction (the marker is catalog-required on every genuine upload,
  proxies of real printings included, so its presence carries no
  discriminating power over any specific match) — through that date it
  was a sixth veto in this list. Error term `ε₄ = ∏ᵢ P(veto i passes | the match is actually wrong)` — a wrong match survives only if **all** vetoes
  clear it. **Firing rates are measured, catch-precision is not**: on
  the 2026-07-21 run PREDATING that correction, the vetoes fired at
  `proxy-marker-veto` 1,533, `border-mismatch` 507, `frame-mismatch` 35
  (and copyright-year / truncation folded into the same skip
  vocabulary) — `proxy-marker-veto` firings are no longer part of `ε₄`
  going forward. What is **not** measured is what fraction of each
  firing was a _true_ wrong-match caught versus a correctly-matched
  card whose observed frame/border was merely noisy — that split needs
  labeled ground truth (§9). So these counts bound how _often_ `g₄`
  intervenes, not how _accurately_.
- **`g₅` — human-backed consensus gate.** The match becomes a
  `CardPrintingTag` at `VoteSource.OCR` weight
  (`PRINTING_TAG_MACHINE_WEIGHT`, 0.5) and is reconciled by
  `vote_consensus.resolve_weighted_consensus`, which resolves a card
  **iff** the winning group clears `min_weight`, clears `min_share`,
  **and** contains at least one human-backed vote. A machine vote at
  0.5 cannot satisfy the third condition alone. Per the 2026-07-22
  vote-weight ratification (§4 item 2), this is no longer only a
  form-the-quorum-alone guarantee: machine weight (and the passive
  `VoteSource.IMPLICIT`/weight-0.25/cap-1.0 class, and non-human-backed
  `VoteSource.FEDERATED`/weight-1.0) is additionally excluded from the
  gate's winner-selection and share arithmetic entirely once a
  human-backed contest or an already-quorum-valid human winner is in
  play (the [no-machine-tipping and machine-dissent-never-de-resolves
  mechanisms](features/printing-tags.md#human-contest-machine-weight-drop))
  — so a machine wrong-match can neither win a live
  human-vs-human disagreement nor de-resolve a human-backed card that
  already cleared this gate. `P(card resolved to catalog | machine wrong-match) = 0` **structurally**, independent of
  `ε₁…ε₄`, and — as of the ratification — so is
  `P(a human-backed-resolved card is de-resolved by machine wrong-match | already resolved)`.

### 7b. The composed false-accept expression, honestly separated

Two different quantities matter, and conflating them is the usual way
a bound like this gets oversold:

**Suggestion-level false accept** (a wrong printing _surfaced_ to a
reviewer, before any human confirmation):

    P(false-accept suggestion per card) ≤ ε₁ · ε₂ · ε₃* · ε₄

where `ε₃*` = `ε₃` on the ambiguous branch and `1` otherwise (a
non-ambiguous match never invokes `g₃`). This is an **upper bound of a
product of mostly-unmeasured conditional terms**. What is anchored
empirically about it: `ε₂`'s admits-more-than-one rate (2/20,677) and
`g₄`'s firing counts above. What is **not** anchored: `ε₁`, `ε₃`, and
each veto's conditional catch-precision inside `ε₄`. We therefore do
**not** claim a numeric value for this product — only that it
factors by the chain rule into a sequence of conditional terms, each
≤ 1 (each stage can only narrow or withhold, never manufacture a
match), over a closed candidate set, and that the two factors we _can_
see are small.

**Resolution-level false accept** (a wrong printing actually committed
to the catalog by machine evidence alone):

    P(false-accept resolved by machine alone)
        = P(false-accept suggestion) · P(g₅ fails to gate it)
        = (anything ≤ 1) · 0
        = 0,  structurally.

This is not an estimate. It is the same soundness property §2c and §4
state, re-derived in the composition's own terms, and **it is measured
on this exact chain**: the 2026-07-21 write run verified **0 / 8,925**
touched cards resolved on machine evidence alone (independently
re-derived via `resolve_printing`, and cross-checked against the
`printing_tag_status` cache — `docs/reports/2026-07-21-staged-write.md`),
matching the older live pilot's **0 / 43,425** (§2c). The two runs
measure the same structural guarantee on two different pipelines; both
read 0, by construction, at the scales observed.

**The one-line honest summary:** the _resolution_ false-accept rate is
**0 by construction and measured 0** (twice, on two pipelines); the
_suggestion_ false-accept rate is a product of independent reductions
over a closed set, **bounded but not calibrated** — the individual
`εᵢ` are not yet measured, and §9 says what measuring them would take.

### 7c. Empirical parity-replay check (2026-07-22)

§7b's bound is honest about what's calibrated versus what isn't: the
suggestion-level product is unmeasured per-term, and the
resolution-level 0 is measured only at write-run scale (0/8,925,
0/43,425). The pipeline-fidelity gate's artifact-1 parity replay
(GitHub issue #154; full numbers and the owner ruling:
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §4) adds a
third, larger, cross-pipeline data point, and speaks to `g₁`/`g₄`
specifically rather than just re-confirming `g₅`.

**Baseline vs. method.** The "older live pilot" below is the
**legacy multi-channel engine** (OCR plus the `local-phash-v1`/
`local-fallback-v1` phash channels voting concurrently), not this
chain run twice — this chain (§7's composition) is **OCR-only by
design**. So the replay is a **cross-method** verdict diff: the new
OCR-only chain, computed against current `ImageEvidence`, against the
older multi-channel engine's recorded votes, not the new method
validated against itself. The 83.2% below is OCR-channel agreement
specifically.

**What ran.** A read-only, full-cohort (not sampled) diff of this
chain's own verdict function (`calculate_join_key_verdict`) against the
older live pilot's recorded votes, on every card the pilot voted
(41,586 cards). Restricted to the 28,456 cards whose pilot vote used
the OCR channel this chain can reproduce, the two pipelines agree on
**83.2%** of verdicts outright.

**What the disagreements say about the OCR channel (`g₁`).** Of 17,793
total disagreements, the overwhelming majority are architecture, not
error: 13,026 are cards the pilot matched via engines this chain
doesn't run at all (full-image phash / border-artist-symbol fallback,
out of scope per the note above), and 4,394 are cards this chain's
`g₄` veto layer correctly withholds that the pilot's looser model
accepted. Only **373 (0.9% of the full cohort)** were genuinely
unexplained at replay time, and both were subsequently root-caused to
specific, narrow `g₁` parser defects — a short-circuit gate that
treated a blank OCR read as equivalent to a confident digit-free read,
and a single-character glued-token misparse of a set code — not
diffuse, unbounded noise across the token space. That is weak but real
evidence that `ε₁` (§7a: "unmeasured as a rate; structurally bounded"
by the parser's own shape constraints) is, at least at this scale,
dominated by a small number of identifiable failure modes rather than
a long unstructured tail — a claim about the _shape_ of `ε₁`'s error
distribution, not a calibrated value for it.

**What the disagreements say about conservative abstention
(`g₄`/`g₅`).** Zero of the 373 unexplained cases — and zero of the
full 17,793 — was a case where this chain committed to a _wrong_
printing that the pilot's own recorded vote contradicts. Every
unexplained divergence was this chain declining to match (an
abstention) where the pilot had matched, never the reverse. This is
exactly the asymmetry §7b's resolution-level bound predicts (`g₅`
structurally excludes wrong-printing resolution), extended for the
first time past write-run vote counts to a full-cohort, cross-pipeline
verdict comparison: at 41,586 cards, the chain never silently swapped
in a wrong answer, only ever withheld one where the older, looser
pipeline had guessed.

The owner accepted this outcome (2026-07-22) against the gate's
_intent_ — no confidently-wrong verdicts at scale — rather than its
literal zero-divergence wording; both root causes are fixed in code
(merged PR #340), with the live 373-card cohort's benefit pending a
separately gated Stage C re-extraction. This is a corroborating
empirical check, not a new calibrated `εᵢ` — §9's calibration program
is unaffected by it.

**Measurement basis going forward (owner-ratified 2026-07-23).** This
replay is the last data point measured against the legacy multi-channel
pilot as a moving baseline — that comparison is now closed history,
kept here as permanent cross-method corroboration, not something to
re-run as new data lands. Going forward, the measurement basis is this
system's own full-catalog evidence (the 2026-07-22 Stage C sweep) plus
its own derived pilot: the upcoming full-pool Stage D dry-run is the
pilot of record, and its own statistics become the cited figures for
any future soundness claim about this chain. Full detail and the fire
sequence this basis change feeds into:
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §8–§9.

### 7d. Full-catalog fire outcome (2026-07-23/24) — the soundness design empirically confirmed at scale

The §9 fire sequence completed end to end 2026-07-23: the pilot's
full-eligible-pool `--write` cast **130,210** machine votes across both
channels (join-key 100,500 — 39,253 match / 61,247 no_match; fallback
29,710 match, its first production execution), followed strictly last
by `consensus_recompute --apply`. Against that ~130k-vote input, the
human-backed gate initially materialized **exactly one additional
resolved printing** (3 → 4) — every other card either stayed unresolved
(pending further evidence/votes) or, where the machine channels
abstained (no-match/skip), correctly cast no resolving signal at all.
**A second `consensus_recompute` closer pass the following night
(2026-07-24) then flipped that same card back** (`resolved→unresolved`),
so the live resolved count today is **3** — unchanged in aggregate from
before the fire despite ~130k intervening machine votes and two
consensus recomputes, an even sharper illustration of the same point:
a large volume of machine votes does not translate into net new
resolutions unless the gate's own consensus threshold is actually met
card-by-card, and stays met. This is the same conservative-abstention
asymmetry §7c already established at 41,586-card replay scale (zero of
373 unexplained divergences was a wrong-printing commitment) now
observed at full-catalog production scale with real writes, not a
replay. A further finding from the same 2026-07-24 measurement: despite
131,020 artist-credit evidence fields filled and 7,130 `CardArtistVote`
pairs checked by the closer, **zero cards resolved on artist** — every
checked pair carries only a single machine vote, below the
owner-ratified vote-weight resolution threshold (see
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §14's
"Artist-consensus finding"). Full numbers, the write's DB-verification
against the dry-run's prediction, and both `consensus_recompute`
outcomes:
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §14 and
[`data/2026-07-23-pilot-write-and-recompute.md`](data/2026-07-23-pilot-write-and-recompute.md).
Not a new calibrated `εᵢ` — a corroborating data point at the scale
that matters most (full catalog, real writes), same as §7c's replay was
at replay scale.

## 8. Confidence semantics for downstream consumers

The federation program (`docs/federation-v1.md`,
`docs/federation/public-export-v1.md`) needs a **portable, auditable**
notion of confidence: a number a peer can check against stated math,
not a black-box score it has to trust. This section pins down exactly
what our confidence signals may and may not claim. There are two
distinct signals, and they carry very different epistemic weight.

### 8a. What the numeric machine confidence _is_ — an ordinal pipeline-state label, not a posterior

The `confidence` field on a machine-cast `CardPrintingTag` takes one
of a small set of hand-set literals
(`JOIN_KEY_CONFIDENCE_BOTH = 0.85`, `…COLLECTOR_ONLY = 0.75`,
`…SYMBOL_TIEBREAK = 0.75`, `…ARTIST_DISAGREEMENT = 0.65`,
`JOIN_KEY_NO_MATCH_CONFIDENCE = 0.6`). Read against §7's stages, these
are **a strict encoding of which stages passed, and with what
strength** — nothing more:

| value | pipeline state it records                                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------- |
| 0.85  | `g₂` matched on **both** set code and collector number (strongest join key)                                    |
| 0.75  | `g₂` matched on collector number **only** (pre-M15), **or** `g₃` symbol-phash tie-break resolved the ambiguity |
| 0.65  | a match, but `g₄`'s artist-OCR cross-check **disagreed** (weakened, not vetoed)                                |
| 0.6   | a validated `no_match` (`g₂` = `parsed-but-no-match`)                                                          |

**Two hard facts about this number, both verified against the code, not
assumed:**

1. **It does not affect resolution at all.**
   `resolve_weighted_consensus` reconciles votes **strictly by
   source-derived weight** (`VoteTuple.weight`), and there is **no
   reference to `confidence` anywhere in `vote_consensus.py`**. The
   field is descriptive metadata on the vote row; changing it changes
   no outcome. (`local_calculate_verdicts.py`'s own
   `JOIN_KEY_CONFIDENCE_BOTH` comment makes the same point.)
2. **It is ordinal, not calibrated.** `0.85` means "stronger join key
   than 0.75," full stop. It does **not** mean "85% probability the
   printing is correct." No data ties any tier to an observed accuracy
   — see §9. Treat it as a rank, not a probability.

### 8b. What the human-confirmed signal _is_ — a structurally checkable gate outcome

The UI's confidence display (the checkmark-vs-numeric decision:
**checkmark once a printing has cleared the human-backed consensus
gate, a numeric score otherwise**) draws the line in exactly the right
place. The checkmark is **not** a high value of the §8a number — it is
a **categorically different, stronger claim**: "this printing cleared
`g₅` — a consensus of `min_weight`/`min_share` **including at least one
human-backed vote**." That claim is **structurally re-derivable** by
anyone holding the vote tally: given `vote_weight` and `human_votes`
(both already exported per record, `public-export-v1.md` §1), a peer
recomputes the gate predicate from the published constants and confirms
it, rather than trusting our assertion.

### 8c. The defensible mapping, and the federation posture that follows from it

Putting 8a and 8b together yields a clean, defensible mapping from
pipeline state to an exportable confidence claim:

- **Human-confirmed tier (checkmark / `basis.human_confirmed = true`).**
  A **binary, auditable** claim: "cleared a human-backed consensus gate
  of total weight `W` with `H ≥ 1` human votes." A peer verifies it
  against §7's `g₅` predicate. This is the **only** tier v1 federation
  publishes — `public-export-v1.md` §1's "the gate **is** the export":
  machine suggestions that have not cleared `g₅` **stay home**.
- **Machine-suggestion tier (numeric, no checkmark).** An **ordinal**
  claim: "the strongest evidence stage that passed is `T`" (the §8a
  table). A peer can recompute the same tier from the same evidence
  fields (was a set code present? did the collector number match? did
  the symbol tie-break clear threshold-and-margin? did artist OCR
  agree?) — it is portable and checkable, but it is a **rank over
  pipeline states, never a probability**. v1 federation deliberately
  does **not** export this tier.

**What our confidence therefore MAY claim, to a peer or a UI:** (i) a
binary, re-derivable "cleared the human-backed gate, here is the tally
to check it against," and (ii) an ordinal "here is which decode stages
succeeded, on a fixed ladder you can reproduce." **What it MUST NOT
claim:** that any number is a calibrated posterior `P(printing correct)`. It is not — not until the data in §9 exists. This is the
"auditable against stated math rather than trust" property the
federation program is aiming for: every claim above is something the
consumer can independently recompute from fields we already publish,
none of it is a score they must take on faith.

## 9. From bound to calibrated probability — what upgrading would require (future work, nothing built)

§7 gives a **structural** zero (resolution-level) and an **uncalibrated**
bound (suggestion-level); §8 gives **ordinal** confidence. Upgrading
any of the §8a tiers — or the individual `εᵢ` of §7 — into an honest
**calibrated probability** `P(printing correct | tier)` requires data
that **does not exist yet**, and inventing a number in its absence
would violate this project's own "config values land only from
measurement" rule. Concretely, three things would be needed, in
increasing order of cost:

1. **A labeled human-verified sample, per tier, adjudicated
   independently of the machine suggestion.** For each confidence tier
   (0.85 / 0.75 / 0.65) and for `no_match` (0.6), draw a random sample
   of cards the machine assigned that tier and have humans establish
   the true printing **without seeing the machine's guess** (else the
   estimate is circular). The empirical accuracy per tier, with a
   Wilson interval, is the calibration curve. This is the minimum bar,
   and it is the one currently blocked: real human participation is
   still tiny (§6 — 4 distinct voters), so the confirmed-label volume
   to estimate even one tier's accuracy tightly is not there.
2. **Per-veto precision/recall calibration for `g₄`.** Measure, over a
   labeled sample, what fraction of each veto's firings
   (`border-mismatch`, `frame-mismatch`, `proxy-marker-veto`,
   `copyright-year-mismatch`, `truncated-image`) were _true_ wrong-match
   catches versus correctly-matched cards vetoed on noisy observed
   attributes, and — harder — what fraction of _passed_ matches were
   nonetheless wrong (the miss rate). Only then does `ε₄` become a
   number rather than a firing count. Same labeled-data dependency as
   (1).
3. **Dawid-Skene integration** (the model §6's final section already
   names). Replace the **fixed** per-source weights (0.5 / 1.0 / 5.0)
   and the **fixed** ordinal confidence tiers with **reliabilities
   estimated jointly from the data** — per source, and potentially per
   confidence tier — so that a vote's contribution reflects its
   _measured_ correctness rate, not a hand-set prior. This is what
   turns the §8a ordinal into an estimated likelihood that composes,
   over the closed set `C(n)`, into a genuine posterior. It is gated on
   exactly the volume condition §6 already states for the Sybil work:
   a data-estimated reliability is only more stable than the current
   hand-set prior once per-source volume is high enough, which it is
   not yet. The same estimation, applied to a federation peer as "just
   another noisy source" (§6, `federation-v1.md`), is what would let a
   peer's verdicts earn a _measured_ weight rather than a default one.

Until (1)–(3) exist, the honest ceiling is what §§7–8 already state:
resolution false-accept is structurally and measuredly **0**;
suggestion confidence is an **ordinal, auditable pipeline-state label**;
neither is a calibrated probability, and this document does not pretend
otherwise.

## 10. Streaming and continuous operation

Stage E (`docs/proposals/stage-e-streaming.md`, GitHub issue #153) moves
this pipeline from discrete batch runs to continuous, event-driven
dispatch. The question this section answers: does anything above change
when cards are processed as they arrive rather than in a bounded cohort?
**No.** Every soundness property this document establishes is a
per-card or per-vote property, checked at decode time or at gate time —
never a property of the schedule that decides _when_ a card is decoded.
Concretely, four properties, none of which reference batch boundaries,
run cadence, or wall-clock timing anywhere in their own definition:

1. **The decode-or-abstain rule (§1)** — "accept iff exactly one
   candidate survives within the evidence ball; abstain otherwise" is a
   per-card function of the evidence gathered for that one card against
   its own closed candidate set `C(n)`. Nothing about this rule reads
   the state of any other card, any batch, or any clock; a streaming
   dispatcher calling the same decoder once per card, seconds apart,
   computes the identical output a batch driver calling it once per
   card, in one process, would have computed for that card.
2. **Vote weights (§4 item 2, the owner-ratified vote-weight scenario
   matrix)** — `VoteSource` weights (machine 0.5, human 1.0, admin 5.0,
   implicit 0.25 capped, federated 1.0-but-non-human-backed) are fixed
   properties of _who cast a vote and how_, resolved per (card, tag)
   outcome group at gate-evaluation time. `resolve_weighted_consensus`
   has no notion of streaming vs. batch dispatch at all — it reads
   whatever votes currently exist for a card and applies the same
   matrix regardless of whether those votes arrived one batch apart or
   one continuous stream apart.
3. **The human-backed gate (§4 item 2)** — machine-sourced weight can
   never alone clear the resolution threshold; at least one human- or
   admin-weighted vote must be present in the winning tally. This is
   evaluated identically per card regardless of dispatch cadence, and a
   continuous stream does not add any new machine-only resolution path
   that batch dispatch lacked — see decision (5) of the streaming brief
   itself, which states this invariant is "untouched by moving from
   batch to streaming, since it lives in the vote-weight/consensus
   layer, not the dispatch layer."
4. **The resolution false-accept bound (§7b)** — `P(false-accept resolved by machine alone) = 0, structurally`, because it factors
   through `g₅` (the human-backed gate) exactly as in point 3 above.
   This is a property of the composition `decode → gate`, not of the
   loop that decides when `decode` runs for a given card next.

**What genuinely IS new under continuous operation**, and the only
soundness-adjacent surface this section flags: a human vote's own
quality can, in principle, depend on the served MIX of cards a person
is shown in a session — a queue that serves long, repetitive stretches
of visually similar cards (a plausible byproduct of an event-driven
trigger firing in clusters, e.g. one drive upload producing many
consecutive near-duplicate submissions) could degrade attentiveness
compared to the more varied mix a hand-curated batch cohort tends to
produce. This is a real effect worth naming honestly, but it is
**not** a resolver-soundness effect in the sense §§1–9 formalize: it
would show up (if at all) as noisier _individual_ human votes feeding
into the same, unchanged vote-weight/gate machinery described in
points 2–3 above — the gate does not get weaker, a given vote might
just be a worse signal. The pipeline's own existing selection layer —
the `/whatsthat` vote-queue funnel (`question_feed.py`,
`docs/features/printing-tags.md`'s "Frontend consumer" section) — is
where a mix-composition property like this would need to be measured
and, if it turns out to matter, mitigated (e.g. explicit variety-aware
ordering, or logging the served sequence so a mix effect could be
detected after the fact). It is deliberately **not** something this
document proposes changing in the resolver — `resolve_weighted_consensus`
has no mix-awareness today and gains none from this section; any
mitigation belongs entirely to the selection/serving layer, matching
this document's own repeated pattern of keeping "what narrows the
candidate set or feeds evidence" strictly separate from "what the
gate does with whatever evidence exists."

**Not yet backed by written data**: at the time of writing, no
committed doc or dated report in this repo measures serve-mix effects
on vote quality empirically, or documents a specific mix-logging
mitigation already built — this section states the argument (the
effect is plausible, it lives in the selection layer, the resolver is
unaffected) without asserting a citable measurement that does not yet
exist, consistent with this document's own "no number without
measurement" discipline (§9). If a labeled study of this effect (or a
built mix-logging mechanism) lands later, this section is the place to
fold it in — flagged here rather than left unlinked.

**Mix-logging mechanism landed, 2026-07-24** (same day, a separate
change): `cardpicker.question_feed`'s ≥51%-likely-resolve serving
policy (docs/features/printing-tags.md's "Mix-composition policy" —
itself owner-ratified from a read-only WTC vote-queue data brief, not
from this section) writes one `QuestionFeedServedLog` row per served
question (`anonymous_id`/`pool`/`question_type`/`origin_reason`/
`served_at`) — the mix-logging mechanism this paragraph names as the
prerequisite for a future labeled study. This still is NOT the labeled
study itself (no agreement-rate/latency data has been analyzed against
it yet), and it changes nothing about the argument above — the
resolver remains unaffected either way. Noted here per this section's
own "the place to fold it in" invitation, not asserting more than the
log now existing.

---

## Status

**Reviewed and approved by the owner, 2026-07-17**, with 3 edits
(the §2b false-accept/abstention-verification reframe and arithmetic
correction, and §3's XOR-framing correction) applied above. Calibrated
against the full-catalog run completed 2026-07-16/17
(`run_id=20260716T193408-6613a1a6`, 165,980 candidates scanned, 43,425
votes cast across 41,586 distinct cards, 26.2% invocation hit rate,
0/43,425 gate verification — corrected 2026-07-22, see
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md)) and the
pre-existing 300+300 validation and no-match autopsy numbers in
`docs/features/printing-tags.md`. The §2a pair-count shortfall (both
harvested-pair categories have an unexplained ~10-20% gap between
harvest count and analyzed count, checked against source data and not
resolvable from what's recorded) is an **accepted documented
limitation** — calibration on the accounted-for cases (241/269) is
correct as-is, no harvest re-run planned.

**§§7–9 added 2026-07-21** (owner-commissioned formalization): the
deduction chain written as an explicit stage composition (§7), the
confidence semantics federation needs (§8), and the calibration work
that would upgrade the ordinal confidence to a real posterior (§9).
These sections formalize the **current** Stage D chain
(`local_calculate_verdicts.py`), which is architecturally narrower
than §1's live-pilot three-channel model (§7 opens by stating that
divergence plainly rather than retrofitting §1). Anchored on the
2026-07-21 `staged-write-20260721T0434Z` run (8,925 join-key votes,
0/8,925 gate verification, 2/20,677 ambiguous rate;
`docs/reports/2026-07-21-staged-write.md`) alongside §2's existing
0/43,425 and 269-pair numbers. The commission is owner-approved; the
§§7–9 **text** is pending the same owner review §§1–6 received.

**§7c added 2026-07-22**: the pipeline-fidelity gate's artifact-1
parity-replay result (GitHub issue #154), folded in as a third,
full-cohort empirical data point for the `g₁`/`g₄` discussion in
§7a/§7b — corroborating the existing bound's shape, not calibrating a
new number. The owner accepted the underlying replay outcome
2026-07-22 against the gate's soundness intent (373/41,586 unexplained
divergences, 0/373 a wrong-printing vote); full numbers and the ruling
live in [`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §4,
not duplicated here.

**§7c amended 2026-07-23**: added the owner-ratified measurement-basis
change — the legacy-pilot comparison this subsection describes is now
closed history, not a baseline to keep re-measuring against; the new
system's own full-pool Stage D dry-run becomes the pilot/measurement of
record going forward. Full detail:
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §8–§9.

**§7d added 2026-07-23**: the §9 fire sequence completed end to end the
same day (pilot `--write` + `consensus_recompute --apply`) — folded in
as the soundness design's first full-catalog, real-write empirical
confirmation: ~130k machine votes entered, the human-backed gate
resolved exactly one additional card. Corroborating data, not a new
calibrated number; full figures live in
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §14, not
duplicated here.

**§4 amended 2026-07-23**: the owner-ratified deductive-backfill
zero-weighting (28,112 `CardPrintingTag` votes,
`anonymous_id="deductive-backfill-v1"`, permanently zero consensus
weight) folded in as a further, narrower soundness tightening, with
the live-audit basis numbers and the "image-derived + human evidence
only" framing. Full mechanism:
`cardpicker.vote_consensus.resolve_vote_weight`; full ruling:
[`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §3 item 3.

**§10 added 2026-07-24** (Stage E Phase 1, `docs/proposals/stage-e-streaming.md`,
itself still HOLD pending owner review of its own §3-§5): the argument
that moving from batch to continuous/streaming dispatch changes nothing
about this document's soundness model — decode-or-abstain (§1), vote
weights and the human-backed gate (§4 item 2), and the resolution
false-accept bound (§7b) are all per-card/per-vote properties independent
of scheduling. Names the one new, non-resolver soundness-adjacent surface
(served-mix effects on human vote quality, living in the selection/
vote-queue layer) without asserting a citable measurement that does not
yet exist in the written record — see §10's own "Not yet backed by
written data" note. Like §§7-9, §10's **text** is pending the same owner
review §§1-6 received; the top-of-document STATUS banner is unchanged by
this addition.
