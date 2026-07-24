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
import { navigateToPrintPDFTab } from "./test-utils";

// Parked-spec port wave (2026-07-24, issue #272). Re-homed onto the standalone /print route
// (D10, pages/print.tsx) - see PDFGenerator.spec.ts's own module comment for the full rationale.
//
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

// Generous file-level timeout (not the 30s default) - navigateToPrintPDFTab's own retry against
// /print's cold-compile race (test-utils.ts's own comment) needs headroom beyond a single 30s
// test timeout to actually get a second attempt in, same precedent PDFGenerator.spec.ts uses.
test.describe.configure({ timeout: 60_000 });

test.describe("Post-export contribution prompt (issue #166) - /print PDF tab", () => {
  test("appears after a successful export from PDFGenerator.tsx's own /print mount", async ({
    page,
    network,
  }) => {
    network.use(imageBucketSuccess, imageWorkerSuccess, ...oneCardHandlers);
    await navigateToPrintPDFTab(page, "my search query");

    const prompt = page.getByTestId("post-export-contribution-prompt");
    await expect(prompt).not.toBeVisible();

    await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Generate PDF" }).click(),
    ]);

    await expect(prompt).toBeVisible();
  });
});
