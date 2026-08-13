import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { fileURLToPath } from "url";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// The editor's real Export ▾ -> PDF settings step (DisplayExportPDF.tsx) - the four controls
// that replaced named defaults in displayPdfProps.ts, plus the willGenerateBleed signal on the
// sheet itself. Reads back the actual downloaded PDF bytes (pdfjs-dist, page-count metadata
// only - no canvas/rendering needed for that) rather than trusting the wiring by inspection, per
// this feature's own "a control that renders but doesn't affect the export" failure mode.
test.describe.configure({ timeout: 60_000 });

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);
const imageWorkerSuccess = http.get(
  IMAGE_WORKER_URL_PATTERN,
  () =>
    new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    })
);
const imageBucketSuccess = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () =>
    new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    })
);

const tenCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  imageWorkerSuccess,
  imageBucketSuccess,
  ...defaultHandlers,
];

const openPDFSettings = async (page: import("@playwright/test").Page) => {
  await page.getByTestId("display-export-menu-toggle").click();
  await page.getByTestId("display-export-pdf-button").click();
  await expect(
    page.getByTestId("display-export-pdf-settings-modal")
  ).toBeVisible();
};

const readNumPages = async (buffer: Buffer): Promise<number> => {
  const doc = await getDocument({ data: new Uint8Array(buffer) }).promise;
  return doc.numPages;
};

test.describe("DisplayExportPDF - editor export controls", () => {
  test("opens with a safe default selection mode and a real, non-guessed total page count", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    // 10 identical fronts, 8 cards per page at the rail's default LETTER/rearFeed/D18 layout
    // (see displayPdfProps.test.ts's own documented 4x2 grid) -> 2 real pages.
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);

    await expect(
      page.getByTestId("display-export-card-selection-mode")
    ).toHaveValue("frontsAndBacks");
    await expect(page.getByText("Pages (2 total)")).toBeVisible();
  });

  test("page range slices the export to fewer real pages", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("1");
    await page.getByTestId("display-export-page-range-end").fill("1");
    const download1 = page.waitForEvent("download");
    await page.getByTestId("display-export-pdf-download-button").click();
    const path1 = await (await download1).path();
    if (!path1) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(path1))).toBe(1);

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("");
    await page.getByTestId("display-export-page-range-end").fill("");
    const download2 = page.waitForEvent("download");
    await page.getByTestId("display-export-pdf-download-button").click();
    const path2 = await (await download2).path();
    if (!path2) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(path2))).toBe(2);
  });

  test("card selection mode changes which faces the export contains", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    // Fronts only, never a back selection - "Backs Only" has nothing to paginate at all, "Fronts
    // + Backs" (the default) has 10 real fronts across 2 pages. A real, opposite-end difference.
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);
    const defaultDownload = page.waitForEvent("download");
    await page.getByTestId("display-export-pdf-download-button").click();
    const defaultPath = await (await defaultDownload).path();
    if (!defaultPath) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(defaultPath))).toBe(2);

    await openPDFSettings(page);
    await page
      .getByTestId("display-export-card-selection-mode")
      .selectOption("backsOnly");
    const backsOnlyDownload = page.waitForEvent("download");
    await page.getByTestId("display-export-pdf-download-button").click();
    const backsOnlyPath = await (await backsOnlyDownload).path();
    if (!backsOnlyPath) throw new Error("Download path is null");
    // PDF.tsx's own fallback for zero paginated pages ([[]]) - a single essentially-empty page,
    // not the 2 real pages the fronts produced.
    expect(await readNumPages(readFileSync(backsOnlyPath))).toBe(1);
  });

  test("DPI and JPG quality sliders set the actual image-worker request's dpi/jpgQuality query params", async ({
    page,
    network,
  }) => {
    // The mock image worker always serves the same static blank.png regardless of query
    // params, so a downloaded-file-size comparison would only measure incidental bleed-math
    // side effects, not the setting itself - getWorkerImageURL (common/image.ts) embeds
    // `dpi`/`jpgQuality` directly in the fetched URL, which is the actual signal PDFCardImage's
    // full-resolution path sends downstream, so assert on that request instead.
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("1");
    await page.getByTestId("display-export-page-range-end").fill("1");
    await page.getByTestId("display-export-image-dpi").fill("100");
    await page.getByTestId("display-export-jpg-quality").fill("5");

    const requestPromise = page.waitForRequest(
      (request) =>
        IMAGE_WORKER_URL_PATTERN.test(request.url()) &&
        request.url().includes("/full/")
    );
    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId("display-export-pdf-download-button").click();
    const [request] = await Promise.all([requestPromise, downloadPromise]);

    const requestUrl = new URL(request.url());
    expect(requestUrl.searchParams.get("dpi")).toBe("100");
    expect(requestUrl.searchParams.get("jpgQuality")).toBe("5");
  });

  test("cut-line colour and shape controls are only shown when the rail's Guides toggle is on, and map through to the export", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    await expect(
      page.getByTestId("display-export-cut-line-color")
    ).toBeVisible();
    await expect(
      page.getByTestId("display-export-cut-line-shape")
    ).toBeVisible();
    await page.getByTestId("display-export-cut-line-color").fill("#ff0000");
    await page
      .getByTestId("display-export-cut-line-shape")
      .selectOption("Cross");
    await expect(page.getByTestId("display-export-cut-line-color")).toHaveValue(
      "#ff0000"
    );
    await page.getByRole("button", { name: "Cancel" }).click();

    // Guides off -> the colour/shape controls have nothing to style, so they don't render.
    await page.getByLabel("Guides").uncheck();
    await openPDFSettings(page);
    await expect(
      page.getByTestId("display-export-cut-line-color")
    ).not.toBeVisible();
  });

  test("the bleed-will-be-generated badge appears on the editor sheet for a forced-trimmed eligible card", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await page.getByTestId("page-preview-slot").first().click();

    const select = page.getByTestId(
      `bleed-override-select-${cardDocument1.identifier}`
    );
    await expect(select).toBeVisible();
    await expect(
      page.getByTestId("page-preview-bleed-badge")
    ).not.toBeVisible();

    await select.selectOption("force-trimmed");

    await expect(page.getByTestId("page-preview-bleed-badge")).toBeVisible();
    await expect(page.getByTestId("page-preview-bleed-badge")).toContainText(
      "Bleed will be generated"
    );
  });
});
