import { computeLayout, LayoutMargins, LayoutSpacing } from "./layout";

const CardWidthMM = 63;
const CardHeightMM = 88;
const BleedEdgeMM = Math.round(0.12 * 25.4 * 1000) / 1000; // 3.048, matches common/constants.ts

// pdfPointsToMM(SIZES.A4) / pdfPointsToMM(SIZES.LETTER), captured to full precision
const A4_WIDTH_MM = 210.0015555555555;
const A4_HEIGHT_MM = 297.00008333333335;
const LETTER_WIDTH_MM = 215.89999999999998;
const LETTER_HEIGHT_MM = 279.4;

const ZERO_MARGINS: LayoutMargins = { top: 0, bottom: 0, left: 0, right: 0 };
const ZERO_SPACING: LayoutSpacing = { row: 0, col: 0 };

/** The pre-#301 rigid formula (slotSizeMM = cardSizeMM + 2*bleedEdgeMM, fixed for every count) -
 * kept here (not in layout.ts) purely as an oracle so these tests can assert the NEW fit math
 * against the OLD one directly: unchanged when there's no crowding, strictly more cards when
 * there is. Mirrors fitCardsInDimension's pre-#301 shape exactly. */
function legacyRigidFit(
  availableMM: number,
  cardSizeMM: number,
  bleedEdgeMM: number,
  spacingMM: number
): { count: number; containerMM: number } {
  const slotSizeMM = cardSizeMM + 2 * bleedEdgeMM;
  const containerFor = (count: number) =>
    count * slotSizeMM + (count - 1) * spacingMM + 0.1;
  let count = 1;
  while (true) {
    const container = containerFor(count);
    if (container < availableMM) {
      count++;
    } else {
      const finalCount = Math.max(1, count - 1);
      return { count: finalCount, containerMM: containerFor(finalCount) };
    }
  }
}

describe("computeLayout - byte-equivalent when bleed already fits (regression guard)", () => {
  // Constructed so the bare-card fit and the old full-bleed rigid fit land on the EXACT same
  // count with zero leftover slack beyond full bleed - the tightest possible "already fits"
  // case, and therefore the strongest single-number proof that #301 didn't change anything here.
  it("exact-boundary width: 3 cards, 3.175mm bleed, 2mm spacing, zero slack", () => {
    const bleed = 3.175;
    const spacingCol = 2;
    // A hair over the exact old-formula boundary (not bit-identical to it) - the old rigid fit's
    // own `container < availableMM` check is a STRICT inequality, so an exactly-equal available
    // width would make the OLD algorithm itself roll back to count-1 (a genuine property of that
    // algorithm, not something #301 should paper over) - real floating-point inputs always carry
    // some slack, so this mirrors that rather than the unrealistic exact-equality case.
    const availableWidthMM =
      3 * (CardWidthMM + 2 * bleed) + 2 * spacingCol + 0.1 + 1e-6;
    const result = computeLayout(
      availableWidthMM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      bleed,
      ZERO_MARGINS,
      { row: 0, col: spacingCol }
    );
    expect(result.cardsPerRow).toBe(3);
    expect(result.slots[0].bleedMM.left).toBeCloseTo(bleed, 9);
    expect(result.slots[0].bleedMM.right).toBeCloseTo(bleed, 9);
    expect(result.containerWidthMM).toBeCloseTo(availableWidthMM, 5);
    const legacyExact = legacyRigidFit(
      availableWidthMM,
      CardWidthMM,
      bleed,
      spacingCol
    );
    expect(legacyExact.count).toBe(result.cardsPerRow);
    expect(result.containerWidthMM).toBeCloseTo(legacyExact.containerMM, 9);
  });

  it("A4, standard bleed, zero margin, zero spacing - real slack, still full bleed, unchanged", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      ZERO_MARGINS,
      ZERO_SPACING
    );
    const legacyWidth = legacyRigidFit(
      A4_WIDTH_MM,
      CardWidthMM,
      BleedEdgeMM,
      0
    );
    const legacyHeight = legacyRigidFit(
      A4_HEIGHT_MM,
      CardHeightMM,
      BleedEdgeMM,
      0
    );
    expect(result.cardsPerRow).toBe(legacyWidth.count);
    expect(result.cardsPerCol).toBe(legacyHeight.count);
    expect(result.containerWidthMM).toBeCloseTo(legacyWidth.containerMM, 6);
    expect(result.containerHeightMM).toBeCloseTo(legacyHeight.containerMM, 6);
    expect(result.containerWidthMM).toBeCloseTo(207.388, 6);
    expect(result.containerHeightMM).toBeCloseTo(282.388, 6);
    // Full bleed granted on every edge - nothing to crop when there's this much slack.
    for (const slot of result.slots) {
      expect(slot.bleedMM.left).toBeCloseTo(BleedEdgeMM, 6);
      expect(slot.bleedMM.right).toBeCloseTo(BleedEdgeMM, 6);
      expect(slot.bleedMM.top).toBeCloseTo(BleedEdgeMM, 6);
      expect(slot.bleedMM.bottom).toBeCloseTo(BleedEdgeMM, 6);
    }
  });

  it("A4, standard bleed, 10mm margins, 3mm spacing - width axis unchanged (no crowding there)", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 10, bottom: 10, left: 10, right: 10 },
      { row: 3, col: 3 }
    );
    expect(result.cardsPerRow).toBe(2);
    expect(result.containerWidthMM).toBeCloseTo(141.292, 6);
    expect(result.slots[0].bleedMM.left).toBeCloseTo(BleedEdgeMM, 6);
    expect(result.slots[0].bleedMM.right).toBeCloseTo(BleedEdgeMM, 6);
  });

  it("Letter, zero bleed, 5mm margins, 2mm spacing - bleed=0 is trivially unaffected", () => {
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
    for (const slot of result.slots) {
      expect(slot.bleedMM.left).toBe(0);
      expect(slot.bleedMM.top).toBe(0);
    }
  });
});

