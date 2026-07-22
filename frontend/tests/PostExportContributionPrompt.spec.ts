import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

// Issue #166 - the post-export contribution prompt. Mounted from PDFGenerator.tsx (so the
// classic "Print!" tab / Print page gets it). It used to ALSO be mounted from DisplayPage.tsx's
// own inline export (Proposal H, item 2) - issue #275 removed that inline pipeline entirely (PDF
// generation now lives solely on the Print page, D10/pages/print.tsx), so that describe block
// (and its own `display-generate-pdf` coverage) is retired alongside it; this file's remaining
// coverage - PDFGenerator.tsx's own, unchanged mount - still exercises the real component this
// prompt is.

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

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

test.describe("Post-export contribution prompt (issue #166) - classic Print! tab", () => {
  test("also appears after a successful export from PDFGenerator.tsx's own classic tab", async ({
    page,
    network,
  }) => {
    network.use(imageBucketSuccess, imageWorkerSuccess, ...oneCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("tab", { name: "Print!" }).click();
    await page.getByRole("tab", { name: "PDF" }).click();

    const prompt = page.getByTestId("post-export-contribution-prompt");
    await expect(prompt).not.toBeVisible();

    await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Generate PDF" }).click(),
    ]);

    await expect(prompt).toBeVisible();
  });
});
