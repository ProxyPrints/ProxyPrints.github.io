import { CardType } from "@/common/schema_types";
import { ManualOverride } from "@/features/pdf/bleedNormalize";
import {
  buildDisplayPDFProps,
  DisplayPDFPropsInput,
} from "@/features/pdf/displayPdfProps";
import { computeLayout } from "@/features/pdf/layout";
import { getPageSizeMM } from "@/features/pdf/pageSize";
import { DEFAULT_CARD_SELECTION_MODE } from "@/features/pdf/PDF";

// PDF.tsx pulls in @react-pdf/renderer at module scope (StyleSheet.create); nothing under test
// here touches it, so stub the renderer out rather than booting it in jsdom - same pattern
// pagination.test.ts uses for the same reason.
jest.mock("@react-pdf/renderer", () => ({
  Document: () => null,
  Image: () => null,
  Page: () => null,
  StyleSheet: { create: (styles: unknown) => styles },
  View: () => null,
}));

// The rail's own defaults (DisplayPage.tsx DEFAULT_SHEET_SETTINGS) - a LETTER landscape sheet at
// the standard 3.175mm MPC bleed, guides on, no registration offset. LETTER portrait dims from
// the same getPageSizeMM lookup DisplayPage/displayPdfProps both use.
const LETTER_PORTRAIT = getPageSizeMM("LETTER", undefined, undefined);
// Includes the rail's "Print quality" (imageDPI/jpgQuality/roundCorners) and "Export"
// (cardSelectionMode/pageRangeStart/pageRangeEnd) defaults - both migrated here from
// DisplayExportPDF.tsx's own settings step, see displayPdfProps.ts's own comment.
// The same lime guide colour PagePreview.tsx's E19 screen-side guides render with.
const DEFAULT_SHEET_SETTINGS = {
  pageSize: "LETTER" as const,
  bleedEdgeMM: 3.175,
  showCutLines: true,
  cutLineColor: "#8ae234",
  showCrossCutLines: false,
  cutLineLengthMM: 3,
  cutLineThicknessMM: 0.6,
  cutLineOffsetMM: 0,
  offsetXMM: 0,
  offsetYMM: 0,
  imageDPI: 600,
  jpgQuality: 100,
  roundCorners: true,
  cardSelectionMode: DEFAULT_CARD_SELECTION_MODE,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  marginOverride: undefined,
  drawPageCutLines: true,
  // The export settings step's own defaults (DisplayExportPDF.tsx DEFAULT_EXPORT_SETTINGS)
  // before SCM mode migrated into DisplaySheetExportSettings alongside everything else.
  scmMode: false,
  scmPaperSize: "letter" as const,
  scmVariant: "default" as const,
  scmRegistration: 3 as const,
  scmDuplex: true,
  scmOffsetXMM: 0,
  scmOffsetYMM: 0,
  scmOffsetAngleDeg: 0,
};

const EMPTY_DOCS: { [identifier: string]: undefined } = {};
const NO_OVERRIDES: { [identifier: string]: ManualOverride } = {};

const baseInput: DisplayPDFPropsInput = {
  sheetSettings: DEFAULT_SHEET_SETTINGS,
  marginProfile: "rearFeed",
  cardSpacing: { row: 14.5, col: 0 },
  projectMembers: [],
  projectCardback: undefined,
  cardDocumentsByIdentifier: EMPTY_DOCS,
  manualOverrides: NO_OVERRIDES,
};

