import { expect } from "@playwright/test";

import {
  defaultHandlers,
  questionFeedConfirmSuggestion,
  questionFeedIdentifyPrinting,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Mobile funnel pass - thumb-native tap targets. WCAG 2.5.5 (Target Size, AA) and Apple's HIG
// both call for a 44px minimum touch target; Bootstrap's own default .btn height (~38px) and
// the attribute chips' original padding (~30px) both fell short. These assert the real,
// measured height of each control class the funnel uses for answering a question, not just
// that a CSS rule exists - a min-height declaration overridden elsewhere (e.g. a conflicting
// Bootstrap utility class) wouldn't be caught by a stylesheet-only check.
test.describe("question feed - tap target sizes (mobile funnel pass)", () => {
  test("Level 1's stacked answer buttons meet the 44px floor", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    for (const testId of [
      "question-feed-level1-yes",
      "question-feed-level1-not-sure",
      "question-feed-level1-no",
      "question-feed-level1-skip",
    ]) {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });

  test("Level 2's filter toggle and exit buttons meet the 44px floor", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const toggleBox = await page
      .getByTestId("question-feed-filter-toggle")
      .boundingBox();
    expect(toggleBox).not.toBeNull();
    expect(toggleBox!.height).toBeGreaterThanOrEqual(44);

    for (const testId of [
      "question-feed-no-match",
      "question-feed-custom-art",
      "question-feed-skip",
    ]) {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });

  test("attribute chips meet the 44px floor once the filter panel is expanded", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-filter-toggle").click();
    const firstChip = page
      .locator('[data-testid^="attribute-chip-"][data-chip-state]')
      .first();
    await expect(firstChip).toBeVisible();
    const box = await firstChip.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.width).toBeGreaterThanOrEqual(44);
  });
});
