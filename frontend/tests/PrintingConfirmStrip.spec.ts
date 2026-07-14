import { expect } from "@playwright/test";

import {
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  printingTagQueueOneResult,
  submitPrintingTagResolvesToPrintingCandidate1,
  submitPrintingTagResolvesToPrintingCandidate2,
  submitTagVoteResolvesToApply,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("PrintingConfirmStrip tests", () => {
  test("pre-fills chips from the resolved candidate's own fullArt/isBorderless flags", async ({
    page,
    network,
  }) => {
    // printingCandidate1 has fullArt: false, isBorderless: false
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByAltText("abc 1").click();

    const strip = page.getByTestId("printing-confirm-strip");
    await expect(strip).toBeVisible();
    await expect(page.getByTestId("printing-confirm-full-art")).not.toHaveClass(
      /highlighted/
    );
    await expect(
      page.getByTestId("printing-confirm-borderless")
    ).not.toHaveClass(/highlighted/);
  });

  test("pre-fills chips as highlighted when the candidate's flags are true", async ({
    page,
    network,
  }) => {
    // printingCandidate2 has fullArt: true, isBorderless: true
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate2,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByAltText("xyz 42").click();

    await expect(page.getByTestId("printing-confirm-full-art")).toHaveClass(
      /highlighted/
    );
    await expect(page.getByTestId("printing-confirm-borderless")).toHaveClass(
      /highlighted/
    );
  });

  test("tapping a chip submits a tag vote and marks it confirmed", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate1,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByAltText("abc 1").click();
    await page.getByTestId("printing-confirm-full-art").click();

    await expect(page.getByTestId("printing-confirm-full-art")).toContainText(
      "Confirmed"
    );
    // the strip stays put - confirming a chip doesn't itself advance the queue
    await expect(page.getByTestId("printing-confirm-strip")).toBeVisible();
  });

  test("skip advances without submitting any tag vote", async ({
    page,
    network,
  }) => {
    let tagVoteSubmitted = false;
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        tagVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByAltText("abc 1").click();
    await expect(page.getByTestId("printing-confirm-strip")).toBeVisible();
    await page.getByTestId("printing-confirm-skip").click();

    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
    expect(tagVoteSubmitted).toBe(false);
  });
});