describe("buildDisplayPDFProps - page size and grid match the rail's live sheet", () => {
  it("a LETTER landscape rail yields a landscape LETTER export (never A4)", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.pageSize).toBe("CUSTOM");
    // Landscape rule: width/height swapped against PDF.tsx's portrait table, so the exported
    // page is exactly the sheet the rail showed: 279.4 x 215.9mm landscape LETTER.
    expect(props.pageWidth).toBeCloseTo(LETTER_PORTRAIT.height, 5);
    expect(props.pageHeight).toBeCloseTo(LETTER_PORTRAIT.width, 5);
    // The adapter always emits CUSTOM with computed dims, so both are defined here.
    expect(props.pageWidth!).toBeGreaterThan(props.pageHeight!);
    // ...and specifically NOT A4 (297 x 210 landscape - the /print page's own default).
    const a4Portrait = getPageSizeMM("A4", undefined, undefined);
    expect(props.pageWidth).not.toBeCloseTo(a4Portrait.width, 5);
    expect(props.pageHeight).not.toBeCloseTo(a4Portrait.height, 5);
  });

  it("the exported PDF lays out the same grid as the rail's sheet (LETTER landscape -> 4x2)", () => {
    const props = buildDisplayPDFProps(baseInput);
    // The adapter's own output feeds computeLayout exactly as PDF.tsx feeds it (getPageSizeMM
    // on the props, then layoutForPage with the props' margins/spacing/bleed)...
    const size = getPageSizeMM(
      props.pageSize,
      props.pageWidth,
      props.pageHeight
    );
    const pdfLayout = computeLayout(
      size.width,
      size.height,
      63,
      88,
      props.bleedEdgeMM,
      {
        top: props.pageMarginTopMM,
        bottom: props.pageMarginBottomMM,
        left: props.pageMarginLeftMM,
        right: props.pageMarginRightMM,
      },
      { row: props.cardSpacingRowMM, col: props.cardSpacingColMM }
    );
    // ...and the rail's own sheet is fed the same numbers via DisplayPage (sheetWidthMM =
    // portraitSize.height, margins from the same profile, spacing from the same slice).
    const railLayout = computeLayout(
      LETTER_PORTRAIT.height,
      LETTER_PORTRAIT.width,
      63,
      88,
      DEFAULT_SHEET_SETTINGS.bleedEdgeMM,
      { top: 3, bottom: 3, left: 3, right: 20 }, // MARGIN_PROFILES.rearFeed
      { row: 14.5, col: 0 }
    );
    expect(pdfLayout.cardsPerRow).toBe(railLayout.cardsPerRow);
    expect(pdfLayout.cardsPerCol).toBe(railLayout.cardsPerCol);
    // The actual numbers the /display rail's own default sheet shows (its documented 4x2).
    expect(pdfLayout.cardsPerRow).toBe(4);
    expect(pdfLayout.cardsPerCol).toBe(2);
  });

  it("an A4 rail yields an A4 landscape export, not LETTER", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: { ...DEFAULT_SHEET_SETTINGS, pageSize: "A4" },
    });
    const a4Portrait = getPageSizeMM("A4", undefined, undefined);
    expect(props.pageWidth).toBeCloseTo(a4Portrait.height, 5);
    expect(props.pageHeight).toBeCloseTo(a4Portrait.width, 5);
  });

  it("a Custom rail page size exports at exactly the entered portrait dimensions, swapped", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        pageSize: "CUSTOM",
        customPageWidthMM: 100,
        customPageHeightMM: 150,
      },
    });
    expect(props.pageSize).toBe("CUSTOM");
    // Landscape rule swap, same as every other page size: portrait height becomes the
    // exported width, portrait width becomes the exported height.
    expect(props.pageWidth).toBeCloseTo(150, 5);
    expect(props.pageHeight).toBeCloseTo(100, 5);
  });
});

