# OCR tier-2 pre-check gate: measured, not shipped (2026-08-19)

## Task

Part 2 of the per-extractor-reextraction work: propose a cheap pre-check
gating `collector_line_ocr`'s tier-2 escalation (the 4 heavier-preprocessed
tesseract attempts, `_collector_line_ocr_attempts`' own tier 2) — "does this
card even have a collector line?" — and measure it before shipping, the same
way the earlier tier-3 removal was measured (its own probe:
`ocr_ladder_tier_attribution.py`, cited in `_collector_line_ocr_attempts`'
own docstring).

## Gate signal proposed

Laplacian-kernel edge variance (`local_image_quality.compute_blur_variance`,
already used elsewhere in this file for `quality_signals`) of the tier-1
collector-line crop (`DEFAULT_CROP_BOX`, converted to grayscale) — a real
printed collector line has measurably more high-frequency edge content than
a blank/uniform card-border region. Cost: one Pillow filter + one variance
call over a small crop, no tesseract call at all — several orders of
magnitude cheaper than the 4 tesseract calls it would avoid.

## Method

Read-only, against the live production database (235,865 `ImageEvidence`
rows). Two pools, sampled without replacement:

- **`found`**: cards whose stored `collector_line_collector_number` is
  non-blank (a real parse already exists) — 135 candidates.
- **`blank`**: cards whose stored `collector_line_collector_number` is blank
  (no candidate ever parsed, and `fetch_ok` was true) — 135 candidates.

For 45 cards from each pool (90 total, real image fetched from Google Drive,
real tesseract calls, no mocking): ran the FULL 2-tier ladder to completion
(never stopping at the first success — mirroring the tier-3 probe's own
"walk to full completion" method) and recorded the tier of the FIRST
`collector_number`-bearing parse (1, 2, or never), plus the gate signal
computed from the tier-1 crop alone. Genuine set-code-lexicon/artist gates
were NOT applied (this measures raw ladder-yield-by-tier, the question this
gate's decision is actually about); the earlier tier-3 probe used
candidate-validated matches for a stricter question, which is out of scope
here since the gate's own decision point is upstream of both gates entirely.

90 cards completed in 104s (real network fetch + real tesseract, no
caching) — of which 43 parsed at tier 1, 25 needed tier 2 to parse, and 22
never parsed under either tier.

## Result: the two populations the gate must separate overlap almost

completely

```
gate(tier2 success):  n=25  min=6.2   p25=219.4  median=449.3  p75=1643.5  max=2675.5
gate(never parsed):   n=22  min=10.2  p25=177.9  median=412.9  p75=1063.2  max=2584.7
```

The median gate value for "tier 2 genuinely rescued this card" (449.3) and
"this card never parses no matter what" (412.9) are within 9% of each
other, and both distributions span nearly the SAME range (6–2676 vs
10–2585). A card with a real, tier-2-recoverable collector line and a card
with no collector line at all produce statistically indistinguishable edge
variance in the tier-1 crop, in this sample.

Sweeping candidate thresholds confirms it — every threshold that skips a
meaningful fraction of the always-blank population also discards real
tier-2 rescues, roughly proportionally:

```
threshold=  10: would_skip=1  LOST_real_tier2=1  correctly_skipped_never=0
threshold=  15: would_skip=3  LOST_real_tier2=1  correctly_skipped_never=2
threshold=  30: would_skip=5  LOST_real_tier2=1  correctly_skipped_never=4
threshold=  75: would_skip=7  LOST_real_tier2=3  correctly_skipped_never=4
threshold= 100: would_skip=7  LOST_real_tier2=3  correctly_skipped_never=4
```

At the most favourable threshold observed (30), the gate saves 4 cards'
worth of tier-2 compute at the cost of 1 lost real collector-number read
(a 4:1 ratio at best) — and that ratio degrades, not improves, at every
higher threshold tried. There is no threshold in this sweep where the gate
recovers a meaningfully larger fraction of the always-blank population
without a proportional loss of real tier-2 rescues.

## Accuracy delta vs timing delta, stated separately (task's own requirement)

- **Timing delta**: real and favourable — the gate itself costs roughly
  nothing next to the 4 tesseract calls it would avoid, and the always-blank
  population is genuinely large catalogue-wide (~38% of the catalogue per
  the task brief, though this sample skews smaller for "never parsed" at
  the tested threshold band).
- **Accuracy delta**: real and NOT acceptable. At every threshold tested
  that saves a non-trivial amount of compute, the gate also loses real,
  previously-successful collector-number reads — reads that feed the
  join-key calculator (19,828 votes in the last pass, per the task brief)
  and are irreplaceable once skipped (a card whose evidence carries no
  collector number contributes nothing to that calculator for this pass).

## Decision: do not ship

Per the task's own instruction, this is reported as a valuable measured
outcome, not a failure to deliver: **the proposed gate signal does not
cleanly separate the two populations it needs to, so gating tier 2 on it
would trade a real, valuable signal (join-key votes) for a compute saving
that a cleaner gate might achieve, but this one does not.** No code change
ships for Part 2. Part 1 (per-extractor re-extraction) ships alone.

## What a future attempt would need

A different, sharper signal than raw edge variance over the FULL crop band

- possibly restricted to a narrower sub-region, or a signal that
  distinguishes "text-shaped" edges from "border/frame decoration" edges
  (the crop band includes card-frame elements, not just the collector-line
  text itself, which likely explains why "never parsed" cards - which still
  have a printed frame in that crop - show similar variance to real text).
  Any future attempt should re-run this same measurement method before
  shipping, not assume a different signal fares better without checking.

## Reproduction

The probe script (`ocr_gate_probe.py`, not committed - a one-off
measurement tool, matching this repo's own "the probe's job is a decision,
not a deliverable" precedent for `ocr_ladder_tier_attribution.py`) ran via
`docker exec -i mpcautofill_django python manage.py shell` against the live
database, real Google Drive fetches, real tesseract calls - no mocking
anywhere in the measurement path.
