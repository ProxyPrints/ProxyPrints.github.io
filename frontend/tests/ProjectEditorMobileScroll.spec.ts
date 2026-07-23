import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
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

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

// Real touch-driven scroll chaining (the actual mechanism this fix addresses) can't be
// exercised by a synthetic browser-automation event - Chromium doesn't drive compositor-level
// touch scrolling from JS-dispatched events the way a genuine OS touch gesture does. These
// tests verify the CSS/layout precondition for chaining to work (overscroll-behavior-y: auto,
// not none) and that the panel is structurally reachable - see this PR's merge-time checklist
// for the real-device confirmation this can't replace.
test.describe("Editor - mobile scroll chaining (item 5)", () => {
  test("at a mobile viewport, the stacked panels allow scroll to chain instead of trapping it", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const leftPanel = page.getByTestId("left-panel");
    const rightPanel = page.getByTestId("right-panel");

    const leftOverscroll = await leftPanel.evaluate(
      (el) => getComputedStyle(el).overscrollBehaviorY
    );
    const rightOverscroll = await rightPanel.evaluate(
      (el) => getComputedStyle(el).overscrollBehaviorY
    );
    expect(leftOverscroll).toBe("auto");
    expect(rightOverscroll).toBe("auto");
  });

  test("at a mobile viewport, 'I've Finished My Project' is reachable once the card grid is scrolled past", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const finishedButton = page.getByText("I've Finished My Project");
    await finishedButton.scrollIntoViewIfNeeded();
    await expect(finishedButton).toBeVisible();
    await expect(finishedButton).toBeInViewport();
  });

  test("at desktop width, overscroll-behavior-y stays auto on the side-by-side panels too (unaffected by the mobile fix)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const leftPanel = page.getByTestId("left-panel");
    const rightPanel = page.getByTestId("right-panel");
    const leftOverscroll = await leftPanel.evaluate(
      (el) => getComputedStyle(el).overscrollBehaviorY
    );
    const rightOverscroll = await rightPanel.evaluate(
      (el) => getComputedStyle(el).overscrollBehaviorY
    );
    expect(leftOverscroll).toBe("auto");
    expect(rightOverscroll).toBe("auto");
  });

  test("other OverflowCol usages (e.g. the Add Cards panel) keep overscroll-behavior-y: none, unaffected by this fix", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    const addCardsPanel = page.getByTestId("add-cards-panel");
    const overscroll = await addCardsPanel.evaluate(
      (el) => getComputedStyle(el).overscrollBehaviorY
    );
    expect(overscroll).toBe("none");
  });
});
