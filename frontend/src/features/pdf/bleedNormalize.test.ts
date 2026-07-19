import {
  ASYMMETRY_FLAG_THRESHOLD_MM,
  BLEED_ASPECT_RATIO,
  BLEED_SIDES,
  BleedSide,
  classifyBleedAspectRatio,
  detectBleedAsymmetry,
  measureCardBleedPx,
  OVERSIZED_MULTIPLE,
  PixelBuffer,
  resolveBleedPlan,
  TRIM_ASPECT_RATIO,
  willLikelyGenerateBleed,
} from "@/features/pdf/bleedNormalize";

const WIDTH = 200;
const HEIGHT = 260;
const TARGET_BLEED_PX = 10;
// Chosen so px and mm are numerically identical (25.4mm = 1 inch = this many px at this dpi) -
// not a realistic dpi, just removes unit-conversion noise from the assertions below.
const IDENTITY_DPI = 25.4;

// WIDTH/HEIGHT's own ratio (0.769...) sits outside ASPECT_CLASSIFICATION_TOLERANCE of both
// TRIM_ASPECT_RATIO and BLEED_ASPECT_RATIO - deliberate, not an oversight: these fixtures exist
// to exercise the probe walk's logic (measureCardBleedPx), not to double as a real card's
// dimensions, so passing WIDTH/HEIGHT as resolveBleedPlan's sourceWidthPx/sourceHeightPx always
// abstains. That's the point of several tests below (see "probes no longer drive the plan
// directly") - resolveBleedPlan's sourceWidthPx/sourceHeightPx are independent parameters from
// the measurement buffer's own pixel dimensions, so a fixture can freely pick realistic values
// for one without needing to build a giant pixel buffer to match.

const MARGIN_COLOR: [number, number, number] = [230, 230, 230];
// Two far-apart colors, alternating per-pixel, so any probe crossing from margin into "content"
// trips the RGB-distance threshold immediately - and a solid-content image (no real margin)
// can't be mistaken for a wide bleed margin, since adjacent content pixels also differ sharply.
const contentColorAt = (x: number, y: number): [number, number, number] =>
  (x + y) % 2 === 0 ? [10, 10, 10] : [245, 40, 40];

function buildBuffer(
  marginDepthAt: (side: BleedSide, positionAlongEdge: number) => number
): PixelBuffer {
  const data = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) {
      const inMargin =
        y < marginDepthAt("top", x) ||
        HEIGHT - 1 - y < marginDepthAt("bottom", x) ||
        x < marginDepthAt("left", y) ||
        WIDTH - 1 - x < marginDepthAt("right", y);
      const [r, g, b] = inMargin ? MARGIN_COLOR : contentColorAt(x, y);
      const offset = (y * WIDTH + x) * 4;
      data[offset] = r;
      data[offset + 1] = g;
      data[offset + 2] = b;
      data[offset + 3] = 255;
    }
  }
  return { data, width: WIDTH, height: HEIGHT };
}

const uniform =
  (depths: Partial<Record<BleedSide, number>>) =>
  (side: BleedSide): number =>
    depths[side] ?? 0;

// A confident (non-ambiguous), non-degenerate buffer usable wherever a test only cares about
// resolveBleedPlan's own logic and needs measureCardBleedPx's ambiguous flag to read false on
// every side - the buffer's own depth values are otherwise irrelevant post-#134, since the
// probe-measured depthPx no longer drives the plan's arithmetic (see resolveBleedPlan).
function confidentMeasurement() {
  const buffer = buildBuffer(uniform({ top: 6, bottom: 6, left: 6, right: 6 }));
  return measureCardBleedPx(buffer, TARGET_BLEED_PX);
}

describe("classifyBleedAspectRatio (task #134 - mirrors the backend's classify_bleed_edge)", () => {
  it("classifies a trim-ratio image as trimmed", () => {
    expect(classifyBleedAspectRatio(TRIM_ASPECT_RATIO * 10000, 10000)).toBe(
      "trimmed"
    );
  });

  it("classifies a bleed-ratio image as bleed", () => {
    expect(classifyBleedAspectRatio(BLEED_ASPECT_RATIO * 10000, 10000)).toBe(
      "bleed"
    );
  });

  it("abstains on a ratio implausible for a standard MTG card", () => {
    expect(classifyBleedAspectRatio(WIDTH, HEIGHT)).toBe("abstain");
  });

  it("abstains on a degenerate zero-height image rather than dividing by zero", () => {
    expect(classifyBleedAspectRatio(100, 0)).toBe("abstain");
  });
});

