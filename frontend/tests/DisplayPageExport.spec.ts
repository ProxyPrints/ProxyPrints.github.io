import { expect, Page } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import { cardDocument1, cardDocument2 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  cardDocumentsSixResults,
  defaultHandlers,
  searchResultsOneResult,
  searchResultsSixResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

// Proposal H, item 2 (owner's hands-on review): "Generate PDF" on /display now runs the REAL
// export pipeline in-page - the exact same useDownloadPDF/useSaveToDrivePDF/
// ImageFailureConfirmModal PDFGenerator.tsx itself uses (exported for this, not forked), fed by
// this page's own toolbar settings instead of a navigation to the classic PDF tab. These tests
// mirror PDFGenerator.spec.ts's own proven coverage for that shared pipeline (warn/cancel/
// continue/success, live fetch progress) scoped to this page's own entry point, plus this page's
// own non-default-settings and progress-bar-specific assertions.

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

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

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

const goToDisplay = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importText(page, "my search query");
  await page.getByRole("link", { name: "Display (beta)" }).click();
  await expect(page.getByTestId("display-page")).toBeVisible();
};

test.describe("DisplayPage inline export (Proposal H, item 2)", () => {
  test("exports with this page's own current, non-default settings and downloads cards.pdf - no navigation to a classic tab", async ({
    page,
    network,
  }) => {
    network.use(imageBucketSuccess, imageWorkerSuccess, ...oneCardHandlers);
    await goToDisplay(page);

    // Non-default settings: a distinct bleed edge from the default, and Guides off - these feed
    // the real export via exportPdfProps (see DisplayPage.tsx), not a separate settings store.
    await page.getByLabel("Bleed edge (mm)").fill("5");
    await page.getByLabel("Guides").uncheck();

    // The real pipeline fetches full-resolution images over the network (the #81 paced fetcher,
    // not a stub) - capturing that request is what proves this page's current settings actually
    // drove a real export rather than a no-op button.
    const fullResolutionFetch = page.waitForRequest(IMAGE_WORKER_URL_PATTERN);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      fullResolutionFetch,
      page.getByTestId("display-generate-pdf").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Stayed on /display throughout - the whole point of item 2 is no navigation to the classic
    // tab for this.
    await expect(page).toHaveURL(/\/display/);
  });

  test("shows a real determinate progress bar while images are fetched, then clears once the render settles", async ({
    page,
    network,
  }) => {
    // Longer than the file's default 30s - the staggered second image below deliberately adds
    // real wall-clock delay on top of this test's own dev-server first-compile cost (whichever
    // test in this file runs first pays that, same as DisplayPage.spec.ts's own documented
    // "first hit" cost).
    test.setTimeout(60_000);
    // Two distinct cards (not duplicate slots of the same one, which the export pipeline
    // dedupes by identifier down to a single fetch) - a single-image export can complete its
    // one and only progress callback already at completed===total, jumping straight to the
    // "Assembling PDF…" phase with no visibly distinct "fetching, not yet done" moment.
    // Staggered, not equally delayed - the Semaphore(3) paced fetcher (pdfImage.ts) issues both
    // requests concurrently, so two equally-delayed responses land back to back and can still
    // race past the assertion's poll before it ever observes completed < total. Resolving the
    // first request fast and the second slowly guarantees a long, stable window where exactly
    // one of two images has finished.
    let requestCount = 0;
    const staggeredImageWorkerSuccess = http.get(
      IMAGE_WORKER_URL_PATTERN,
      async () => {
        requestCount += 1;
        await new Promise((resolve) =>
          setTimeout(resolve, requestCount === 1 ? 0 : 3_000)
        );
        return new HttpResponse(validImageBytes, {
          status: 200,
          headers: { "Content-Type": "image/png" },
        });
      }
    );
    network.use(
      cardDocumentsSixResults,
      sourceDocumentsOneResult,
      searchResultsSixResults,
      imageBucketFailure, // bucket miss, falls through to the (staggered) worker
      staggeredImageWorkerSuccess,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 query 1\n1 query 2");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();

    // Wait for BOTH cards' documents to have resolved into state before exporting - otherwise
    // exportPdfProps' cardDocumentsByIdentifier can still only have 1 entry at click time (the
    // second card's fetch still in flight), making the pipeline's own total 1 instead of 2 and
    // collapsing the "fetching" phase to nothing observable, independent of this mock's own
    // stagger. The <img> alt text is set from the resolved CardDocument's own name - a reliable
    // readiness signal that doesn't depend on mediumThumbnailUrl, which every mock CardDocument
    // in test-constants.ts deliberately leaves as an empty string.
    const sheetSlots = page.getByTestId("page-preview-slot");
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument1.name
    );
    await expect(sheetSlots.nth(1).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );

    // A MutationObserver, not a polled Playwright assertion - the "fetching" phase's own
    // window can be narrower than an assertion's poll interval, especially for a 2-image export
    // where the whole phase might only last as long as this test's own stagger. The observer
    // fires synchronously on every DOM change, so it can't miss a value between polls the way an
    // expect().toContainText() retry loop can.
    await page.evaluate(() => {
      (
        window as unknown as { __progressTexts: Array<string | null> }
      ).__progressTexts = [];
      const observer = new MutationObserver(() => {
        const el = document.querySelector(
          '[data-testid="display-export-progress-bar"]'
        );
        if (el != null) {
          (
            window as unknown as { __progressTexts: Array<string | null> }
          ).__progressTexts.push(el.textContent);
        }
      });
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("display-generate-pdf").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    const progressTexts = await page.evaluate(
      () =>
        (window as unknown as { __progressTexts: Array<string | null> })
          .__progressTexts
    );
    expect(
      progressTexts.some((text) => text?.includes("Fetching images:"))
    ).toBe(true);

    await expect(page.getByTestId("display-export-progress")).not.toBeVisible();
  });

  test("blocks the download behind the in-app failure-confirm modal on a dead image link, and cancelling actually prevents the download", async ({
    page,
    network,
  }) => {
    network.use(imageBucketFailure, imageWorkerFailure, ...oneCardHandlers);
    await goToDisplay(page);

    const downloadPromise = page
      .waitForEvent("download", { timeout: 3_000 })
      .catch(() => undefined);
    await page.getByTestId("display-generate-pdf").click();

    const modal = page.getByTestId("image-failure-confirm-modal");
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await expect(modal).toContainText(cardDocument1.name);

    await page.getByTestId("image-failure-confirm-cancel").click();
    await expect(modal).not.toBeVisible();
    await expect(downloadPromise).resolves.toBeUndefined();
  });

  test("downloads anyway once the user confirms despite the failed image - same in-app modal PDFGenerator.tsx uses, not forked", async ({
    page,
    network,
  }) => {
    network.use(imageBucketFailure, imageWorkerFailure, ...oneCardHandlers);
    await goToDisplay(page);

    await page.getByTestId("display-generate-pdf").click();
    await expect(page.getByTestId("image-failure-confirm-modal")).toBeVisible({
      timeout: 15_000,
    });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("image-failure-confirm-continue").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
  });
});
