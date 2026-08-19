import { expose } from "comlink";

import type { PDFProps } from "./PDF";
import type { ImageFetchFailure } from "./pdfImage";
import { resetImageBlobCache, revokeTrackedObjectURLs } from "./pdfImage";

export interface RenderPDFResult {
  blob: Blob;
  // Cards whose image couldn't be fetched, and so render blank in the PDF -
  // populated via PDFProps.reportImageFailure, which renderPDF supplies
  // itself (not something a caller of renderPDF passes in).
  failures: Array<ImageFetchFailure>;
}

let log = console.info;

// Registered via onImageProgress below, called once per resolved image slot (success or
// failure) so the main thread can show live "fetching images: N/M" progress instead of a static
// spinner - a large export can take several minutes once full-resolution fetches are paced to
// the image CDN's shared rate limit (see pdfImage.ts's fetchFullResolutionImageAsBlob).
let imageProgressCallback: ((completed: number, total: number) => void) | null =
  null;

// How many PDF pages each `pdf()` call renders before its partial PDF is merged into the
// accumulating output (see renderPDF below). This is the knob that bounds the PDF worker's peak
// memory: the pre-batching code materialised the WHOLE document - every page's layout nodes and
// every fetched full-resolution image blob, each held via an object URL that was never revoked -
// in worker memory at once, which is what OOM'd large exports during the final assembly. With
// batching, only this many pages' images are ever live at once, and revokeTrackedObjectURLs
// releases their blobs the moment each batch's toBlob() has embedded them. Sized for the
// default full-resolution path (600 DPI / quality 100): one card's fetched + bleed-normalized +
// renderer-decoded copies are a few MB, a page holds up to ~9 of them, so 8 pages keeps a
// batch's durable image memory in the low hundreds of MB on a worker heap that must also hold
// the accumulating merged output. Tunable without touching the merge machinery.
export const PAGES_PER_BATCH = 8;

export const renderPDF = async (props: PDFProps): Promise<RenderPDFResult> => {
  const { pdf } = await import("@react-pdf/renderer");
  const { computePDFRenderWindow, createPDFElement } = await import("./PDF");
  const { MemorySink, PDFIncrementalWriter } = await import(
    "./pdfIncrementalWriter"
  );
  const { OpfsSink, cleanupStaleOpfsSinks, isOpfsAvailable } = await import(
    "./pdfOpfsSink"
  );

  const failures: Array<ImageFetchFailure> = [];
  // Approximate, not exact: counts unique card identifiers in the export, but `completed`
  // increments once per resolved image SLOT (PDF.tsx's PDFCardImage calls reportImageProgress
  // from every slot's own image resolution), not once per identifier - a card that appears in
  // more than one slot (e.g. multiple copies in the deck) still counts once per slot even though
  // pdfImage.ts's identifier-keyed cache (see getCachedImageBlob) means it's only actually
  // FETCHED once per batch - completed can end up slightly ahead of this total on decks with
  // duplicates. Good enough for a "this is actively working" indicator; not presented as an
  // exact fraction in the UI for that reason.
  const total = Object.keys(props.cardDocumentsByIdentifier).length;
  let completed = 0;

  const reportImageFailure = (identifier: string, label: string) =>
    failures.push({ identifier, label });
  const reportImageProgress = () => {
    completed++;
    imageProgressCallback?.(completed, total);
  };

  // Render the deck in page batches: each batch is a full standalone PDF of at most
  // PAGES_PER_BATCH pages (PDF()/SCMPDF slice the deck by the overloaded page range exactly as
  // the user's own page-range control would), and each batch's objects are streamed into `sink`
  // (OPFS-backed when available - see pdfOpfsSink.ts) before the next batch starts. Nothing the
  // writer produces is ever held in the worker's JS heap: PDFIncrementalWriter writes every
  // object straight through as it parses each batch, so peak memory is bounded by one batch's
  // render plus its own small per-batch parse tables - never by total page count. Batch order
  // equals write order, so the final document is the same page sequence the single-shot render
  // produced; each partial keeps its own font/image subsets, so per-page raster output is
  // unchanged (files may be marginally larger from duplicated subsets, never different content).
  await cleanupStaleOpfsSinks();
  const sink = isOpfsAvailable() ? await OpfsSink.create() : new MemorySink();
  const writer = new PDFIncrementalWriter(sink);
  const { startPage, totalPages } = computePDFRenderWindow(props);
  for (
    let batchStartPage = 1;
    batchStartPage <= totalPages;
    batchStartPage += PAGES_PER_BATCH
  ) {
    const batchEndPage = Math.min(
      batchStartPage + PAGES_PER_BATCH - 1,
      totalPages
    );
    let partialPdf: Blob;
    try {
      // batchStartPage/batchEndPage are page numbers WITHIN the caller's range slice; the
      // element receives them restated against the FULL deck (see computePDFRenderWindow),
      // because PDF()/SCMPDF() slice the full deck by these bounds - batch-relative numbers
      // would re-slice from page 1 and silently drop the caller's pageRangeStart offset.
      const element = createPDFElement({
        ...props,
        pageRangeStart: startPage + batchStartPage - 1,
        pageRangeEnd: startPage + batchEndPage - 1,
        reportImageFailure,
        reportImageProgress,
      });
      partialPdf = await pdf(element).toBlob();
    } finally {
      // Every object URL this batch's image resolution created (pdfImage.ts's tracking) is dead
      // once the batch's PDF has embedded its image bytes - releasing them keeps the browser's
      // blob store bounded by one batch instead of the whole deck (see PAGES_PER_BATCH). Also
      // runs on failure, so a mid-render error leaks at most the failing batch's URLs.
      revokeTrackedObjectURLs();
      // Clears pdfImage.ts's identifier-keyed fetch dedup cache in the same place, for the same
      // batch-bounded-memory reason (see getCachedImageBlob's comment) - a later batch that
      // re-references an identifier fetches it fresh rather than reusing a blob whose object
      // URLs this call just revoked.
      resetImageBlobCache();
    }
    await writer.appendBatch(new Uint8Array(await partialPdf.arrayBuffer()));
  }
  await writer.finalize();
  return {
    blob:
      sink instanceof MemorySink
        ? new Blob([new Uint8Array(sink.toUint8Array())], {
            type: "application/pdf",
          })
        : await sink.toBlob(),
    failures,
  };
};

const renderPDFInWorker = async (props: PDFProps): Promise<RenderPDFResult> => {
  try {
    return await renderPDF(props);
  } catch (error) {
    log(error);
    throw error;
  }
};

const onProgress = (cb: typeof console.info) => (log = cb);

const onImageProgress = (
  cb: (completed: number, total: number) => void
): void => {
  imageProgressCallback = cb;
};

expose({
  renderPDF,
  renderPDFInWorker: renderPDFInWorker,
  onProgress,
  onImageProgress,
});
export type PDFWorker = {
  renderPDF: typeof renderPDF;
  renderPDFInWorker: typeof renderPDFInWorker;
  onProgress: typeof onProgress;
  onImageProgress: typeof onImageProgress;
};
