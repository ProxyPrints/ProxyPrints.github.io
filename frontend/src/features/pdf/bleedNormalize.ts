/**
 * Proposal B — export-time per-side bleed normalization (docs/proposals/proposal-b-bleed-
 * normalization.md). Pure measurement + plan-resolution math, deliberately independent of
 * canvas/DOM (mirrors layout.ts's split from PDF.tsx) so the algorithm is unit-testable without
 * a browser. bleedExtension.ts consumes a BleedPlan from here and does the actual pixel work.
 *
 * PLAN INPUT HIERARCHY (task #134, 2026-07-18 - see CALIBRATION PASS comment below for why):
 * the PRIMARY signal is the source image's own pixel dimensions, classified against the
 * standard trim/bleed aspect ratios (classifyBleedAspectRatio) - a card's frame color has no
 * bearing on its own file dimensions, so this is unaffected by the confound that broke the
 * probe walk. The probe walk (measureCardBleedPx, next paragraph) is demoted to two advisory
 * roles with ZERO trim authority: per-side ambiguity detection (still forces that side to the
 * prior/manual-override fallback, unchanged from before) and detectBleedAsymmetry's manual-
 * review flag (informational only, never alters the resolved plan). See resolveBleedPlan's own
 * doc comment for the full resolution order.
 *
 * Measurement walks ~PROBE_COUNT evenly-spaced probe lines inward from each of the four edges,
 * looking for where the edge's own uniform-color run ends - that run is presumed bleed margin
 * (real print-prep bleed is typically a flat color extension or a smooth gradient near the
 * card's own edge), and where it ends is presumed the trim-line/card-content boundary. The
 * median across probes is robust to individual probes crossing art or text near an edge (a
 * borderless full-art card, a corner symbol); IQR spread across probes catches the case where
 * probes disagree enough that the median itself shouldn't be trusted.
 */

import { CardHeightMM, CardWidthMM } from "@/common/constants";

/** RGBA pixel data + dimensions - structurally compatible with a real ImageData (so a caller
 * can pass one directly) but declared independently so tests can build synthetic fixtures
 * without any canvas/DOM API. */
