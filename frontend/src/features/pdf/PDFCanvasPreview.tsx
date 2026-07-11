import { useEffect, useRef } from "react";

// pdf.js renders straight into <canvas> elements we own, with zero native
// browser chrome (no toolbar, no thumbnail sidebar, no page-fit letterboxing)
// and - unlike the native <object>/<iframe> embed this replaces - works
// identically in every browser, including Firefox.
const PAGE_GAP_PX = 12;
const RESIZE_DEBOUNCE_MS = 200;

export const PDFCanvasPreview = ({ url }: { url: string | undefined }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!url) {
      return;
    }

    let cancelled = false;
    let renderToken = 0;
    let pdfDocument: import("pdfjs-dist").PDFDocumentProxy | undefined;
    let resizeTimeout: ReturnType<typeof setTimeout> | undefined;

    const renderPages = async () => {
      if (pdfDocument == null || containerRef.current == null) {
        return;
      }
      const thisRenderToken = ++renderToken;
      const container = containerRef.current;
      container.replaceChildren();
      const containerWidth = container.clientWidth;

      for (
        let pageNumber = 1;
        pageNumber <= pdfDocument.numPages;
        pageNumber++
      ) {
        if (cancelled || thisRenderToken !== renderToken) {
          return;
        }
        const page = await pdfDocument.getPage(pageNumber);
        const unscaledViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / unscaledViewport.width;
        const viewport = page.getViewport({ scale });

        const canvas = document.createElement("canvas");
        canvas.style.display = "block";
        canvas.style.width = "100%";
        canvas.style.marginBottom = PAGE_GAP_PX + "px";
        const devicePixelRatio = window.devicePixelRatio || 1;
        canvas.width = viewport.width * devicePixelRatio;
        canvas.height = viewport.height * devicePixelRatio;
        const context = canvas.getContext("2d");
        if (context == null || cancelled || thisRenderToken !== renderToken) {
          return;
        }
        context.scale(devicePixelRatio, devicePixelRatio);
        container.appendChild(canvas);

        await page.render({ canvasContext: context, viewport }).promise;
      }
    };

    const load = async () => {
      const pdfjsLib = await import("pdfjs-dist");
      // Served from public/ (see scripts/copy-pdf-worker.js) rather than resolved
      // as an ESM module import - Next's webpack config can't bundle pdfjs-dist's
      // worker via `new URL(..., import.meta.url)`.
      pdfjsLib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

      const loadingTask = pdfjsLib.getDocument(url);
      pdfDocument = await loadingTask.promise;
      if (cancelled) {
        return;
      }
      await renderPages();
    };

    load();

    const resizeObserver = new ResizeObserver(() => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(renderPages, RESIZE_DEBOUNCE_MS);
    });
    if (containerRef.current != null) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      cancelled = true;
      clearTimeout(resizeTimeout);
      resizeObserver.disconnect();
      pdfDocument?.destroy();
    };
  }, [url]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", overflowY: "auto" }}
    />
  );
};
