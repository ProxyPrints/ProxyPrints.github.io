/**
 * Proposal B — export-time per-side bleed normalization (docs/proposals/proposal-b-bleed-
 * normalization.md). Pure measurement + plan-resolution math, deliberately independent of
 * canvas/DOM (mirrors layout.ts's split from PDF.tsx) so the algorithm is unit-testable without
 * a browser. bleedExtension.ts consumes a BleedPlan from here and does the actual pixel work.
 *
 * Measurement walks ~PROBE_COUNT evenly-spaced probe lines inward from each of the four edges,
 * looking for where the edge's own uniform-color run ends - that run is presumed bleed margin
 * (real print-prep bleed is typically a flat color extension or a smooth gradient near the
 * card's own edge), and where it ends is presumed the trim-line/card-content boundary. The
 * median across probes is robust to individual probes crossing art or text near an edge (a
 * borderless full-art card, a corner symbol); IQR spread across probes catches the case where
 * probes disagree enough that the median itself shouldn't be trusted.
 */

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
// CALIBRATION CAVEAT: every value below is a reasonable starting guess, not empirically tuned -
// the merge-time checklist carries a server-side calibration pass (~20-30 real catalog images
// across the fixture categories below) to replace these with measured values before this ships
// to real exports. Do not treat these as validated the way the backend's own bleed-edge
// classification constants (classify_bleed_edge's TRIM_ASPECT_RATIO/BLEED_ASPECT_RATIO,
// docs/features/printing-tags.md) were - those went through a real 40-source validation pass
// before shipping; these have not yet.
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
 * real bleed at all, synthesizing the full target on all four sides). In "auto" mode, each side
 * resolves independently: a confident (non-ambiguous, non-oversized) measurement wins; an
 * ambiguous or implausibly-oversized (>OVERSIZED_MULTIPLE x target) measurement falls back to
 * the prior.
 */
export function resolveBleedPlan(
  measurement: CardMeasurement,
  dpi: number,
  targetBleedMM: number,
  prior: BleedPrior,
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
  return Object.fromEntries(
    BLEED_SIDES.map((side) => {
      const { depthPx, ambiguous } = measurement[side];
      const measuredMM = pxToMM(depthPx, dpi);
      const oversized = measuredMM > targetBleedMM * OVERSIZED_MULTIPLE;
      if (ambiguous || oversized) {
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
