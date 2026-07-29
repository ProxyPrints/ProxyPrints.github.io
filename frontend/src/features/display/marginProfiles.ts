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
 * below computes each profile's cap from the SAME formula `layout.ts`'s `fitAxisWithBleed`
 * uses (rather than copying the D6 table's numbers verbatim), so the cap stays correct if the
 * page size or column spacing ever changes instead of silently drifting from the real layout
 * engine's own math.
 *
 * #301 (croppable bleed) reframed what this cap MEANS, not its formula: pre-#301, exceeding it
 * meant `layout.ts`'s rigid slot-fit dropped the sheet from 4 columns to 3 (a whole card gone).
 * Post-#301, the fit is bare-card-count-first (see `fitAxisWithBleed`'s own comment) - the 4th
 * column no longer disappears; bleed on the affected edge crops down to this same cap value
 * instead. The formula below is UNCHANGED (it already computed exactly the per-edge bleed
 * `fitAxisWithBleed`'s water-filling converges to at count=4 - `(available - 4*card -
 * 3*spacing - 0.1) / 8` is `slackMM / (2*count)` with count=4, the same expression) - only
 * `MarginProfileControl.tsx`'s warning copy, which used to describe the old "fewer cards"
 * behavior, needed to change to describe the new "cropped, with reduced cutting tolerance"
 * behavior (issue #301 decision 3).
 */
import { MarginProfileKey } from "@/common/types";
import { LayoutMargins } from "@/features/pdf/layout";

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
      "No printer margin at all. Supported to Letter/Legal on the Epson ET-8500/8550 " +
      "(spec sheet CPD-59931R2) - the only profile that fits the full 3.175mm MPC bleed " +
      "alongside a 4x2 sheet.",
  },
  bordered: {
    key: "bordered",
    label: "Bordered (3mm)",
    margins: { top: 3, bottom: 3, left: 3, right: 3 },
    description:
      "The ET-8500/8550's own minimum bordered-print margin, all four edges (User's Guide " +
      "CPD-59879). Caps usable bleed below the 3.175mm MPC default - bleed beyond the cap is " +
      "trimmed to fit (see the warning above for the exact crop and its cutting-tolerance " +
      "trade-off).",
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
      "The rear paper feed's 20mm unprintable zone (User's Guide CPD-59879) lands on the " +
      "trailing SIDE edge in this page's landscape layout, not top/bottom. Leaves almost no " +
      "room for bleed at a 4x2 sheet - #301: the trailing edge is trimmed to fit rather than " +
      "dropping a column (see the warning above for the exact crop).",
  },
};

/**
 * The largest bleed edge (mm) a 4-column sheet can render at FULL bleed under the given page
 * width/margins - beyond this, `computeLayout`'s width axis (the D4/D6 binding constraint) still
 * keeps all 4 columns (#301: bare card count no longer depends on bleed at all), but crops the
 * bleed on every column boundary down to exactly this value (see `fitAxisWithBleed`'s own
 * per-axis water-filling comment, features/pdf/layout.ts - this is that formula's
 * `slackMM / (2*count)` solved at a fixed count of 4, algebraically identical to the pre-#301
 * "count * slotSizeMM + (count-1)*spacingMM + 0.1 < availableMM" boundary this was originally
 * derived from), rather than hardcoding the D6 table's numbers - so a paper-size or spacing
 * change can never leave this cap silently wrong.
 */
export function maxBleedForFourColumns(
  pageWidthMM: number,
  margins: LayoutMargins,
  cardWidthMM: number,
  spacingColMM: number
): number {
  const availableWidthMM = pageWidthMM - margins.left - margins.right;
  return (availableWidthMM - 4 * cardWidthMM - 3 * spacingColMM - 0.1) / 8;
}
