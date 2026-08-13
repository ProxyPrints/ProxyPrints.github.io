import { CardType } from "@/common/schema_types";
import { ManualOverride } from "@/features/pdf/bleedNormalize";
import {
  buildDisplayPDFProps,
  DisplayExportSettings,
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
const DEFAULT_SHEET_SETTINGS = {
  pageSize: "LETTER" as const,
  bleedEdgeMM: 3.175,
  showCutLines: true,
  offsetXMM: 0,
  offsetYMM: 0,
};

// The export settings step's own defaults (DisplayExportPDF.tsx DEFAULT_EXPORT_SETTINGS) - the
// same full-res 600 DPI/100% pipeline PDFGenerator.tsx's own download path uses, and the same
// lime corner-only guide style PagePreview.tsx's E19 guides render on screen.
const DEFAULT_EXPORT_SETTINGS: DisplayExportSettings = {
  cardSelectionMode: DEFAULT_CARD_SELECTION_MODE,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  imageDPI: 600,
  jpgQuality: 100,
  cutLineColor: "#8ae234",
  cutLineShape: "InsideOnly",
};

const EMPTY_DOCS: { [identifier: string]: undefined } = {};
const NO_OVERRIDES: { [identifier: string]: ManualOverride } = {};

const baseInput: DisplayPDFPropsInput = {
  sheetSettings: DEFAULT_SHEET_SETTINGS,
  exportSettings: DEFAULT_EXPORT_SETTINGS,
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
});

describe("buildDisplayPDFProps - rail guide state reaches the exported PDF's cut lines", () => {
  it("showCutLines: true -> drawCardCutLines: true (and the default lime corner-only geometry)", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.drawCardCutLines).toBe(true);
    // Colour/shape come from exportSettings now (real controls); placement/length/thickness/
    // offset stay adapter defaults, matching PagePreview's E19 lime corner-only guides.
    expect(props.cutLineColor).toBe("#8ae234");
    expect(props.cutLineShape).toBe("InsideOnly");
    expect(props.cutLinePlacement).toBe("Inside");
  });

  it("showCutLines: false -> drawCardCutLines: false", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      sheetSettings: { ...DEFAULT_SHEET_SETTINGS, showCutLines: false },
    });
    expect(props.drawCardCutLines).toBe(false);
  });

  it("page cut lines are a named default (false) - the rail's Guides toggle never drew them", () => {
    expect(buildDisplayPDFProps(baseInput).drawPageCutLines).toBe(false);
  });

  it("cut line colour and shape map straight through from export settings", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      exportSettings: {
        ...DEFAULT_EXPORT_SETTINGS,
        cutLineColor: "#ff0000",
        cutLineShape: "Cross",
      },
    });
    expect(props.cutLineColor).toBe("#ff0000");
    expect(props.cutLineShape).toBe("Cross");
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

describe("buildDisplayPDFProps - export settings map straight through", () => {
  it("imageQuality is always full-resolution; DPI and JPG quality come from export settings", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      exportSettings: {
        ...DEFAULT_EXPORT_SETTINGS,
        imageDPI: 300,
        jpgQuality: 80,
      },
    });
    expect(props.imageQuality).toBe("full-resolution");
    expect(props.imageDPI).toBe(300);
    expect(props.jpgQuality).toBe(80);
  });

  it("card selection mode maps straight through from export settings", () => {
    const props = buildDisplayPDFProps({
      ...baseInput,
      exportSettings: {
        ...DEFAULT_EXPORT_SETTINGS,
        cardSelectionMode: "backsOnly",
      },
    });
    expect(props.cardSelectionMode).toBe("backsOnly");
  });

  it("page range maps straight through, undefined by default (all pages)", () => {
    expect(buildDisplayPDFProps(baseInput).pageRangeStart).toBeUndefined();
    expect(buildDisplayPDFProps(baseInput).pageRangeEnd).toBeUndefined();

    const props = buildDisplayPDFProps({
      ...baseInput,
      exportSettings: {
        ...DEFAULT_EXPORT_SETTINGS,
        pageRangeStart: 2,
        pageRangeEnd: 4,
      },
    });
    expect(props.pageRangeStart).toBe(2);
    expect(props.pageRangeEnd).toBe(4);
  });
});

describe("buildDisplayPDFProps - named defaults for fields with no editor equivalent", () => {
  it("corners stay square and SCM mode stays off", () => {
    const props = buildDisplayPDFProps(baseInput);
    expect(props.roundCorners).toBe(false);
    expect(props.scmMode).toBe(false);
    expect(props.scmPaperSize).toBe("letter");
    expect(props.scmVariant).toBe("default");
    expect(props.scmRegistration).toBe(3);
    expect(props.scmDuplex).toBe(true);
    expect(props.scmOffsetXMM).toBe(0);
    expect(props.scmOffsetYMM).toBe(0);
    expect(props.scmOffsetAngleDeg).toBe(0);
  });
});
