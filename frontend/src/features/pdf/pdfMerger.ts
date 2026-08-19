import { PDFDocument, PDFName } from "pdf-lib";

const CATALOG_PAGE_MODE = PDFName.of("PageMode");
const CATALOG_PAGE_MODE_USE_THUMBS = PDFName.of("UseThumbs");

/**
 * Target document for pdf.worker.ts's page-batch pipeline. Each page batch's partial PDF
 * (rendered by @react-pdf/renderer) is appended via appendPDFDocument; the accumulated pages
 * are serialized once with saveMergedPDFBlob. Keeping the merge inside the same worker that
 * rendered the batches means a partial never crosses the main-thread postMessage boundary, and
 * only ONE partial document is ever live alongside the accumulating target - memory stays
 * bounded by (batch + accumulated-output), never (all-batches + all-output).
 */
export const createMergedPDFDocument = async (): Promise<PDFDocument> => {
  const document = await PDFDocument.create();
  // The single-shot render's <Document pageMode="useThumbs"> writes the catalog's PageMode
  // entry directly (react-pdf's render() does ctx._root.data.PageMode = "UseThumbs") - mirror
  // that on the merged output so the final file opens with the thumbnails sidebar exactly like
  // the pre-batching render. pdf-lib exposes no setPageMode helper; the catalog dict is the API.
  document.catalog.set(CATALOG_PAGE_MODE, CATALOG_PAGE_MODE_USE_THUMBS);
  return document;
};

/**
 * Appends every page of one @react-pdf/renderer partial PDF onto `target`, in document order.
 * copyPages carries each page's content stream and resources (image XObjects, fonts) verbatim -
 * image bytes are embedded as-is, never re-encoded, so output fidelity is unchanged. The source
 * document is dropped as soon as its pages are copied, so only `target` keeps growing.
 */
export const appendPDFDocument = async (
  target: PDFDocument,
  partial: Blob
): Promise<void> => {
  // pdf-lib validates inputs with `instanceof`, which fails for cross-realm
  // ArrayBuffers (jsdom's Blob.arrayBuffer returns one); re-wrap in this
  // realm's Uint8Array so the bytes type-check regardless of environment.
  const source = await PDFDocument.load(
    new Uint8Array(await partial.arrayBuffer())
  );
  const copiedPages = await target.copyPages(source, source.getPageIndices());
  for (const page of copiedPages) {
    target.addPage(page);
  }
};

/** Serializes the accumulated merged document to the final application/pdf Blob. */
export const saveMergedPDFBlob = async (target: PDFDocument): Promise<Blob> =>
  // target.save() returns Uint8Array<ArrayBufferLike> (its @types-era signature), which the
  // modern TS DOM lib's BlobPart no longer accepts; re-wrapping in a fresh Uint8Array makes the
  // buffer type ArrayBuffer so the Blob constructor type-checks. One final byte copy of the
  // serialized output - O(accumulated), a single one-time cost, not per-batch.
  new Blob([new Uint8Array(await target.save())], { type: "application/pdf" });
