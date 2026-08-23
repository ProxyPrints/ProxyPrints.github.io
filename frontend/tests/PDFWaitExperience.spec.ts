import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import {
  cardDocumentsOneResult,
  defaultHandlers,
  questionFeedConfirmSuggestionSingleton,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayExportMenu,
} from "./test-utils";

// Issue #811 - the editor's own wait experience for DisplayExportPDF.tsx's Download/Save-to-Drive
// buttons (PDFWaitPanel.tsx, mounted from DisplayExportPDF.tsx itself - see that file's own
// module comment). The equivalent coverage for /print's now-deleted PDFGenerator.tsx
// (PDFWaitExperience.spec.ts's original version) was dropped, not ported, when #813 retired that
// page and the route this suite used to reach it - this is the replacement, written against the
// editor's own Export ▾ -> PDF surface instead.
test.describe.configure({ timeout: 60_000 });

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);

// Artificially delayed (not instant) so the fetching phase - and thus the game embed - has a
// real window to be observed in, matching the same precedent DisplayExportPDFSettings.spec.ts's
// own sibling suite already establishes for this fixture.
const delayedImageWorkerSuccess = http.get(
  IMAGE_WORKER_URL_PATTERN,
  async () => {
    await new Promise((resolve) => setTimeout(resolve, 3_000));
    return new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    });
  }
);

const imageBucketFailure = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () => new HttpResponse(null, { status: 404 })
);

const imageBucketSuccess = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () =>
    new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    })
);

// Clicking PDF shows the cardback reminder gate on the first export attempt each test (a
// fresh project still riding the untouched default cardback) - CB1 suppresses it for the rest of
// that session. Same pattern DisplayExportPDFSettings.spec.ts's own clickDownload helper uses.
const clickDownload = async (page: import("@playwright/test").Page) => {
  await page.getByTestId("display-export-pdf-button").click();
  await page
    .getByTestId("pre-print-cardback-gate")
    .getByTestId("cardback-gate-use-current")
    .click({ timeout: 3_000 })
    .catch(() => {});
};

test.describe("PDF-generation wait experience (issue #811)", () => {
  test("the progress indicator appears before the render finishes, shows live fetching progress, and clears once the download completes", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      delayedImageWorkerSuccess,
      questionFeedConfirmSuggestionSingleton,
      ...defaultHandlers
    );

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await openDisplayExportMenu(page);

    const progressModal = page.getByTestId("display-export-pdf-progress-modal");
    await expect(progressModal).not.toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await clickDownload(page);

        // Appears promptly - well before the ~3s artificial image delay resolves, not after.
        await expect(progressModal).toBeVisible({ timeout: 2_000 });
        const progressBox = progressModal.getByTestId("pdf-progress");
        await expect(progressBox).toContainText("Fetching images", {
          timeout: 1_000,
        });

        // react-bootstrap's ProgressBar puts role="progressbar"/aria-valuenow on the INNER bar
        // element, not the outer data-testid'd wrapper.
        const bar = progressBox.getByRole("progressbar");
        await expect(bar).toHaveAttribute("aria-valuenow", /\d+/);
        const valueNow = await bar.getAttribute("aria-valuenow");
        // The determinate bar never claims a false 100% mid-fetch.
        expect(Number(valueNow)).toBeLessThanOrEqual(99);
      })(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Reaches completion and clears - no lingering "done" state to dismiss.
    await expect(progressModal).not.toBeVisible();
  });

  test("game embed: lazy-mounts the real QuestionFeed while generating, and tears down on finish", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      delayedImageWorkerSuccess,
      questionFeedConfirmSuggestionSingleton,
      ...defaultHandlers
    );

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    // Never mounted before generation starts - not even the Export dropdown has opened yet.
    await expect(page.getByTestId("pdf-wait-game")).toHaveCount(0);
    await expect(page.getByTestId("question-feed")).toHaveCount(0);

    await openDisplayExportMenu(page);
    // Opening the dropdown itself never mounts the game either - only actual generation does
    // (PDFWaitPanel.tsx's own module comment: "only imported once a caller actually mounts it").
    await expect(page.getByTestId("pdf-wait-game")).toHaveCount(0);
    await expect(page.getByTestId("question-feed")).toHaveCount(0);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await clickDownload(page);

        const embed = page.getByTestId("pdf-wait-game");
        await expect(embed).toBeVisible({ timeout: 2_000 });
        // The real, unforked QuestionFeed.
        await expect(embed.getByTestId("question-feed")).toBeVisible({
          timeout: 15_000,
        });
        await expect(embed.getByTestId("pdf-wait-game-ribbon")).toBeVisible();
        await expect(embed.getByTestId("pdf-wait-game-ribbon")).toContainText(
          "Building your PDF"
        );
      })(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Torn down on finish - the game (and QuestionFeed with it) unmounts entirely.
    await expect(page.getByTestId("pdf-wait-game")).toHaveCount(0);
    await expect(page.getByTestId("question-feed")).toHaveCount(0);
  });

  test("an image that fails to fetch surfaces a confirmation instead of silently stalling the bar", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      // Every image-worker request fails too, in addition to imageBucketFailure - forces
      // pdfImage.ts's own fetch chain to exhaust every fallback and report a genuine failure
      // rather than quietly recovering via the bucket/worker fallback pair.
      http.get(
        IMAGE_WORKER_URL_PATTERN,
        () => new HttpResponse(null, { status: 404 })
      ),
      questionFeedConfirmSuggestionSingleton,
      ...defaultHandlers
    );

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await openDisplayExportMenu(page);
    await clickDownload(page);

    const confirmModal = page.getByTestId("image-failure-confirm-modal");
    await expect(confirmModal).toBeVisible({ timeout: 15_000 });
    await expect(confirmModal).toContainText(
      "Some card images couldn't be loaded"
    );

    // Cancelling declines the download - the wait experience clears without ever completing.
    await confirmModal.getByTestId("image-failure-confirm-cancel").click();
    await expect(confirmModal).not.toBeVisible();
    await expect(
      page.getByTestId("display-export-pdf-progress-modal")
    ).not.toBeVisible();
  });

  test("a successful export shows the post-export 'What's That Card?' prompt", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      questionFeedConfirmSuggestionSingleton,
      ...defaultHandlers
    );

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await openDisplayExportMenu(page);

    await expect(
      page.getByTestId("post-export-contribution-prompt")
    ).toHaveCount(0);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickDownload(page),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    const prompt = page.getByTestId("post-export-contribution-prompt");
    await expect(prompt).toBeVisible();
    await expect(prompt).toContainText("What's That Card?");
    await expect(
      page.getByTestId("post-export-contribution-prompt-link")
    ).toHaveAttribute("href", "/whatsthat");
  });
});
