import { expect } from "@playwright/test";

import { cardDocument1 } from "@/common/test-constants";
import {
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  printingTagQueueNoResults,
  printingTagQueueOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("PrintingTagQueue tests", () => {
  test("lists cards that still need a printing tagged", async ({
    page,
    network,
  }) => {
    network.use(printingTagQueueOneResult, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(
      page.getByText("Still need a printing tagged: 1 card")
    ).toBeVisible();
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
  });

  test("shows zero cards remaining when the queue is empty", async ({
    page,
    network,
  }) => {
    network.use(printingTagQueueNoResults, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(
      page.getByText("Still need a printing tagged: 0 cards")
    ).toBeVisible();
  });

  test("clicking a queued card opens its detailed view for tagging", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await page.getByAltText(cardDocument1.name).click();

    await expect(page.getByText("Card Details")).toBeVisible();
    await expect(page.getByText("Which printing is this?")).toBeVisible();
  });
});
