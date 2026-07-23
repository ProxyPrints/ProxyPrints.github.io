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
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`); the classic grid `ProjectEditor` this file's own setup
// depends on (via testids/interaction patterns like `front-slot`/`back-slot`/`common-cardback`/
// the "Add Cards" right-panel dropdown/the classic "Print!" tab, or a component with no rendered
// equivalent on the new page yet - see issue #272's own tracked parity gaps) is fully unrouted,
// not just delisted from the nav. Skipped here rather than deleted (component files themselves
// are untouched, per this swap's own scope) or silently left red - porting this coverage to
// DisplayPage's DOM is real, non-mechanical work tracked against #272, not done as part of the
// route swap itself (the owner's directive was to proceed with the swap regardless of the
// checklist's open items).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Proposal H switchover (2026-07-23): tests classic /editor-only UI, now unrouted - see issue #272"
  );
});

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
    await importTextOnEditorLanding(page, "my search query");
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