describe("buildDisplayPDFProps - rail guide state reaches the exported PDF's cut lines", () => {
  it("showCutLines: true -> drawCardCutLines: true (and the default lime dashed-outline geometry, cross marks off)", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.drawCardCutLines).toBe(true);
    expect(props.cutLineColor).toBe("#8ae234");
    expect(props.showCrossCutLines).toBe(false);
    expect(props.cutLineLengthMM).toBe(3);
    expect(props.cutLineThicknessMM).toBe(0.6);
    expect(props.cutLineOffsetMM).toBe(0);
  });

  it("showCutLines: false -> drawCardCutLines: false", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: { ...DEFAULT_SHEET_SETTINGS, showCutLines: false },
    });
    expect(props.drawCardCutLines).toBe(false);
  });

  it("page cut lines default to on, matching /print's own default, and map straight through from the rail's sheet settings", () => {
    expect(buildDisplayPDFProps(baseInput).drawPageCutLines).toBe(true);
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: { ...DEFAULT_SHEET_SETTINGS, drawPageCutLines: false },
    });
    expect(props.drawPageCutLines).toBe(false);
  });

  it("cut line colour, cross-marks toggle, and geometry all map straight through from the rail's sheet settings", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        cutLineColor: "#ff0000",
        showCrossCutLines: true,
        cutLineLengthMM: 5,
        cutLineThicknessMM: 1,
        cutLineOffsetMM: 0.5,
      },
    });
    expect(props.cutLineColor).toBe("#ff0000");
    expect(props.showCrossCutLines).toBe(true);
    expect(props.cutLineLengthMM).toBe(5);
    expect(props.cutLineThicknessMM).toBe(1);
    expect(props.cutLineOffsetMM).toBe(0.5);
  });
});

describe("buildDisplayPDFProps - corner rounding maps straight through", () => {
  it("defaults to round (true), and reads false when set", () => {
    expect(buildDisplayPDFProps(baseInput).roundCorners).toBe(true);
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: { ...DEFAULT_SHEET_SETTINGS, roundCorners: false },
    });
    expect(props.roundCorners).toBe(false);
  });
});

describe("buildDisplayPDFProps - live editor state maps through", () => {
  it("margin profile becomes per-side page margins", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      marginProfile: "borderless",
    });
    expect(props.pageMarginTopMM).toBe(0);
    expect(props.pageMarginBottomMM).toBe(0);
    expect(props.pageMarginLeftMM).toBe(0);
    expect(props.pageMarginRightMM).toBe(0);

    const bordered = buildDisplayPDFProps({
      ...baseInput,
      marginProfile: "bordered",
    });
    expect(bordered.pageMarginTopMM).toBe(3);
    expect(bordered.pageMarginRightMM).toBe(3);
  });

  it("an explicit margin override replaces the profile's margins for this export only", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      marginProfile: "borderless",
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        marginOverride: { top: 1, bottom: 2, left: 3, right: 4 },
      },
    });
    expect(props.pageMarginTopMM).toBe(1);
    expect(props.pageMarginBottomMM).toBe(2);
    expect(props.pageMarginLeftMM).toBe(3);
    expect(props.pageMarginRightMM).toBe(4);
    // The "borderless" profile itself (all-zero margins) is unaffected by the override - only
    // this call's OWN output changed.
    expect(
      buildDisplayPDFProps({ ...baseInput, marginProfile: "borderless" })
        .pageMarginTopMM
    ).toBe(0);
  });

  it("card spacing maps straight through", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      cardSpacing: { row: 7, col: 2.5 },
    });
    expect(props.cardSpacingRowMM).toBe(7);
    expect(props.cardSpacingColMM).toBe(2.5);
  });

  it("bleed edge and registration offsets map straight through", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        bleedEdgeMM: 2,
        offsetXMM: -3.5,
        offsetYMM: 1.25,
      },
    });
    expect(props.bleedEdgeMM).toBe(2);
    expect(props.pageOffsetXMM).toBe(-3.5);
    expect(props.pageOffsetYMM).toBe(1.25);
  });

  it("project content and per-card bleed overrides map straight through", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      projectMembers: [
        {
          id: "member-1",
          front: {
            query: { cardType: CardType.Card, query: "x" },
            selectedImage: "a",
            selected: true,
          },
          back: null,
        },
      ],
      projectCardback: "cb-id",
      cardDocumentsByIdentifier: { a: undefined },
      manualOverrides: { a: "force-bleed" },
    });
    expect(props.projectMembers).toEqual([
      {
        id: "member-1",
        front: {
          query: { cardType: CardType.Card, query: "x" },
          selectedImage: "a",
          selected: true,
        },
        back: null,
      },
    ]);
    expect(props.projectCardback).toBe("cb-id");
    expect(props.cardDocumentsByIdentifier).toEqual({ a: undefined });
    expect(props.bleedOverrides).toEqual({ a: "force-bleed" });
  });
});

