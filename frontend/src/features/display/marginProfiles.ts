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
 * below computes each profile's cap from the SAME formula `layout.ts`'s `fitCardsInDimension`
 * uses (rather than copying the D6 table's numbers verbatim), so the cap stays correct if the
 * page size or column spacing ever changes instead of silently drifting from the real layout
 * engine's own math.
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
      "CPD-59879). Caps usable bleed below the 3.175mm MPC default - see the warning above " +
      "if your bleed edge exceeds it.",
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
      "room for bleed at a 4x2 sheet - see the warning above.",
  },
};

/**
 * The largest bleed edge (mm) a 4-column sheet can carry under the given page width/margins
 * before `computeLayout`'s width axis (the D4/D6 binding constraint) drops to 3 columns. Mirrors
 * `fitCardsInDimension`'s own `count * slotSizeMM + (count - 1) * spacingMM + 0.1 < availableMM`
 * boundary (features/pdf/layout.ts), solved for bleed at a fixed count of 4, rather than
 * hardcoding the D6 table's numbers - so a paper-size or spacing change can never leave this
 * cap silently wrong.
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
