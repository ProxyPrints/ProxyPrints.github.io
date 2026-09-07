# Bleed measurement (`bleed_diff_mm`, `measured_bleed_mm`, `bleedProvenance`)

## What it is

`bleed_diff_mm` is a per-card floating-point field on `ImageEvidence` that
quantifies how far a card image's actual bleed margin deviates from the MPC
standard of 3.175 mm per edge.

A positive value means the image has **less** bleed than standard; negative
means **more**. Zero is perfect standard bleed.

## How it is measured

The standard MPC card has trim dimensions 63 mm × 88 mm plus a 3.175 mm bleed
on every edge. The full-image (pre-trim) aspect ratio at exact standard bleed
is therefore:

    r_bleed = (63 + 2·3.175) / (88 + 2·3.175) = 69.35 / 94.35 ≈ 0.73506

Given a fetched card image with pixel dimensions `w × h` (w < h for a portrait
card), the measured aspect ratio is `r = w / h`. Solving
`r = (63 + 2m) / (88 + 2m)` for the per-edge bleed margin `m`:

    m = (88·r − 63) / (2·(1 − r))     [mm]

`bleed_diff_mm = 3.175 − m`.

Implementation: `measure_bleed_diff_mm(card_image)` in
`cardpicker/local_fallback.py` (PROTECTED CORE; added under an explicit owner
exception for this function only). Returns `None` for degenerate inputs
(zero-height image or aspect ratio ≥ 1.0).

## Where it is written

Stage C's `geometry_bleed` extractor block in `extract_card_evidence`
(`cardpicker/image_evidence.py`) calls `measure_bleed_diff_mm` and writes
`fields["bleed_diff_mm"]` when the result is not `None`.

## Model field

`ImageEvidence.bleed_diff_mm = FloatField(null=True, blank=True)` — migration
`0087_imageevidence_bleed_diff_mm`.

## Golden set

All 30 golden cards have `bleed_diff_mm` expectations in
`GOLDEN_EXPECTATIONS["bleed_diff_mm"]` (`cardpicker/golden_set.py`). Most
production cards (standard 750×1050 px) show ≈ −0.0189 mm (minimal
over-bleed); some older scans and borderless cards show larger deviations.

## What it is not

This field measures the image's geometric bleed from its pixel dimensions
alone — not whether the art fills the bleed region, not a content-aware crop
analysis. It is a pure aspect-ratio calculation with no image-content analysis.

## Cross-checked consumer API: `measured_bleed_mm()` and `bleedProvenance`

`Card.measured_bleed_mm()` (`cardpicker/models.py`) returns this card's
**cross-checked** measured bleed in millimetres. It uses the calculator's
two-method cross-check (`calculate_bleed_verdict` in
`cardpicker/local_bleed_calculator.py`), not Method A alone.

### Preference order

1. **Method B preferred** — where Method B (pinline-ruler, per-edge) is
   present and agrees with Method A (aspect-ratio-derived) inside the 2 mm
   gate, `measured_bleed_mm()` returns Method B's mean value.
2. **Method A fallback** — where only Method A is present, or Method B is
   absent/inapplicable, the Method A value is returned.
3. **Abstain** — where both methods are present and disagree beyond the 2 mm
   gate (`METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM`), the method returns
   `None`. The `bleedProvenance` field reports `"abstained"` in this case.
4. **No evidence** — where no current `ImageEvidence` row has completed the
   `geometry_bleed` extractor, the method returns `None` and
   `bleedProvenance` reports `"no-evidence"`.

### Provenance tracking

`bleedProvenance` (on the serialised card schema) records which method
answered. Possible values:

| Value           | Meaning                                                             |
| --------------- | ------------------------------------------------------------------- |
| `"method-b"`    | Pinline-ruler per-edge measurement (preferred when agreeing with A) |
| `"method-a"`    | Aspect-ratio-derived closed form (fallback)                         |
| `"abstained"`   | Both methods present, disagreed beyond the 2mm gate                 |
| `"no-evidence"` | No completed geometry_bleed extractor on current evidence           |

This field lets consumers (e.g. issue #978's proposed editor cut-line) distinguish
a real per-card measurement from one of Method A's three dominant constants.

### Readers

The following locations read `measured_bleed_mm()` or the serialised
`measuredBleedMm`/`bleedProvenance` fields:

- `question_feed.py:_log_served` — attaches the value and provenance to
  the served question feed item's card after the card is chosen (not during
  pool eligibility scanning, so zero cost elsewhere).
- `schema_types.py:Card` / `schema_types.ts:Card` — the serialised card
  schema carries both `measuredBleedMm` (nullable float) and
  `bleedProvenance` (the four-value enum above). These are the fields the
  frontend reads.
- No other backend consumers currently call `measured_bleed_mm()` directly;
  the question feed's `_log_served` is the sole attachment point.
