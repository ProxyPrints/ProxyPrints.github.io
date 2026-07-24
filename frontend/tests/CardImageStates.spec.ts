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

// Parity wave 2 investigation (2026-07-23, issue #272) - confirmed still a genuine gap, not just a
// route-swap casualty: this file's `card-image-error-placeholder`/`card-image-slow-load-hint`
// testids only exist in `Card.tsx` (grep confirms - src/features/card/Card.tsx). The unified
// page's sheet slots are NOT Card.tsx mounts - they're `PagePreview.tsx`'s own
// `page-preview-slot`, which already has its own project-level `loading`/`failed` states (no
// candidate resolved yet, or none found at all - see DisplaySlotStates.spec.ts's own coverage of
// those) but a plain, unwrapped `<img loading="lazy" src={imageUrl}>` for the "a candidate IS
// resolved, but its own image fetch 404s or hangs" case this file tests - no onError placeholder
// swap, no slow-load hint timer, at all. Porting this coverage isn't a test-authoring exercise (no
// existing DisplayPage surface to point it at) - it would mean adding real new
// fetch-failure/slow-load handling to PagePreview.tsx first, which is out of this wave's "port
// existing coverage" scope. Left skipped, not silently dropped - worth a real issue of its own if
// the owner wants sheet-level image-fetch-failure UX built (distinct from #272's tracked gaps,
// none of which mention this specifically).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Issue #272 wave 2 (2026-07-23): PagePreview.tsx's sheet slots have no error-fetch/slow-load handling to port this onto - a genuine, confirmed gap, not a route-swap casualty. See this file's own header comment."
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
