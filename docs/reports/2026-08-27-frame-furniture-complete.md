```
TASK: frame furniture, complete mask (measure/frame-furniture-complete branch, no PR/commit
yet beyond this checkpoint) — extend the sibling frame-furniture-mask measurement's PARTIAL
mask (5 documented ImageEvidence crop boxes) with a COMPLETE mask that additionally excludes
the four card-specific regions with no stored geometry (mana cost, type line, P/T box, loyalty
box), derived by eye from a rendered coordinate grid over real sample cards, and report both
variants' coverage/distance/clustering side by side.

WHAT SHIPPED SO FAR (checkpoint, analysis in progress):
1. Read-only DB query (docker exec mpcautofill_django python manage.py shell,
   .filter()/.values() only) confirmed all 149 images in /home/ubuntu/frame-label-images/ have
   a current ImageEvidence row with all five documented crop boxes populated, plus
   CanonicalPrintingMetadata.frame for the weak sanity check. All 149 share
   width=1251/height=1702/bleed_class="bleed", so the five documented boxes reduce to one
   shared fractional definition.
2. Derived the four missing boxes by rendering a labelled 0.05-fraction grid over 10 real
   sample cards (2 per era, one creature + one non-creature, 2015 slot doubling as the only
   planeswalker sample) and reading coordinates off by eye (Read tool image view, not a
   summarizing tool) — full per-image readings in scratch/build_masks.py's docstring.
3. Built PARTIAL and COMPLETE boolean masks, computed coverage (PARTIAL 35.73%, COMPLETE
   26.04% of canvas survives), and the marginal contribution of each of the four new boxes.
4. Rendered and visually inspected mask overlays on 5 era samples x 2 variants (10 images) —
   confirmed the masks tint the intended regions and generalize across the planeswalker's
   different frame proportions.

DEVIATIONS: none yet from the assigned method; two findings surfaced during construction are
recorded in the artifact report rather than treated as deviations:
  - pt_box and loyalty_box (2 of the 4 new regions) turn out to already be fully covered by the
    documented artist_crop_px band (full-width, y 0.82-1.00) — their marginal contribution to
    COMPLETE's coverage is ~0. mana_cost and type_line carry the real difference.
  - Neither PARTIAL nor COMPLETE excludes the rules-text/ability-text box, which is exactly as
    card-specific as the four named regions and larger by area — flagged as a scope limitation
    of the task's own four-region list, not fixed unilaterally.
  - One planeswalker sample uses a nonstandard top-left color-pip position instead of the
    standard top-right mana cost; not folded into mana_cost's box on a single sample (would
    over-reach into card-name territory for the other 148 images) — disclosed as an open gap.

VERIFICATION: coverage numbers computed via scratch/build_masks.py (numpy boolean rasterization);
overlays rendered via scratch/render_overlays.py and inspected directly with the Read tool
(image attachment), not summarized. Deferred: pixel-distance comparison, no-era clustering,
purity-vs-frame_value weak check, confound check (set/source/resolution/aspect) — all in
progress, will land in the same artifact directory.

OPEN ITEMS:
1. None requiring a decision yet — proceeding per the assigned method.

LIVE STATE: artifacts at /home/ubuntu/pipeline-artifacts/frame-furniture-complete/ (report.md,
mask_boxes.json, output/overlays/*.png) — NOT yet the final report, will be overwritten.
Scratch work at /tmp/opencode/frame-furniture-complete/{scratch,output}/ (own directory, sibling
run's /tmp/opencode/frame-furniture-mask/ was read from for reference only, never written to).
This file is a checkpoint commit on measure/frame-furniture-complete, pushed to origin, before
the pixel-distance/clustering pass. No database writes, no image fetches (all local disk), no
mutating management commands.
```
