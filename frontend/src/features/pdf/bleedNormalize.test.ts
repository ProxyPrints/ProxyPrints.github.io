import {
  BLEED_SIDES,
  BleedSide,
  measureCardBleedPx,
  OVERSIZED_MULTIPLE,
  PixelBuffer,
  resolveBleedPlan,
  willLikelyGenerateBleed,
} from "@/features/pdf/bleedNormalize";

const WIDTH = 200;
const HEIGHT = 260;
const TARGET_BLEED_PX = 10;
// Chosen so px and mm are numerically identical (25.4mm = 1 inch = this many px at this dpi) -
// not a realistic dpi, just removes unit-conversion noise from the assertions below.
const IDENTITY_DPI = 25.4;

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

describe("measureCardBleedPx + resolveBleedPlan (Proposal B, 6 synthetic fixtures)", () => {
  it("fixture: no bleed - all sides measure near zero and are marked ambiguous (degenerate)", () => {
    const buffer = buildBuffer(uniform({}));
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    for (const side of BLEED_SIDES) {
      expect(measurement[side].depthPx).toBeLessThanOrEqual(1);
      expect(measurement[side].ambiguous).toBe(true);
    }
  });

  it("fixture: full bleed matching target - confident measurement, near-zero adjustment", () => {
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
      "bleed"
    );
    for (const side of BLEED_SIDES) {
      expect(Math.abs(plan[side])).toBeLessThanOrEqual(2);
    }
  });

  it("fixture: partial bleed (half target) - confident measurement drives a positive (extend) adjustment", () => {
    const buffer = buildBuffer(
      uniform({ top: 5, bottom: 5, left: 5, right: 5 })
    );
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    for (const side of BLEED_SIDES) {
      expect(measurement[side].ambiguous).toBe(false);
    }
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "bleed"
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBeGreaterThan(3);
      expect(plan[side]).toBeLessThan(7);
    }
  });

  it("fixture: asymmetric bleed - bled sides and trimmed sides on the same card resolve independently", () => {
    const buffer = buildBuffer(
      uniform({ top: 10, left: 10, bottom: 0, right: 0 })
    );
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    expect(measurement.top.ambiguous).toBe(false);
    expect(measurement.left.ambiguous).toBe(false);
    expect(measurement.bottom.ambiguous).toBe(true);
    expect(measurement.right.ambiguous).toBe(true);

    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "trimmed"
    );
    expect(Math.abs(plan.top)).toBeLessThanOrEqual(2);
    expect(Math.abs(plan.left)).toBeLessThanOrEqual(2);
    expect(plan.bottom).toBeCloseTo(TARGET_BLEED_PX, 0);
    expect(plan.right).toBeCloseTo(TARGET_BLEED_PX, 0);
  });

  it("fixture: oversized measurement (>3x target) is routed to the fallback, not trusted directly", () => {
    const buffer = buildBuffer(
      uniform({ top: 35, bottom: 35, left: 35, right: 35 })
    );
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    for (const side of BLEED_SIDES) {
      // Uniform margin depth - probes agree, so this isn't caught by the IQR/degenerate checks.
      expect(measurement[side].ambiguous).toBe(false);
      expect(measurement[side].depthPx).toBeGreaterThan(
        TARGET_BLEED_PX * OVERSIZED_MULTIPLE
      );
    }
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "trimmed"
    );
    for (const side of BLEED_SIDES) {
      // Fallback (extend the full target) - NOT the raw target-minus-measured, which would be
      // a large trim (~-25) if the oversized measurement were trusted directly.
      expect(plan[side]).toBeCloseTo(TARGET_BLEED_PX, 0);
    }
  });

  it("fixture: ambiguous noise - per-probe disagreement on one side is caught by IQR spread, exercising the fallback path", () => {
    const noisyTop = (side: BleedSide, pos: number) => {
      if (side !== "top") return 0;
      return pos < WIDTH / 2 ? 2 : 25;
    };
    const buffer = buildBuffer(noisyTop);
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    // Not degenerate (median isn't 0 or the full scan depth) - this is specifically the IQR
    // spread path, distinct from the "no bleed" fixture's degenerate-zero path above.
    expect(measurement.top.depthPx).toBeGreaterThan(0);
    expect(measurement.top.ambiguous).toBe(true);

    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "bleed"
    );
    // fallback for prior="bleed" is extend 0 - confirms the noisy median itself wasn't used.
    expect(plan.top).toBeCloseTo(0, 0);
  });

  it("manual override force-bleed treats every side as already matching the target, regardless of measurement", () => {
    const buffer = buildBuffer(uniform({})); // no bleed at all
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "trimmed",
      "force-bleed"
    );
    for (const side of BLEED_SIDES) {
      expect(plan[side]).toBe(0);
    }
  });

  it("manual override force-trimmed synthesizes the full target on every side, regardless of measurement", () => {
    const buffer = buildBuffer(
      uniform({ top: 10, bottom: 10, left: 10, right: 10 })
    ); // full bleed already present
    const measurement = measureCardBleedPx(buffer, TARGET_BLEED_PX);
    const plan = resolveBleedPlan(
      measurement,
      IDENTITY_DPI,
      TARGET_BLEED_PX,
      "bleed",
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
