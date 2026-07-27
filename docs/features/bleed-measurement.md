# Bleed measurement (`bleed_diff_mm`)

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
