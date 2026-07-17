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

export const renderPDF = async (props: PDFProps): Promise<RenderPDFResult> => {
  const { pdf } = await import("@react-pdf/renderer");
  const { PDF } = await import("./PDF");
  const failures: Array<ImageFetchFailure> = [];
  const blob = await pdf(
    // @ts-ignore
    createElement(PDF, {
      ...props,
      reportImageFailure: (identifier: string, label: string) =>
        failures.push({ identifier, label }),
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

expose({ renderPDF, renderPDFInWorker: renderPDFInWorker, onProgress });
export type PDFWorker = {
  renderPDF: typeof renderPDF;
  renderPDFInWorker: typeof renderPDFInWorker;
  onProgress: typeof onProgress;
};
