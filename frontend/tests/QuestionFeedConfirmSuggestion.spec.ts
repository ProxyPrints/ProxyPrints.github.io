import { expect } from "@playwright/test";

import { printingCandidate1 } from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedConfirmSuggestion,
  submitPrintingTagResolvesToPrintingCandidate1,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("question feed - confirm_suggestion question type", () => {
  test("lands on Level 1 - a single suggested printing, no grid - and shows the 'Is it this one?' prompt", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("Is it this one?");
    await expect(page.getByTestId("question-feed-level1-yes")).toBeVisible();
    // no candidate grid at Level 1 - only reachable via NOT SURE/NO
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);
  });

  test("YES confirms the suggested printing directly, without visiting the grid", async ({
    page,
    network,
  }) => {
    let submittedPrintingIdentifier: string | undefined;
    network.use(
      questionFeedConfirmSuggestion,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrintingIdentifier =
          request.postDataJSON()?.printingIdentifier;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-level1-yes").click();

    await expect
      .poll(() => submittedPrintingIdentifier)
      .toBe(printingCandidate1.identifier);
  });

  test("NOT SURE drops to Level 2's candidate grid without casting a vote", async ({
    page,
    network,
  }) => {
    let printingTagSubmitted = false;
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-level1-not-sure").click();

    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(suggestedCandidate).toBeVisible();
    await expect(suggestedCandidate).toHaveClass(/highlighted/);
    expect(printingTagSubmitted).toBe(false);
  });

  test("NO drops to Level 2's candidate grid without casting a vote", async ({
    page,
    network,
  }) => {
    let printingTagSubmitted = false;
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-level1-no").click();

    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toBeVisible();
    expect(printingTagSubmitted).toBe(false);
  });
});
