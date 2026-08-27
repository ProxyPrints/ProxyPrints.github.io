```
TASK: frame furniture, complete mask (measure/frame-furniture-complete branch, no PR — this is
a measurement task, artifacts live outside the repo) — extend the sibling frame-furniture-mask
measurement's PARTIAL mask (5 documented ImageEvidence crop boxes) with a COMPLETE mask that
additionally excludes the four card-specific regions with no stored geometry (mana cost, type
line, P/T box, loyalty box), derived by eye from a rendered coordinate grid over real sample
cards, and report both variants' coverage/distance/clustering side by side.

WHAT SHIPPED:
1. Read-only DB query (docker exec mpcautofill_django python manage.py shell,
   .filter()/.values() only) confirmed all 149 images in /home/ubuntu/frame-label-images/ have
   a current ImageEvidence row with all five documented crop boxes populated, plus
   CanonicalPrintingMetadata.frame for the weak sanity check (found to match era_folder exactly
   for all 149 — the folders were evidently curated from this field).
2. Derived the four missing boxes by rendering a labelled 0.05-fraction grid over 10 real
   sample cards (2 per era, one creature + one non-creature, 2015 slot doubling as the only
   planeswalker sample) and reading coordinates off by eye. Final boxes: mana_cost
   (0.66,0.05,0.93,0.20), type_line (0.00,0.53,1.00,0.68), pt_box (0.70,0.82,1.00,0.95),
   loyalty_box (0.83,0.82,1.00,0.95).
3. Built PARTIAL and COMPLETE masks: coverage 35.73%→26.04% (designed), 35.77%→26.24%
   (empirical). Found pt_box/loyalty_box contribute ~0 marginal coverage (already inside the
   documented artist_crop_px band); mana_cost/type_line carry the real 9.67pp difference.
4. FOUND AND FIXED A REAL BUG mid-analysis: 146/149 on-disk images have per-image black
   letterbox padding (content-bbox aspect ratio spans 0.684-0.806) that a first pass's
   fraction-based masking silently misaligned against — caught by direct visual inspection of
   the overlays (the exact method step this failure mode targets) and cross-checked against the
   sibling run's own card_bbox_aspect_ratio field, which shows they hit and fixed the same
   issue independently. Corrected by detecting each image's own content bbox and cropping to it
   before applying any fractional box; the uncorrected run's silhouette scores were measurably
   higher (0.23-0.32 vs corrected 0.14-0.21) — the letterbox itself was generating spurious
   apparent structure.
5. Direct pixel-distance comparison (no hashing, 300x408 common canvas, masked-region-only
   Euclidean distance) over all 149x148/2 pairs, both variants: within-era and cross-era means
   differ by under 0.2% — no separation, for PARTIAL or COMPLETE.
6. Unsupervised clustering (average-linkage, k=2..8 by silhouette, no era info as input): best
   k=2 both variants (silhouette 0.20-0.21, weak). k=5 purity 26.85%/27.52% vs a ~20.1%
   one-cluster floor — barely above chance. Checked what k=2 actually tracks: mean brightness
   (186 vs 103 in the two clusters), not era — confound identified and reported directly, not
   inferred.
7. Cross-checked against the sibling run's own artifacts (existed by the time this run reached
   its analysis step): PARTIAL coverage 35.57% (theirs) vs 35.73-35.77% (this run) — no
   disagreement. k=5 purity 26.85% (theirs) vs 26.85% (this run's PARTIAL) — exact match despite
   independent implementations. Their own separately-tuned "Variant B" (9.78% coverage) is a
   different construction than this run's COMPLETE, not reconciled further (answers a different
   question, and their own report notes it still leaked on 4/5 spot-checks).
8. Report + sample.json + mask_boxes.json + content_bboxes.json + cluster_results_v2.json +
   scratch scripts + 20 overlay/grid images shipped to
   /home/ubuntu/pipeline-artifacts/frame-furniture-complete/.

DEVIATIONS: none from the assigned method. Two premise concerns surfaced and are reported
in-artifact rather than silently fixed:
  - Neither PARTIAL nor COMPLETE excludes the rules-text/ability-text box (~11.2% of canvas,
    larger than mana_cost+type_line's combined 9.67pp marginal contribution) — flagged as a
    scope limitation of the task's own four-region list, not unilaterally added as a fifth
    exclusion (would change what PARTIAL-vs-COMPLETE isolates).
  - The one planeswalker sample uses a nonstandard top-left color-pip position instead of a
    standard top-right mana cost; not folded into mana_cost's box on a single sample (would
    over-reach into card-name territory for the other 148 images) — disclosed as an open gap,
    not resolved by invented geometry.

VERIFICATION: coverage via numpy boolean rasterization; overlays rendered and inspected directly
with the Read tool's image view (not summarized) both before AND after the letterbox bugfix;
distance/clustering via scipy/sklearn on the bbox-corrected pipeline; cross-checked against the
sibling run's independently-produced artifacts. 7 cluster-count configurations (k=2..8) swept
and all reported, none cherry-picked.

OPEN ITEMS / DECISIONS NEEDED:
1. None requiring owner input — this is a completed negative-result measurement, converging
   with the sibling run's own independent negative result.

LIVE STATE: final artifacts at /home/ubuntu/pipeline-artifacts/frame-furniture-complete/
(report.md, sample.json, mask_boxes.json, content_bboxes.json, cluster_results_v2.json,
scratch/*.py, output/overlays/*.png — 20 images). Scratch work at
/tmp/opencode/frame-furniture-complete/{scratch,output}/ (own directory; sibling run's
/tmp/opencode/frame-furniture-mask/ was read from for reference/cross-check only, never written
to). This is the final commit on measure/frame-furniture-complete, pushed to origin. No database
writes, no image fetches (all local disk), no mutating management commands.
```
