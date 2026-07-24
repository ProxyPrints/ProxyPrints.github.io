import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { getWorkerImageURL } from "@/common/image";
import {
  cardDocument1,
  localBackendURL,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import { defaultHandlers } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

/**
 * WTC REBUILD (2026-07-24, SPEC-wtc-rebuild.md) - RETIRES the sliced WHAT'S/THAT/CARD? pop
 * sequence and the card-pulse-in-sync-with-THAT effect this file used to cover (issue #305's
 * `WhatsThatWords`/`CardPulseWrapper`): WD1 kills the old gold/navy wordmark identity those
 * animations were built around, and ANNEX C's animation inventory (mystery reveal,
 * confirm-lands feedback, the static reveal glow, the static solved affordance) does not list
 * a wordmark pop or a card pulse - neither is carried forward. `WhatsThatWords` is now a
 * plain, single-tree, un-animated `<h1>` (see that component's own header comment) - there is
 * no narrow/wide fork and no pop sequence left to test here.
 *
 * This file is RE-PURPOSED (not deleted) to cover what ANNEX C actually specifies for the
 * rebuilt page: the mystery-card reveal fade's reduced-motion gate (unchanged mechanism,
 * verbatim per the spec's file-level table) and the wordmark's new single-tree rendering
 * (replacing the old narrow/wide visibility-toggle coverage this file used to carry).
 */

function buildRoute(route: string) {
  return `${localBackendURL}/${route}`;
}

function questionFeedItem(card: typeof cardDocument1) {
  return HttpResponse.json(
    {
      item: {
        type: "identify_printing",
        card,
        candidates: [printingCandidate1, printingCandidate2],
        tagConfidence: {},
      },
      remainingEstimate: { total: 3, confirmable: 0, contested: 0, fresh: 3 },
    },
    { status: 200 }
  );
}

test.describe("What's That Card? - wordmark (WTC rebuild, single tree, no viewport fork)", () => {
  test("the wordmark renders identically (one <h1>, no narrow/wide swap) at a narrow and a wide viewport", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        questionFeedItem(cardDocument1)
      ),
      ...defaultHandlers
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");
    const wordmarkNarrow = page.getByTestId("whatsthat-words");
    await expect(wordmarkNarrow).toBeVisible();
    await expect(wordmarkNarrow).toContainText("What's That Card?");
    // Exactly one wordmark element renders at every width - the pre-rebuild narrow/wide
    // CSS-display fork (`NarrowWordmark`/`WideWordmark`, both always mounted, one hidden via
    // CSS) is retired; there is only ever one `<h1>` in the DOM now.
    await expect(page.getByTestId("whatsthat-words")).toHaveCount(1);

    await page.setViewportSize({ width: 1400, height: 900 });
    const wordmarkWide = page.getByTestId("whatsthat-words");
    await expect(wordmarkWide).toBeVisible();
    await expect(wordmarkWide).toContainText("What's That Card?");
    await expect(page.getByTestId("whatsthat-words")).toHaveCount(1);
  });
});

test.describe("What's That Card? - mystery-card reveal (ANNEX C, reduced-motion)", () => {
  // The D17 flake lesson (docs/troubleshooting.md) applies here: don't screenshot mid-frame in
  // CI - assert the *computed* CSS animation properties instead, which are stable regardless
  // of exactly when in the fade's run the assertion happens.
  test("under prefers-reduced-motion, the reveal overlay never animates - the card shows immediately", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        questionFeedItem(cardDocument1)
      ),
      ...defaultHandlers
    );
    // Explicit, not relying on playwright.config.ts's project default, so this assertion is
    // self-contained and keeps passing even if that default ever changes.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // reduced-motion + this suite's own empty-mediumThumbnailUrl fixture convention both
    // short-circuit straight to the settled state - the reveal overlay never mounts visibly.
    await expect(
      page.getByTestId("question-feed-reveal-overlay")
    ).not.toBeVisible();
  });

  test("the animation sequence does not start until the card image actually loads (real, non-reduced motion)", async ({
    page,
    network,
  }) => {
    const testCard = {
      ...cardDocument1,
      mediumThumbnailUrl: "non-empty-sentinel-see-comment-above",
    };
    // getWorkerImageURL reads process.env.NEXT_PUBLIC_IMAGE_WORKER_URL directly - matches
    // playwright.config.ts's webServer.env value for this Node-side computation only; it has
    // no effect on the already-running browser, which resolves this independently against its
    // own build-time value.
    process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = "https://cdn.proxyprints.ca";
    const CDN_IMAGE_URL = getWorkerImageURL(testCard, "small")!;
    const CDN_IMAGE_URL_PATTERN = new RegExp(
      `^${CDN_IMAGE_URL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`
    );
    network.use(
      http.get(buildRoute("2/questionFeed/"), () => questionFeedItem(testCard)),
      ...defaultHandlers
    );

    // Holds the card image's own response until releaseImage() is called below - a real
    // network delay, not a fake timer, so this proves the gate against actual load timing.
    let releaseImage: () => void = () => {};
    const imageGate = new Promise<void>((resolve) => {
      releaseImage = resolve;
    });
    await page.route(CDN_IMAGE_URL_PATTERN, async (route) => {
      await imageGate;
      await route.fulfill({ path: "public/blank.png" });
    });

    await page.emulateMedia({ reducedMotion: "no-preference" });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Before the image resolves: the reveal fade must still be paused (the shared
    // `imageLoaded`-gated `$playing` prop - see QuestionFeed.tsx's `onCardImageSettled`), and
    // the cover must still be up.
    const overlayPlayState = await page
      .getByTestId("question-feed-reveal-overlay")
      .evaluate((el) => window.getComputedStyle(el).animationPlayState);
    expect(overlayPlayState).toBe("paused");
    await expect(
      page.getByTestId("question-feed-reveal-overlay")
    ).toBeVisible();

    // Release the image response - only now should the fade be allowed to start.
    releaseImage();

    await expect
      .poll(
        () =>
          page
            .getByTestId("question-feed-reveal-overlay")
            .evaluate((el) => window.getComputedStyle(el).animationPlayState)
            .catch(() => "running") // overlay may already have unmounted by the time we poll -
        // treat that as success too, since it means the fade already ran to completion
      )
      .not.toBe("paused");
  });
});
