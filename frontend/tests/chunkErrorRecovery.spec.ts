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

// CI diagnosis #1 (PR #395, run 30039392833, shard 1/4 - failed twice consecutively, including a
// clean re-run, while passing locally; fixed by PR #397): the recovery mechanism's own
// sessionStorage guard (chunkErrorRecovery.ts's CHUNK_RELOAD_GUARD_KEY, a real 10s "don't loop"
// debounce, not a bug) can legitimately already be set by the time a test gets around to
// dispatching its own synthetic error - `npm run dev`'s on-demand page compilation, triggered by
// the navbar's own "Editor" nav link being prefetched by next/link while already ON /editor, is
// exactly the class of transient chunk hiccup this mechanism exists to recover from, and a real
// one firing first consumes the guard before the test's own dispatch. PR #397 fixed this by
// clearing the guard immediately before each test's own dispatch.
//
// CI diagnosis #2 (PR #395, run 30043836352, shard 1/4, after #397 was merged - all 3 attempts
// including retries failed, and reproduced intermittently on a local box too): #397's fix wasn't
// sufficient on its own, for two independent reasons.
//
// (a) #397 called clearReloadGuard(page) and dispatchChunkError(page) as two SEPARATE
// page.evaluate() round-trips, leaving a real (if narrow) gap between them for the exact same
// class of dev-server chunk noise diagnosis #1 already identified to land in. Fixed below by
// folding the clear and the dispatch into one page.evaluate() call
// (clearGuardAndDispatchChunkError / clearGuardAndDispatchChunkErrorAsRejection) - a single
// synchronous browser-side task nothing else on the page's event loop can interleave with.
//
// (b) loadPageWithDefaultBackend()'s own "Choose Art" click is a raw DOM click, which Chromium
// dispatches whether or not React has actually hydrated and useChunkErrorRecovery's useEffect has
// run yet - a successful click is not proof the recovery listener is live. Locally, this spec
// failed intermittently at `--workers=4` (parallel Playwright workers contending for CPU with the
// dev server's own on-demand compilation) but passed reliably at `--workers=1` - that
// serial-vs-parallel signature points squarely at hydration timing. A native DOM event dispatched
// before a listener is attached is simply lost (never delivered once the listener does attach),
// so this can't be worked around by polling for longer - it has to be worked around by proving
// hydration completed *before* the test's own real dispatch.
//
// CI diagnosis #3 (this box, reproduced locally at `--workers=4 --repeat-each=10` against a cold
// `.next` cache) - two dead ends before landing on the fix below, both worth recording since
// they're each individually tempting to re-derive:
//   - A disposable warm-up ChunkLoadError dispatch, intercepted and aborted via page.route()
//     (mirroring how every other dispatch in this file is guarded): under this exact stress, EVERY
//     test started failing deterministically (40/40) with `page.evaluate: SecurityError: Failed to
//     read the 'sessionStorage' property from 'Window': Access is denied for this document` on the
//     very next page.evaluate() call after that abort - evidence the document was transiently in
//     an about:blank-like state right after the abort completed (Chromium's bookkeeping for an
//     aborted top-level navigation isn't fully synchronous under this much contention).
//   - Letting that same warm-up reload complete for real (no interception), then re-running
//     loadPageWithDefaultBackend() to get back to a configured page: this traded the SecurityError
//     for `page.goto: Navigation ... is interrupted by another navigation to ".../editor"` -
//     confirming the self-referential "Editor" nav-link prefetch (diagnosis #1) is a genuinely
//     recurring background navigation under this stress, not a one-off, and collides with ANY
//     explicit page.goto()/reload this file issues, not just the first one.
// Both dead ends required an EXTRA top-level navigation beyond what PR #397's baseline already
// safely did (confirmed 40/40 stable under the identical stress in an A/B before either attempt).
// The fix below requires none: react-bootstrap's uncontrolled `Tab.Container` in
// ProjectEditor.tsx defaults `editorPanel` to `"import"` (the "Add Cards" tab), so the "editor"
// tab's content - including CardGrid.tsx's "Your project is empty at the moment." empty-state
// text - is present in the DOM either way but only becomes *visible* once Tab.Container's
// onSelect handler actually runs and flips `activeKey` to `"editor"`, which needs the same
// hydration/effect-flush pass that mounts useChunkErrorRecovery's own listeners (React flushes a
// commit's effects top-down in one pass, and Layout wraps ProjectEditor). Waiting for that text to
// become visible is therefore direct, hydration-dependent proof, entirely via DOM state - no
// dispatch, no route, no navigation, so nothing left to race.
//
// loadPageWithDefaultBackend() (test-utils.ts) already clicks "Choose Art" once, but if that
// single click lands before hydration finishes, it's a dead click - React never sees it, the tab
// never switches, and no later click replays it (a native DOM event dispatched into an inert,
// not-yet-hydrated element is simply gone). So this can't just *wait* for the earlier click's
// result; it has to be prepared to *retry* the click itself until one lands after hydration -
// exactly the established pattern test-utils.ts's own openAddCardsDropdown() already uses for the
// identical symptom ("sometimes playwright is too 'fast' and clicking doesn't open the dropdown").
// See docs/troubleshooting.md's chunkErrorRecovery.spec.ts entry for the full trace-based
// diagnosis of all three rounds.
const awaitHydrated = (page: Page) =>
  expect(async () => {
    await page.getByText("Choose Art").click();
    await expect(
      page.getByText("Your project is empty at the moment.")
    ).toBeVisible();
  }).toPass({ timeout: 10_000 });

