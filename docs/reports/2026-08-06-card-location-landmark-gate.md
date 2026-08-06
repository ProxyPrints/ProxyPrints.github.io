# Card-location landmark: STEP 1 gate result (NOT MET — no replacement shipped)

2026-08-06. Follow-on to `docs/reports/2026-08-06-crop-geometry-audit.md` (issue #735/#736),
which measured that `classify_border_color`'s fixed-fraction bands land on canvas rather than the
printed card on 8/8 directly-viewed images. This session attempted the fix that audit's own
acceptance criteria called for — locate the card's own rectangle inside the image using an
internal landmark (the rules-text-box's bottom edge), then rebuild bleed measurement and border/
frame detection on top of it — and could not clear its own gate. No code changed;
`classify_bleed_edge`, `compute_bleed_diff_mm`, `classify_border_color`,
`local_art_edge.classify_art_edge_continuity` and every constant they depend on are byte-identical
to `master`. This report is the deliverable in place of that replacement, per the originating
brief's own instruction: "If step 1 does not validate, the deliverable is the measurement and no
replacement."

## Headline finding

The brief's method assumes one constant, `f` (the text-box-bottom's position as a fraction of the
CARD's own height), holds across the catalogue, and that vertical canvas padding is symmetric
(same amount top and bottom) so a single measured row plus `f` is enough to solve for it. Neither
premise survived direct measurement:

- **`f` is not one constant.** On renders that preserve a genuine collector-line row below the
  text box (the same convention `local_ocr.DEFAULT_CROP_BOX`'s empirically-tuned top edge, 0.90,
  already encodes), `f ≈ 0.90` — confirmed by direct visual inspection of six independent card
  renders (see "Deriving f", below). On renders from a different, common house style — a rounded-
  rectangle card graphic floating on a plain canvas, with NO printed strip below the text box at
  all, collector/artist-credit text stamped directly onto the canvas instead — the text box's own
  bottom edge sits at `f ≈ 0.99` of that same visible rectangle, because there is no card
  real-estate left below it to measure. A single global `f` cannot serve both populations, and
  nothing in the image alone identifies which population a given card belongs to without already
  knowing where its true boundary is — circular.
- **Vertical padding is not symmetric.** Direct pixel-level measurement (colour-transition
  scanning, not eyeballing) on the three cards this task's own originating audit named as
  confirmed misclassifications — card 30255 (Frostwalla, Berndt_Toast83), card 84481 (Silverchase
  Fox, RustyShackleford), and card 182512 (Équilibre, Celid) — found top padding of 5.8–6.5% of
  image height against bottom padding of 6.5–10.1%: a 0–4 percentage-point asymmetry, confirmed
  independently by locating the actual thin printed-frame colour strip (see "Ground-truth padding
  measurement", below) rather than inferred from the formula. The brief's `pad = (f·H − y) / (2f−1)` has one unknown and one equation; it cannot recover two different numbers from one
  measurement, so on the asymmetric cases (three of the four I pixel-verified) it returns a single
  value that is wrong for both edges.
- **Net effect, measured on the same 4 confirmed-defect cards this task's own audit named:**
  applying `f=0.90` and the symmetric formula, my prototype detector's answer for card 30255
  (Frostwalla) was "padding ≈ 0.3%" against a pixel-verified real padding of 5.95%/10.05%
  (top/bottom) — wrong by more than an order of magnitude, and silent about the direction of the
  error. It abstained outright on the other three (84481, 95604, 182512) because the formula's own
  plausibility bound (`0 ≤ pad ≤ 0.30·H`) rejected the implied answer as degenerate. Zero of the
  four cards this brief was specifically written to fix got a usable, accurate rectangle.

## Method

### Deriving f

Fetched 24 images (stratified across 20+ sources, both `bleed_class` values, and 7 non-standard
`CanonicalPrintingMetadata.layout` values — adventure/case/class/planar/saga/split/transform —
drawn via the same `row_number() OVER (PARTITION BY ...)` stratified-sample pattern the originating
audit used) plus the 4 specific cards that audit named as confirmed misclassifications, via the
public CDN Worker route (`cdn.proxyprints.ca`, Google Drive sources only), paced at ≤4 req/s
against `GOOGLE_IMAGE`'s ratified 7.0 req/s ceiling, sequential, no concurrency. Zero Scryfall
calls this session (Step 1 never reached the frame-continuity work Step 3 would have needed
Scryfall ground truth for).

Drew fine-grained (1–2%-of-height) horizontal gridline overlays on six diverse renders — an
official-template M13 card (Stormtide Leviathan, source Berndt_Toast83), a parchment-styled
old-border pastiche, and four further stylistically distinct fan renders (BFM, 0xProxies, 40k
Contest crossover, DrDolathan) — and read each overlay directly (`read` tool, not a script) to
find the exact row where the light rules-text-box background gives way to the frame/border below.
All six independently converged on `y ≈ 0.895–0.91` of the full image height, matching
`local_ocr.DEFAULT_CROP_BOX`'s own top edge (0.90) almost exactly — that constant was empirically
tuned to sit just below the text box, so this is an independent re-derivation landing on the same
number, not a coincidence. `f = 0.90` is genuinely well-supported for this population.

### Ground-truth padding measurement

For the 4 audit-flagged cards, direct colour sampling along each image's own centre row/column
(scan inward from each edge for the first pixel departing from near-black, `max(R,G,B) > 40`)
found: card 30255 top-pad 55px/5.95%, bottom-pad 93px/10.05%, left/right-pad 55–56px/8.1–8.2%;
card 84481 top=bottom=60px/6.49%, left=right=60px/8.81%; cards 95604 and 182512 (same rendered
dimensions, both top/bottom 54px/5.84% + 89px/9.62%, left/right 52px/7.65% — likely the same
template reused across sources). Left/right padding is symmetric in all four cases (within 1px) —
that half of the brief's assumption holds. Top/bottom is symmetric in exactly one of four (84481)
and asymmetric by 4.1–4.4 percentage points in the other three.

Cross-checked this scan against exact pixel values (not just the scan's own output) for card 30255:
sampling the centre column row-by-row from `y=0` shows pure `(0,0,0)` through `y=46`, a green-frame
transition band at `y=56–70` (the card's own thin printed border — greenish-grey, e.g. `(169,183, 184)` fading to `(56,122,95)`), then the light title-bar background from `y=74`. The same pattern
recurs at the bottom: light text-box background (`≈(220,230,230)`) through `y=826`, a 4px green
transition at `y=828–830`, then pure black from `y=832` to the image's own bottom edge (`y=924`).
This directly confirms the audit's own claim — a real, if thin (4–16px), printed coloured border
does exist on these cards, sitting well inboard of the image edge, with genuine canvas beyond it —
and separately explains why `f=0.90` fails here: this specific template's OWN internal proportions
put the text box within 1% of its own visible-rectangle's bottom edge (no rendered collector-line
row at all), not at the 10%-from-bottom position `f=0.90` assumes. Confirmed the same pattern
(light text box straight to black canvas, no intervening border strip) on a second, independently-
sampled card (187110, Chiky — drawn from the general stratified sample, not the audit's flagged
set) via the identical pixel-scan method, so this is not a one-card artefact.

### Prototype detector and its gate result

Built a standalone (`local_fallback`-independent, not wired into any module) row-brightness-profile
detector implementing the brief's formula: scan for the first sustained "light region ends, drop to
darker" transition in a 0.72–0.94 image-height band, apply `pad = (0.90·H − y)/0.8`, derive
horizontal padding from the located card height and whichever of `TRIM_ASPECT_RATIO`/
`BLEED_ASPECT_RATIO` the full image's own aspect ratio is nearer to (matching
`classify_bleed_edge`'s existing choice), abstain (reusing the existing `"ambiguous"` skip-reason
string) if no transition is found or the implied padding exceeds a 30%-of-dimension plausibility
bound.

Run against all 28 fetched images (24 general + 4 flagged): **11/28 (39.3%) produced a candidate
rectangle; 17/28 (60.7%) abstained.** Of the 11 confident answers, one (card 30255, Frostwalla —
one of the four cards this task exists to fix) was independently pixel-verified WRONG by more than
an order of magnitude (predicted 0.3% padding; measured 5.95%/10.05%). A second (card 187110,
Chiky, a general-sample card, not one of the four originally flagged) was pixel-verified
directionally correct but imprecise (predicted symmetric 6.15%; measured top≈5.8%, and — following
the same "no border row below text box" pattern found on the flagged cards — a bottom edge that
the formula's symmetric assumption cannot separately recover). No confident answer was verified
accurate to a standard that would let Step 2/3's mm-level and RGB-distance-margin measurements
build on it without inheriting this error.

**Confident-and-correct rate on the 4 specific cards this brief was written to fix: 0/4** (3
abstained outright, 1 gave a wrong answer verified wrong to more than an order of magnitude).

## Why f isn't rescuable with a second landmark

The brief's own fallback — cross-check against `ImageEvidence.collector_line_word_boxes` where OCR
succeeded (~60% of the catalogue) — doesn't close this gap: it's a second measurement of the SAME
underlying quantity (where does this card's own template place its bottom print row), which is
exactly the thing just shown to vary by template. On the two flagged cards inspected pixel-by-pixel
here, the collector-line/artist-credit text is printed directly onto the black canvas itself, not
onto any part of the card — so a hypothetical successful OCR read of it would report a position
that is by construction outside the card, not a second constraint that helps solve for asymmetric
padding at the card's true edge.

## Gate verdict

Per the originating brief: **"If the located rectangle is not reliable, stop here and report —
steps 2 and 3 are worthless on a bad rectangle."** The measured confident-rate (39.3%) and, more
decisively, the measured accuracy on exactly the population this task exists to fix (0/4, with one
wrong by >10x) mean Step 1 does not validate. Steps 2 (bleed remeasurement) and 3 (border/frame
detection rebuild) were not attempted — building a millimetre-precision measurement or a
2.6-unit-margin RGB-distance classifier on a rectangle this unreliable would produce numbers no
more trustworthy than the fixed-fraction bands they were meant to replace, and would consume the
golden-set/version-bump/migration machinery those steps require for no verified gain.

## What this does and doesn't rule out

This is a negative result for the SPECIFIC method the brief specified (one global text-box-bottom
fraction + symmetric-padding arithmetic), not a claim that no geometric fix is possible. Two
directions a follow-up could take, neither attempted here:

1. **Per-template calibration.** If the "no border row below text box" style is a small, countable
   number of shared community templates (Frostwalla/Chiky's pattern recurred identically on a card
   from a different, unrelated source in this sample — c.f. the crop-geometry audit's own finding
   that specific black-bordered "PROXY: Not for sale" templates get shared across uploaders),
   fingerprinting the template (e.g. via a phash of the canvas-corner region) and keeping a small
   per-template `f`/padding-convention table might work where one global constant does not. Not
   attempted here — no time budget left after the gate failed, and it changes the method's shape
   substantially enough to need its own scoping.
2. **A genuinely two-parameter measurement.** Recovering asymmetric top/bottom padding needs two
   independent vertical landmarks, not one. The title-bar's own top edge (a comparably strong,
   near-universal horizontal feature, symmetric counterpart to the text-box-bottom this brief
   specified) is the natural second constraint — text-box-bottom and title-bar-top, solved jointly,
   give two equations for `pad_top`/`pad_bottom` instead of one equation assuming they're equal.
   Not attempted here — flagged as the most promising concrete next step, but a new derivation
   needing its own validation pass, not a small patch to what was built this session.

## Validation detail

- **Sample:** 24 images stratified by `bleed_class` (drawn via
  `row_number() OVER (PARTITION BY ie.bleed_class, c.source_id ORDER BY random())`, joined
  `cardpicker_card`/`cardpicker_imageevidence`/`cardpicker_source`, read-only via
  `docker exec -i mpcautofill_postgres psql`) plus 7 rows drawn the same way but partitioned by
  `CanonicalPrintingMetadata.layout` (adventure/case/class/planar/saga/split/transform, resolved
  via `COALESCE(canonical_card_id, inferred_canonical_card_id)`), plus the 4 cards (30255/84481/
  95604/182512) the originating crop-geometry audit named by id as confirmed misclassifications.
  28 images viewed/measured in total; 10 viewed directly via fine-grained gridline overlays (6 for
  deriving `f`, 4 for the flagged-card padding measurement); all 28 run through the automated
  detector for the confident/abstain tabulation.
- **Accuracy against direct viewing:** reported above — 39.3% confident rate; 0/4 correct on the
  cards the fix targets; 1/2 spot-checked confident answers pixel-verified wrong by >10x, the
  second directionally right but not to a trustworthy precision.
- **Host load / fetch pacing:** checked before and during fetching (`uptime`,
  `systemctl list-units --type=service --state=active --plain 'sfc-*'`); load ranged 3.0–4.8
  throughout (never near the 15 pause threshold), 0 `sfc-*` units active. All image fetches via the
  existing public CDN Worker route, Google Drive sources only, paced well under `GOOGLE_IMAGE`'s
  7.0 req/s ceiling. No Scryfall calls. No writes to the database; all SQL read-only via
  `docker exec -i mpcautofill_postgres psql`, never against `mpcautofill_django`. No management
  command run.
- **Scratch:** `/tmp/opencode/border-audit/` (fetched images, gridline-overlay renders, detector
  prototype scripts, SQL files) — outside `MPCAutofill/`, not part of this deliverable, safe to
  delete.

## What changed in code

Nothing. `local_fallback.classify_bleed_edge`/`compute_bleed_diff_mm`/`classify_border_color`,
`local_art_edge.classify_art_edge_continuity`/`cast_art_edge_continuity_vote`, every
`*_CROP_BOX`/`_BORDER_SAMPLE_BANDS` constant, `image_evidence.py`'s extractor wiring, and
`golden_set.py`'s pinned values are byte-identical to `master`. No migration. No version bump —
none of `GEOMETRY_BLEED_EXTRACTOR_VERSION`/`LAYOUT_CLASS_EXTRACTOR_VERSION` describes a changed
computation, so bumping either would falsely invalidate ~220k already-extracted rows for no actual
behaviour change.
