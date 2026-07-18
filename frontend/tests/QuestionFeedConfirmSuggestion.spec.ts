import { expect } from "@playwright/test";

import { cardDocument1, printingCandidate1 } from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedConfirmSuggestion,
  submitPrintingTagResolvesToPrintingCandidate1,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Rectangles intersect iff they overlap on both axes - the standard axis-aligned bounding box
// (AABB) test. Any edge-touching (a.right === b.left) counts as NOT intersecting, matching how
// two adjacent, non-overlapping page elements normally abut each other.
function boxesIntersect(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number }
): boolean {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

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

    // Regression check (#49 dropped this): Level 1 still needs its own reference render of the
    // suggested printing to compare against - "Is it this one?" is unanswerable from text alone.
    const referenceImage = page
      .getByTestId("question-feed-level1-reference-image")
      .locator("img");
    await expect(referenceImage).toBeVisible();
    await expect(referenceImage).toHaveAttribute(
      "src",
      printingCandidate1.mediumThumbnailUrl
    );
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

  test("at a 390px mobile viewport, no answer control overlaps the card art", async ({
    page,
    network,
  }) => {
    // Regression guard for a real-device-only bug (not reproducible in this sandbox's
    // Chromium): Level 1 previously reused Level 2's sticky, negative-z-index CardPanel for
    // its own short single-screen layout, which composited incorrectly on a real phone -
    // answer controls painted overlapping the card art instead of cleanly below it. The fix
    // (StaticCardPanel - see cardPanel.tsx) puts everything back in normal document flow;
    // this asserts that property directly via bounding-box math rather than relying on visual
    // diffing this sandbox can't validate against real hardware anyway.
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // The card's full box (art + starburst + name caption), not just the <img> - the
    // real-device bug this guards against overlapped the caption too, not only the artwork.
    const cardPanel = page.getByTestId("question-feed-level1-card-panel");
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await expect(page.getByTestId("question-feed-level1-yes")).toBeVisible();

    const cardBox = await cardPanel.boundingBox();
    expect(cardBox).not.toBeNull();

    const controls = [
      page.getByTestId("question-feed-tier-badge"),
      page.getByTestId("question-feed-suggestion-prompt"),
      page.getByTestId("question-feed-level1-yes"),
      page.getByTestId("question-feed-level1-not-sure"),
      page.getByTestId("question-feed-level1-no"),
      page.getByTestId("question-feed-level1-skip"),
    ];
    for (const control of controls) {
      const controlBox = await control.boundingBox();
      expect(controlBox).not.toBeNull();
      expect(boxesIntersect(cardBox!, controlBox!)).toBe(false);
    }
  });
});
