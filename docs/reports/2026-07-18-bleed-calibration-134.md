As of: 2026-07-18
Task: #134 — Proposal B merge-time calibration pass (real catalog images)
Branch: `claude/bleed-calibration-134`

## What this is

`bleedNormalize.ts` shipped (PR #66) with four named measurement constants
(`PROBE_COUNT`, `RGB_DISTANCE_THRESHOLD`, `IQR_AMBIGUITY_FRACTION`,
`OVERSIZED_MULTIPLE`) flagged as "reasonable starting guesses, not
empirically tuned" pending a real-image calibration pass. This is that
pass: 30 real catalog images, run through the actual shipped measurement
function, defaults evaluated against real photographic/scan data (not the
synthetic six-category fixture set, which already validates the
algorithm's _logic_ and is untouched by this pass).

## Sample

30 real cards fetched through the production image-CDN's full-tier
endpoint (`cdn.proxyprints.ca/images/google_drive/full/<id>.jpg?dpi=<dpi>`),
which routes through the Worker's own `fetchWithRateLimit` global limiter
(shared 3 req/s ceiling) — this pass never bypassed or added load beyond
what a real export already contends with, and added a courtesy 400ms
client-side gap on top. 10 distinct sources, 6 DPIs (460/600/800/1120/
1200/1210/1240), both jpg and png.

**Ground truth**: not a DB vote lookup — the negative-only voting change
means a "bleed" reading casts no `CardTagVote` at all (see
`docs/features/printing-tags.md`'s bleed-edge section), so absence of a
vote can't distinguish "confirmed bleed" from "never processed." Instead,
each image's own file dimensions were classified via the same
aspect-ratio method the backend's already-validated `classify_bleed_edge`
uses (`TRIM_ASPECT_RATIO ≈ 0.7159`, `BLEED_ASPECT_RATIO ≈ 0.7350`,
abstain past 0.03 from both) — deterministic, no vote dependency, and
directly checked against each image's actual pixel dimensions (confirmed
within <1% of the theoretical bleed-inclusive size at the image's own
declared DPI, e.g. Evil Twin: 1253×1702 actual vs 1256×1709 expected at
460 DPI — ruling out a DPI-metadata mismatch as a confound).

Split: **28 bleed / 2 trimmed / 0 abstain** — consistent in direction
with the backend's own ~97.5% bleed-prevalence finding on its separate,
larger 40-source sample.

## Result: constants left unchanged

See `bleedNormalize.ts`'s calibration-caveat comment (top of file) for
the canonical writeup now living with the code. Summary:

**A real, reproducible measurement bias was found**: real bleed-
classified images measure a median per-side depth of ~5.8-6.3mm against
a true target of 3.175mm (1/8" bleed at 63×88mm trim) — roughly 2x
expected.

**Root cause, not just symptom**: swept `RGB_DISTANCE_THRESHOLD` from
24 down to 6 (4x stricter) across all 28 bleed-classified images/112
side-measurements:

| threshold    | median mm | mean mm | ambiguous |
| ------------ | --------- | ------- | --------- |
| 24 (default) | 5.90      | 6.26    | 4/112     |
| 16           | 5.86      | 6.22    | 3/112     |
| 12           | 5.85      | 6.20    | 3/112     |
| 10           | 5.85      | 6.19    | 3/112     |
| 8            | 5.85      | 6.18    | 3/112     |
| 6            | 5.76      | 6.14    | 3/112     |

Under 3% movement across a 4x threshold range rules out "threshold too
loose" as the cause. The real cause: a typical MTG card's own physical
border/frame is _also_ a flat, uniform color (commonly black) sitting
immediately inside the synthetic bleed extension (which is deliberately
colored to match the frame, so print misalignment doesn't show a visible
seam) — the probe's uniform-run walk measures bleed+border combined, not
bleed alone, regardless of threshold.

**Why no constant was changed**: `OVERSIZED_MULTIPLE` could mechanically
be tuned down to push this ~2x overshoot into the oversized-fallback
path, but the approved spec defines that constant as a bad-DPI-metadata
guard specifically — repurposing it to paper over a different, now-
understood failure mode would be a `resolveBleedPlan` behavior change
made unilaterally, on code another session was concurrently touching
same-day (see `docs/lessons.md`'s stacked-PR/collision entries). That
call belongs to the spec owner. `PROBE_COUNT`/`IQR_AMBIGUITY_FRACTION`
showed no misbehavior in this sample (ambiguous rate ~3%, all on
genuinely degenerate images — see below).

**Production risk, flagged not fixed**: at `OVERSIZED_MULTIPLE=3`, most
real overshoots here (5.5-6.5mm) sit under the ~9.5mm oversized cutoff
for a 3.175mm target, so `resolveBleedPlan` computes a negative
(trim-inward) plan on typical real bled cards — cropping ~2-3mm into
real border content on the common case (28/30 of this sample), not an
edge case. Tracked in `docs/proposals/proposal-b-bleed-normalization.md`
as a design follow-up, not built here.

## Example measurements (raw, target = 3.175mm/side)

- **Evil Twin** (460 DPI, bleed): top/left/right ≈ 5.5mm, bottom 9.2mm.
- **Raise Dead** (460 DPI, bleed): top 6.3mm, bottom 9.6mm, left 5.7mm,
  right 6.0mm.
- **Nebula_Back3** (1210 DPI, bleed): all four sides 5.7-5.9mm — the
  most symmetric case in the sample, still ~1.8x target.

**The two trimmed-classified images, correctly handled differently**:

- **WotC Proxy Policy** (1240 DPI): all four sides measured exactly
  `maxScanDepthPx` (12.7mm) — the degenerate "fully uniform the whole
  scan depth" case, correctly flagged `ambiguous: true` on every side
  (a solid-background text card has no real edge signal at all; falls
  back to the prior as designed).
- **MTG New Card Back No Logo alt dots** (1120 DPI): 2.7-3.3mm, non-
  ambiguous, close to the bleed target despite being a trimmed image —
  a card-back design's own border pattern can read as a plausible
  "uniform run" the same length as a real bleed margin. Noted as a
  smaller secondary finding (false-positive-shaped, not exercised at
  volume by this sample), not investigated further here.

## Bottom-edge asymmetry (also observed, not explained)

Many cards show a distinctly larger bottom-edge measurement than
top/left/right (e.g. Evil Twin: 5.5mm × 3 sides, 9.2mm bottom; Shipwreck
Looter: 5.5mm × 2, 9.2mm bottom). Plausible cause not confirmed: MTG's
typeline/rules-text box near the bottom edge is itself a large,
uniformly-colored region, extending the "uniform run" further than the
top/side art does. Flagged for whoever picks up the border/bleed
measurement redesign — not chased further in this pass.

## Full per-image data (30 images, all 4 sides)

| Card                               | DPI  | Source classification | top mm     | bottom mm  | left mm    | right mm   |
| ---------------------------------- | ---- | --------------------- | ---------- | ---------- | ---------- | ---------- |
| Evil Twin                          | 460  | bleed                 | 5.522      | 9.221      | 5.522      | 5.522      |
| Disappear                          | 460  | bleed                 | 6.516      | 6.46       | 6.129      | 6.129      |
| Raise Dead                         | 460  | bleed                 | 6.295      | 9.553      | 5.687      | 6.046      |
| Forest (Back)                      | 800  | bleed                 | 5.016      | 9.588      | 5.27       | 5.302      |
| Nebula_Back3                       | 1210 | bleed                 | 5.878      | 5.899      | 5.731      | 5.731      |
| Goblin.3                           | 1210 | bleed                 | 6.046      | 9.719      | 5.794      | 5.71       |
| Carrion Feeder                     | 460  | bleed                 | 6.571      | 6.46       | 6.295      | 6.24       |
| Skeletal Vampire                   | 460  | bleed                 | 6.074      | 6.46       | 6.046      | 6.074      |
| Vessel of Endless Rest             | 460  | bleed                 | 6.019      | 6.019      | 6.019      | 6.019      |
| Shipwreck Looter                   | 460  | bleed                 | 5.467      | 9.221      | 5.522      | 5.467      |
| WotC Proxy Policy                  | 1240 | trimmed               | 12.7 (amb) | 12.7 (amb) | 12.7 (amb) | 12.7 (amb) |
| Clue [WHO] (2)                     | 1200 | bleed                 | 6.562      | 9.885      | 5.313      | 5.313      |
| Fathom Fleet Cutthroat             | 460  | bleed                 | 6.019      | 9.221      | 5.577      | 5.798      |
| Pyretic Hunter                     | 460  | bleed                 | 5.522      | 9.277      | 5.577      | 5.467      |
| Mountain                           | 460  | bleed                 | 5.522      | 8.421      | 5.522      | 5.522      |
| Plains                             | 800  | bleed                 | 5.636      | 6.144      | 7.525      | 7.556      |
| piracy its a crime                 | 1210 | bleed                 | 5.878      | 5.899      | 5.731      | 5.731      |
| Avatar                             | 460  | bleed                 | 6.019      | 6.019      | 6.019      | 6.019      |
| Chart a Course                     | 460  | bleed                 | 5.522      | 9.221      | 5.467      | 5.522      |
| Flow of Maggots                    | 460  | bleed                 | 5.853      | 6.157      | 5.577      | 5.467      |
| Goblin Assault Team                | 460  | bleed                 | 5.467      | 9.332      | 5.687      | 5.632      |
| Golos, Tireless Pilgrim            | 1210 | bleed                 | 6.549      | 7.4        | 5.311      | 5.311      |
| Boros                              | 800  | bleed                 | 12.7 (amb) | 12.7 (amb) | 12.7 (amb) | 12.7 (amb) |
| Warrior                            | 1210 | bleed                 | 5.416      | 7.421      | 5.29       | 5.29       |
| Warrior_s Honor                    | 460  | bleed                 | 6.46       | 6.46       | 6.184      | 6.184      |
| Grasp of Phantoms                  | 460  | bleed                 | 5.522      | 9.221      | 5.522      | 5.522      |
| Rumbling Baloth                    | 460  | bleed                 | 6.019      | 6.019      | 6.074      | 6.046      |
| Soldevi Sage                       | 460  | bleed                 | 5.798      | 5.743      | 5.522      | 5.467      |
| MTG New Card Back No Logo alt dots | 1120 | trimmed               | 2.699      | 3.311      | 2.699      | 2.699      |
| Phyrexian Token (Rubric Marine 1)  | 600  | bleed                 | 5.038      | 7.281      | 5.461      | 5.207      |

(`Boros` also measured degenerate/ambiguous on all sides like WotC Proxy
Policy — a full-art or otherwise non-standard image, correctly falling
back to the prior rather than trusting a bad measurement.)
