/**
 * Pure page-layout math shared between the PDF generator (PDF.tsx) and the WYSIWYG page
 * preview (PagePreview.tsx) - page size, card size, bleed, margins, spacing in, page-absolute
 * slot rects out. Extracted from PDF.tsx, which previously computed the same numbers via two
 * independently-tuned algorithms at different call sites (a greedy incrementing loop in
 * calculateCardContainerDimension for the container's own size, a direct division formula in
 * getCardsPerRow/getCardsPerCol re-deriving card counts from that same container size) -
 * mathematically equivalent (see layout.test.ts's algebraic-equivalence test) but genuinely two
 * sources of truth. This module has exactly one.
 *
 * Centering: react-pdf's <Page> applies the margins as CSS padding and centers CardGrid
 * (justifyContent + alignSelf) *within* that padded content box, not the full page - so the
 * page-absolute offset has to add the margin back in, not just center within the full page
 * size. See PDF.tsx's <Page style={{paddingTop: ..., justifyContent: "center"}}> for the
 * behavior this replicates.
 */

export interface LayoutMargins {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface LayoutSpacing {
  row: number;
  col: number;
}

export interface LayoutSlot {
  /** Page-absolute top-left of this slot's bleed box, in mm. */
  xMM: number;
  yMM: number;
}

export interface ComputedLayout {
  pageWidthMM: number;
  pageHeightMM: number;
  /** Size of the tightly-packed grid of card slots (bleed boxes + inter-card spacing). */
  containerWidthMM: number;
  containerHeightMM: number;
  /** Page-absolute top-left of the container (i.e. of slots[0]). */
  offsetXMM: number;
  offsetYMM: number;
  cardsPerRow: number;
  cardsPerCol: number;
  /** One entry per card slot on a full page, row-major (matches CardGrid's flex-wrap order). */
  slots: LayoutSlot[];
}

/**
 * Greedy-fit: the max number of (cardSizeMM + 2*bleedEdgeMM) slots, spaced by spacingMM, that
 * fit within availableMM - and the exact container size that many slots occupy. The `+ 0.1`
 * fudge factor is inherited from the original calculateCardContainerDimension - react-pdf was
 * observed wrapping unexpectedly without it (see git blame), kept verbatim rather than
 * "cleaned up" to avoid silently changing generated-PDF layout.
 */
function fitCardsInDimension(
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

export function computeLayout(
  pageWidthMM: number,
  pageHeightMM: number,
  cardWidthMM: number,
  cardHeightMM: number,
  bleedEdgeMM: number,
  margins: LayoutMargins,
  spacing: LayoutSpacing
): ComputedLayout {
  const availableWidthMM = pageWidthMM - (margins.left + margins.right);
  const availableHeightMM = pageHeightMM - (margins.top + margins.bottom);

  const { count: cardsPerRow, containerMM: containerWidthMM } =
    fitCardsInDimension(
      availableWidthMM,
      cardWidthMM,
      bleedEdgeMM,
      spacing.col
    );
  const { count: cardsPerCol, containerMM: containerHeightMM } =
    fitCardsInDimension(
      availableHeightMM,
      cardHeightMM,
      bleedEdgeMM,
      spacing.row
    );

  // Centered within the margin-inset content box, then translated back to page-absolute
  // coordinates by adding the margin back in - see the module comment for why this isn't
  // just (pageSize - container) / 2 (that would ignore asymmetric margins).
  const offsetXMM = margins.left + (availableWidthMM - containerWidthMM) / 2;
  const offsetYMM = margins.top + (availableHeightMM - containerHeightMM) / 2;

  const slotWidthMM = cardWidthMM + 2 * bleedEdgeMM;
  const slotHeightMM = cardHeightMM + 2 * bleedEdgeMM;

  const slots: LayoutSlot[] = [];
  for (let row = 0; row < cardsPerCol; row++) {
    for (let col = 0; col < cardsPerRow; col++) {
      slots.push({
        xMM: offsetXMM + col * (slotWidthMM + spacing.col),
        yMM: offsetYMM + row * (slotHeightMM + spacing.row),
      });
    }
  }

  return {
    pageWidthMM,
    pageHeightMM,
    containerWidthMM,
    containerHeightMM,
    offsetXMM,
    offsetYMM,
    cardsPerRow,
    cardsPerCol,
    slots,
  };
}
