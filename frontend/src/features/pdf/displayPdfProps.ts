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
 * therefore always `"CUSTOM"` here; the rail's own selection (LETTER/A4/...) is what those
 * dimensions are computed FROM, via the same `getPageSizeMM` lookup the sheet itself uses.
 *
 * ## Named defaults
 *
 * Every `PDFProps` field with no editor equivalent yet — corner rounding, cut-line placement/
 * length/thickness/offset, SCM settings, and page cut lines — gets an explicit named default
 * HERE, the one place those defaults live. Each is named so a later PR can replace it with a
 * real rail control without touching any other file:
 *
 * - `imageQuality: "full-resolution"` — same full-res export pipeline `PDFGenerator.tsx`'s own
 *   download path uses (`fullResolutionPDFProps`). DPI and JPG quality themselves are real
 *   controls now (`DisplayExportSettings.imageDPI`/`jpgQuality`), not defaulted here.
 * - `roundCorners: false`.
 * - Cut-line placement/length/thickness/offset stay matched to the rail's own guide visual
 *   (`PagePreview.tsx`'s E19 lime corner-only guides: 3mm legs, 0.6mm stroke, inside placement)
 *   — `cutLinePlacement: "Inside"`, `cutLineLengthMM: 3`, `cutLineThicknessMM: 0.6`,
 *   `cutLineOffsetMM: 0`. Colour and shape are real controls now
 *   (`DisplayExportSettings.cutLineColor`/`cutLineShape`), not defaulted here.
 * - `drawPageCutLines: false` — the rail's single "Guides" toggle only ever drew the per-card
 *   corner guides (page cut lines were never part of this page's sheet).
 * - SCM mode is off: `scmMode: false` with the standard `scmPaperSize: "letter"`,
 *   `scmVariant: "default"`, `scmRegistration: 3`, `scmDuplex: true`,
 *   `scmOffsetXMM: 0`, `scmOffsetYMM: 0`, `scmOffsetAngleDeg: 0`.
 *
 * Card selection mode, page range, image DPI/JPG quality, and cut-line colour/shape all come
 * from `DisplayExportSettings` — the export affordance's own local state
 * (`DisplayExportPDF.tsx`), not the sheet's. The two fields that DO have editor equivalents
 * beyond the sheet settings — per-side page margins (the rail's margin profile,
 * `marginProfiles.ts`) and card spacing (`cardSpacingSlice`) — are mapped from live state,
 * never defaulted.
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
import type {
  CardSelectionMode,
  CutLineShape,
  PDFProps,
} from "@/features/pdf/PDF";
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
  bleedEdgeMM: number;
  showCutLines: boolean;
  offsetXMM: number;
  offsetYMM: number;
}

/** The export affordance's own settings (`DisplayExportPDF.tsx`) - export-time choices with no
 * relationship to the sheet's own layout, so they live separately from
 * `DisplaySheetExportSettings` above. `pageRangeStart`/`pageRangeEnd` are 1-indexed and inclusive
 * (see `PDFProps.pageRangeStart`'s own comment); `undefined` on either means "all pages". */
export interface DisplayExportSettings {
  cardSelectionMode: keyof typeof CardSelectionMode;
  pageRangeStart?: number;
  pageRangeEnd?: number;
  imageDPI: number;
  jpgQuality: number;
  cutLineColor: string;
  cutLineShape: keyof typeof CutLineShape;
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
  const margins = MARGIN_PROFILES[input.marginProfile].margins;
  // Landscape rule — see the module comment. Same portrait-table lookup + swap DisplayPage uses
  // for its own sheet, so the exported page is exactly the size the rail shows.
  const portraitSize = getPageSizeMM(
    sheetSettings.pageSize,
    undefined,
    undefined
  );
  return {
    cardSelectionMode: exportSettings.cardSelectionMode,
    cutLinePlacement: "Inside",
    cutLineShape: exportSettings.cutLineShape,
    pageSize: "CUSTOM",
    pageWidth: portraitSize.height,
    pageHeight: portraitSize.width,
    bleedEdgeMM: sheetSettings.bleedEdgeMM,
    roundCorners: false,
    drawCardCutLines: sheetSettings.showCutLines,
    drawPageCutLines: false,
    cutLineLengthMM: 3,
    cutLineOffsetMM: 0,
    cutLineThicknessMM: 0.6,
    cutLineColor: exportSettings.cutLineColor,
    cardSpacingRowMM: input.cardSpacing.row,
    cardSpacingColMM: input.cardSpacing.col,
    pageMarginTopMM: margins.top,
    pageMarginBottomMM: margins.bottom,
    pageMarginLeftMM: margins.left,
    pageMarginRightMM: margins.right,
    pageOffsetXMM: sheetSettings.offsetXMM,
    pageOffsetYMM: sheetSettings.offsetYMM,
    pageRangeStart: exportSettings.pageRangeStart,
    pageRangeEnd: exportSettings.pageRangeEnd,
    cardDocumentsByIdentifier: input.cardDocumentsByIdentifier,
    projectMembers: input.projectMembers,
    projectCardback: input.projectCardback,
    imageQuality: "full-resolution",
    imageDPI: exportSettings.imageDPI,
    jpgQuality: exportSettings.jpgQuality,
    bleedOverrides: input.manualOverrides,
    scmMode: false,
    scmPaperSize: "letter",
    scmVariant: "default",
    scmRegistration: 3,
    scmDuplex: true,
    scmOffsetXMM: 0,
    scmOffsetYMM: 0,
    scmOffsetAngleDeg: 0,
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
