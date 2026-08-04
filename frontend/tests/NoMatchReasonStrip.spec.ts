import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import {
  cardDocument1,
  localBackendURL,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import {
  defaultHandlers,
  NO_MATCH_REASON_TAG_DISPLAY_NAMES,
  questionFeedIdentifyPrinting,
  submitPrintingTagNoMatch,
  submitTagVoteResolvesToApply,
  tagsAllNoMatchReasonTags,
  tagsSomeNoMatchReasonTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

// One item, then caught-up once a "No match" vote has actually been cast for it -
// deliberately NOT call-count-based (e.g. "serve the item on the first GET, caught-up
// after"): React 18's Strict Mode double-invokes effects in dev, so the feed's fetch effect
// fires twice on mount before the app "really" settles, and a naive call-count mock would
// hand the caught-up response to that second (real, kept) invocation, never showing the item
// at all. Tying "caught up" to the domain event that actually ends this card's flow (both
// the reason-tap and skip paths share this same precursor) is robust to however many GETs
// Strict Mode's double-invoke produces. Returns both the questionFeed handler and the
// submitPrintingTag handler that flips the shared flag - use both from the same call.
function questionFeedUntilNoMatchVoted(): {
  questionFeed: ReturnType<typeof http.get>;
  submitPrintingTagNoMatch: ReturnType<typeof http.post>;
} {
  let voted = false;
  return {
    questionFeed: http.get(buildRoute("2/questionFeed/"), () => {
      if (!voted) {
        return HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: cardDocument1,
              candidates: [printingCandidate1, printingCandidate2],
              tagConfidence: { "Full Art": 0, Borderless: 0.6 },
            },
            remainingEstimate: {
              total: 1,
              confirmable: 0,
              contested: 0,
              fresh: 1,
            },
          },
          { status: 200 }
        );
      }
      return HttpResponse.json(
        {
          remainingEstimate: {
            total: 0,
            confirmable: 0,
            contested: 0,
            fresh: 0,
          },
        },
        { status: 200 }
      );
    }),
    submitPrintingTagNoMatch: http.post(
      buildRoute("2/submitPrintingTag/"),
      () => {
        voted = true;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: true, voteTally: [] },
          { status: 200 }
        );
      }
    ),
  };
}

test.describe("NoMatchReasonStrip reason-tag partition", () => {
  // Deliberately exercised through the actual rendered page (not a direct Node-side import
  // of NoMatchReasonStrip.tsx's NO_MATCH_REASON_TAG_GROUPS/NO_MATCH_REASON_TAG_NAMES) -
  // Playwright test files run under plain Node module resolution outside webpack, which
  // can't resolve react-bootstrap's package-subpath imports (e.g. "react-bootstrap/Button"),
  // so importing a component module at the top of a .spec.ts file breaks collection of every
  // test in the file. Rendering through the real page instead exercises the exact same
  // partition the browser actually uses, and is checked against
  // NO_MATCH_REASON_TAG_DISPLAY_NAMES (mocks/handlers.ts's own independent mirror of
  // cardpicker/reason_tags.py's NO_MATCH_REASON_TAGS) as the "full set" oracle, so this
  // still fails if a tag goes missing from - or ends up duplicated across - the UI's two
  // groups, not just if the two groups disagree with each other.
  test("the not-official-printing/not-official-art groups are exhaustive over the full reason-tag list, with no overlap", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags, // all seven reason tags seeded
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();

    const strip = page.getByTestId("no-match-reason-strip");
    await expect(strip).toBeVisible();

    // Every rendered reason-chip testid, across BOTH groups combined - excludes the group
    // wrapper testids (which share the "no-match-reason-" prefix) and the Skip button.
    const renderedTagTestIds = await strip
      .locator(
        '[data-testid^="no-match-reason-"]:not([data-testid^="no-match-reason-group-"]):not([data-testid="no-match-reason-skip"])'
      )
      .evaluateAll((elements) =>
        elements.map((element) => element.getAttribute("data-testid"))
      );
    const expectedTagTestIds = NO_MATCH_REASON_TAG_DISPLAY_NAMES.map(
      ([name]) => `no-match-reason-${name}`
    );

    // Exhaustive: nothing from the backend's known tag set is missing from the union of the
    // two rendered groups.
    expect([...renderedTagTestIds].sort()).toEqual(
      [...expectedTagTestIds].sort()
    );
    // No overlap: if a tag were rendered in both groups, its testid would appear twice here.
    expect(new Set(renderedTagTestIds).size).toBe(renderedTagTestIds.length);
  });
});

