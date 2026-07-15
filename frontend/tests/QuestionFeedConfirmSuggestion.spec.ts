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
  test("pre-highlights the AI-suggested printing and shows the 'Is it this one?' prompt", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("Is it this one?");

    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(suggestedCandidate).toHaveClass(/highlighted/);
  });

  test("one tap on the highlighted candidate confirms it", async ({
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

    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await suggestedCandidate.click();

    await expect
      .poll(() => submittedPrintingIdentifier)
      .toBe(printingCandidate1.identifier);
  });
});