describe("detectBleedAsymmetry (task #134 - advisory only, never alters the plan)", () => {
  it("flags a card whose probe-measured sides spread past the threshold", () => {
    const buffer = buildBuffer(
      uniform({
        top: 2,
        bottom: 2 + ASYMMETRY_FLAG_THRESHOLD_MM + 1,
        left: 2,
        right: 2,
      })
    );
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    expect(detectBleedAsymmetry(measurement, IDENTITY_DPI)).toBe(true);
  });

  it("does not flag a card whose sides agree within the threshold", () => {
    const measurement = confidentMeasurement();
    expect(detectBleedAsymmetry(measurement, IDENTITY_DPI)).toBe(false);
  });
});

describe("measureCardBleedPx + resolveBleedPlan (Proposal B, task #134 dimension-basis fixtures)", () => {
  it("fixture: no bleed - all sides measure near zero and are marked ambiguous (degenerate)", () => {
    const buffer = buildBuffer(uniform({}));
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    for (const side of BLEED_SIDES) {
      expect(measurement[side].depthPx).toBeLessThanOrEqual(1);
      expect(measurement[side].ambiguous).toBe(true);
    }
  });

  it("fixture: a confident probe measurement no longer drives the plan directly - non-classifiable dimensions fall back to the prior", () => {
    // Full TARGET_BLEED_PX margin on every side - under the OLD probe-driven design this
    // confident, non-ambiguous measurement would resolve to a near-zero adjustment regardless
    // of prior. Post-#134, probes have zero trim authority: since WIDTH/HEIGHT don't classify
    // (see the module comment above), every side must fall back to the prior instead - proven
    // here by using prior="trimmed" (fallback = TARGET_BLEED_PX), which the old design would
    // have gotten wrong (~0, not ~TARGET_BLEED_PX) for this exact buffer.
    const buffer = buildBuffer(
      uniform({ top: 10, bottom: 10, left: 10, right: 10 })
    );
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    for (const side of BLEED_SIDES) {
      expect(measurement[side].ambiguous).toBe(false);
      expect(measurement[side].depthPx).toBeGreaterThanOrEqual(8);
    }
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "trimmed",
      WIDTH,
      HEIGHT
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBeCloseTo(TARGET_BLEED_PX, 0);
    }
  });

  it("fixture: real calibration dimensions (Evil Twin @460dpi, bleed-classified) resolve to a near-no-op plan - not the ~2x-overshoot trim the old probe-driven design would have computed", () => {
    // docs/reports/2026-07-18-bleed-calibration-134.md: Evil Twin measured 1253x1702px at its
    // own recorded 460dpi, aspect-classified "bleed". targetBleedMM matches the standard
    // convention BLEED_ASPECT_RATIO is itself derived from (3.175mm/side) - a real card at
    // these real dimensions should resolve to close to zero adjustment on every side, since its
    // own pixel dimensions already carry ~the target bleed.
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      460,
      3.175,
      "unresolved", // deliberately the "always extend full target" prior - proves the dimension
      // signal wins outright rather than merely nudging the fallback.
      1253,
      1702
    );
    for (const side of BLEED_SIDES) {
      expect(Math.abs(plan[side])).toBeLessThan(0.5);
    }
  });

  it("fixture: width axis (left/right) and height axis (top/bottom) resolve independently from the source's own real pixel dimensions", () => {
    // 1200x1633px @400dpi classifies "bleed" (ratio 0.7348, within tolerance of 0.7350) but the
    // two axes' own excess differs meaningfully - real photographed cards routinely show this
    // (see the calibration report's per-image table, e.g. Golos, Tireless Pilgrim: left/right
    // ~5.3mm vs top/bottom ~7mm) - proving the plan isn't computed from one aggregate number.
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      400,
      3.175,
      "unresolved",
      1200,
      1633
    );
    expect(plan.left).toBeCloseTo(plan.right, 5);
    expect(plan.top).toBeCloseTo(plan.bottom, 5);
    expect(plan.left).toBeCloseTo(-3.425, 1);
    expect(plan.top).toBeCloseTo(-4.673, 1);
    // The two axes differ from each other - not coupled to a single card-wide value.
    expect(plan.top).toBeLessThan(plan.left);
  });

  it("fixture: oversized dimension-derived measurement (dpi understated - bad metadata) is routed to the fallback, not trusted directly", () => {
    // Same 1200x1633px source as the axis-independence fixture (still classifies "bleed" - the
    // RATIO alone drives classification, independent of dpi), but a wildly understated dpi (50,
    // vs. a plausible several-hundred) inflates the computed excess past OVERSIZED_MULTIPLE x
    // target - the bad-DPI-metadata guard the approved spec always intended this constant for.
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      50,
      3.175,
      "trimmed",
      1200,
      1633
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBeCloseTo(3.175, 0);
    }
  });

  it("fixture: oversized dimension-derived measurement (dpi overstated - bad metadata) is routed to the fallback in the negative direction too", () => {
    // A dimension-derived value can come out implausibly NEGATIVE (dpi overstated, inflating
    // the trim-px subtracted from the source's real dimensions) in a way a probe run length
    // (always >= 0) never could - resolveBleedPlan's guard checks Math.abs() specifically to
    // catch this direction as well, not just the positive-overshoot case the old design saw.
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      5000,
      3.175,
      "bleed",
      1200,
      1633
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBeCloseTo(0, 0);
    }
  });

  it("fixture: probe ambiguity still forces the fallback even when dimensions classify confidently (degenerate/full-art guard, preserved from before)", () => {
    // task #134's calibration found exactly this shape in real data: WotC Proxy Policy and
    // Boros both classified confidently by aspect ratio, but their content is degenerate
    // (solid-color scan / full-art) and the probes correctly flagged every side ambiguous - the
    // spec requires this to still force the prior fallback, not the (potentially misleading)
    // dimension-derived value, exactly as an ambiguous probe measurement always has.
    const noisyTop = (side: BleedSide, pos: number) => {
      if (side !== "top") return 6;
      return pos < WIDTH / 2 ? 2 : 25;
    };
    const buffer = buildBuffer(noisyTop);
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    expect(measurement.top.ambiguous).toBe(true);
    expect(measurement.bottom.ambiguous).toBe(false);

    const plan = resolveBleedPlan(
      measurement,
      460,
      3.175,
      "unresolved",
      1253,
      1702
    );
    // top: ambiguous -> fallback (prior="unresolved" -> extend full target).
    expect(plan.top).toBeCloseTo(3.175, 0);
    // bottom: not ambiguous, same real dimensions as the near-no-op fixture -> near-zero.
    expect(Math.abs(plan.bottom)).toBeLessThan(0.5);
  });

  it("manual override force-bleed treats every side as already matching the target, regardless of measurement or dimensions", () => {
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "trimmed",
      WIDTH,
      HEIGHT,
      "force-bleed"
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBe(0);
    }
  });

  it("manual override force-trimmed synthesizes the full target on every side, regardless of measurement or dimensions", () => {
    const measurement = confidentMeasurement();
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "bleed",
      1253,
      1702,
      "force-trimmed"
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBe(TARGET_BLEED_PX);
    }
  });
});

describe("willLikelyGenerateBleed (Proposal B PR-3's preview badge hedge)", () => {
  it("prior 'bleed', auto: assumes no synthetic bleed will be generated", () => {
    expect(willLikelyGenerateBleed("bleed", "auto")).toBe(false);
  });

  it("prior 'trimmed', auto: assumes bleed will be generated", () => {
    expect(willLikelyGenerateBleed("trimmed", "auto")).toBe(true);
  });

  it("prior 'unresolved', auto: assumes bleed will be generated (same fallback as 'trimmed')", () => {
    expect(willLikelyGenerateBleed("unresolved", "auto")).toBe(true);
  });

  it("force-bleed wins outright regardless of prior", () => {
    expect(willLikelyGenerateBleed("trimmed", "force-bleed")).toBe(false);
    expect(willLikelyGenerateBleed("unresolved", "force-bleed")).toBe(false);
  });

  it("force-trimmed wins outright regardless of prior", () => {
    expect(willLikelyGenerateBleed("bleed", "force-trimmed")).toBe(true);
  });

  it("defaults manualOverride to 'auto' when omitted", () => {
    expect(willLikelyGenerateBleed("bleed")).toBe(false);
    expect(willLikelyGenerateBleed("trimmed")).toBe(true);
  });
});
