/**
 * The ONE adapter from /display editor state to the `PDFProps` shape `PDF.tsx` already consumes.
 *
 * The editor's live sheet and the exported PDF share `computeLayout()` (`features/pdf/layout.ts`)
 * but historically disagreed anyway, because the two surfaces were fed from different stores:
 * `DisplayPage.tsx`'s local `DisplaySheetSettings` + the margin-profile/card-spacing redux slices
 * drive the on-screen sheet, while `PDFGenerator.tsx` (the /print page) had its own private
 * settings store that never read any of those. A rail configured for LETTER landscape 4x2 could
 * therefore export an A4 3x3 PDF and nothing anywhere would notice.
 *
 * This module is the seam that closes that gap: everything the sheet renders from flows into the
 * PDF generator here, so a rail change moves both surfaces in lockstep. It deliberately does NOT
 * fork, copy or reimplement anything from `PDF.tsx` / `pdf.worker.ts` / `pdfRenderService.ts` —
 * the generator is correct; only the source of its props changes. `/print`'s `PDFGenerator.tsx`
 * keeps its own independent settings and is untouched.
 *
 * ## The landscape rule
 *
 * `PDF.tsx`'s `PageSize` table is portrait-oriented (a holdover from the classic print tab's own
 * page-size semantics, unchanged there). The /display sheet is landscape by design (see
 * `DisplayPage.tsx`'s own `sheetWidthMM`/`sheetHeightMM` derivation — portrait size, width/height
 * swapped). Expressing that to `PDF.tsx` requires the `CUSTOM` page-size branch with the swapped
 * dimensions: `getPageSizeMM("CUSTOM", w, h)` returns exactly `{ width: w, height: h }`, so the
 * generated page carries the same landscape dimensions the rail's sheet shows. `pageSize` is
 * therefore always `"CUSTOM"` here; the rail's own selection (LETTER/A4/.../Custom) is what those
 * dimensions are computed FROM, via the same `getPageSizeMM` lookup the sheet itself uses — for
 * the rail's own `Custom` option, `getPageSizeMM` takes `sheetSettings.customPageWidthMM`/
 * `customPageHeightMM` (portrait mm, same convention as every other table entry) straight through
 * instead of looking them up.
 *
 * ## Named defaults
 *
 * `PDFProps` fields with no editor equivalent yet get an explicit named default HERE, the one
 * place those defaults live, named so a later PR can replace one with a real rail control without
 * touching any other file:
 *
 * - `imageQuality: "full-resolution"` — same full-res export pipeline `PDFGenerator.tsx`'s own
 *   download path uses (`fullResolutionPDFProps`). DPI and JPG quality themselves are real
 *   controls (`DisplaySheetExportSettings.imageDPI`/`jpgQuality`), not defaulted here.
 *
 * Everything else `PDF.tsx`'s own `PDFProps` interface exposes is now a real control, sourced
 * from either `DisplaySheetExportSettings` (the rail's own sheet state - page size including its
 * `Custom` option, bleed edge, guides and their colour/length/thickness/offset geometry plus an
 * opt-in crosshair-marks toggle, image DPI/JPG quality, corner rounding, card selection mode,
 * page range, and an opt-in per-side page-margin override - moved here from the export step's own
 * settings so they're editable next to the live sheet they govern, see `DisplayPage.tsx`'s own
 * "Guides", "Print quality", and "Export" rail sections, plus the margin override grouped under
 * the margin-profile control in "Page Setup") or `DisplayExportSettings` (the export affordance's
 * own settings step - SCM mode and its six sub-settings).
 *
 * ## Margin-preset vs. per-side override
 *
 * The rail's margin PROFILE (`marginProfileSlice`, three named presets) still drives both the
 * live sheet and, by default, the export — unchanged, and never silently overridden. The four
 * independent per-side values a real print run sometimes needs are a genuinely finer model than
 * a 3-option preset, so they're an OPT-IN advanced override scoped to a single export run:
 * `DisplaySheetExportSettings.marginOverride`, `undefined` by default (meaning "use the rail's
 * current profile, exactly as before this field existed"). It lives in the rail's own Page Setup
 * section, directly under the margin-profile control it overrides (`DisplayPage.tsx`) rather than
 * the export dialog - the four fields are a manual override of that same profile decision, not an
 * unrelated one-off export-run choice like SCM mode. When the toggle is on, `marginOverride`
 * carries an explicit `{top,bottom,left,right}` that replaces the profile's margins for the
 * EXPORT only — the live sheet, the profile data, and every other export always keep reading the
 * profile. Seeded from the current profile's own values when the toggle turns on (see
 * `DisplayPage.tsx`), so turning it on never starts from a jarring unrelated number.
 */
