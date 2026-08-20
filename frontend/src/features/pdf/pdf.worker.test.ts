import type { PDFProps } from "./PDF";
import { PAGES_PER_BATCH, renderPDF } from "./pdf.worker";

// Self-contained factory: pdf.worker.ts calls expose() at module load, before this file's
// module body runs, so the factory cannot close over a not-yet-initialized const.
jest.mock("comlink", () => ({
  expose: jest.fn(),
}));

import { expose as comlinkExpose } from "comlink";

const mockExpose = comlinkExpose as jest.Mock;

const mockPdf = jest.fn();
jest.mock("@react-pdf/renderer", () => ({
  pdf: (element: unknown) => mockPdf(element),
}));

const mockComputePDFRenderWindow = jest.fn();
const mockCreatePDFElement = jest.fn();
jest.mock("./PDF", () => ({
  computePDFRenderWindow: (props: PDFProps) =>
    mockComputePDFRenderWindow(props),
  createPDFElement: (props: PDFProps) => mockCreatePDFElement(props),
}));

const mockAppendBatch = jest.fn();
const mockFinalize = jest.fn();
// Real classes (not jest.fn() factories) so `new PDFIncrementalWriter(sink)` and the worker's
// own `sink instanceof MemorySink` check both resolve against the exact class this mock module
// exports - the same identity pdf.worker.ts's dynamic `await import("./pdfIncrementalWriter")`
// receives.
class MockPDFIncrementalWriter {
  constructor(public readonly sink: unknown) {}
  appendBatch(bytes: Uint8Array) {
    return mockAppendBatch(bytes);
  }
  finalize() {
    return mockFinalize();
  }
}
const mockToUint8Array = jest.fn(() => new Uint8Array([1, 2, 3]));
class MockMemorySink {
  toUint8Array() {
    return mockToUint8Array();
  }
}
jest.mock("./pdfIncrementalWriter", () => ({
  PDFIncrementalWriter: MockPDFIncrementalWriter,
  MemorySink: MockMemorySink,
}));

const mockCleanupStaleOpfsSinks = jest.fn();
const mockIsOpfsAvailable = jest.fn();
const mockOpfsSinkCreate = jest.fn();
const mockOpfsSinkToBlob = jest.fn();
class MockOpfsSink {
  toBlob() {
    return mockOpfsSinkToBlob();
  }
}
jest.mock("./pdfOpfsSink", () => ({
  OpfsSink: { create: () => mockOpfsSinkCreate() },
  cleanupStaleOpfsSinks: () => mockCleanupStaleOpfsSinks(),
  isOpfsAvailable: () => mockIsOpfsAvailable(),
}));

const mockRevokeTrackedObjectURLs = jest.fn();
const mockResetImageBlobCache = jest.fn();
jest.mock("./pdfImage", () => ({
  revokeTrackedObjectURLs: () => mockRevokeTrackedObjectURLs(),
  resetImageBlobCache: () => mockResetImageBlobCache(),
}));

// The API the worker passed to comlink's expose() on module load - the test drives onImageProgress
// through it the same way pdfRenderService.ts does via Comlink.proxy(). The call already happened
// during import (before any test body runs), so it's read from the registry mock's recorded calls.
const exposedApi = mockExpose.mock.calls[0]?.[0] as
  | {
      renderPDF: typeof renderPDF;
      renderPDFInWorker: typeof renderPDF;
      onProgress: (cb: typeof console.info) => void;
      onImageProgress: (cb: (completed: number, total: number) => void) => void;
    }
  | undefined;

const makePDFProps = (overrides: Partial<PDFProps> = {}): PDFProps => ({
  cardSelectionMode: "frontsAndBacks",
  cutLinePlacement: "Inside",
  cutLineShape: "InsideOnly",
  pageSize: "LETTER",
  pageWidth: undefined,
  pageHeight: undefined,
  bleedEdgeMM: 3.175,
  roundCorners: false,
  drawCardCutLines: true,
  drawPageCutLines: true,
  cutLineLengthMM: 3,
  cutLineOffsetMM: 0,
  cutLineThicknessMM: 0.6,
  cutLineColor: "#8ae234",
  cardSpacingRowMM: 14.5,
  cardSpacingColMM: 0,
  pageMarginTopMM: 3,
  pageMarginBottomMM: 3,
  pageMarginLeftMM: 3,
  pageMarginRightMM: 20,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  cardDocumentsByIdentifier: { a: undefined, b: undefined },
  projectMembers: [],
  projectCardback: undefined,
  imageQuality: "full-resolution",
  imageDPI: 600,
  jpgQuality: 100,
  fileHandles: {},
  scmMode: false,
  scmPaperSize: "letter",
  scmVariant: "default",
  scmRegistration: 3,
  scmDuplex: true,
  scmOffsetXMM: 0,
  scmOffsetYMM: 0,
  scmOffsetAngleDeg: 0,
  ...overrides,
});

