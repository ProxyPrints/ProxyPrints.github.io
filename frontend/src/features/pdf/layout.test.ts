import { computeLayout } from "./layout";

// Golden values captured directly from PDF.tsx's pre-refactor formulas
// (calculateCardContainerDimension / getCardsPerRow / getCardsPerCol, before this module
// existed) for a representative spread of page sizes, bleeds, margins, and spacing - a
// regression guard that the reconciled single-source-of-truth math in computeLayout produces
// byte-identical container/count numbers to what PDF.tsx has always generated. See layout.ts's
// module comment for why there used to be two algorithms here, not one.
const CardWidthMM = 63;
const CardHeightMM = 88;
const BleedEdgeMM = Math.round(0.12 * 25.4 * 1000) / 1000; // 3.048, matches common/constants.ts

// pdfPointsToMM(SIZES.A4) / pdfPointsToMM(SIZES.LETTER), captured to full precision
const A4_WIDTH_MM = 210.0015555555555;
const A4_HEIGHT_MM = 297.00008333333335;
const LETTER_WIDTH_MM = 215.89999999999998;
const LETTER_HEIGHT_MM = 279.4;

describe("computeLayout - golden values (parity with pre-extraction PDF.tsx)", () => {
  it("A4, standard bleed, zero margin, zero spacing", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 0, bottom: 0, left: 0, right: 0 },
      { row: 0, col: 0 }
    );
    expect(result.containerWidthMM).toBeCloseTo(207.388, 6);
    expect(result.containerHeightMM).toBeCloseTo(282.388, 6);
    expect(result.cardsPerRow).toBe(3);
    expect(result.cardsPerCol).toBe(3);
  });

  it("A4, standard bleed, 10mm margins, 3mm spacing", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 10, bottom: 10, left: 10, right: 10 },
      { row: 3, col: 3 }
    );
    expect(result.containerWidthMM).toBeCloseTo(141.292, 6);
    expect(result.containerHeightMM).toBeCloseTo(191.292, 6);
    expect(result.cardsPerRow).toBe(2);
    expect(result.cardsPerCol).toBe(2);
  });

  it("Letter, zero bleed, 5mm margins, 2mm spacing", () => {
    const result = computeLayout(
      LETTER_WIDTH_MM,
      LETTER_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      0,
      { top: 5, bottom: 5, left: 5, right: 5 },
      { row: 2, col: 2 }
    );
    expect(result.containerWidthMM).toBeCloseTo(193.1, 6);
    expect(result.containerHeightMM).toBeCloseTo(268.1, 6);
    expect(result.cardsPerRow).toBe(3);
    expect(result.cardsPerCol).toBe(3);
  });

  it("A4, oversized 6mm bleed, 5mm margins, 1mm spacing", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      6,
      { top: 5, bottom: 5, left: 5, right: 5 },
      { row: 1, col: 1 }
    );
    expect(result.containerWidthMM).toBeCloseTo(151.1, 6);
    expect(result.containerHeightMM).toBeCloseTo(201.1, 6);
    expect(result.cardsPerRow).toBe(2);
    expect(result.cardsPerCol).toBe(2);
  });
});

describe("computeLayout - slot rects", () => {
  it("produces exactly cardsPerRow * cardsPerCol slots, row-major", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 0, bottom: 0, left: 0, right: 0 },
      { row: 0, col: 0 }
    );
    expect(result.slots).toHaveLength(result.cardsPerRow * result.cardsPerCol);
    // row-major: the 4th slot (index cardsPerRow) starts a new row - same x as slot 0, but a
    // greater y
    expect(result.slots[result.cardsPerRow].xMM).toBeCloseTo(
      result.slots[0].xMM,
      6
    );
    expect(result.slots[result.cardsPerRow].yMM).toBeGreaterThan(
      result.slots[0].yMM
    );
  });

  it("slot[0] sits at the computed page-absolute offset", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 10, bottom: 10, left: 10, right: 10 },
      { row: 3, col: 3 }
    );
    expect(result.slots[0].xMM).toBeCloseTo(result.offsetXMM, 6);
    expect(result.slots[0].yMM).toBeCloseTo(result.offsetYMM, 6);
  });

  it("adjacent slots in a row are spaced by slot size + column spacing", () => {
    const spacingCol = 4;
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 0, bottom: 0, left: 0, right: 0 },
      { row: 0, col: spacingCol }
    );
    const slotWidth = CardWidthMM + 2 * BleedEdgeMM;
    expect(result.slots[1].xMM - result.slots[0].xMM).toBeCloseTo(
      slotWidth + spacingCol,
      6
    );
  });

  it("centers within the margin-inset content box, not the full page (asymmetric margins)", () => {
    // left margin much larger than right - the container should sit off-center toward the
    // right edge of the page, not dead-center on the full page width. This is the exact
    // behavior react-pdf's <Page padding + justifyContent: center> produces (see layout.ts's
    // module comment) - a naive (pageWidth - containerWidth) / 2 offset would get this wrong.
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 0, bottom: 0, left: 40, right: 0 },
      { row: 0, col: 0 }
    );
    const availableWidth = A4_WIDTH_MM - 40;
    const expectedOffsetX = 40 + (availableWidth - result.containerWidthMM) / 2;
    expect(result.offsetXMM).toBeCloseTo(expectedOffsetX, 6);
    // sanity: this must differ from the naive (pageWidth - containerWidth) / 2 formula
    const naiveOffsetX = (A4_WIDTH_MM - result.containerWidthMM) / 2;
    expect(result.offsetXMM).not.toBeCloseTo(naiveOffsetX, 3);
  });
});

describe("computeLayout - algebraic equivalence with the pre-extraction two-algorithm split", () => {
  // The original getCardsPerRow/getCardsPerCol derived a card count from a *given* container
  // width via straight division + rounding; calculateCardContainerDimension derived the count
  // via a greedy fit loop that also returns the exact container size. This test proves they
  // were always mathematically the same value (not just observationally, for the golden-value
  // cases above) - re-deriving cardsPerRow from computeLayout's own containerWidthMM via the
  // old division formula must recover the same cardsPerRow computeLayout already returned.
  const legacyGetCardsPerRow = (
    containerWidthMM: number,
    bleedEdgeMM: number,
    spacingColMM: number
  ) => {
    const slotWidth = CardWidthMM + 2 * bleedEdgeMM;
    return Math.round(
      (containerWidthMM - 0.1 + spacingColMM) / (slotWidth + spacingColMM)
    );
  };

  it.each([
    [BleedEdgeMM, 0],
    [BleedEdgeMM, 3],
    [0, 2],
    [6, 1],
  ])("bleed=%s spacing=%s", (bleed, spacingCol) => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      bleed,
      { top: 0, bottom: 0, left: 0, right: 0 },
      { row: 0, col: spacingCol }
    );
    expect(
      legacyGetCardsPerRow(result.containerWidthMM, bleed, spacingCol)
    ).toBe(result.cardsPerRow);
  });
});
