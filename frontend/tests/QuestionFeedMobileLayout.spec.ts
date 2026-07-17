import { expect } from "@playwright/test";

import { cardDocument1, printingCandidate1 } from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedIdentifyPrinting,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// identify_printing lands straight on Level 2 (the candidate grid) - confirm_suggestion's
// Level 1 has no grid to reorder at all, so it's not a fit for this ordering check anymore
// (see QuestionFeedConfirmSuggestion.spec.ts for Level 1's own coverage).
test.describe("question feed - mobile layout", () => {
  test("at a mobile viewport, the mystery card renders above the answer candidates, not below them", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(cardImage).toBeVisible();
    await expect(suggestedCandidate).toBeVisible();

    const cardBox = await cardImage.boundingBox();
    const candidateBox = await suggestedCandidate.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(candidateBox).not.toBeNull();
    // The card must be reachable without scrolling past every answer option first - its top
    // edge should render above (a smaller y than) the candidate grid's.
    expect(cardBox!.y).toBeLessThan(candidateBox!.y);
  });

  test("at desktop width, candidates still render to the left of the card (unaffected by the mobile reorder)", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    // default chromium project viewport (800x600) is already >= the md breakpoint
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(cardImage).toBeVisible();
    await expect(suggestedCandidate).toBeVisible();

    const cardBox = await cardImage.boundingBox();
    const candidateBox = await suggestedCandidate.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(candidateBox).not.toBeNull();
    expect(candidateBox!.x).toBeLessThan(cardBox!.x);
  });
});