describe("computeLayout - crowded axes now fit MORE cards than the old rigid fit (#301)", () => {
  // Same inputs as the old (pre-#301) "A4, oversized 6mm bleed, 5mm margins, 1mm spacing" golden
  // test, which used to assert cardsPerRow=2/cardsPerCol=2 (the old rigid fit dropped a card on
  // BOTH axes rather than shrink the (deliberately oversized, 2x standard) 6mm bleed even a
  // little). Under #301 the bare-card count doesn't care about bleed at all, so a 3rd card fits
  // on both axes - with less bleed than the 6mm cap, not a dropped card. This is the intended,
  // spec'd behavior change (issue #301 decision 1: "up to X available," never "X or a dropped
  // card") - the deviation from the old golden numbers is the FIX, not a regression.
  it("A4, oversized 6mm bleed, 5mm margins, 1mm spacing: 3 cards now fit both axes, cropped", () => {
    const margins: LayoutMargins = { top: 5, bottom: 5, left: 5, right: 5 };
    const spacing: LayoutSpacing = { row: 1, col: 1 };
    const bleedCap = 6;
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      bleedCap,
      margins,
      spacing
    );

    const legacyWidth = legacyRigidFit(
      A4_WIDTH_MM - 10,
      CardWidthMM,
      bleedCap,
      1
    );
    const legacyHeight = legacyRigidFit(
      A4_HEIGHT_MM - 10,
      CardHeightMM,
      bleedCap,
      1
    );
    expect(legacyWidth.count).toBe(2); // the old, worse answer
    expect(legacyHeight.count).toBe(2);

    expect(result.cardsPerRow).toBe(3);
    expect(result.cardsPerCol).toBe(3);
    expect(result.cardsPerRow).toBeGreaterThan(legacyWidth.count);
    expect(result.cardsPerCol).toBeGreaterThan(legacyHeight.count);

    // Cropped below the target cap on both axes (that's the trade the extra card costs).
    expect(result.slots[0].bleedMM.left).toBeCloseTo(1.4835926, 5);
    expect(result.slots[0].bleedMM.left).toBeLessThan(bleedCap);
    expect(result.slots[0].bleedMM.top).toBeCloseTo(3.4833472, 5);
    expect(result.slots[0].bleedMM.top).toBeLessThan(bleedCap);
  });

  it("A4, standard bleed, 10mm margins, 3mm spacing: height axis now fits a 3rd row, cropped", () => {
    // The width axis in this same configuration is NOT crowded (see the regression-guard
    // describe block above) - proves per-AXIS independence: one axis can crop while the other
    // stays full bleed, in the same computeLayout() call.
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      { top: 10, bottom: 10, left: 10, right: 10 },
      { row: 3, col: 3 }
    );
    const legacyHeight = legacyRigidFit(
      A4_HEIGHT_MM - 20,
      CardHeightMM,
      BleedEdgeMM,
      3
    );
    expect(legacyHeight.count).toBe(2); // the old, worse answer

    expect(result.cardsPerCol).toBe(3);
    expect(result.cardsPerCol).toBeGreaterThan(legacyHeight.count);
    expect(result.slots[0].bleedMM.top).toBeCloseTo(1.150014, 5);
    expect(result.slots[0].bleedMM.top).toBeLessThan(BleedEdgeMM);
    // Width axis (same call) is untouched - full bleed, matching the regression-guard test above.
    expect(result.slots[0].bleedMM.left).toBeCloseTo(BleedEdgeMM, 6);
  });
});

