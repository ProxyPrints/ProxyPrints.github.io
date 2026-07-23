import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

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

// Matches the domains configured via NEXT_PUBLIC_IMAGE_WORKER_URL /
// NEXT_PUBLIC_IMAGE_BUCKET_URL in playwright.config.ts's webServer env.
const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

test.describe("Card image - error and slow-load states", () => {
  test("a failed image fetch renders a restyled placeholder, not the old solid-black 404 asset", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(
        IMAGE_BUCKET_URL_PATTERN,
        () => new HttpResponse(null, { status: 404 })
      ),
      http.get(
        IMAGE_WORKER_URL_PATTERN,
        () => new HttpResponse(null, { status: 404 })
      ),
      ...oneCardHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const placeholder = page.getByTestId("card-image-error-placeholder");
    await expect(placeholder).toBeVisible({ timeout: 15_000 });
    await expect(placeholder).toContainText("Image unavailable");
    // The old fix used a literal src="/error_404*.png" <img>; confirm that's gone from the
    // errored card specifically (an unrelated favicon/logo <img> elsewhere on the page is
    // fine - this scopes to the slot that actually errored).
    await expect(
      page.getByTestId("front-slot0").locator('img[src*="error_404"]')
    ).toHaveCount(0);
  });

  test("an image fetch that never resolves shows a 'still loading' hint after a delay, not just an indefinite bare spinner", async ({
    page,
    network,
  }) => {
    // A genuinely never-resolving request (rather than page.clock virtual-time trickery,
    // which risks starving React's own MessageChannel-based scheduler) - this test just
    // pays the real ~6s wall-clock cost of the hint's own delay threshold.
    network.use(
      http.get(
        IMAGE_BUCKET_URL_PATTERN,
        () => new Promise<never>(() => undefined)
      ),
      http.get(
        IMAGE_WORKER_URL_PATTERN,
        () => new Promise<never>(() => undefined)
      ),
      ...oneCardHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    await expect(
      page.getByTestId("card-image-slow-load-hint")
    ).not.toBeVisible();

    const hint = page.getByTestId("card-image-slow-load-hint");
    await expect(hint).toBeVisible({ timeout: 10_000 });
    await expect(hint).toContainText("Still loading");
  });
});