describe("PAGES_PER_BATCH", () => {
  it("is the documented 8-page batch", () => {
    expect(PAGES_PER_BATCH).toBe(8);
  });
});

describe("renderPDF - page batching bounds worker memory", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockComputePDFRenderWindow.mockReturnValue({ startPage: 1, totalPages: 1 });
    mockCreatePDFElement.mockImplementation((props: PDFProps) => props);
    mockPdf.mockImplementation(() => ({
      toBlob: jest
        .fn()
        .mockResolvedValue(new Blob(["partial"], { type: "application/pdf" })),
    }));
    mockAppendBatch.mockResolvedValue(undefined);
    mockFinalize.mockResolvedValue(undefined);
    mockToUint8Array.mockReturnValue(new Uint8Array([1, 2, 3]));
    mockCleanupStaleOpfsSinks.mockResolvedValue(undefined);
    // jsdom has no real OPFS - exercising the MemorySink fallback path is what the test
    // environment can actually cover; OpfsSink.create()/toBlob() are asserted separately.
    mockIsOpfsAvailable.mockReturnValue(false);
    mockOpfsSinkCreate.mockResolvedValue(new MockOpfsSink());
    mockOpfsSinkToBlob.mockResolvedValue(
      new Blob(["opfs"], { type: "application/pdf" })
    );
  });

  it("renders one element per PAGES_PER_BATCH page chunk, in absolute deck-page order", async () => {
    mockComputePDFRenderWindow.mockReturnValue({
      startPage: 1,
      totalPages: 20,
    });
    await renderPDF(makePDFProps());
    expect(mockComputePDFRenderWindow).toHaveBeenCalledTimes(1);
    const ranges = mockCreatePDFElement.mock.calls.map(([props]) => [
      (props as PDFProps).pageRangeStart,
      (props as PDFProps).pageRangeEnd,
    ]);
    expect(ranges).toEqual([
      [1, 8],
      [9, 16],
      [17, 20],
    ]);
  });

  it("restates batch bounds against the FULL deck when the caller supplied a page range", async () => {
    // Caller asked for pages 3..14; the window derives firstPage=3, totalPages=12.
    mockComputePDFRenderWindow.mockReturnValue({
      startPage: 3,
      totalPages: 12,
    });
    await renderPDF(makePDFProps({ pageRangeStart: 3, pageRangeEnd: 14 }));
    const ranges = mockCreatePDFElement.mock.calls.map(([props]) => [
      (props as PDFProps).pageRangeStart,
      (props as PDFProps).pageRangeEnd,
    ]);
    // Absolute deck pages, not slice-relative - PDF()/SCMPDF() slice the full deck by these.
    // Batch 2 is slice pages 9..12, restated against the full deck as 3+9-1 .. 3+12-1 = 11..14.
    expect(ranges).toEqual([
      [3, 10],
      [11, 14],
    ]);
  });

  it("streams each batch's partial into the incremental writer in render order, then finalizes once", async () => {
    mockComputePDFRenderWindow.mockReturnValue({
      startPage: 1,
      totalPages: 16,
    });
    const partials: Array<Blob> = [];
    mockPdf.mockImplementation(() => ({
      toBlob: jest.fn(() => {
        const blob = new Blob(["partial"], { type: "application/pdf" });
        partials.push(blob);
        return Promise.resolve(blob);
      }),
    }));
    const result = await renderPDF(makePDFProps());

    expect(mockAppendBatch).toHaveBeenCalledTimes(2);
    for (let i = 0; i < partials.length; i++) {
      const expectedBytes = new Uint8Array(await partials[i].arrayBuffer());
      expect(mockAppendBatch.mock.calls[i][0]).toEqual(expectedBytes);
    }
    expect(mockFinalize).toHaveBeenCalledTimes(1);
    expect(result.blob.type).toBe("application/pdf");
    expect(result.failures).toEqual([]);
  });

  it("falls back to MemorySink when OPFS is unavailable, and to OpfsSink when it is", async () => {
    mockIsOpfsAvailable.mockReturnValue(false);
    await renderPDF(makePDFProps());
    expect(mockOpfsSinkCreate).not.toHaveBeenCalled();
    expect(mockToUint8Array).toHaveBeenCalledTimes(1);

    jest.clearAllMocks();
    mockComputePDFRenderWindow.mockReturnValue({ startPage: 1, totalPages: 1 });
    mockCreatePDFElement.mockImplementation((props: PDFProps) => props);
    mockPdf.mockImplementation(() => ({
      toBlob: jest
        .fn()
        .mockResolvedValue(new Blob(["partial"], { type: "application/pdf" })),
    }));
    mockAppendBatch.mockResolvedValue(undefined);
    mockFinalize.mockResolvedValue(undefined);
    mockCleanupStaleOpfsSinks.mockResolvedValue(undefined);
    mockOpfsSinkCreate.mockResolvedValue(new MockOpfsSink());
    mockOpfsSinkToBlob.mockResolvedValue(
      new Blob(["opfs"], { type: "application/pdf" })
    );
    mockIsOpfsAvailable.mockReturnValue(true);

    await renderPDF(makePDFProps());
    expect(mockCleanupStaleOpfsSinks).toHaveBeenCalledTimes(1);
    expect(mockOpfsSinkCreate).toHaveBeenCalledTimes(1);
    expect(mockOpfsSinkToBlob).toHaveBeenCalledTimes(1);
    expect(mockToUint8Array).not.toHaveBeenCalled();
  });

  it("single-page exports render exactly one batch range [1,1]", async () => {
    mockComputePDFRenderWindow.mockReturnValue({ startPage: 1, totalPages: 1 });
    await renderPDF(makePDFProps());
    expect(mockCreatePDFElement).toHaveBeenCalledTimes(1);
    const range = mockCreatePDFElement.mock.calls[0][0] as PDFProps;
    expect(range.pageRangeStart).toBe(1);
    expect(range.pageRangeEnd).toBe(1);
  });

  it("exact multiples of PAGES_PER_BATCH do not emit an empty trailing batch", async () => {
    mockComputePDFRenderWindow.mockReturnValue({ startPage: 1, totalPages: 8 });
    await renderPDF(makePDFProps());
    expect(mockCreatePDFElement).toHaveBeenCalledTimes(1);
  });

  it("wires image progress and failure reporting through every batch, accumulated across batches", async () => {
    const progress = jest.fn();
    exposedApi?.onImageProgress(progress);
    mockComputePDFRenderWindow.mockReturnValue({
      startPage: 1,
      totalPages: 16,
    });
    mockCreatePDFElement.mockImplementation((props: PDFProps) => {
      // Simulate two card images resolving per batch (front + back of one card).
      props.reportImageProgress?.();
      props.reportImageProgress?.();
      props.reportImageFailure?.("card-a", "front");
      return props;
    });

    const result = await renderPDF(makePDFProps());

    // 2 batches x 2 progress ticks = 4; total = 2 identifiers in cardDocumentsByIdentifier.
    expect(progress.mock.calls).toEqual([
      [1, 2],
      [2, 2],
      [3, 2],
      [4, 2],
    ]);
    // One ImageFetchFailure per failed slot per batch - the same card can fail twice.
    expect(result.failures).toEqual([
      { identifier: "card-a", label: "front" },
      { identifier: "card-a", label: "front" },
    ]);
  });

  it("revokes tracked object URLs after EVERY batch, including when a batch render fails", async () => {
    mockComputePDFRenderWindow.mockReturnValue({
      startPage: 1,
      totalPages: 16,
    });
    mockPdf
      .mockImplementationOnce(() => ({
        toBlob: jest
          .fn()
          .mockResolvedValue(new Blob(["ok"], { type: "application/pdf" })),
      }))
      .mockImplementationOnce(() => ({
        toBlob: jest.fn().mockRejectedValue(new Error("render boom")),
      }));

    await expect(renderPDF(makePDFProps())).rejects.toThrow("render boom");
    // Batch 1's URL set released on success, batch 2's in the failure path's finally.
    expect(mockRevokeTrackedObjectURLs).toHaveBeenCalledTimes(2);
    // The dedup cache is cleared alongside the URL revoke every time, same batch boundary.
    expect(mockResetImageBlobCache).toHaveBeenCalledTimes(2);
    expect(mockAppendBatch).toHaveBeenCalledTimes(1);
    expect(mockFinalize).not.toHaveBeenCalled();
  });

  it("exposes the same comlink surface as before batching", () => {
    expect(exposedApi).toBeDefined();
    expect(exposedApi!.renderPDF).toBe(renderPDF);
    expect(typeof exposedApi!.renderPDFInWorker).toBe("function");
    expect(typeof exposedApi!.onProgress).toBe("function");
    expect(typeof exposedApi!.onImageProgress).toBe("function");
  });
});
