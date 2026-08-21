import { expect } from "@playwright/test";

import { defaultHandlers, questionFeedIllustration } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

const VIEWPORT_WIDTHS = [390, 800, 1400];

test.describe("question feed - illustration question visual QA", () => {
  for (const width of VIEWPORT_WIDTHS) {
    test(`renders the illustration grid with no horizontal overflow at ${width}px`, async ({
      page,
      network,
    }) => {
      network.use(questionFeedIllustration, ...defaultHandlers);
      await page.setViewportSize({ width, height: 900 });
      await loadPageWithDefaultBackend(page, "whatsthat");

      const grid = page.getByTestId("question-feed-illustration-grid");
      await expect(grid).toBeVisible();

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);

      await page.screenshot({
        path: `.playwright-mcp/illustration-question-${width}.png`,
        fullPage: false,
      });
    });
  }
});
