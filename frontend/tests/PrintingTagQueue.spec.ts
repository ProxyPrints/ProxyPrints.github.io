import { expect } from "@playwright/test";

import { cardDocument1, cardDocument2 } from "@/common/test-constants";
import {
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  printingTagQueueNoResults,
  printingTagQueueOneResult,
  printingTagQueueTwoResults,
  submitPrintingTagResolvesToPrintingCandidate1,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("PrintingTagQueue tests", () => {
  test("shows the current card and its candidate printings", async ({
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

    await expect(
      page.getByText("Still need a printing tagged: 1 card")
    ).toBeVisible();
    await expect(
      page.getByTestId("planeswalker-queue-current-card")
    ).toBeVisible();
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await expect(page.getByAltText("abc 1")).toBeVisible();
    await expect(page.getByAltText("xyz 42")).toBeVisible();
  });

  test("shows a caught-up message when the queue is empty", async ({
    page,
    network,
  }) => {
    network.use(printingTagQueueNoResults, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
  });

  test("submitting a vote shows flavor text and advances the queue", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByAltText("abc 1").click();

    // that was the only card in the queue - submitting advances past the end of it
    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
    await expect(
      page.getByTestId("planeswalker-queue-flavor-text")
    ).toBeVisible();
  });

  test("skip moves to the next card without submitting a vote", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueTwoResults,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await page.getByRole("button", { name: "Skip" }).click();

    await expect(page.getByAltText(cardDocument2.name)).toBeVisible();
    await expect(
      page.getByTestId("planeswalker-queue-flavor-text")
    ).toBeVisible();
  });
});
