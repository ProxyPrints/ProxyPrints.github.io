import { proxy, Remote, wrap } from "comlink";

import { PDFProps } from "@/features/pdf/PDF";

import type { PDFWorker, RenderPDFResult } from "./pdf.worker";

export class PDFRenderService {
  worker: Remote<PDFWorker> | undefined;
  constructor() {
    this.worker = undefined;
  }

  public initialiseWorker() {
    const worker = new Worker(new URL("./pdf.worker.ts", import.meta.url), {
      type: "module",
    });
    this.worker = wrap<PDFWorker>(worker);
  }

  public renderPDF(props: PDFProps): Promise<RenderPDFResult> {
    if (this.worker === undefined) {
      throw new Error("PDFRenderService was not initialised!");
    }
    return this.worker.renderPDF(props);
  }

  // TODO: awful naming. fix.
  public renderPDFInWorker(props: PDFProps): Promise<RenderPDFResult> {
    if (this.worker === undefined) {
      throw new Error("PDFRenderService was not initialised!");
    }
    return this.worker.renderPDFInWorker(props);
  }

  /** Registers a callback for live "fetching images: N/M" progress during the NEXT render call
   * on this worker - see pdf.worker.ts's onImageProgress for what drives it. Call this before
   * renderPDF/renderPDFInWorker, not after; there's nothing to subscribe to once the render
   * promise has already resolved. */
  public onImageProgress(cb: (completed: number, total: number) => void): void {
    if (this.worker === undefined) {
      throw new Error("PDFRenderService was not initialised!");
    }
    // A plain function isn't structured-clone-able, so comlink's default postMessage transfer
    // throws a DataCloneError the instant this actually fires - Comlink.proxy() wraps it as a
    // MessagePort-backed remote-callable proxy instead, comlink's documented mechanism for
    // passing a live callback (as opposed to plain data) across the worker boundary.
    this.worker.onImageProgress(proxy(cb));
  }
}

export const pdfRenderService = new PDFRenderService();