describe("computeLayout - the canonical spacing=0 shared-gutter case (#301 decision 2)", () => {
  it("spacing.col=0, two neighbours each carrying 3.175mm: each renders half the shared boundary", () => {
    const bleedCap = 3.175;
    // available width = 2 bare cards + exactly enough slack for 2*bleedCap total, spread across
    // 2*count=4 half-boundaries (2 page edges + 1 shared gutter's 2 halves) - so every
    // half-boundary, edge and gutter alike, is squeezed to exactly half the target:
    // (2*3.175)/4 = 1.5875mm = 3.175mm / 2.
    const availableWidthMM = 2 * CardWidthMM + 0.1 + 2 * bleedCap;
    const result = computeLayout(
      availableWidthMM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      bleedCap,
      ZERO_MARGINS,
      { row: 0, col: 0 }
    );

    expect(result.cardsPerRow).toBe(2);
    const [card1, card2] = result.slots.slice(0, 2);
    const expectedHalf = bleedCap / 2;
    expect(card1.bleedMM.right).toBeCloseTo(expectedHalf, 6);
    expect(card2.bleedMM.left).toBeCloseTo(expectedHalf, 6);
    // Split the difference: each neighbour contributes equally to the shared boundary.
    expect(card1.bleedMM.right).toBeCloseTo(card2.bleedMM.left, 9);
    // Page edges are "just another constraint on the same clamp" - not a special case that
    // stays at full bleed while only the interior gutter crops.
    expect(card1.bleedMM.left).toBeCloseTo(expectedHalf, 6);
    expect(card2.bleedMM.right).toBeCloseTo(expectedHalf, 6);
    // Never crops into the card itself.
    expect(card1.widthMM).toBeCloseTo(CardWidthMM + bleedCap, 6);
  });
});

describe("computeLayout - symmetry (identical neighbours crop identically)", () => {
  it("two neighbours sharing a squeezed gutter get the exact same bleed, proven not eyeballed", () => {
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      6, // oversized cap, deliberately forces cropping - see the "crowded axes" describe block
      { top: 5, bottom: 5, left: 5, right: 5 },
      { row: 1, col: 1 }
    );
    expect(result.cardsPerRow).toBe(3);
    const [slot0, slot1, slot2] = result.slots;
    // Proves real (non-vacuous) cropping happened - not just two zeros trivially matching.
    expect(slot0.bleedMM.right).toBeGreaterThan(0);
    expect(slot0.bleedMM.right).toBeLessThan(6);
    // The shared gutter between slot0/slot1 and between slot1/slot2 must be split identically.
    expect(slot0.bleedMM.right).toBeCloseTo(slot1.bleedMM.left, 9);
    expect(slot1.bleedMM.right).toBeCloseTo(slot2.bleedMM.left, 9);
    expect(slot0.bleedMM.right).toBeCloseTo(slot1.bleedMM.right, 9);
  });
});

