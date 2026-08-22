import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CardType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";
import {
  buildDisplayPDFProps,
  DisplayExportSettings,
  DisplayPDFPropsInput,
  DisplaySheetExportSettings,
} from "@/features/pdf/displayPdfProps";
import {
  computePDFRenderPageCount,
  computePDFRenderWindow,
  createPDFElement,
  DEFAULT_CARD_SELECTION_MODE,
  PDFProps,
} from "@/features/pdf/PDF";

// PDF.tsx pulls in @react-pdf/renderer at module scope (StyleSheet.create); this file exercises
// PDF.tsx's count/window/element helpers by RENDERING them, so the renderer is replaced with
// pass-through element factories that emit real DOM-ish tags in markup - renderToStaticMarkup
// then lets the tests count how many <pdf-page> elements PDF/SCMPDF actually produce and demand
// that count equal computePDFRenderPageCount. Same module-scope mock idea as the displayPdfProps
// and pagination tests, but structural rather than null so rendering works. Svg/Rect (the dashed
// trim-outline cut guide) need the same pass-through treatment as View/Image - without a mock,
// PDF.tsx's import of them from the real module would be undefined here.
jest.mock("@react-pdf/renderer", () => {
  const React = jest.requireActual<typeof import("react")>("react");
  return {
    Document: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-document", null, children),
    Page: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-page", null, children),
    View: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-view", null, children),
    Svg: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-svg", null, children),
    Rect: () => null,
    Image: () => null,
    StyleSheet: { create: (styles: unknown) => styles },
  };
});

// The rail's own defaults (DisplayPage.tsx DEFAULT_SHEET_SETTINGS) - a LETTER landscape sheet at
// the standard 3.175mm MPC bleed, guides on, no registration offset.
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
  roundCorners: false,
  cardSelectionMode: DEFAULT_CARD_SELECTION_MODE,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  marginOverride: undefined,
};

const DEFAULT_EXPORT_SETTINGS: DisplayExportSettings = {
  drawPageCutLines: true,
  scmMode: false,
  scmPaperSize: "letter",
  scmVariant: "default",
  scmRegistration: 3,
  scmDuplex: true,
  scmOffsetXMM: 0,
  scmOffsetYMM: 0,
  scmOffsetAngleDeg: 0,
};

const cardDoc = (identifier: string): CardDocument =>
  ({ identifier, name: `Card ${identifier}` } as CardDocument);

// 20 members, every back the shared project cardback - the ordinary deck fixture. LETTER
// landscape rearFeed is a 4x2 grid (8 cards/page, proven in displayPdfProps.test.ts), so the
// Fronts+Backs paginator's 20-front set and 20-back set each chunk into 3 pages -> 6 total.
const DECK_MEMBERS = Array.from({ length: 20 }, (_, i) => ({
  id: `slot-${i}`,
  front: {
    query: { cardType: CardType.Card, query: `front-${i}` },
    selectedImage: `front-${i}`,
    selected: true,
  },
  back: {
    query: { cardType: CardType.Card, query: "cardback" },
    selectedImage: "cardback",
    selected: true,
  },
}));
const DECK_DOCS: { [identifier: string]: CardDocument | undefined } =
  Object.fromEntries(
    [
      ...DECK_MEMBERS.map((m) => m.front.selectedImage as string),
      "cardback",
    ].map((id) => [id, cardDoc(id)])
  );

const baseInput: DisplayPDFPropsInput = {
  sheetSettings: DEFAULT_SHEET_SETTINGS,
  exportSettings: DEFAULT_EXPORT_SETTINGS,
  marginProfile: "rearFeed",
  cardSpacing: { row: 14.5, col: 0 },
  projectMembers: DECK_MEMBERS,
  projectCardback: "cardback",
  cardDocumentsByIdentifier: DECK_DOCS,
  manualOverrides: {},
};

const withExportSettings = (
  input: DisplayPDFPropsInput,
  exportSettings: DisplayExportSettings
): DisplayPDFPropsInput => ({ ...input, exportSettings });

const withSheetSettings = (
  input: DisplayPDFPropsInput,
  sheetSettings: Partial<DisplaySheetExportSettings>
): DisplayPDFPropsInput => ({
  ...input,
  sheetSettings: { ...input.sheetSettings, ...sheetSettings },
});

// buildDisplayPDFProps stops at Omit<PDFProps, "fileHandles"> (the main-thread adapter has no
// handles to populate; the render service adds them) - the functions under test take full
// PDFProps, so the empty-handles case is supplied here.
const buildFullPDFProps = (input: DisplayPDFPropsInput): PDFProps => ({
  ...buildDisplayPDFProps(input),
  fileHandles: {},
});

