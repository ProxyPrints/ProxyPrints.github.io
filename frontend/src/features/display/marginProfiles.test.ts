/**
 * Proposal H D5/D6 (docs/proposals/proposal-h-display-layout-spec.md) - unit coverage for the
 * margin-profile cap math, checked directly against the D6 table's own worked numbers (US
 * Letter landscape, 279.4mm wide, 63mm card width, 0mm column spacing/D18 default) so a future
 * change to the formula can't silently drift from the spec's own arithmetic.
 */
import { MARGIN_PROFILES, maxBleedForFourColumns } from "./marginProfiles";

const PAGE_WIDTH_MM = 279.4; // US Letter landscape width
const CARD_WIDTH_MM = 63;

describe("maxBleedForFourColumns", () => {
  it("matches the D6 table's Borderless max bleed (~3.412mm)", () => {
    const cap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.borderless.margins,
      CARD_WIDTH_MM,
      0
    );
    expect(cap).toBeCloseTo(3.4125, 3);
  });

  it("matches the D6 table's Bordered max bleed (~2.662mm)", () => {
    const cap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.bordered.margins,
      CARD_WIDTH_MM,
      0
    );
    expect(cap).toBeCloseTo(2.6625, 3);
  });

  it("matches the D6 table's Rear-feed max bleed (~0.537mm)", () => {
    const cap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.rearFeed.margins,
      CARD_WIDTH_MM,
      0
    );
    expect(cap).toBeCloseTo(0.5375, 3);
  });

  it("Borderless is the only profile whose cap clears the D6 default 3.175mm bleed", () => {
    const borderlessCap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.borderless.margins,
      CARD_WIDTH_MM,
      0
    );
    const borderedCap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.bordered.margins,
      CARD_WIDTH_MM,
      0
    );
    const rearFeedCap = maxBleedForFourColumns(
      PAGE_WIDTH_MM,
      MARGIN_PROFILES.rearFeed.margins,
      CARD_WIDTH_MM,
      0
    );
    expect(borderlessCap).toBeGreaterThanOrEqual(3.175);
    expect(borderedCap).toBeLessThan(3.175);
    expect(rearFeedCap).toBeLessThan(3.175);
  });
});
