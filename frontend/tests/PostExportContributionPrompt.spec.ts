import { expect, Page } from "@playwright/test";
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

// Issue #166 - the post-export contribution prompt. Mounted from both real export surfaces
// (docs/features/print-export-page.md, docs/features/pdf-generator.md): DisplayPage.tsx's own
// inline export (Proposal H, item 2) and PDFGenerator.tsx itself (so the classic "Print!" tab
// gets it too, since it mounts the same component). These tests mirror DisplayPageExport.spec.ts
// and PDFGenerator.spec.ts's own proven mock/network setup, scoped to this new prompt.

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

test.describe("Post-export contribution prompt (issue #166) - /display", () => {
  test("appears after a successful export, links to /whatsthat, and is dismissible", async ({
    page,
    network,
  }) => {
    network.use(imageBucketSuccess, imageWorkerSuccess, ...oneCardHandlers);
    await goToDisplay(page);

    const prompt = page.getByTestId("post-export-contribution-prompt");
    await expect(prompt).not.toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("display-generate-pdf").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    await expect(prompt).toBeVisible();
    await expect(prompt).toContainText("What's That Card?");

    const link = page.getByTestId("post-export-contribution-prompt-link");
    await expect(link).toHaveAttribute("href", "/whatsthat");
    await link.click();
    await expect(page).toHaveURL(/\/whatsthat/);
  });

  test("dismissing it hides it, and it never re-appears again this session even after another successful export", async ({
    page,
    network,
  }) => {
    network.use(imageBucketSuccess, imageWorkerSuccess, ...oneCardHandlers);
    await goToDisplay(page);

    const prompt = page.getByTestId("post-export-contribution-prompt");
    await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("display-generate-pdf").click(),
    ]);
    await expect(prompt).toBeVisible();

    await prompt.getByRole("button", { name: /close/i }).click();
    await expect(prompt).not.toBeVisible();

    // A second successful export in the same session must not bring it back - "never repeats
    // within a session" (design doc's own §4.4′ footnote, task #31).
    await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("display-generate-pdf").click(),
    ]);
    await page.waitForTimeout(1_000);
    await expect(prompt).not.toBeVisible();
  });

  test("does NOT appear when the export is cancelled due to an image failure", async ({
    page,
    network,
  }) => {
    network.use(imageBucketFailure, imageWorkerFailure, ...oneCardHandlers);
    await goToDisplay(page);

    await page.getByTestId("display-generate-pdf").click();
    const modal = page.getByTestId("image-failure-confirm-modal");
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("image-failure-confirm-cancel").click();
    await expect(modal).not.toBeVisible();

    await page.waitForTimeout(1_000);
    await expect(
      page.getByTestId("post-export-contribution-prompt")
    ).not.toBeVisible();
  });
});

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