export interface PixelBuffer {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

export type BleedSide = "top" | "bottom" | "left" | "right";
export const BLEED_SIDES: BleedSide[] = ["top", "bottom", "left", "right"];

// Named per the spec's explicit "ship as named constants with a calibration caveat" requirement.
//
// CALIBRATION PASS (2026-07-18): ran against 30 real catalog images spanning 10 distinct
// sources, 6 DPIs (460-1240), both jpg/png - not the synthetic six-category fixture set (that
// already exists in bleedNormalize.test.ts and covers the algorithm's *logic*; this pass is
// about real photographic/scan noise). Ground truth was assigned per-image via the same
// aspect-ratio classification the backend's already-validated `classify_bleed_edge` uses
// (TRIM_ASPECT_RATIO/BLEED_ASPECT_RATIO, docs/features/printing-tags.md) - not a DB vote lookup,
// since the negative-only voting change means a "bleed" reading casts no vote at all, but the
// file's own dimensions already encode the same signal deterministically. Split 28 bleed / 2
// trimmed (consistent with the backend's own ~97.5% bleed-prevalence finding on a different,
// larger sample). Full data: 30 images, per-side measurements, and the sweep below live in the
// PR that added this comment (docs/reports/2026-07-18-bleed-calibration-134.md).
//
// RESULT: none of the 4 constants below changed. Not because nothing was found - a real,
// reproducible measurement bias WAS found (next paragraph) - but because sweeping each constant
// against the real sample didn't show any single value cleanly fixing it, and forcing a fix
// through a constant not designed for it (see below) would be a behavior change beyond this
// pass's calibration charter. Left at the original starting-guess values pending a real design
// follow-up, tracked below rather than patched blind.
//
// FINDING: real bleed-classified images measure a median per-side depth of ~5.8-6.3mm against a
// true bleed target of 3.175mm (1/8" at 63x88mm trim) - roughly 2x the expected value, and
// consistent (Evil Twin @460dpi: top/left/right ~5.5mm, bottom 9.2mm; Nebula_Back3 @1210dpi: all
// four sides ~5.7-5.9mm). Root-caused, not just observed: sweeping RGB_DISTANCE_THRESHOLD from
// 24 down to 6 (4x stricter) moved the sample median by under 3% (5.90mm -> 5.76mm) - ruling out
// "threshold too loose" as the cause. Image dimensions were independently confirmed to match the
// bleed-inclusive aspect ratio at each card's own declared DPI (within <1%), ruling out a DPI-
// metadata bug. The real cause: a typical MTG card's own physical border/frame is *also* a flat,
// uniform color (commonly black) immediately inside the synthetic bleed extension, which is
// deliberately colored to match the frame so print misalignment doesn't show a visible seam -
// the probe's uniform-color-run walk can't tell "still inside the bleed extension" from "now
// inside the card's own border" when both are the same color, so it measures bleed+border
// combined, not bleed alone. This isn't a threshold problem; it's the measurement's core
// assumption (uniform run = bleed) not holding once a normal card frame's own uniform border
// sits right next to it.
//
// WHY NOT JUST LOWER OVERSIZED_MULTIPLE: it's tempting to fix this via the 4th constant (it's
// one of the "4 named constants" in scope), since a ~2x overshoot could be pushed under the
// oversized-fallback path by tightening the multiple. Deliberately not done here: the approved
// spec defines OVERSIZED_MULTIPLE as a bad-DPI-metadata guard specifically, not a border-color
// guard - repurposing it to paper over a different, now-understood failure mode is a
// resolveBleedPlan behavior change dressed as a calibration tweak, decided unilaterally, on code
// another session is concurrently touching (see docs/lessons.md's stacked-PR/collision entries
// from this same day). That decision belongs to the spec owner, not a same-session judgment call.
//
// PRODUCTION RISK, flagged not fixed: at the current OVERSIZED_MULTIPLE=3, a 3.175mm target's
// oversized cutoff is ~9.5mm - most real overshoots observed here (5.5-6.5mm) sit *under* that
// cutoff, so resolveBleedPlan's `targetBleedMM - measuredMM` arithmetic produces a *negative*
// plan value (a trim instruction) on typical real bled cards, cropping ~2-3mm into the card's
// own border content, not just excess bleed. This is a real, non-hypothetical risk on the common
// case (28/30 of this sample), not an edge case - tracked as a follow-up design item, not built
// here (see docs/proposals/proposal-b-bleed-normalization.md's "Tracked, not building" section).
//
// Do not treat the values below as validated the way the backend's own bleed-edge classification
// constants were (a real 40-source pass before shipping) - this pass ran, found a real issue, and
// left them as starting guesses pending the design follow-up above, which is a different state
// from "unvalidated" or "validated."
//
// SUPERSEDED (2026-07-18, same day, task #134's design follow-up): the "production risk" flagged
// above is fixed - resolveBleedPlan no longer trusts the probe walk to drive trim/extend
// decisions at all. Root cause (a card's own border being the same flat color as its bleed
// margin) is structural to color-run measurement - it's not a threshold or constant this
// measurement approach could ever tune its way out of, because the invisibility IS the bleed
// extension doing its job (seamless with the frame, by design). The fix instead promotes the
// source image's own pixel dimensions to the PRIMARY signal (classifyBleedAspectRatio +
// dimensionDerivedBleedMM, below) - a card's file dimensions carry the same trim/bleed math
// regardless of border color, so they don't share the probe walk's confound. The four constants
// below still govern the probe walk's remaining advisory roles (per-side ambiguity fallback,
// detectBleedAsymmetry's manual-review flag) but no longer reach the plan's arithmetic directly.
// See resolveBleedPlan's own doc comment for the full resolution order, and
// docs/reports/2026-07-18-bleed-calibration-134.md for the measurement bias this responds to.
export const PROBE_COUNT = 20;
/** Euclidean RGB distance (0-441, sqrt(255^2*3)) above which two pixels are "different enough"
 * to mark the end of a uniform bleed-margin run. */
export const RGB_DISTANCE_THRESHOLD = 24;
/** A probe's run-length spread (Q3-Q1) wider than this fraction of MAX_SCAN_DEPTH_PX marks the
 * whole side ambiguous - the probes disagree too much for the median to be trustworthy. */
export const IQR_AMBIGUITY_FRACTION = 0.5;
/** A measured depth more than this multiple of the target bleed is treated as bad DPI metadata
 * rather than a real oversized bleed margin, per the approved spec. */
export const OVERSIZED_MULTIPLE = 3;

/** Starting guess, not itself calibrated the way the four constants above were (task #134's
 * calibration pass measured absolute per-side depth against a fixed target, not cross-side
 * spread) - flagged for a future pass the same way the original four were shipped. */
export const ASYMMETRY_FLAG_THRESHOLD_MM = 2;

// -------------------------------------------------------------------------------------------
// Dimension-derived bleed classification (task #134's PRIMARY plan-resolution signal - see the
// module comment above). Mirrors the backend's already-validated aspect-ratio classification
// exactly: same reference geometry (63x88mm trim, 3.175mm/side standard bleed convention), same
// 0.03 tolerance, same "abstain past both known ratios" shape (MPCAutofill/cardpicker/
// local_fallback.py's classify_bleed_edge/TRIM_ASPECT_RATIO/BLEED_ASPECT_RATIO) - validated
// there against a real 40-source sample (bleed cluster 0.7325-0.7393 vs theoretical 0.7350, the
// one trimmed example at 0.7163 vs theoretical 0.7159: a clean, well-separated bimodal signal
// with nothing observed in the gap between clusters). Geometric and DPI-independent: a source
// image's raw pixel dimensions encode the same trim/bleed math regardless of resolution or
// whether the card's own border reads as a normal frame or borderless full-art - exactly why
// this is trustworthy where the probe walk (frame-color confound) isn't.
// -------------------------------------------------------------------------------------------

/** Not the same value as a caller's chosen output bleedEdgeMM target (which can be anything,
 * including 0) - this is the fixed standard bleed convention baked into BLEED_ASPECT_RATIO
 * itself, matching the backend's _BLEED_MARGIN_MM exactly. */
const STANDARD_BLEED_MARGIN_MM = 3.175;

export const TRIM_ASPECT_RATIO = CardWidthMM / CardHeightMM;
export const BLEED_ASPECT_RATIO =
  (CardWidthMM + 2 * STANDARD_BLEED_MARGIN_MM) /
  (CardHeightMM + 2 * STANDARD_BLEED_MARGIN_MM);
/** Ratio units (unitless), not mm - how far a source's aspect ratio may sit from both known
 * reference ratios before it's treated as ambiguous rather than misclassified. */
export const ASPECT_CLASSIFICATION_TOLERANCE = 0.03;

export type BleedAspectClassification = "bleed" | "trimmed" | "abstain";

/** Classifies a source image's own pixel dimensions against the standard trim/bleed aspect
 * ratios. "abstain" covers both a genuinely non-standard image (a token, a double-faced
 * composite scan, a corrupted fetch) and the degenerate height===0 case - both fall back to the
 * prior/manual-override chain in resolveBleedPlan, the same as an ambiguous probe measurement
 * always has. */
export function classifyBleedAspectRatio(
  widthPx: number,
  heightPx: number
): BleedAspectClassification {
  if (heightPx === 0) {
    return "abstain";
  }
  const ratio = widthPx / heightPx;
  const distToTrim = Math.abs(ratio - TRIM_ASPECT_RATIO);
  const distToBleed = Math.abs(ratio - BLEED_ASPECT_RATIO);
  if (Math.min(distToTrim, distToBleed) > ASPECT_CLASSIFICATION_TOLERANCE) {
    return "abstain";
  }
  return distToBleed < distToTrim ? "bleed" : "trimmed";
}

/** Bounds how far a single probe walks inward, both to bound cost and to give "the whole
 * scanned depth was uniform" (a degenerate, ambiguous result) a concrete meaning. Scaled to the
 * oversized threshold so a genuinely-normal image can't get capped before OVERSIZED_MULTIPLE's
 * own check would fire. */
const maxScanDepthPx = (targetBleedPx: number): number =>
  Math.max(1, Math.round(targetBleedPx * (OVERSIZED_MULTIPLE + 1)));

const rgbDistance = (
  data: Uint8ClampedArray,
  aOffset: number,
  bOffset: number
): number => {
  const dr = data[aOffset] - data[bOffset];
  const dg = data[aOffset + 1] - data[bOffset + 1];
  const db = data[aOffset + 2] - data[bOffset + 2];
  return Math.sqrt(dr * dr + dg * dg + db * db);
};

/** One probe: from the edge-most pixel at (x, y) walking inward by (dx, dy) per step, how many
 * consecutive pixels stay within rgbDistanceThreshold of the edge pixel before one doesn't -
 * that count is this probe's measured run length. Reaching maxDepth without ever exceeding the
 * threshold returns maxDepth itself (the degenerate "fully uniform" case). */
function probeRunLengthPx(
  buffer: PixelBuffer,
  x: number,
  y: number,
  dx: number,
  dy: number,
  maxDepth: number,
  rgbDistanceThreshold: number
): number {
  const edgeOffset = (y * buffer.width + x) * 4;
  for (let depth = 1; depth <= maxDepth; depth++) {
    const px = x + dx * depth;
    const py = y + dy * depth;
    if (px < 0 || px >= buffer.width || py < 0 || py >= buffer.height) {
      return depth - 1;
    }
    const offset = (py * buffer.width + px) * 4;
    if (rgbDistance(buffer.data, edgeOffset, offset) > rgbDistanceThreshold) {
      return depth - 1;
    }
  }
  return maxDepth;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function interquartileRange(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const q = (fraction: number): number => {
    const pos = fraction * (sorted.length - 1);
    const lower = Math.floor(pos);
    const upper = Math.ceil(pos);
    return lower === upper
      ? sorted[lower]
      : sorted[lower] + (sorted[upper] - sorted[lower]) * (pos - lower);
  };
  return q(0.75) - q(0.25);
}

export interface SideMeasurement {
  depthPx: number;
  /** True when the probes disagreed too much (wide IQR) or the median itself is degenerate
   * (0, or the full scan depth) - the FALLBACK path (resolveBleedPlan) governs this side
   * instead of the raw measurement. */
  ambiguous: boolean;
}

/** Measures one side by walking PROBE_COUNT evenly-spaced probes inward, perpendicular to that
 * edge, and taking the median run length. targetBleedPx bounds the scan depth (see
 * maxScanDepthPx) - it does not otherwise bias the measurement. */
export function measureSideBleedPx(
  buffer: PixelBuffer,
  side: BleedSide,
  targetBleedPx: number,
  probeCount: number = PROBE_COUNT,
  rgbDistanceThreshold: number = RGB_DISTANCE_THRESHOLD,
  iqrAmbiguityFraction: number = IQR_AMBIGUITY_FRACTION
): SideMeasurement {
  const maxDepth = maxScanDepthPx(targetBleedPx);
  const along =
    side === "top" || side === "bottom" ? buffer.width : buffer.height;
  const depths: number[] = [];
  for (let i = 0; i < probeCount; i++) {
    // Evenly spaced, inset from both ends by half a step so no probe sits exactly on a corner
    // (corners are the likeliest place for a rounded/anti-aliased trim edge to confuse a
    // single-pixel-wide probe - see the "asymmetric" test fixture for a case this matters for).
    const step = along / probeCount;
    const position = Math.round(step / 2 + i * step);
    let x: number, y: number, dx: number, dy: number;
    switch (side) {
      case "top":
        x = position;
        y = 0;
        dx = 0;
        dy = 1;
        break;
      case "bottom":
        x = position;
        y = buffer.height - 1;
        dx = 0;
        dy = -1;
        break;
      case "left":
        x = 0;
        y = position;
        dx = 1;
        dy = 0;
        break;
      case "right":
        x = buffer.width - 1;
        y = position;
        dx = -1;
        dy = 0;
        break;
    }
    depths.push(
      probeRunLengthPx(buffer, x, y, dx, dy, maxDepth, rgbDistanceThreshold)
    );
  }

  const depthPx = median(depths);
  const spread = interquartileRange(depths);
  const degenerate = depthPx === 0 || depthPx === maxDepth;
  const ambiguous = degenerate || spread > maxDepth * iqrAmbiguityFraction;

  return { depthPx, ambiguous };
}

export type CardMeasurement = Record<BleedSide, SideMeasurement>;

/** Measures all four sides. dpiValue converts each side's px measurement to mm (see
 * measurementPxToMM) at the call site - kept separate here so the pure px-domain measurement
 * stays independent of any particular dpi. */
export function measureCardBleedPx(
  buffer: PixelBuffer,
  targetBleedPx: number,
  probeCount: number = PROBE_COUNT,
  rgbDistanceThreshold: number = RGB_DISTANCE_THRESHOLD,
  iqrAmbiguityFraction: number = IQR_AMBIGUITY_FRACTION
): CardMeasurement {
  return Object.fromEntries(
    BLEED_SIDES.map((side) => [
      side,
      measureSideBleedPx(
        buffer,
        side,
        targetBleedPx,
        probeCount,
        rgbDistanceThreshold,
        iqrAmbiguityFraction
      ),
    ])
  ) as CardMeasurement;
}

export const pxToMM = (px: number, dpi: number): number => (px * 25.4) / dpi;
export const mmToPx = (mm: number, dpi: number): number => (mm * dpi) / 25.4;

/** The per-side bleed depth implied directly by the source's own pixel dimensions against the
 * standard 63x88mm trim size, split evenly between opposing sides - a source is never bled more
 * on one physical side than its opposite (only where the trim/content sits WITHIN that bleed
 * can shift, which is exactly the per-side independence the probe walk was chasing and
 * confounding on - see the module comment). Can come out negative (the source is narrower/
 * shorter than the bare trim size) when dpi metadata is wrong - resolveBleedPlan's oversized
 * guard catches that, not this function. */
function dimensionDerivedBleedMM(
  sourceWidthPx: number,
  sourceHeightPx: number,
  dpi: number
): Record<BleedSide, number> {
  const widthExcessPx = sourceWidthPx - mmToPx(CardWidthMM, dpi);
  const heightExcessPx = sourceHeightPx - mmToPx(CardHeightMM, dpi);
  const perSideWidthMM = pxToMM(widthExcessPx / 2, dpi);
  const perSideHeightMM = pxToMM(heightExcessPx / 2, dpi);
  return {
    left: perSideWidthMM,
    right: perSideWidthMM,
    top: perSideHeightMM,
    bottom: perSideHeightMM,
  };
}

/** Advisory only - a probe-measured spread across the four sides wider than thresholdMM marks
 * the card worth a human's manual-override look (task #134's calibration found e.g. Evil Twin's
 * top/left/right ~5.5mm vs bottom ~9.2mm, a ~3.7mm spread never explained - see the calibration
 * report's "Bottom-edge asymmetry" section), but never changes the resolved plan itself - probes
 * have zero trim authority post-#134 (see resolveBleedPlan). No UI consumer wired yet; exported
 * for one, the same way E-2's degradedQueries flag shipped ahead of its first consumer. */
export function detectBleedAsymmetry(
  measurement: CardMeasurement,
  dpi: number,
  thresholdMM: number = ASYMMETRY_FLAG_THRESHOLD_MM
): boolean {
  const depthsMM = BLEED_SIDES.map((side) =>
    pxToMM(measurement[side].depthPx, dpi)
  );
  const spreadMM = Math.max(...depthsMM) - Math.min(...depthsMM);
  return spreadMM > thresholdMM;
}

/** The appropriate-bleed machine-vote lean for a card, read via APIGetTagConsensus (the same
 * per-card confidence-fill path the attribute chips use - see store/api.ts, already exists, no
 * new endpoint). "unresolved" covers both "no vote at all" and "a vote exists but doesn't lean
 * clearly either way" - the spec's fallback treats both the same as "trimmed" (extend full
 * target), the safer assumption when the signal genuinely doesn't say "bleed". */
export type BleedPrior = "bleed" | "trimmed" | "unresolved";

export type ManualOverride = "auto" | "force-bleed" | "force-trimmed";

/** Per-side plan in mm: positive = extend outward by this much (deficit), negative = trim
 * inward by this much (excess), 0 = source already matches the target exactly. Mutually
 * exclusive by construction - a side is never both trimmed and extended. */
export type BleedPlan = Record<BleedSide, number>;

function priorAdjustmentMM(prior: BleedPrior, targetBleedMM: number): number {
  // "machine says bleed -> extend 0; trimmed or unresolved -> extend full target" (approved
  // spec's FALLBACK section, verbatim).
  return prior === "bleed" ? 0 : targetBleedMM;
}

/**
 * Resolves the final per-side plan. manualOverride, when not "auto", wins outright for every
 * side (force-bleed treats the source as if it already exactly matches the target on all four
 * sides - today's pre-Proposal-B behavior for that card; force-trimmed treats it as having no
 * real bleed at all, synthesizing the full target on all four sides).
 *
 * In "auto" mode (task #134, superseding the original probe-driven design - see the module
 * comment and the CALIBRATION PASS comment above PROBE_COUNT): the PRIMARY signal is the
 * source's own pixel dimensions, classified against the standard trim/bleed aspect ratios
 * (classifyBleedAspectRatio, same method + constants as the backend's classify_bleed_edge). A
 * non-abstain classification means the image's raw dimensions are trustworthy evidence of how
 * much real bleed margin it already carries (dimensionDerivedBleedMM) - that's what actually
 * resolves the plan now. The probe walk (measureCardBleedPx) is demoted to advisory-only, ZERO
 * trim authority: a per-side ambiguous flag still forces that side to the prior fallback
 * (preserves the original degenerate/full-art handling - e.g. a solid-color card back or
 * full-bleed art proxy, where probes read the whole scan depth as one uniform run, regardless
 * of what the aspect classification says). detectBleedAsymmetry, exported separately, flags a
 * card for manual review without altering this function's output at all. An abstain
 * classification (image aspect ratio isn't close to either reference - a token, a double-faced
 * composite scan, a corrupted fetch) falls back to the prior/manualOverride chain exactly as an
 * ambiguous probe measurement always has. The OVERSIZED_MULTIPLE bad-DPI guard still applies,
 * now against the dimension-derived measurement instead of the probe one - checked in both
 * directions, since a dimension-derived value can come out implausibly negative (DPI metadata
 * overstated, inflating the trim-px subtracted from the source's real dimensions) in a way a
 * probe run length (always >= 0) never could.
 */
export function resolveBleedPlan(
  measurement: CardMeasurement,
  dpi: number,
  targetBleedMM: number,
  prior: BleedPrior,
  sourceWidthPx: number,
  sourceHeightPx: number,
  manualOverride: ManualOverride = "auto"
): BleedPlan {
  if (manualOverride === "force-bleed") {
    return Object.fromEntries(
      BLEED_SIDES.map((side) => [side, 0])
    ) as BleedPlan;
  }
  if (manualOverride === "force-trimmed") {
    return Object.fromEntries(
      BLEED_SIDES.map((side) => [side, targetBleedMM])
    ) as BleedPlan;
  }

  const fallbackMM = priorAdjustmentMM(prior, targetBleedMM);
  const classification = classifyBleedAspectRatio(
    sourceWidthPx,
    sourceHeightPx
  );
  const dimensionMM =
    classification === "abstain"
      ? null
      : dimensionDerivedBleedMM(sourceWidthPx, sourceHeightPx, dpi);

  return Object.fromEntries(
    BLEED_SIDES.map((side) => {
      const { ambiguous } = measurement[side];
      if (ambiguous || dimensionMM === null) {
        return [side, fallbackMM];
      }
      const measuredMM = dimensionMM[side];
      const oversized =
        Math.abs(measuredMM) > targetBleedMM * OVERSIZED_MULTIPLE;
      if (oversized) {
        return [side, fallbackMM];
      }
      // Positive when the source falls short of the target (extend); negative when it
      // overshoots (trim) - a single signed value, per the module comment above.
      return [side, targetBleedMM - measuredMM];
    })
  ) as BleedPlan;
}

/**
 * Cheap, preview-only hedge for whether export is EXPECTED to synthesize bleed for this card
 * (Proposal B PR-3's badge, "bleed will be generated"). Deliberately does NOT run the real
 * per-side probe measurement - the WYSIWYG preview (Proposal A) is a cheap CSS approximation on
 * small thumbnails, not a full-resolution decode, so no real CardMeasurement is available to it
 * (see the approved spec's own "PREVIEW INTERACTION" line: real edge-extension happens ONLY at
 * export). This mirrors resolveBleedPlan's manualOverride/prior precedence exactly, minus the
 * per-side measurement branch, since a manual override is the one signal that's both already
 * resolved synchronously (no network, no canvas) AND fully determines the outcome the same way a
 * real measurement would - the closest available stand-in for "the measurement where available".
 */
export function willLikelyGenerateBleed(
  prior: BleedPrior,
  manualOverride: ManualOverride = "auto"
): boolean {
  if (manualOverride === "force-bleed") {
    return false;
  }
  if (manualOverride === "force-trimmed") {
    return true;
  }
  return prior !== "bleed";
}
