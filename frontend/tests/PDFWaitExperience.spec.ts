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
} from "./test-utils";

// PDF-generation wait experience round (SPEC-cardback-pdfwait.md §D, PKG2) - reached via the real
// editor -> Finish footer -> (cardback reminder gate) -> /print flow, not the classic /editor
// route (fully unrouted post-Proposal-H - see PDFGenerator.spec.ts's own module comment). This is
// the ONE live entry point PDFGenerator.tsx has today.

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);

const imageBucketFailure = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () => new HttpResponse(null, { status: 404 })
);
// Artificially delayed (not instant) so the "fetching" phase - and thus the game embed - has a
// real window to be observed in, matching the pre-existing precedent for this same need
// (PDFGenerator.spec.ts's own "shows live 'fetching images' progress" test, before that whole
// file was retired by the Proposal H route swap).
const delayedImageWorkerSuccess = http.get(
  IMAGE_WORKER_URL_PATTERN,
  async () => {
    await new Promise((resolve) => setTimeout(resolve, 4_000));
    return new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    });
  }
);

const reachPDFTabOnPrintPage = async (
  page: import("@playwright/test").Page
) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "my search query");

  await page.getByTestId("finish-footer-print-export").click();
  const cardbackGate = page.getByTestId("pre-print-cardback-gate");
  await expect(cardbackGate).toBeVisible();
  await cardbackGate.getByTestId("cardback-gate-use-current").click();

  await page.waitForURL(/\/print/, { timeout: 30_000 });
  await page.getByRole("tab", { name: "PDF" }).click();
};

test.describe("PDF-generation wait experience (SPEC-cardback-pdfwait.md §D, PKG2)", () => {
  test.describe.configure({ mode: "serial", timeout: 90_000 });

  test("progress phases: determinate fetching -> indeterminate assembling -> green done, replacing the bare text line", async ({
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

    await reachPDFTabOnPrintPage(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await page.getByRole("button", { name: "Generate PDF" }).click();

        const progressBox = page.getByTestId("pdf-progress");
        await expect(progressBox).toBeVisible({ timeout: 15_000 });
        await expect(progressBox).toContainText("Fetching images", {
          timeout: 3_000,
        });
        // react-bootstrap's ProgressBar puts role="progressbar"/aria-valuenow on the INNER bar
        // element, not the outer data-testid'd wrapper - scope via role instead.
        const bar = progressBox.getByRole("progressbar");
        await expect(bar).toHaveAttribute("aria-valuenow", /\d+/);

        // The determinate bar never claims a false 100% mid-fetch (seam 2a).
        const valueNow = await bar.getAttribute("aria-valuenow");
        expect(Number(valueNow)).toBeLessThanOrEqual(99);
      })(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Done phase - green bar, "PDF ready" label.
    const progressBox = page.getByTestId("pdf-progress");
    await expect(progressBox).toContainText("✓ PDF ready");
  });

  test("game embed: lazy-mounts the real QuestionFeed while generating, and tears down to the outro on finish (no standalone duplicate)", async ({
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

    await reachPDFTabOnPrintPage(page);

    // Never mounted before generation starts (2c - lazy-load only once isDownloading is true).
    await expect(page.getByTestId("pdf-wait-game")).toHaveCount(0);
    await expect(page.getByTestId("question-feed")).toHaveCount(0);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await page.getByRole("button", { name: "Generate PDF" }).click();

        const embed = page.getByTestId("pdf-wait-game");
        await expect(embed).toBeVisible({ timeout: 15_000 });
        // The real, unforked QuestionFeed funnel - Level 1 YES/NOT SURE/NO/SKIP.
        await expect(embed.getByTestId("question-feed")).toBeVisible({
          timeout: 15_000,
        });
        await expect(embed.getByTestId("question-feed-level1")).toBeVisible();
        await expect(embed.getByTestId("pdf-wait-game-ribbon")).toBeVisible();
      })(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // Torn down on finish - the game (and QuestionFeed with it) unmounts entirely.
    await expect(page.getByTestId("pdf-wait-game")).toHaveCount(0);
    await expect(page.getByTestId("question-feed")).toHaveCount(0);

    // The outro (the shipped PostExportContributionPrompt, unchanged) replaces it in the SAME
    // right column.
    const outro = page.getByTestId("post-export-contribution-prompt");
    await expect(outro).toBeVisible();
    await expect(outro).toContainText("What's That Card?");

    // §D.3/PE1 - exactly ONE nudge: the standalone left-column mount is suppressed while the
    // embed's own outro is showing (there is only ever one post-export-contribution-prompt
    // testid on the page at a time).
    await expect(
      page.getByTestId("post-export-contribution-prompt")
    ).toHaveCount(1);
  });

  test("the classic direct 'Generate PDF' path reachable from /print still respects the cardback reminder guard's own once-per-session suppression", async ({
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

    await reachPDFTabOnPrintPage(page);

    // The editor's own Finish-footer gate already ran (and was suppressed via "Use current &
    // continue") earlier in this same session/tab - PDFGenerator.tsx's OWN independent guard
    // (usePrePrintSaveGate's sibling call site around the classic direct Generate/Save-to-Drive
    // buttons) reads the SAME per-project sessionStorage suppression key, so a click here does
    // NOT show a second reminder - straight into the real fetch/assemble/done flow, confirming
    // both call sites share one coherent CB1 "once per session" contract rather than each
    // maintaining an independent (and possibly nagging-twice) copy.
    await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        await page.getByRole("button", { name: "Generate PDF" }).click();
        await expect(page.getByTestId("pre-print-cardback-gate")).toHaveCount(
          0
        );
        await expect(page.getByTestId("pdf-progress")).toBeVisible({
          timeout: 15_000,
        });
      })(),
    ]);
  });
});
