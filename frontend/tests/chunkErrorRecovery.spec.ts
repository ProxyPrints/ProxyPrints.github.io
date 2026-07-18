import { expect, Page } from "@playwright/test";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Verifies useChunkErrorRecovery is genuinely mounted and wired to real browser event listeners
// in the live app - not just that the pure isChunkLoadError/shouldAttemptReload logic is correct
// in isolation (covered separately by chunkErrorRecovery.test.ts). Dispatches synthetic error
// events directly rather than depending on Next.js dev-mode's internal chunk-naming/navigation
// timing, which is an implementation detail this test shouldn't be coupled to.
//
// A real window.location.reload() genuinely reloads the page - a naive attempt to observe it by
// stubbing window.location.reload via property redefinition was silently ineffective (Location
// is a legacy platform object Chromium doesn't let script override that way), and letting the
// real reload complete destroys Playwright's JS execution context before any in-page assertion
// can run. Instead, this intercepts the network request the reload issues (a real HTTP fetch of
// the page's own current URL - unambiguous evidence location.reload() was actually called) and
// aborts it, so the current document keeps running for the rest of the test.
const dispatchChunkError = (page: Page) =>
  page.evaluate(() => {
    const error = new Error("Loading chunk 5 failed.");
    error.name = "ChunkLoadError";
    window.dispatchEvent(
      new ErrorEvent("error", { error, message: error.message })
    );
  });

test.describe("Chunk-load-error recovery", () => {
  test("a ChunkLoadError dispatched as a window 'error' event triggers a reload", async ({
    page,
  }) => {
    await loadPageWithDefaultBackend(page);
    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await dispatchChunkError(page);

    await expect.poll(() => reloadRequests).toBe(1);
  });

  test("a ChunkLoadError surfaced as an unhandled promise rejection triggers a reload", async ({
    page,
  }) => {
    await loadPageWithDefaultBackend(page);
    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await page.evaluate(() => {
      const error = new Error("Loading CSS chunk 2 failed.");
      // PromiseRejectionEvent isn't constructible directly in most browsers - a plain object
      // with the same shape the real listener reads (`.reason`) is sufficient here since the
      // hook only ever reads that one property.
      window.dispatchEvent(
        Object.assign(new Event("unhandledrejection"), { reason: error })
      );
    });

    await expect.poll(() => reloadRequests).toBe(1);
  });

  test("an unrelated error never triggers a reload", async ({ page }) => {
    await loadPageWithDefaultBackend(page);
    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await page.evaluate(() => {
      const error = new Error("Network request failed");
      window.dispatchEvent(
        new ErrorEvent("error", { error, message: error.message })
      );
    });

    // No poll-until-truthy here (there's nothing to wait for) - a short settle is enough to be
    // confident nothing fired asynchronously either.
    await page.waitForTimeout(1_000);
    expect(reloadRequests).toBe(0);
  });

  test("two ChunkLoadErrors in quick succession only trigger one reload attempt", async ({
    page,
  }) => {
    await loadPageWithDefaultBackend(page);
    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await dispatchChunkError(page);
    await expect.poll(() => reloadRequests).toBe(1);

    // The aborted reload never completed, so the same document/listeners are still live -
    // dispatch a second chunk error and confirm the guard window suppresses a second attempt.
    await dispatchChunkError(page);
    await page.waitForTimeout(1_000);
    expect(reloadRequests).toBe(1);
  });
});