describe("buildDisplayPDFProps - print-quality rail settings map straight through", () => {
  it("imageQuality is always full-resolution; DPI and JPG quality come from the rail's sheet settings", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        imageDPI: 300,
        jpgQuality: 80,
      },
    });
    expect(props.imageQuality).toBe("full-resolution");
    expect(props.imageDPI).toBe(300);
    expect(props.jpgQuality).toBe(80);
  });
});

describe("buildDisplayPDFProps - card selection mode and page range map straight through from the rail's sheet settings", () => {
  it("card selection mode maps straight through", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        cardSelectionMode: "backsOnly",
      },
    });
    expect(props.cardSelectionMode).toBe("backsOnly");
  });

  it("page range is undefined by default (all sheets), for both the PDF page range and projectMembers", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.pageRangeStart).toBeUndefined();
    expect(props.pageRangeEnd).toBeUndefined();
    expect(props.projectMembers).toEqual(baseInput.projectMembers);
  });
});

describe("buildDisplayPDFProps - page range is a SHEET range for the standard grid, not a raw PDF page range", () => {
  const members: DisplayPDFPropsInput["projectMembers"] = Array.from(
    { length: 12 },
    (_, i) => ({
      id: `member-${i}`,
      front: {
        query: { cardType: CardType.Card, query: `q-${i}` },
        selectedImage: `front-${i}`,
        selected: true,
      },
      back: null,
    })
  );

  it("a sheet range restricts projectMembers to that sheet's own slots and clears the PDF page range fields", () => {
    // LETTER/rearFeed/default spacing is this file's own documented 4x2 grid (8 cards/sheet) -
    // sheet 2 of a 12-member deck is members 8-11, the deck's trailing partial sheet.
    const props = buildDisplayPDFProps({
      ...baseInput,
      projectMembers: members,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        pageRangeStart: 2,
        pageRangeEnd: 2,
      },
    });
    expect(props.pageRangeStart).toBeUndefined();
    expect(props.pageRangeEnd).toBeUndefined();
    expect(props.projectMembers).toEqual(members.slice(8, 12));
  });

  it("SCM mode keeps its own, pre-existing reading of the page range untouched", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      projectMembers: members,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        scmMode: true,
        pageRangeStart: 2,
        pageRangeEnd: 2,
      },
    });
    expect(props.pageRangeStart).toBe(2);
    expect(props.pageRangeEnd).toBe(2);
    expect(props.projectMembers).toEqual(members);
  });
});

describe("buildDisplayPDFProps - SCM mode maps straight through", () => {
  it("defaults to off, with the standard SCM baseline values", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.scmMode).toBe(false);
    expect(props.scmPaperSize).toBe("letter");
    expect(props.scmVariant).toBe("default");
    expect(props.scmRegistration).toBe(3);
    expect(props.scmDuplex).toBe(true);
    expect(props.scmOffsetXMM).toBe(0);
    expect(props.scmOffsetYMM).toBe(0);
    expect(props.scmOffsetAngleDeg).toBe(0);
  });

  it("every SCM sub-setting maps straight through from the rail's sheet settings when scmMode is on", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: {
        ...DEFAULT_SHEET_SETTINGS,
        scmMode: true,
        scmPaperSize: "a4",
        scmVariant: "borderless",
        scmRegistration: 4,
        scmDuplex: false,
        scmOffsetXMM: 1.5,
        scmOffsetYMM: -0.5,
        scmOffsetAngleDeg: 0.25,
      },
    });
    expect(props.scmMode).toBe(true);
    expect(props.scmPaperSize).toBe("a4");
    expect(props.scmVariant).toBe("borderless");
    expect(props.scmRegistration).toBe(4);
    expect(props.scmDuplex).toBe(false);
    expect(props.scmOffsetXMM).toBe(1.5);
    expect(props.scmOffsetYMM).toBe(-0.5);
    expect(props.scmOffsetAngleDeg).toBe(0.25);
  });
});
