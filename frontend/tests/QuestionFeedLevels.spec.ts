import { expect } from "@playwright/test";

import {
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedIdentifyPrinting,
  submitPrintingTagResolvesToPrintingCandidate1,
  submitPrintingTagResolvesToPrintingCandidate2,
  submitTagVoteResolvesToApply,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("question feed - Level 2 (candidate grid)", () => {
  test("the attribute-chip filter is collapsed by default and expands on tap", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("attribute-chip-panel")).not.toBeVisible();
    await expect(page.getByTestId("question-feed-filter-toggle")).toHaveText(
      "Filter by attribute"
    );

    await page.getByTestId("question-feed-filter-toggle").click();

    await expect(page.getByTestId("attribute-chip-panel")).toBeVisible();
    await expect(page.getByTestId("question-feed-filter-toggle")).toHaveText(
      "Hide filters"
    );
  });

  test("narrowing by a chip hides non-matching candidates behind a clearable count, once expanded", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-filter-toggle").click();
    await page.getByTestId("attribute-chip-Full Art").click(); // candidate1 is fullArt=false

    await expect(page.getByTestId("question-feed-hidden-count")).toContainText(
      "1 hidden"
    );
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);

    await page.getByTestId("question-feed-clear-filters").click();
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toBeVisible();
  });

  test('"Art matches, not an official printing" casts a no-match printing vote plus a positive custom-art tag vote, then advances', async ({
    page,
    network,
  }) => {
    let submittedPrinting: {
      printingIdentifier?: string;
      isNoMatch?: boolean;
    } = {};
    let submittedTag: { tagName?: string; polarity?: number } = {};
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate1,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrinting = request.postDataJSON();
      }
      if (request.url().includes("/2/submitTagVote/")) {
        submittedTag = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-custom-art").click();

    await expect.poll(() => submittedPrinting.isNoMatch).toBe(true);
    expect(submittedPrinting.printingIdentifier).toBeUndefined();
    await expect.poll(() => submittedTag.tagName).toBe("custom-art");
    expect(submittedTag.polarity).toBe(1);
    await expect(page.getByTestId("question-feed-flavor-text")).toContainText(
      "custom / alternate art"
    );
  });
});

test.describe("question feed - Level 3 (conditional open-attribute confirm)", () => {
  test("selecting a candidate whose border color falls outside the taxonomy opens Level 3 for Border Color only", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
      .click();

    await expect(page.getByTestId("question-feed-level3")).toBeVisible();
    await expect(
      page.getByTestId("question-feed-level3-chip-Black Border")
    ).toBeVisible();
    // Frame ("2003" -> Modern Border) already matched, so it's not asked about again here.
    await expect(
      page.getByTestId("question-feed-level3-chip-Full Art")
    ).toHaveCount(0);
  });

  test("picking one option in Level 3 and confirming submits just that vote", async ({
    page,
    network,
  }) => {
    const submittedTagNames: string[] = [];
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        const tagName = request.postDataJSON()?.tagName;
        if (tagName != null) submittedTagNames.push(tagName);
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
      .click();
    await expect(page.getByTestId("question-feed-level3")).toBeVisible();

    await page.getByTestId("question-feed-level3-chip-White Border").click();
    await page.getByTestId("question-feed-level3-confirm").click();

    await expect
      .poll(() => submittedTagNames.includes("White Border"))
      .toBe(true);
  });

  test("Level 3's skip advances without submitting any open-question vote", async ({
    page,
    network,
  }) => {
    let tagVoteSubmitted = false;
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        tagVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
      .click();
    await expect(page.getByTestId("question-feed-level3")).toBeVisible();
    tagVoteSubmitted = false; // ignore the auto-tag votes cast on selection itself

    await page.getByTestId("question-feed-level3-skip").click();

    // the static mock re-serves the identical item on refetch (no stateful "next card"), so
    // this only asserts the negative - no open-question vote was submitted by Skip - rather
    // than a post-advance UI state the mock can't actually produce.
    await page.waitForTimeout(200);
    expect(tagVoteSubmitted).toBe(false);
  });
});