const FULL_DECK_PAGES = 6;

const countRenderedPages = (props: React.ReactElement) =>
  (renderToStaticMarkup(props).match(/<pdf-page/g) ?? []).length;

describe("computePDFRenderPageCount - standard path", () => {
  it("is the page total the render emits (fronts+backs, 8 cards/page -> 6 pages)", () => {
    const props = buildFullPDFProps(baseInput);
    expect(props.scmMode).toBe(false);
    expect(countRenderedPages(createPDFElement(props))).toBe(FULL_DECK_PAGES);
    expect(computePDFRenderPageCount(props)).toBe(FULL_DECK_PAGES);
  });

  it("counts the range-sliced page total, not the full deck", () => {
    const props = buildFullPDFProps(
      withSheetSettings(baseInput, { pageRangeStart: 2, pageRangeEnd: 4 })
    );
    expect(computePDFRenderPageCount(props)).toBe(3);
    expect(countRenderedPages(createPDFElement(props))).toBe(3);
  });

  it("an empty export still plans one page (the render's single-empty-page fallback)", () => {
    const props = buildFullPDFProps({
      ...baseInput,
      projectMembers: [],
      projectCardback: undefined,
      cardDocumentsByIdentifier: {},
    });
    expect(computePDFRenderPageCount(props)).toBe(1);
    expect(countRenderedPages(createPDFElement(props))).toBe(1);
  });
});

describe("computePDFRenderPageCount - SCM path", () => {
  const scmInput = (
    exportOverrides: Partial<DisplayExportSettings> = {},
    sheetOverrides: Partial<DisplaySheetExportSettings> = {}
  ): DisplayPDFPropsInput =>
    withSheetSettings(
      withExportSettings(baseInput, {
        ...DEFAULT_EXPORT_SETTINGS,
        scmMode: true,
        scmPaperSize: "letter",
        scmVariant: "default",
        scmDuplex: true,
        ...exportOverrides,
      }),
      sheetOverrides
    );

  it("counts the SCM render's own pagination (letter default 2x4, duplex -> 2/group)", () => {
    // 20 members -> ceil(20/8) = 3 groups -> 6 duplex pages.
    const props = buildFullPDFProps(scmInput());
    expect(props.scmMode).toBe(true);
    expect(computePDFRenderPageCount(props)).toBe(6);
    expect(countRenderedPages(createPDFElement(props))).toBe(6);
  });

  it("counts non-duplex SCM as one page per group", () => {
    const props = buildFullPDFProps(scmInput({ scmDuplex: false }));
    expect(computePDFRenderPageCount(props)).toBe(3);
    expect(countRenderedPages(createPDFElement(props))).toBe(3);
  });

  it("applies the range to the SCM page sequence (front/back interleaved)", () => {
    const props = buildFullPDFProps(
      scmInput({}, { pageRangeStart: 2, pageRangeEnd: 4 })
    );
    // Pages 2..4 = group0 back, group1 front, group1 back.
    expect(computePDFRenderPageCount(props)).toBe(3);
    expect(countRenderedPages(createPDFElement(props))).toBe(3);
  });

  it("an empty SCM export plans the duplex empty-page pair", () => {
    const props = buildFullPDFProps({
      ...scmInput(),
      projectMembers: [],
      projectCardback: undefined,
      cardDocumentsByIdentifier: {},
    });
    expect(computePDFRenderPageCount(props)).toBe(2);
    expect(countRenderedPages(createPDFElement(props))).toBe(2);
  });
});

describe("computePDFRenderWindow - absolute start page + range-sliced total", () => {
  it("full deck: starts at page 1, total = full page count", () => {
    const { startPage, totalPages } = computePDFRenderWindow(
      buildFullPDFProps(baseInput)
    );
    expect(startPage).toBe(1);
    expect(totalPages).toBe(FULL_DECK_PAGES);
  });

  it("a mid-deck range reports the slice's absolute start and its own length", () => {
    const { startPage, totalPages } = computePDFRenderWindow(
      buildFullPDFProps(
        withSheetSettings(baseInput, { pageRangeStart: 3, pageRangeEnd: 5 })
      )
    );
    expect(startPage).toBe(3);
    expect(totalPages).toBe(3);
  });
});

describe("createPDFElement - the per-batch element pdf() consumes", () => {
  it("is a valid React element carrying the caller's props untouched", () => {
    const props = buildFullPDFProps(baseInput);
    const element = createPDFElement(props);
    expect(React.isValidElement(element)).toBe(true);
    expect(element.props).toStrictEqual(
      expect.objectContaining({ pageRangeStart: undefined })
    );
  });
});
