import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  CardHeightMM,
  CardWidthMM,
  DEFAULT_CUT_LINE_COLOR,
  DEFAULT_CUT_LINE_LENGTH_MM,
  DEFAULT_CUT_LINE_THICKNESS_MM,
} from "@/common/constants";
import { CardType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";
import {
  buildDisplayPDFProps,
  DisplayPDFPropsInput,
  DisplaySheetExportSettings,
} from "@/features/pdf/displayPdfProps";
import { computeLayout } from "@/features/pdf/layout";
import { getPageSizeMM } from "@/features/pdf/pageSize";
import {
  computeExportedCardIdentifiers,
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
// bleed-outline cut guide) need the same pass-through treatment as View/Image - without a mock,
// PDF.tsx's import of them from the real module would be undefined here. View/Svg also carry
// their `style` prop through as a `data-style` JSON attribute, and Rect carries every prop
// through as `data-props` JSON, so the cut-guide geometry tests below can read back exactly what
// PDFCardCutLines computed rather than only counting rendered tags.
jest.mock("@react-pdf/renderer", () => {
  const React = jest.requireActual<typeof import("react")>("react");
  return {
    Document: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-document", null, children),
    Page: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("pdf-page", null, children),
    View: ({
      children,
      style,
    }: {
      children?: React.ReactNode;
      style?: unknown;
    }) =>
      React.createElement(
        "pdf-view",
        { "data-style": JSON.stringify(style ?? null) },
        children
      ),
    Svg: ({
      children,
      style,
      width,
      height,
    }: {
      children?: React.ReactNode;
      style?: unknown;
      width?: number;
      height?: number;
    }) =>
      React.createElement(
        "pdf-svg",
        { "data-style": JSON.stringify(style ?? null), width, height },
        children
      ),
    Rect: (props: Record<string, unknown>) =>
      React.createElement("pdf-rect", {
        "data-props": JSON.stringify(props),
      }),
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
  cutLineColor: DEFAULT_CUT_LINE_COLOR,
  showCrossCutLines: false,
  cutLineLengthMM: DEFAULT_CUT_LINE_LENGTH_MM,
  cutLineThicknessMM: DEFAULT_CUT_LINE_THICKNESS_MM,
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
  drawPageCutLines: true,
  scmMode: false,
  scmPaperSize: "letter" as const,
  scmVariant: "default" as const,
  scmRegistration: 3 as const,
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
  marginProfile: "rearFeed",
  cardSpacing: { row: 14.5, col: 0 },
  projectMembers: DECK_MEMBERS,
  projectCardback: "cardback",
  cardDocumentsByIdentifier: DECK_DOCS,
  manualOverrides: {},
};

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
    sheetOverrides: Partial<DisplaySheetExportSettings> = {}
  ): DisplayPDFPropsInput =>
    withSheetSettings(baseInput, {
      scmMode: true,
      scmPaperSize: "letter",
      scmVariant: "default",
      scmDuplex: true,
      ...sheetOverrides,
    });

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
      scmInput({ pageRangeStart: 2, pageRangeEnd: 4 })
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

describe("computeExportedCardIdentifiers", () => {
  it("returns every distinct identifier across the full, unranged deck", () => {
    const props = buildFullPDFProps(baseInput);
    expect(computeExportedCardIdentifiers(props).sort()).toEqual(
      [...DECK_MEMBERS.map((m) => m.front.selectedImage), "cardback"].sort()
    );
  });

  it("scopes to only the ranged page's identifiers, not the whole project", () => {
    const props = buildFullPDFProps(
      withSheetSettings(baseInput, { pageRangeStart: 2, pageRangeEnd: 2 })
    );
    // Page 2 (index 1) is group 0's back page - every slot's back is the shared "cardback"
    // identifier, deduplicated to the one entry actually needed for this ranged export.
    expect(computeExportedCardIdentifiers(props)).toEqual(["cardback"]);
  });

  it("scopes to a front-only page's identifiers", () => {
    const props = buildFullPDFProps(
      withSheetSettings(baseInput, { pageRangeStart: 3, pageRangeEnd: 3 })
    );
    expect(computeExportedCardIdentifiers(props).sort()).toEqual(
      Array.from({ length: 8 }, (_, i) => `front-${i + 8}`).sort()
    );
  });

  it("returns no identifiers for SCM mode, which never reads bleedPriors", () => {
    const props = buildFullPDFProps(
      withSheetSettings(baseInput, { scmMode: true })
    );
    expect(computeExportedCardIdentifiers(props)).toEqual([]);
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

describe("PDFCardCutLines geometry - the bleed-edge guide", () => {
  const ptToMm = (pt: number) => (pt / 72) * 25.4;

  // The first <pdf-svg>/<pdf-rect> pair in render order is always the (colIndex 0, rowIndex 0)
  // card slot's own cut-line guide - Svg is only ever rendered from PDFCardCutLines in this
  // codebase, one per slot, in grid order.
  const firstCutLineGuide = (props: PDFProps) => {
    const html = renderToStaticMarkup(createPDFElement(props));
    const svgStyleJson = /<pdf-svg data-style="([^"]*)"/.exec(html)?.[1];
    const rectPropsJson = /<pdf-rect data-props="([^"]*)"/.exec(html)?.[1];
    if (svgStyleJson == null || rectPropsJson == null) {
      throw new Error("no cut-line guide found in the rendered markup");
    }
    const svgStyle = JSON.parse(svgStyleJson.replace(/&quot;/g, '"')) as {
      left: string;
      top: string;
    };
    const rectProps = JSON.parse(rectPropsJson.replace(/&quot;/g, '"')) as {
      x: number;
      width: number;
      height: number;
      rx: number;
      ry: number;
      stroke: string;
      strokeWidth: number;
    };
    return { svgStyle, rectProps };
  };

  // Independently re-derives the same per-edge bleed grant PDF.tsx's own contextAvailableBleedMM
  // reads (computeLayout's slot 0), so the assertions below check against the real granted
  // bleed rather than assuming the full requested bleedEdgeMM survived uncropped.
  const grantedBleedMM = (props: PDFProps) => {
    const size = getPageSizeMM(
      props.pageSize,
      props.pageWidth,
      props.pageHeight
    );
    const layout = computeLayout(
      size.width,
      size.height,
      CardWidthMM,
      CardHeightMM,
      props.bleedEdgeMM,
      {
        top: props.pageMarginTopMM,
        bottom: props.pageMarginBottomMM,
        left: props.pageMarginLeftMM,
        right: props.pageMarginRightMM,
      },
      { row: props.cardSpacingRowMM, col: props.cardSpacingColMM }
    );
    return layout.slots[0].bleedMM;
  };

  it("tracks the configured bleed edge, not a fixed constant: width follows the real per-edge grant at two different bleed values", () => {
    // rearFeed's own fit math caps the granted bleed well below the MPC-standard 3.175mm request
    // (BleedGrantedReadout.tsx's whole reason for existing) - 0.2mm/0.4mm stay under that cap on
    // both requests, so the two actually resolve to two different grants rather than both
    // clamping to the same ceiling.
    const smallBleedProps = buildFullPDFProps(
      withSheetSettings(baseInput, { bleedEdgeMM: 0.2 })
    );
    const largeBleedProps = buildFullPDFProps(
      withSheetSettings(baseInput, { bleedEdgeMM: 0.4 })
    );

    for (const props of [smallBleedProps, largeBleedProps]) {
      const bleedMM = grantedBleedMM(props);
      const expectedWidthMM = CardWidthMM + bleedMM.left + bleedMM.right;
      const expectedHeightMM = CardHeightMM + bleedMM.top + bleedMM.bottom;
      const { rectProps } = firstCutLineGuide(props);
      expect(ptToMm(rectProps.width)).toBeCloseTo(expectedWidthMM, 3);
      expect(ptToMm(rectProps.height)).toBeCloseTo(expectedHeightMM, 3);
    }

    // The two bleed values must actually produce two different guide sizes - otherwise the
    // above could pass by coincidence (e.g. both silently clamped to the same value).
    const { rectProps: small } = firstCutLineGuide(smallBleedProps);
    const { rectProps: large } = firstCutLineGuide(largeBleedProps);
    expect(ptToMm(large.width)).toBeGreaterThan(ptToMm(small.width));
  });

  it("sits outside the printed card face, on the true bleed edge - not straddling the trim line", () => {
    const props = buildFullPDFProps(baseInput);
    const bleedMM = grantedBleedMM(props);
    expect(bleedMM.left).toBeGreaterThan(0); // otherwise this fixture can't distinguish the two anchors

    const { svgStyle, rectProps } = firstCutLineGuide(props);
    const strokePadMM = props.cutLineThicknessMM / 2;

    // Anchored at the slot's own outer edge (offset 0 minus half the stroke), never at
    // `bleedMM.left`/`bleedMM.top` - a regression back to the trim-edge anchor would put this at
    // a positive ~bleedMM.left mm instead.
    expect(svgStyle.left).toBe(`${-strokePadMM}mm`);
    expect(svgStyle.top).toBe(`${-strokePadMM}mm`);
    // The outline spans the full card-plus-bleed box, strictly larger than the bare card.
    expect(ptToMm(rectProps.width)).toBeGreaterThan(CardWidthMM);
    expect(ptToMm(rectProps.height)).toBeGreaterThan(CardHeightMM);
  });

  it("a positive offset grows the guide further outward, past the bleed edge", () => {
    const props = buildFullPDFProps(
      withSheetSettings(baseInput, { cutLineOffsetMM: 2 })
    );
    const strokePadMM = props.cutLineThicknessMM / 2;
    const { svgStyle } = firstCutLineGuide(props);
    expect(svgStyle.left).toBe(`${-2 - strokePadMM}mm`);
    expect(svgStyle.top).toBe(`${-2 - strokePadMM}mm`);
  });

  it("defaults to a thin lime hairline, not the old thick 0.6mm stroke", () => {
    expect(DEFAULT_CUT_LINE_COLOR).toBe("#8ae234");
    expect(DEFAULT_CUT_LINE_THICKNESS_MM).toBe(0.25);

    const props = buildFullPDFProps(baseInput);
    const { rectProps } = firstCutLineGuide(props);
    expect(rectProps.stroke).toBe(DEFAULT_CUT_LINE_COLOR);
    expect(ptToMm(rectProps.strokeWidth)).toBeCloseTo(
      DEFAULT_CUT_LINE_THICKNESS_MM,
      3
    );
  });

  it("roundCorners toggles the guide's own corner radius, square by default", () => {
    const square = firstCutLineGuide(buildFullPDFProps(baseInput));
    expect(square.rectProps.rx).toBe(0);
    expect(square.rectProps.ry).toBe(0);

    const rounded = firstCutLineGuide(
      buildFullPDFProps(withSheetSettings(baseInput, { roundCorners: true }))
    );
    expect(rounded.rectProps.rx).toBeGreaterThan(0);
    expect(rounded.rectProps.ry).toBeGreaterThan(0);
  });
});
