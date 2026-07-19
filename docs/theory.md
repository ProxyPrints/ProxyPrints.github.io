# Theory note: the printing-identification pipeline as candidate-constrained decoding

**STATUS: Reviewed and approved by the owner, 2026-07-17.** Written per
the catalog-completion plan's Part 6, gated on the full-catalog run's
final report existing. Written for an external reader — this also
doubles as the technical annex for a future federation pitch (see
`docs/federation-v1.md`), so it avoids repo-internal jargon where a
general term exists.

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
**every one of the 43,426 machine votes cast (165,980 candidates
processed, 26.2% invocation hit rate) was verified, after the fact,
against `verify_zero_resolutions` — 0/43,426 affected cards were ever
resolved by machine evidence alone.** This is not a sampled estimate; it
is the literal count. It's a soundness property, not an accuracy one
(see §4) — but it means that even in the counterfactual worst case where
every one of those 43,426 votes were wrong, **not one of them was ever
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
2. **The human-backed gate** (`vote_consensus.is_human_backed_source`):
   machine-sourced votes (`VoteSource.OCR`, `VoteSource.DEDUCTION`, machine
   weight 0.5 by default) can never _alone_ clear the resolution
   threshold (`PRINTING_TAG_MIN_VOTES=2`) — at least one human vote
   (weight 1.0) or admin vote (weight 5.0) must be present in the
   winning tally for a card to actually resolve. Machine evidence
   narrows and prioritizes what a human is asked to confirm; it never
   substitutes for that confirmation. This is the property §2c's
   0/43,426 result is actually verifying — not "43,426 correct
   decisions," but "43,426 decisions that were structurally incapable of
   resolving anything on their own."

Together these mean the system's worst-case failure mode, even under a
badly miscalibrated engine, is a wasted human review cycle (a bad
suggestion surfaced for confirmation) — never a silent wrong answer
committed to the catalog.

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
that machine evidence alone can never resolve anything.

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
`VOTE_FEDERATED_WEIGHT=1.0`) rather than weights estimated from the data
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

---

## Status

**Reviewed and approved by the owner, 2026-07-17**, with 3 edits
(the §2b false-accept/abstention-verification reframe and arithmetic
correction, and §3's XOR-framing correction) applied above. Calibrated
against the full-catalog run completed 2026-07-16/17
(`run_id=20260716T193408-6613a1a6`, 165,980 candidates, 43,426 votes,
26.2% invocation hit rate, 0/43,426 gate verification) and the
pre-existing 300+300 validation and no-match autopsy numbers in
`docs/features/printing-tags.md`. The §2a pair-count shortfall (both
harvested-pair categories have an unexplained ~10-20% gap between
harvest count and analyzed count, checked against source data and not
resolvable from what's recorded) is an **accepted documented
limitation** — calibration on the accounted-for cases (241/269) is
correct as-is, no harvest re-run planned.