const clearReloadGuard = (page: Page) =>
  page.evaluate(
    (key) => window.sessionStorage.removeItem(key),
    CHUNK_RELOAD_GUARD_KEY
  );

const clearGuardAndDispatchChunkError = (page: Page) =>
  page.evaluate((key) => {
    window.sessionStorage.removeItem(key);
    const error = new Error("Loading chunk 5 failed.");
    error.name = "ChunkLoadError";
    window.dispatchEvent(
      new ErrorEvent("error", { error, message: error.message })
    );
  }, CHUNK_RELOAD_GUARD_KEY);

const clearGuardAndDispatchChunkErrorAsRejection = (page: Page) =>
  page.evaluate((key) => {
    window.sessionStorage.removeItem(key);
    const error = new Error("Loading CSS chunk 2 failed.");
    // PromiseRejectionEvent isn't constructible directly in most browsers - a plain object
    // with the same shape the real listener reads (`.reason`) is sufficient here since the
    // hook only ever reads that one property.
    window.dispatchEvent(
      Object.assign(new Event("unhandledrejection"), { reason: error })
    );
  }, CHUNK_RELOAD_GUARD_KEY);

test.describe("Chunk-load-error recovery", () => {
  test("a ChunkLoadError dispatched as a window 'error' event triggers a reload", async ({
    page,
  }) => {
    await loadPageWithDefaultBackend(page);
    await awaitHydrated(page);

    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await clearGuardAndDispatchChunkError(page);

    await expect.poll(() => reloadRequests).toBe(1);
  });

  test("a ChunkLoadError surfaced as an unhandled promise rejection triggers a reload", async ({
    page,
  }) => {
    await loadPageWithDefaultBackend(page);
    await awaitHydrated(page);

    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await clearGuardAndDispatchChunkErrorAsRejection(page);

    await expect.poll(() => reloadRequests).toBe(1);
  });

  test("an unrelated error never triggers a reload", async ({ page }) => {
    await loadPageWithDefaultBackend(page);
    await awaitHydrated(page);

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
    await awaitHydrated(page);

    let reloadRequests = 0;
    await page.route(page.url(), async (route) => {
      reloadRequests++;
      await route.abort();
    });

    await clearGuardAndDispatchChunkError(page);
    await expect.poll(() => reloadRequests).toBe(1);

    // The aborted reload never completed, so the same document/listeners are still live -
    // dispatch a second chunk error and confirm the guard window suppresses a second attempt.
    // (Deliberately no guard-clear here - this second dispatch is exactly what's meant to hit
    // the still-live guard from the first one above.)
    await dispatchChunkError(page);
    await page.waitForTimeout(1_000);
    expect(reloadRequests).toBe(1);
  });
});