import {
  CardDocument,
  MarginProfileKey,
  SlotProjectMembers,
  useAppSelector,
} from "@/common/types";
import { MARGIN_PROFILES } from "@/features/display/marginProfiles";
import { ManualOverride } from "@/features/pdf/bleedNormalize";
import { getPageSizeMM, PageSize } from "@/features/pdf/pageSize";
import type { CardSelectionMode, PDFProps } from "@/features/pdf/PDF";
import type {
  ScmPaperSize,
  ScmRegistration,
  ScmVariant,
} from "@/features/pdf/scm/scmLayout";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import { selectCardSpacing } from "@/store/slices/cardSpacingSlice";
import { selectMarginProfile } from "@/store/slices/marginProfileSlice";
import {
  selectManualOverrides,
  selectProjectCardback,
  selectProjectMembers,
} from "@/store/slices/projectSlice";

/**
 * The subset of `DisplayPage.tsx`'s local `DisplaySheetSettings` the export needs (structurally
 * identical — `DisplayPage` passes its own `settings` state straight in). Defined here rather
 * than imported from `DisplayPage.tsx` so the adapter stays the single source of truth for what
 * editor state reaches the PDF; `DisplayPage`'s local type is free to stay page-local.
 */
export interface DisplaySheetExportSettings {
  pageSize: keyof typeof PageSize;
  /** Portrait mm, same convention as `pageSize.ts`'s own table — only read when `pageSize` is
   * `"CUSTOM"`. The rail seeds both together (see `DisplayPage.tsx`'s paper-size `onChange`), so
   * `pageSize === "CUSTOM"` always carries both values in practice; `getPageSizeMM` still handles
   * either being absent by falling through to its own lookup, same as every other caller. */
  customPageWidthMM?: number;
  customPageHeightMM?: number;
  bleedEdgeMM: number;
  showCutLines: boolean;
  /** Guide appearance - only meaningful while `showCutLines` is true (see `DisplayPage.tsx`'s
   * rail, which hides these controls whenever Guides is off). Moved here from the export step's
   * own `DisplayExportSettings` (this module's own comment) - the guides' printed appearance is a
   * property of the artifact, not a one-off export-run choice, so it lives in the rail next to
   * the Guides toggle it depends on rather than behind the Export PDF dialog. Applies to both the
   * dashed trim outline and, when enabled, the crosshair corner marks below. */
  cutLineColor: string;
  /** Optional crosshair corner marks alongside the default dashed trim outline - see
   * `PDFProps.showCrossCutLines`'s own comment. Default off (`DisplayPage.tsx`). */
  showCrossCutLines: boolean;
  cutLineLengthMM: number;
  cutLineThicknessMM: number;
  cutLineOffsetMM: number;
  offsetXMM: number;
  offsetYMM: number;
  /** Moved here from the export step's own `DisplayExportSettings` (this module's own comment) -
   * a print-quality choice, not an export-run-only one, so it lives next to the sheet it governs
   * in the rail's "Print quality" section rather than behind the Export PDF dialog. */
  imageDPI: number;
  jpgQuality: number;
  /** Same migration as `imageDPI`/`jpgQuality` above. */
  roundCorners: boolean;
  /** Moved here from the export step's own `DisplayExportSettings` (this module's own comment) -
   * which cards make it into the export and which of its pages actually render aren't a one-off
   * export-run choice, they're a property of what the printed artifact IS, so they live in the
   * rail's "Export" section next to the sheet they govern rather than behind the Export PDF
   * dialog. `pageRangeStart`/`pageRangeEnd` are 1-indexed and inclusive (see
   * `PDFProps.pageRangeStart`'s own comment); `undefined` on either means "all pages". */
  cardSelectionMode: keyof typeof CardSelectionMode;
  pageRangeStart?: number;
  pageRangeEnd?: number;
  /** Opt-in advanced per-side override of the margin profile above - see the module comment's
   * "Margin-preset vs. per-side override" section. `undefined` = use the rail's current margin
   * profile unchanged (the default). Lives here (rather than `DisplayExportSettings`) because it
   * groups with the rail's own margin-profile control (`DisplayPage.tsx`'s Page Setup section),
   * not the export dialog - a manual override of that same profile decision. */
  marginOverride?: PageMarginOverride;
  /** The guillotine-cut page guide lines (as opposed to `showCutLines`'s per-card trim marks) - a
   * full sheet's own cut guides, independent of whether card cut lines are drawn at all. Moved
   * here from the export step's own `DisplayExportSettings` - it groups with the rail's "Cut
   * lines & snip guides" section (`DisplayPage.tsx`) rather than the export dialog, same
   * reasoning as the per-card guide appearance fields above. `/print`'s `PDFGenerator.tsx`
   * exposes this as its own "Page Cut Guide Lines" toggle; this field is the editor's
   * equivalent. */
  drawPageCutLines: boolean;
}

/** An explicit per-side override for `DisplaySheetExportSettings.marginOverride` — see the module
 * comment's "Margin-preset vs. per-side override" section. */
