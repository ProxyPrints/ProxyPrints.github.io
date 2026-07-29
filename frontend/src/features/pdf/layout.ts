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
 *
 * CROPPABLE BLEED (#301, extending #299's per-card bleed normalization - see bleedNormalize.ts's
 * module comment for the split of responsibility): bleed used to be a RIGID addend baked into
 * the slot size (`slotSizeMM = cardSizeMM + 2*bleedEdgeMM`) - a card count that didn't fit at
 * FULL bleed just got dropped a card, even when the true (bare) cards themselves would have
 * fit fine with a little less bleed. `bleedEdgeMM` is now a per-edge MAXIMUM (the amount of
 * bleed a #299-normalized card actually CARRIES) that the layout grants as much of as the space
 * affords, never more - see `fitAxisWithBleed`'s own comment for the water-filling formula this
 * uses, and `LayoutSlot.bleedMM` for what a caller (pdfImage.ts, PDF.tsx, PagePreview.tsx)
 * consumes from it. #299 produces the resource (how much bleed a card carries); this module
 * decides how much of it renders, given the page - neither replaces the other.
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

/** Per-edge bleed actually granted (mm) - the amount of a card's #299-carried bleed this layout
 * has room to render on that specific edge, never more than the configured target/cap
 * (`bleedEdgeMM`). 0 on an edge means that edge crops all the way down to the bare trim line -
 * "up to X available," never "X or a dropped card" (issue #301, decision 1). */
export interface LayoutEdgeBleed {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface LayoutSlot {
  /** Page-absolute top-left of this slot's bleed box, in mm. */
  xMM: number;
  yMM: number;
  /** This slot's own bleed-box size, in mm (cardSizeMM + the near/far edge of `bleedMM` on each
   * axis). Every slot computeLayout() returns for a given call carries the SAME widthMM/
   * heightMM/bleedMM as every other slot - see `bleedMM`'s own comment for why. */
  widthMM: number;
  heightMM: number;
  /** Per-edge bleed granted to this slot - see `LayoutEdgeBleed`. `fitAxisWithBleed` resolves
   * bleed per AXIS (column: left/right: row: top/bottom), not per individual slot, so every slot
   * on the page shares one value here; that's a deliberate consequence of the water-filling
   * formula treating every column boundary (page edge or shared interior gutter alike) as an
   * equal claimant on the same axis's slack - not a limitation of the per-slot shape, which is
   * kept (rather than a single page-level field) so a future truly-per-slot refinement doesn't
   * need an API change. */
  bleedMM: LayoutEdgeBleed;
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

interface AxisFit {
  /** Number of cards this axis fits. */
  count: number;
  /** Per-edge bleed (mm) granted to EVERY boundary on this axis - both page-edge boundaries and
   * shared interior gutters alike (see fitAxisWithBleed's own comment). */
  bleedMM: number;
  /** Total size this axis's container occupies (count cards + spacing + granted bleed), mm. */
  containerMM: number;
}

/**
 * #301 croppable-bleed fit for one axis (width or height, called independently - same as
 * before). Two steps:
 *
 * 1. `count` is the largest number of BARE (cardSizeMM, no bleed at all) slots, spaced by
 *    spacingMM, that fit within availableMM - card count no longer depends on bleed at all,
 *    which is what lets a crowded axis fit MORE cards than the old rigid
 *    (cardSizeMM + 2*bleedEdgeMM) slot-fit did: the old fit dropped a whole card the moment full
 *    bleed didn't fit; this one only ever drops a card when the BARE card itself doesn't fit.
 *    The `+ 0.1` fudge factor is inherited from the original calculateCardContainerDimension -
 *    react-pdf was observed wrapping unexpectedly without it (see git blame), kept verbatim
 *    rather than "cleaned up" to avoid silently changing generated-PDF layout.
 *
 * 2. Whatever room is left over after that bare fit (`slackMM`) is handed out as bleed. A row of
 *    `count` cards has `count` near-side and `count` far-side edges - 2*count "half-boundaries"
 *    total - and EVERY one of them draws from the same slack pool equally: an interior gutter's
 *    two facing half-boundaries (one per neighbour) and a page-edge's single half-boundary all
 *    get the identical `slackMM / (2*count)` share, capped at `bleedCapMM` (the configured
 *    target bleed - #299's carried-bleed resource, the most a card could ever render on any
 *    edge). That's "split the difference" at a shared gutter (each neighbour contributes
 *    equally, issue #301 decision 2) and "page edge / margin caps are just another constraint on
 *    the same per-edge clamp" (not a special case) falling out of ONE formula: a page edge is
 *    simply a half-boundary with no neighbour on the other side, not a different code path.
 *
 * When there's enough slack to grant full `bleedCapMM` everywhere (the pre-#301 rigid fit would
 * already have chosen this same `count` with room to spare), `bleedMM` clamps to exactly
 * `bleedCapMM` and `containerMM` comes out byte-identical to the old
 * `count * (cardSizeMM + 2*bleedCapMM) + (count-1)*spacingMM + 0.1` formula - the regression
 * guard layout.test.ts's "byte-equivalent when already fitting" cases check directly.
 */
function fitAxisWithBleed(
  availableMM: number,
  cardSizeMM: number,
  bleedCapMM: number,
  spacingMM: number
): AxisFit {
  const bareContainerFor = (count: number) =>
    count * cardSizeMM + (count - 1) * spacingMM + 0.1;
  let count = 1;
  while (true) {
    const container = bareContainerFor(count);
    if (container < availableMM) {
      count++;
    } else {
      count = Math.max(1, count - 1);
      break;
    }
  }

  const bareContainerMM = bareContainerFor(count);
  // Never negative - `count` is chosen so the bare fit itself already satisfies availableMM
  // (see the loop above), but the forced `count = 1` floor when even one bare card doesn't fit
  // can leave bareContainerMM > availableMM, which must never be read as "negative slack to
  // hand out as bleed" (that would be cropping the card itself, not just its bleed).
  const slackMM = Math.max(0, availableMM - bareContainerMM);
  const bleedMM = Math.min(bleedCapMM, slackMM / (2 * count));
  const containerMM = bareContainerMM + 2 * count * bleedMM;

  return { count, bleedMM, containerMM };
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

  const colFit = fitAxisWithBleed(
    availableWidthMM,
    cardWidthMM,
    bleedEdgeMM,
    spacing.col
  );
  const rowFit = fitAxisWithBleed(
    availableHeightMM,
    cardHeightMM,
    bleedEdgeMM,
    spacing.row
  );

  const cardsPerRow = colFit.count;
  const cardsPerCol = rowFit.count;
  const containerWidthMM = colFit.containerMM;
  const containerHeightMM = rowFit.containerMM;

  // Centered within the margin-inset content box, then translated back to page-absolute
  // coordinates by adding the margin back in - see the module comment for why this isn't
  // just (pageSize - container) / 2 (that would ignore asymmetric margins).
  const offsetXMM = margins.left + (availableWidthMM - containerWidthMM) / 2;
  const offsetYMM = margins.top + (availableHeightMM - containerHeightMM) / 2;

  // Every slot on the page shares one bleedMM - see LayoutSlot.bleedMM's own comment for why
  // fitAxisWithBleed's water-filling makes that the correct (not merely convenient) answer.
  const bleedMM: LayoutEdgeBleed = {
    left: colFit.bleedMM,
    right: colFit.bleedMM,
    top: rowFit.bleedMM,
    bottom: rowFit.bleedMM,
  };
  const slotWidthMM = cardWidthMM + bleedMM.left + bleedMM.right;
  const slotHeightMM = cardHeightMM + bleedMM.top + bleedMM.bottom;

  const slots: LayoutSlot[] = [];
  for (let row = 0; row < cardsPerCol; row++) {
    for (let col = 0; col < cardsPerRow; col++) {
      slots.push({
        xMM: offsetXMM + col * (slotWidthMM + spacing.col),
        yMM: offsetYMM + row * (slotHeightMM + spacing.row),
        widthMM: slotWidthMM,
        heightMM: slotHeightMM,
        bleedMM,
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
