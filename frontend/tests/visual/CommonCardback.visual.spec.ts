import { expect } from "@playwright/test";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardbacksOneResult,
  cardbacksTwoResults,
  cardDocumentsOneResult,
  defaultHandlers,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  expectCardbackSlotState,
  loadPageWithDefaultBackend,
} from "../test-utils";

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

test.describe("CommonCardback visual tests", () => {
  test("common cardback with single search result", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      cardbacksOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await expectCardbackSlotState(page, cardDocument1.name, 1, 1);

    await expect(page.getByTestId("common-cardback")).toMatchAriaSnapshot(`
      - paragraph: Cardback
      - img "Card 1"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - paragraph: 1 / 1
    `);
  });

  test("common cardback with multiple search results", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      cardbacksTwoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await expectCardbackSlotState(page, cardDocument1.name, 1, 2);

    await expect(page.getByTestId("common-cardback")).toMatchAriaSnapshot(`
      - paragraph: Cardback
      - img "Card 1"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - button "1 / 2"
      - button "❮"
      - button "❯"
    `);
  });
});
