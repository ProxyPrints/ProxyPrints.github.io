import { expect, Page } from "@playwright/test";

import { CHUNK_RELOAD_GUARD_KEY } from "@/common/chunkErrorRecovery";

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

// CI diagnosis (PR #395, run 30039392833, shard 1/4 - failed twice consecutively, including a
// clean re-run, while passing locally): the recovery mechanism's own sessionStorage guard
// (chunkErrorRecovery.ts's CHUNK_RELOAD_GUARD_KEY, a real 10s "don't loop" debounce, not a bug)
// can legitimately already be set by the time a test gets around to dispatching its own synthetic
// error. `npm run dev`'s webserver compiles /editor on demand (its own network trace showed a
// second, ~800ms recompile of pages/editor.js mid-test, triggered by the navbar's own "Editor"
// nav link - visible while already ON /editor - being prefetched by next/link's default viewport
// IntersectionObserver behaviour), and that on-demand-compilation churn is exactly the class of
// transient chunk hiccup this whole mechanism exists to recover from - it's plausible for a real
// one to fire and consume the guard before a slow/cold CI runner's test body gets to its own
// dispatch. This is a dev-server/test-harness artifact only: the deployed static export has no
// on-demand compilation or HMR at all, so this can't happen in production, and the guard
// suppressing a second reload within its window is the product working exactly as designed - see
// docs/troubleshooting.md's chunkErrorRecovery.spec.ts entry. Clearing the guard immediately
// before each test's own dispatch establishes the clean precondition the assertion actually means
// to test ("a synthetic ChunkLoadError triggers exactly one reload"), independent of whatever
// unrelated real chunk noise the dev server produced getting the page ready - it does not touch
// the guard-suppression behaviour itself, which the last test below still exercises for real via
// two dispatches inside the same clean window.
const clearReloadGuard = (page: Page) =>
  page.evaluate(
    (key) => window.sessionStorage.removeItem(key),
    CHUNK_RELOAD_GUARD_KEY
  );

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

    await clearReloadGuard(page);
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

    await clearReloadGuard(page);
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

    await clearReloadGuard(page);
    await dispatchChunkError(page);
    await expect.poll(() => reloadRequests).toBe(1);

    // The aborted reload never completed, so the same document/listeners are still live -
    // dispatch a second chunk error and confirm the guard window suppresses a second attempt.
    // (Deliberately no clearReloadGuard() call here - this second dispatch is exactly what's
    // meant to hit the still-live guard from the first one above.)
    await dispatchChunkError(page);
    await page.waitForTimeout(1_000);
    expect(reloadRequests).toBe(1);
  });
});
