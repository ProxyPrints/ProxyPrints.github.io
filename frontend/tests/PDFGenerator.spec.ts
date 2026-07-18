import { expect, Page } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

// Matches the domains configured via NEXT_PUBLIC_IMAGE_WORKER_URL /
// NEXT_PUBLIC_IMAGE_BUCKET_URL in playwright.config.ts's webServer env.
const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

// A small real PNG so @react-pdf/renderer can actually decode it into a page,
// not just a byte blob that happens to satisfy `response.ok`.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);

const imageWorkerFailure = http.get(
  IMAGE_WORKER_URL_PATTERN,
  () => new HttpResponse(null, { status: 500 })
);
const imageBucketFailure = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () => new HttpResponse(null, { status: 404 })
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

const addCardAndOpenPDFTab = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importText(page, "my search query");
  await page.getByRole("tab", { name: "Print!" }).click();
  await page.getByRole("tab", { name: "PDF" }).click();
};

test.describe("PDFGenerator - card image fetch failures", () => {
  test("warns in the live preview when a card image fails to fetch", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);

    const warning = page.getByTestId("pdf-preview-image-failures");
    await expect(warning).toBeVisible({ timeout: 15_000 });
    await expect(warning).toContainText(cardDocument1.name);
  });

  test("blocks the download behind an in-app confirm modal naming the failed card, and honours cancelling it", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(page.getByTestId("pdf-preview-image-failures")).toBeVisible({
      timeout: 15_000,
    });

    const downloadPromise = page
      .waitForEvent("download", { timeout: 3_000 })
      .catch(() => undefined);
    await page.getByRole("button", { name: "Generate PDF" }).click();

    // Not window.confirm() - a real in-app Modal, immune to a browser silently suppressing
    // future confirm() calls after enough of them fire close together with other browser chrome
    // (the real incident this replaced native confirm() over - see PDFGenerator.tsx's comment).
    const modal = page.getByTestId("image-failure-confirm-modal");
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await expect(modal).toContainText(cardDocument1.name);
    await expect(modal).toContainText(/blank/i);

    await page.getByTestId("image-failure-confirm-cancel").click();

    await expect(page.getByText("Download Cancelled")).toBeVisible();
    await expect(modal).not.toBeVisible();
    // Cancelling must actually prevent the file from downloading.
    await expect(downloadPromise).resolves.toBeUndefined();
  });

  test("downloads anyway once the user confirms despite the failed image", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(page.getByTestId("pdf-preview-image-failures")).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: "Generate PDF" }).click();
    await expect(page.getByTestId("image-failure-confirm-modal")).toBeVisible({
      timeout: 15_000,
    });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("image-failure-confirm-continue").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
  });

  test("downloads without any warning or confirm when card images load successfully", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      imageWorkerSuccess,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(
      page.getByTestId("pdf-preview-image-failures")
    ).not.toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Generate PDF" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
    await expect(
      page.getByTestId("image-failure-confirm-modal")
    ).not.toBeVisible();
  });
});

test.describe("PDFGenerator - export image-fetch progress (rate-limit fix)", () => {
  test("shows live 'fetching images' progress instead of a silent, indefinite spinner", async ({
    page,
    network,
  }) => {
    // Artificially delayed (not instant, like every other mock in this file) so the progress
    // text has a real window to be observed in, rather than flashing for under a frame - a
    // large real export is genuinely slow now that full-resolution fetches are paced to the
    // image CDN's shared rate limit (see pdfImage.ts), which is exactly the wait this UI exists
    // to explain.
    const delayedImageWorkerSuccess = http.get(
      IMAGE_WORKER_URL_PATTERN,
      async () => {
        await new Promise((resolve) => setTimeout(resolve, 800));
        return new HttpResponse(validImageBytes, {
          status: 200,
          headers: { "Content-Type": "image/png" },
        });
      }
    );
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure, // bucket miss, falls through to the (delayed) worker
      delayedImageWorkerSuccess,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await page.getByRole("button", { name: "Generate PDF" }).click();
        await expect(page.getByTestId("pdf-image-fetch-progress")).toBeVisible({
          timeout: 15_000,
        });
        await expect(
          page.getByTestId("pdf-image-fetch-progress")
        ).toContainText("Fetching images:");
      })(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Clears once the render settles - doesn't linger after the button goes back to idle.
    await expect(
      page.getByTestId("pdf-image-fetch-progress")
    ).not.toBeVisible();
  });
});
