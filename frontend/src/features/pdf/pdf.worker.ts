import { expose } from "comlink";

import type { PDFProps } from "./PDF";
import type { ImageFetchFailure } from "./pdfImage";
let log = console.info;

import { createElement } from "react";

export interface RenderPDFResult {
  blob: Blob;
  // Cards whose image couldn't be fetched, and so render blank in the PDF -
  // populated via PDFProps.reportImageFailure, which this function supplies
  // itself (not something a caller of renderPDF passes in).
  failures: Array<ImageFetchFailure>;
}

// Registered via onImageProgress below, called once per resolved image slot (success or
// failure) so the main thread can show live "fetching images: N/M" progress instead of a static
// spinner - a large export can take several minutes once full-resolution fetches are paced to
// the image CDN's shared rate limit (see pdfImage.ts's fetchFullResolutionImageAsBlob).
let imageProgressCallback: ((completed: number, total: number) => void) | null =
  null;

export const renderPDF = async (props: PDFProps): Promise<RenderPDFResult> => {
  const { pdf } = await import("@react-pdf/renderer");
  const { PDF } = await import("./PDF");
  const failures: Array<ImageFetchFailure> = [];
  // Approximate, not exact: counts unique card identifiers in the export, but a card that
  // appears in more than one slot (e.g. multiple copies in the deck) fetches its image once per
  // slot, not once per identifier - completed can end up slightly ahead of this total on decks
  // with duplicates. Good enough for a "this is actively working" indicator; not presented as an
  // exact fraction in the UI for that reason.
  const total = Object.keys(props.cardDocumentsByIdentifier).length;
  let completed = 0;
  const blob = await pdf(
    // @ts-ignore
    createElement(PDF, {
      ...props,
      reportImageFailure: (identifier: string, label: string) =>
        failures.push({ identifier, label }),
      reportImageProgress: () => {
        completed++;
        imageProgressCallback?.(completed, total);
      },
    })
  ).toBlob();
  return { blob, failures };
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