test.describe("NoMatchReasonStrip tests", () => {
  test("No match is disabled until a chip is set, then shows the reason strip split into two labelled groups (not the general attribute panel)", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();

    const strip = page.getByTestId("no-match-reason-strip");
    await expect(strip).toBeVisible();

    const printingGroup = strip.getByTestId(
      "no-match-reason-group-not-official-printing"
    );
    const artGroup = strip.getByTestId(
      "no-match-reason-group-not-official-art"
    );
    await expect(printingGroup).toBeVisible();
    await expect(artGroup).toBeVisible();
    await expect(
      printingGroup.getByText("Not an official printing")
    ).toBeVisible();
    await expect(artGroup.getByText("Not official art")).toBeVisible();

    // Every chip lands in exactly the group its axis says it should.
    await expect(printingGroup.getByText("Altered frame")).toBeVisible();
    await expect(printingGroup.getByText("Upscaled")).toBeVisible();
    await expect(printingGroup.getByText("No collector line")).toBeVisible();
    await expect(printingGroup.getByText("Non-English")).toBeVisible();
    await expect(artGroup.getByText("Custom art")).toBeVisible();
    await expect(artGroup.getByText("AI art")).toBeVisible();
    await expect(artGroup.getByText("External IP")).toBeVisible();

    // ... and nowhere else.
    await expect(printingGroup.getByText("Custom art")).not.toBeVisible();
    await expect(artGroup.getByText("Altered frame")).not.toBeVisible();
  });

  test("hides chips for reason tags that don't exist server-side yet, in both groups", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsSomeNoMatchReasonTags, // only custom-art and ai-art exist (both "not-official-art")
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();

    const strip = page.getByTestId("no-match-reason-strip");
    await expect(strip).toBeVisible();

    // Every not-official-printing tag is unseeded here - the whole group hides rather than
    // rendering an empty header.
    await expect(
      strip.getByTestId("no-match-reason-group-not-official-printing")
    ).not.toBeVisible();

    // The not-official-art group still renders (custom-art/ai-art are seeded), but the
    // per-chip filter still hides the one unseeded tag within it (external-ip) - proving the
    // existing graceful-degradation filter applies inside a group, not just across whole
    // groups.
    const artGroup = strip.getByTestId(
      "no-match-reason-group-not-official-art"
    );
    await expect(artGroup).toBeVisible();
    await expect(strip.getByText("Custom art")).toBeVisible();
    await expect(strip.getByText("AI art")).toBeVisible();
    await expect(strip.getByText("External IP")).not.toBeVisible();
    await expect(strip.getByText("Altered frame")).not.toBeVisible();
    await expect(strip.getByText("Upscaled")).not.toBeVisible();
    await expect(strip.getByText("No collector line")).not.toBeVisible();
    await expect(strip.getByText("Non-English")).not.toBeVisible();
  });

  test("tapping a reason chip submits a positive tag vote and advances the feed", async ({
    page,
    network,
  }) => {
    let submittedBody: { tagName?: string; polarity?: number } = {};
    const mocks = questionFeedUntilNoMatchVoted();
    network.use(
      mocks.questionFeed,
      mocks.submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    page.on("request", async (request) => {
      if (
        request.url().includes("/2/submitTagVote/") &&
        request.postDataJSON()?.tagName === "ai-art"
      ) {
        submittedBody = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();
    await page.getByTestId("no-match-reason-ai-art").click();

    await expect(
      page.getByText(
        "You're all caught up - no cards left to work on right now!"
      )
    ).toBeVisible();
    expect(submittedBody.tagName).toBe("ai-art");
    expect(submittedBody.polarity).toBe(1);
  });

  test("tapping a reason chip from the OTHER group (not-official-printing) submits the same vote payload shape through the same endpoint", async ({
    page,
    network,
  }) => {
    let submittedBody: { tagName?: string; polarity?: number } = {};
    const mocks = questionFeedUntilNoMatchVoted();
    network.use(
      mocks.questionFeed,
      mocks.submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    page.on("request", async (request) => {
      if (
        request.url().includes("/2/submitTagVote/") &&
        request.postDataJSON()?.tagName === "altered-frame"
      ) {
        submittedBody = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();
    await page.getByTestId("no-match-reason-altered-frame").click();

    // Same tagName/polarity shape as the not-official-art chip in the previous test - the
    // split is presentational, not a new vote payload.
    await expect(async () => {
      expect(submittedBody.tagName).toBe("altered-frame");
    }).toPass();
    expect(submittedBody.polarity).toBe(1);
  });

  test("a not-official-printing reason returns to this item's candidate grid with the filter panel open, instead of advancing", async ({
    page,
    network,
  }) => {
    // Owner report, 2026-08-04: the artwork is genuine on this axis, so the remaining
    // question (which printing) is still answerable from this same item's own candidate
    // list - this exercises that Level 2 stays put rather than skipping to the next item.
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();
    await page.getByTestId("no-match-reason-altered-frame").click();

    await expect(page.getByTestId("attribute-chip-panel")).toBeVisible();
    await expect(
      page.getByText(
        "You're all caught up - no cards left to work on right now!"
      )
    ).not.toBeVisible();
  });

  test("a not-official-art reason still advances straight through - nothing to narrow towards", async ({
    page,
    network,
  }) => {
    const mocks = questionFeedUntilNoMatchVoted();
    network.use(
      mocks.questionFeed,
      mocks.submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();
    await page.getByTestId("no-match-reason-ai-art").click();

    await expect(
      page.getByText(
        "You're all caught up - no cards left to work on right now!"
      )
    ).toBeVisible();
  });

  test("skip in the reason strip advances without submitting a no-match-reason vote", async ({
    page,
    network,
  }) => {
    let reasonVoteSubmitted = false;
    const mocks = questionFeedUntilNoMatchVoted();
    network.use(
      mocks.questionFeed,
      mocks.submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsAllNoMatchReasonTags,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        reasonVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();
    await expect(page.getByTestId("no-match-reason-strip")).toBeVisible();
    await page.getByTestId("no-match-reason-skip").click();

    await expect(
      page.getByText(
        "You're all caught up - no cards left to work on right now!"
      )
    ).toBeVisible();
    expect(reasonVoteSubmitted).toBe(false);
  });
});
