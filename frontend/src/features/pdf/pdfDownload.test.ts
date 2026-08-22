import { CardType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { downloadFile } from "@/features/download/download";
import {
  buildDisplayPDFProps,
  DisplayExportSettings,
  DisplayPDFPropsInput,
} from "@/features/pdf/displayPdfProps";
import { DEFAULT_CARD_SELECTION_MODE, PDFProps } from "@/features/pdf/PDF";
import { downloadPDF } from "@/features/pdf/pdfDownload";
import { pdfRenderService } from "@/features/pdf/pdfRenderService";
import { APIGetTagConsensus } from "@/store/api";

// PDF.tsx (which pdfDownload.tsx pulls computeExportedCardIdentifiers from) imports
// @react-pdf/renderer at module scope - same stub pagination.test.ts/displayPdfProps.test.ts
// use, since nothing here renders a page.
jest.mock("@react-pdf/renderer", () => ({
  Document: () => null,
  Image: () => null,
  Page: () => null,
  Rect: () => null,
  Svg: () => null,
  StyleSheet: { create: (styles: unknown) => styles },
  View: () => null,
}));

// resolveBleedPriors itself is real code (not mocked) - only its network boundary is, so a
// regression here shows up as the wrong IDENTIFIERS being fetched, not just a mock being
// configured differently.
jest.mock("../../store/api", () => ({ APIGetTagConsensus: jest.fn() }));

jest.mock("../download/download", () => ({
  downloadFile: jest.fn().mockResolvedValue(undefined),
}));

jest.mock("./pdfRenderService", () => ({
  pdfRenderService: {
    renderPDF: jest.fn(),
    renderPDFInWorker: jest.fn(),
    onImageProgress: jest.fn(),
  },
}));

const mockAPIGetTagConsensus = APIGetTagConsensus as jest.Mock;
const mockRenderPDF = pdfRenderService.renderPDF as jest.Mock;
const mockDownloadFile = downloadFile as jest.Mock;

const cardDoc = (identifier: string): CardDocument =>
  ({ identifier, name: `Card ${identifier}` } as CardDocument);

// Same 20-member, fronts+backs, 8-cards/page LETTER-landscape deck PDF.test.ts uses (6 pages
// total: front/back/front/back/front/back, the last pair 4 cards each) - built via the real
// buildDisplayPDFProps adapter rather than a hand-rolled PDFProps, so this fixture matches what
// the export path actually emits.
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

const baseInput = (
  pageRangeStart?: number,
  pageRangeEnd?: number
): DisplayPDFPropsInput => ({
  sheetSettings: {
    pageSize: "LETTER",
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
    pageRangeStart,
    pageRangeEnd,
    marginOverride: undefined,
  },
  exportSettings: DEFAULT_EXPORT_SETTINGS,
  marginProfile: "rearFeed",
  cardSpacing: { row: 14.5, col: 0 },
  projectMembers: DECK_MEMBERS,
  projectCardback: "cardback",
  cardDocumentsByIdentifier: DECK_DOCS,
  manualOverrides: {},
});

const buildFullPDFProps = (
  pageRangeStart?: number,
  pageRangeEnd?: number
): Omit<PDFProps, "fileHandles"> =>
  buildDisplayPDFProps(baseInput(pageRangeStart, pageRangeEnd));

const mockClientSearchService = {
  getFileHandlesByIdentifier: jest.fn().mockResolvedValue({}),
} as unknown as ClientSearchService;

const runDownloadPDF = (props: Omit<PDFProps, "fileHandles">) =>
  downloadPDF(
    props,
    mockClientSearchService,
    jest.fn(),
    "http://backend",
    jest.fn(),
    jest.fn()
  );

describe("downloadPDF - bleed-prior resolution's fetch set", () => {
  beforeEach(() => {
    mockAPIGetTagConsensus.mockReset().mockResolvedValue({ tags: [] });
    mockRenderPDF
      .mockReset()
      .mockResolvedValue({ blob: new Blob(), failures: [] });
    mockDownloadFile.mockClear();
  });

  it("fetches every distinct project identifier for an unranged export", async () => {
    await runDownloadPDF(buildFullPDFProps());

    const fetchedIdentifiers = mockAPIGetTagConsensus.mock.calls.map(
      ([, identifier]) => identifier
    );
    expect(fetchedIdentifiers.sort()).toEqual(
      [...DECK_MEMBERS.map((m) => m.front.selectedImage), "cardback"].sort()
    );
  });

  it("scopes the fetch set to only the ranged page's cards, not the whole project", async () => {
    // Page 3 (index 2) is the front page for members 8..15 (front-8..front-15) - see
    // PDF.test.ts's computeExportedCardIdentifiers coverage for the same page layout.
    await runDownloadPDF(buildFullPDFProps(3, 3));

    const fetchedIdentifiers = mockAPIGetTagConsensus.mock.calls.map(
      ([, identifier]) => identifier
    );
    expect(fetchedIdentifiers.sort()).toEqual(
      Array.from({ length: 8 }, (_, i) => `front-${i + 8}`).sort()
    );
    // The regression this guards against: before the fix, every ranged export still fetched
    // all 21 project identifiers regardless of the 8 this page actually needs.
    expect(fetchedIdentifiers.length).toBe(8);
    expect(fetchedIdentifiers).not.toContain("cardback");
  });
});