export interface PageMarginOverride {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** The export affordance's own settings (`DisplayExportPDF.tsx`) - export-time choices with no
 * relationship to the sheet's own layout, so they live separately from
 * `DisplaySheetExportSettings` above. */
export interface DisplayExportSettings {
  /** Switches the whole export to `SCMPDF.tsx`'s registration-mark layout - a genuinely different
   * output format, not another flag on the standard grid. The six `scm*` fields below are only
   * read by `PDF.tsx` when this is true. */
  scmMode: boolean;
  scmPaperSize: ScmPaperSize;
  scmVariant: ScmVariant;
  scmRegistration: ScmRegistration;
  scmDuplex: boolean;
  scmOffsetXMM: number;
  scmOffsetYMM: number;
  scmOffsetAngleDeg: number;
}

/** Everything `buildDisplayPDFProps` reads — every source the adapter maps, named explicitly so
 * the pure function is trivially testable without a Redux store. */
export interface DisplayPDFPropsInput {
  sheetSettings: DisplaySheetExportSettings;
  exportSettings: DisplayExportSettings;
  marginProfile: MarginProfileKey;
  cardSpacing: { row: number; col: number };
  projectMembers: Array<SlotProjectMembers>;
  projectCardback: string | undefined;
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
  manualOverrides: { [identifier: string]: ManualOverride };
}

export const buildDisplayPDFProps = (
  input: DisplayPDFPropsInput
): Omit<PDFProps, "fileHandles"> => {
  const { sheetSettings, exportSettings } = input;
  // Margin-preset vs. per-side override - see the module comment. The override replaces the
  // profile's margins for THIS export only; the profile itself, and every other consumer of
  // `MARGIN_PROFILES`, are never touched.
  const margins =
    sheetSettings.marginOverride ??
    MARGIN_PROFILES[input.marginProfile].margins;
  // Landscape rule — see the module comment. Same portrait-table lookup + swap DisplayPage uses
  // for its own sheet, so the exported page is exactly the size the rail shows, including its
  // Custom option (customPageWidthMM/HeightMM pass straight through when pageSize is "CUSTOM").
  const portraitSize = getPageSizeMM(
    sheetSettings.pageSize,
    sheetSettings.customPageWidthMM,
    sheetSettings.customPageHeightMM
  );
  return {
    cardSelectionMode: sheetSettings.cardSelectionMode,
    showCrossCutLines: sheetSettings.showCrossCutLines,
    pageSize: "CUSTOM",
    pageWidth: portraitSize.height,
    pageHeight: portraitSize.width,
    bleedEdgeMM: sheetSettings.bleedEdgeMM,
    roundCorners: sheetSettings.roundCorners,
    drawCardCutLines: sheetSettings.showCutLines,
    drawPageCutLines: sheetSettings.drawPageCutLines,
    cutLineLengthMM: sheetSettings.cutLineLengthMM,
    cutLineOffsetMM: sheetSettings.cutLineOffsetMM,
    cutLineThicknessMM: sheetSettings.cutLineThicknessMM,
    cutLineColor: sheetSettings.cutLineColor,
    cardSpacingRowMM: input.cardSpacing.row,
    cardSpacingColMM: input.cardSpacing.col,
    pageMarginTopMM: margins.top,
    pageMarginBottomMM: margins.bottom,
    pageMarginLeftMM: margins.left,
    pageMarginRightMM: margins.right,
    pageOffsetXMM: sheetSettings.offsetXMM,
    pageOffsetYMM: sheetSettings.offsetYMM,
    pageRangeStart: sheetSettings.pageRangeStart,
    pageRangeEnd: sheetSettings.pageRangeEnd,
    cardDocumentsByIdentifier: input.cardDocumentsByIdentifier,
    projectMembers: input.projectMembers,
    projectCardback: input.projectCardback,
    imageQuality: "full-resolution",
    imageDPI: sheetSettings.imageDPI,
    jpgQuality: sheetSettings.jpgQuality,
    bleedOverrides: input.manualOverrides,
    scmMode: exportSettings.scmMode,
    scmPaperSize: exportSettings.scmPaperSize,
    scmVariant: exportSettings.scmVariant,
    scmRegistration: exportSettings.scmRegistration,
    scmDuplex: exportSettings.scmDuplex,
    scmOffsetXMM: exportSettings.scmOffsetXMM,
    scmOffsetYMM: exportSettings.scmOffsetYMM,
    scmOffsetAngleDeg: exportSettings.scmOffsetAngleDeg,
  };
};

/** Live-state binding of `buildDisplayPDFProps`: reads the margin-profile / card-spacing /
 * project slices and the card-document map from Redux, leaving only `DisplayPage`'s own local
 * sheet settings and the export affordance's own local export settings to the caller (both are
 * component-local state, not store state — see `DisplayPage.tsx`'s own "known gap" note on why
 * sheet settings never were persisted; export settings follow the same precedent). */
export const useDisplayPDFProps = (
  sheetSettings: DisplaySheetExportSettings,
  exportSettings: DisplayExportSettings
): Omit<PDFProps, "fileHandles"> => {
  const marginProfile = useAppSelector(selectMarginProfile).profile;
  const cardSpacing = useAppSelector(selectCardSpacing);
  const projectMembers = useAppSelector(selectProjectMembers);
  const projectCardback = useAppSelector(selectProjectCardback);
  const manualOverrides = useAppSelector(selectManualOverrides);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();
  return buildDisplayPDFProps({
    sheetSettings,
    exportSettings,
    marginProfile,
    cardSpacing,
    projectMembers,
    projectCardback,
    cardDocumentsByIdentifier,
    manualOverrides,
  });
};
