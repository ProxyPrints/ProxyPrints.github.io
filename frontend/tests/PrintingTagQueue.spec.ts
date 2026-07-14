import { expect } from "@playwright/test";

import {
  cardDocument1,
  cardDocument2,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
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
      page.getByTestId("printing-tag-queue-current-card")
    ).toBeVisible();
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await expect(page.getByAltText("abc 1")).toBeVisible();
    await expect(page.getByAltText("xyz 42")).toBeVisible();
  });

  test("candidate buttons carry the printing-candidate DOM data attributes", async ({
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

    const candidateButton1 = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-name",
      cardDocument1.name
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-set-code",
      printingCandidate1.expansionCode
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-collector-number",
      printingCandidate1.collectorNumber
    );

    const candidateButton2 = page.locator(
      `[data-card-identifier="${printingCandidate2.identifier}"]`
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-name",
      cardDocument1.name
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-set-code",
      printingCandidate2.expansionCode
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-collector-number",
      printingCandidate2.collectorNumber
    );
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

  test("submitting a resolving vote shows the confirm strip, then advances on continue", async ({
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

    // a resolving vote no longer advances immediately - the confirm strip gets a beat first
    await expect(page.getByTestId("printing-confirm-strip")).toBeVisible();
    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).not.toBeVisible();

    await page.getByTestId("printing-confirm-continue").click();

    // that was the only card in the queue - continuing advances past the end of it
    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
    await expect(
      page.getByTestId("printing-tag-queue-flavor-text")
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
      page.getByTestId("printing-tag-queue-flavor-text")
    ).toBeVisible();
  });
});
