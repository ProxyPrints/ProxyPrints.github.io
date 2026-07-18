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

test.describe("NoMatchReasonStrip tests", () => {
  test("No match is disabled until a chip is set, then shows the reason strip (not the general attribute panel)", async ({
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
    await expect(strip.getByText("Custom art")).toBeVisible();
    await expect(strip.getByText("Altered frame")).toBeVisible();
    await expect(strip.getByText("Upscaled")).toBeVisible();
    await expect(strip.getByText("AI art")).toBeVisible();
    await expect(strip.getByText("No collector line")).toBeVisible();
    await expect(strip.getByText("Non-English")).toBeVisible();
  });

  test("hides chips for reason tags that don't exist server-side yet", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagNoMatch,
      submitTagVoteResolvesToApply,
      tagsSomeNoMatchReasonTags, // only custom-art and ai-art exist
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-no-match").click();

    const strip = page.getByTestId("no-match-reason-strip");
    await expect(strip).toBeVisible();
    await expect(strip.getByText("Custom art")).toBeVisible();
    await expect(strip.getByText("AI art")).toBeVisible();
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
