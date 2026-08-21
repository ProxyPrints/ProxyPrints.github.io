/**
 * Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md) - the /display Page Setup's
 * margin-profile presets, calibrated against the Epson ET-8500/8550's own printable-area spec
 * (User's Guide CPD-59879's "Printable Area Specifications"; borderless support to Letter/Legal
 * confirmed by spec sheet CPD-59931R2). Each profile is a `LayoutMargins` value the right rail's
 * `MarginProfileControl` lets the user pick, replacing DisplayPage.tsx's previous hardcoded
 * 5mm-all-sides `useMemo`.
 *
 * D6's own honesty note carries forward: full MPC bleed (3.175mm) + the D4 4x2 grid fits ONLY
 * the Borderless profile - every bordered profile caps bleed below that. `maxBleedForFourColumns`
 * below answers that question by calling straight into `computeLayout` (the real layout engine,
 * `features/pdf/layout.ts`) rather than re-deriving `fitAxisWithBleed`'s water-filling arithmetic
 * a second time - a hand-copied formula can silently drift from the engine it was copied from the
 * moment either one changes; reading the engine's own output cannot.
 *
 * #301 (croppable bleed) reframed what this cap MEANS: pre-#301, exceeding it meant `layout.ts`'s
 * rigid slot-fit dropped the sheet from 4 columns to 3 (a whole card gone). Post-#301, the fit is
 * bare-card-count-first (see `fitAxisWithBleed`'s own comment) - the 4th column no longer
 * disappears; bleed on the affected edge crops down to this same cap value instead. The granted-
 * vs-requested readout (`BleedGrantedReadout.tsx`) is what surfaces that crop to the user now -
 * this module no longer owns any warning copy of its own.
 */
import { CardHeightMM } from "@/common/constants";
import { MarginProfileKey } from "@/common/types";
import { computeLayout, LayoutMargins } from "@/features/pdf/layout";

export interface MarginProfileDefinition {
  key: MarginProfileKey;
  label: string;
  margins: LayoutMargins;
  /** Plain-language trade-off note surfaced as Page Setup helper text - honest about which
   * profile the ET-8500/8550 source material actually supports, not just the numbers. */
  description: string;
}

export const MARGIN_PROFILES: Record<
  MarginProfileKey,
  MarginProfileDefinition
> = {
  borderless: {
    key: "borderless",
    label: "Borderless (0mm)",
    margins: { top: 0, bottom: 0, left: 0, right: 0 },
    description:
      "No margin. Fits full 3.175mm bleed at 4×2 - Epson ET-8500/8550, borderless to " +
      "Letter/Legal (CPD-59931R2).",
  },
  bordered: {
    key: "bordered",
    label: "Bordered (3mm)",
    margins: { top: 3, bottom: 3, left: 3, right: 3 },
    description:
      "ET-8500/8550's min. bordered margin, 3mm all sides (CPD-59879). Caps bleed below " +
      "3.175mm - excess is cropped to fit.",
  },
  rearFeed: {
    key: "rearFeed",
    label: "Rear-feed (3mm + 20mm trailing edge)",
    // Letter feeds portrait through the ET-8500/8550's rear tray (215.9mm leading edge); in
    // this page's landscape layout that 20mm unprintable zone lands on one SIDE edge, not
    // top/bottom - modeled here on the right edge, labelled "trailing" rather than committing
    // to a physical left/right since that depends on which way the sheet is loaded.
    margins: { top: 3, bottom: 3, left: 3, right: 20 },
    description:
      "Rear feed's 20mm unprintable zone (CPD-59879) lands on the trailing SIDE edge here, " +
      "not top/bottom. Little room for bleed at 4×2 - trailing edge crops to fit.",
  },
};

/**
 * The largest bleed edge (mm) the column axis can render, under the given page width/margins,
 * for however many columns that width naturally bare-fits (in practice 4, for every margin
 * profile this repo ships - see the D6 table this function's own tests check against). Reads
 * `computeLayout`'s real output instead of re-deriving `fitAxisWithBleed`'s water-filling
 * formula: an effectively unbounded `bleedEdgeMM` target (`Number.MAX_SAFE_INTEGER`) means the
 * axis's own slack is what binds the returned `bleedMM`, not the target cap - exactly "the most
 * this axis could ever grant," which is the question this function answers. The row axis is
 * irrelevant to a column-width question, so its inputs (card height, page height) are dummy
 * values sized only to keep `fitAxisWithBleed`'s bare-fit loop from iterating needlessly, not to
 * describe any real card.
 */
export function maxBleedForFourColumns(
  pageWidthMM: number,
  margins: LayoutMargins,
  cardWidthMM: number,
  spacingColMM: number
): number {
  const layout = computeLayout(
    pageWidthMM,
    CardHeightMM + 1,
    cardWidthMM,
    CardHeightMM,
    Number.MAX_SAFE_INTEGER,
    margins,
    { row: 0, col: spacingColMM }
  );
  return layout.slots[0]?.bleedMM.left ?? 0;
}