describe("computeLayout - never crops into the card itself", () => {
  it("bleed floors at 0, never negative, even when the card barely fits at all", () => {
    // availableWidthMM only just fits one bare card - effectively no slack for bleed.
    const result = computeLayout(
      CardWidthMM + 0.05,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      3.175,
      ZERO_MARGINS,
      ZERO_SPACING
    );
    expect(result.cardsPerRow).toBe(1);
    expect(result.slots[0].bleedMM.left).toBeGreaterThanOrEqual(0);
    expect(result.slots[0].bleedMM.right).toBeGreaterThanOrEqual(0);
    expect(result.slots[0].widthMM).toBeGreaterThanOrEqual(CardWidthMM);
  });

  it("pathological: available space smaller than a single bare card - bleed is exactly 0, never negative", () => {
    const result = computeLayout(
      50, // smaller than CardWidthMM (63)
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      3.175,
      ZERO_MARGINS,
      ZERO_SPACING
    );
    expect(result.cardsPerRow).toBe(1);
    expect(result.slots[0].bleedMM.left).toBe(0);
    expect(result.slots[0].bleedMM.right).toBe(0);
    // Still the FULL card width - the card itself is never cropped, only its (already-zero)
    // bleed.
    expect(result.slots[0].widthMM).toBe(CardWidthMM);
  });
});

describe("computeLayout - per-edge availability at page edges (no interior gutter at all)", () => {
  it("a single card per row still crops via the same clamp - just the two page-edge halves", () => {
    const bleedCap = 3.175;
    // slack = 2.4mm total across 2 page-edge half-boundaries -> 1.2mm each.
    const availableWidthMM = CardWidthMM + 0.1 + 2 * 1.2;
    const result = computeLayout(
      availableWidthMM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      bleedCap,
      ZERO_MARGINS,
      { row: 0, col: 5 } // spacing is irrelevant with only 1 card per row
    );
    expect(result.cardsPerRow).toBe(1);
    expect(result.slots[0].bleedMM.left).toBeCloseTo(1.2, 6);
    expect(result.slots[0].bleedMM.right).toBeCloseTo(1.2, 6);
    expect(result.slots[0].bleedMM.left).toBeLessThan(bleedCap);
  });
});

describe("computeLayout - per-edge availability at margins", () => {
  it("a larger margin on one side still yields symmetric left/right bleed (margins gate total available width, not one edge)", () => {
    // Asymmetric margins change the container's page-absolute offset (see the "asymmetric
    // margins" test below) but not which side gets more bleed - both page-edge
    // half-boundaries draw from the same axis-wide slack pool.
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      6,
      { top: 0, bottom: 0, left: 40, right: 5 },
      { row: 0, col: 1 }
    );
    expect(result.slots[0].bleedMM.left).toBeCloseTo(
      result.slots[0].bleedMM.right,
      9
    );
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
      ZERO_MARGINS,
      ZERO_SPACING
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

  it("adjacent slots in a row are spaced by this slot's own widthMM + column spacing", () => {
    const spacingCol = 4;
    const result = computeLayout(
      A4_WIDTH_MM,
      A4_HEIGHT_MM,
      CardWidthMM,
      CardHeightMM,
      BleedEdgeMM,
      ZERO_MARGINS,
      { row: 0, col: spacingCol }
    );
    expect(result.slots[1].xMM - result.slots[0].xMM).toBeCloseTo(
      result.slots[0].widthMM + spacingCol,
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
      ZERO_SPACING
    );
    const availableWidth = A4_WIDTH_MM - 40;
    const expectedOffsetX = 40 + (availableWidth - result.containerWidthMM) / 2;
    expect(result.offsetXMM).toBeCloseTo(expectedOffsetX, 6);
    // sanity: this must differ from the naive (pageWidth - containerWidth) / 2 formula
    const naiveOffsetX = (A4_WIDTH_MM - result.containerWidthMM) / 2;
    expect(result.offsetXMM).not.toBeCloseTo(naiveOffsetX, 3);
  });
});
