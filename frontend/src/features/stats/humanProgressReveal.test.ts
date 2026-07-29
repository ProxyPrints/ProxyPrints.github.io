/**
 * Pure-function regression guard for `humanProgressReveal.ts` (2026-07-29 owner ruling - the
 * gated homepage human-progress series). Covers the units-caveat accessor and the hysteresis rule
 * in isolation, without a component tree - `ParticipationGraph.test.tsx` covers the same rule
 * wired into the real component (third fixture, `participationAtRevealThreshold`).
 */
import {
  HUMAN_VOTE_REVEAL_HYSTERESIS_PP,
  HUMAN_VOTE_REVEAL_PERCENT,
  humanProgressRatioPercent,
  shouldRevealHumanProgress,
} from "@/features/stats/humanProgressReveal";
import {
  participationAtRevealThreshold,
  participationCurrentRatio,
  participationPostSweep,
} from "@/features/stats/testFixtures";

describe("humanProgressRatioPercent", () => {
  it("is humanVotes.total / total, as a percentage - the single accessor both the gate and the drawn series read from", () => {
    expect(
      humanProgressRatioPercent(participationAtRevealThreshold)
    ).toBeCloseTo(10);
    expect(humanProgressRatioPercent(participationCurrentRatio)).toBeCloseTo(
      (237 / 230_770) * 100
    );
  });

  it("holds flat between the current and post-sweep fixtures, since both share the same humanVotes/total inputs to THIS ratio (their difference is confirmable/contested, which this accessor never reads)", () => {
    expect(humanProgressRatioPercent(participationCurrentRatio)).toEqual(
      humanProgressRatioPercent(participationPostSweep)
    );
  });

  it("never divides by zero - a zeroed/cache-miss participation reads as 0%, not NaN/Infinity", () => {
    expect(
      humanProgressRatioPercent({ total: 0, humanVotes: { total: 0 } })
    ).toEqual(0);
  });
});

describe("shouldRevealHumanProgress - hysteresis around HUMAN_VOTE_REVEAL_PERCENT", () => {
  const justBelow = HUMAN_VOTE_REVEAL_PERCENT - 0.01;
  const atThreshold = HUMAN_VOTE_REVEAL_PERCENT;
  const aboveThreshold = HUMAN_VOTE_REVEAL_PERCENT + 5;
  const insideHysteresisBand =
    HUMAN_VOTE_REVEAL_PERCENT - HUMAN_VOTE_REVEAL_HYSTERESIS_PP / 2;
  const belowHysteresisFloor =
    HUMAN_VOTE_REVEAL_PERCENT - HUMAN_VOTE_REVEAL_HYSTERESIS_PP - 0.01;

  it("starting from hidden (no prior state): stays hidden just below the threshold", () => {
    expect(shouldRevealHumanProgress(justBelow, false)).toBe(false);
  });

  it("starting from hidden: reveals at or above the threshold", () => {
    expect(shouldRevealHumanProgress(atThreshold, false)).toBe(true);
    expect(shouldRevealHumanProgress(aboveThreshold, false)).toBe(true);
  });

  it("a value exactly at the boundary is deterministic across repeated evaluations of the same inputs (never flips on consecutive loads)", () => {
    const first = shouldRevealHumanProgress(atThreshold, false);
    const second = shouldRevealHumanProgress(atThreshold, false);
    expect(first).toBe(second);
    expect(first).toBe(true);
  });

  it("the hysteresis band: a value inside the band stays REVEALED if it was previously revealed", () => {
    expect(shouldRevealHumanProgress(insideHysteresisBand, true)).toBe(true);
  });

  it("the hysteresis band: the SAME value approached from below (never previously revealed) stays HIDDEN", () => {
    expect(shouldRevealHumanProgress(insideHysteresisBand, false)).toBe(false);
  });

  it("once revealed, only hides after dropping below the hysteresis floor", () => {
    expect(shouldRevealHumanProgress(belowHysteresisFloor, true)).toBe(false);
  });

  it("once hidden again, re-reveals only at/above the plain threshold again (not the lower hysteresis floor)", () => {
    expect(shouldRevealHumanProgress(insideHysteresisBand, false)).toBe(false);
    expect(shouldRevealHumanProgress(atThreshold, false)).toBe(true);
  });
});

describe("HUMAN_VOTE_REVEAL_PERCENT - build-time override", () => {
  const ORIGINAL_ENV = process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT;

  afterEach(() => {
    process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT = ORIGINAL_ENV;
    jest.resetModules();
  });

  it("defaults to 10 when the env var is unset", async () => {
    delete process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT;
    jest.resetModules();
    const reimported = await import("@/features/stats/humanProgressReveal");
    expect(reimported.HUMAN_VOTE_REVEAL_PERCENT).toEqual(10);
  });

  it("is overridable at build time via NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT, for self-hosters tuning a smaller/larger catalog", async () => {
    process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT = "25";
    jest.resetModules();
    const reimported = await import("@/features/stats/humanProgressReveal");
    expect(reimported.HUMAN_VOTE_REVEAL_PERCENT).toEqual(25);
  });
});
