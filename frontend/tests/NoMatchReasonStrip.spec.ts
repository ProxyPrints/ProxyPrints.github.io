import { expect } from "@playwright/test";

import {
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  printingTagQueueOneResult,
  submitPrintingTagNoMatch,
  submitTagVoteResolvesToApply,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("NoMatchReasonStrip tests", () => {
  test("shows the reason strip (not the general attribute panel) after a no-match vote", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagNoMatch,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByText("No match").click();

    const strip = page.getByTestId("no-match-reason-strip");
    await expect(strip).toBeVisible();
    await expect(strip.getByText("Custom art")).toBeVisible();
    await expect(strip.getByText("Altered frame")).toBeVisible();
    await expect(strip.getByText("Upscaled")).toBeVisible();
    await expect(strip.getByText("AI art")).toBeVisible();
    await expect(strip.getByText("No collector line")).toBeVisible();
    await expect(strip.getByText("Non-English")).toBeVisible();
    await expect(page.getByTestId("attribute-voting-panel")).not.toBeVisible();
  });

  test("tapping a reason chip submits a positive tag vote and advances the queue", async ({
    page,
    network,
  }) => {
    let submittedBody: { tagName?: string; polarity?: number } = {};
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", async (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        submittedBody = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByText("No match").click();
    await page.getByTestId("no-match-reason-ai-art").click();

    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
    expect(submittedBody.tagName).toBe("ai-art");
    expect(submittedBody.polarity).toBe(1);
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
      submitPrintingTagNoMatch,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        tagVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByText("No match").click();
    await expect(page.getByTestId("no-match-reason-strip")).toBeVisible();
    await page.getByTestId("no-match-reason-skip").click();

    await expect(
      page.getByText("You're all caught up - no cards left to tag right now!")
    ).toBeVisible();
    expect(tagVoteSubmitted).toBe(false);
  });
});
