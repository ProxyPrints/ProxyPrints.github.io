import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import {
  cardDocument1,
  localBackendURL,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import { defaultHandlers } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Issue #305 (wtc-redesign-spec.md W9/§5 + the owner's card-pulse addendum) - the sliced
// WHAT'S/THAT/CARD? teaser words pop in a staggered sequence on every new card, and the hero
// card itself pulses in lockstep with THAT (same easing/duration/delay, smaller amplitude).
// The D17 flake lesson (docs/troubleshooting.md) applies here: don't screenshot mid-frame in
// CI - assert the *computed* CSS animation properties instead, which are stable regardless of
// exactly when in the ~1s sequence the assertion runs (animation-name/-duration/-delay/-timing-
// function are declarative and don't change once the animation is applied, only the element's
// current playback position does).

function buildRoute(route: string) {
  return `${localBackendURL}/${route}`;
}

const WORD_TEST_IDS = [
  { testId: "whatsthat-word-WHATS", delay: "0s" },
  { testId: "whatsthat-word-THAT", delay: "0.24s" },
  { testId: "whatsthat-word-CARD", delay: "0.48s" },
];

async function animationProperties(
  page: import("@playwright/test").Page,
  testId: string
) {
  return page.getByTestId(testId).evaluate((el) => {
    const style = window.getComputedStyle(el);
    return {
      name: style.animationName,
      duration: style.animationDuration,
      delay: style.animationDelay,
      timingFunction: style.animationTimingFunction,
    };
  });
}

test.describe("What's That Card? - sliced-word pop + hero card pulse (issue #305)", () => {
  test("on card arrival, WHAT'S/THAT/CARD? pop in a staggered sequence and the hero card pulses in sync with THAT", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: cardDocument1,
              candidates: [printingCandidate1, printingCandidate2],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 3,
              confirmable: 0,
              contested: 0,
              fresh: 3,
            },
          },
          { status: 200 }
        )
      ),
      ...defaultHandlers
    );
    // Overrides playwright.config.ts's project-wide reducedMotion: "reduce" (chosen so every
    // OTHER existing spec never has to account for this animation) just for this one test, so
    // the animation is actually configured to run rather than immediately suppressed.
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await loadPageWithDefaultBackend(page, "whatsthat");

    for (const { testId, delay } of WORD_TEST_IDS) {
      const props = await animationProperties(page, testId);
      expect(props.name).not.toBe("none");
      expect(props.duration).toBe("0.48s");
      expect(props.delay).toBe(delay);
      expect(props.timingFunction).toBe("cubic-bezier(0.34, 1.45, 0.64, 1)");
    }

    // The hero card (CardPulseWrapper) - same curve/duration, THAT's own 0.24s delay, smaller
    // amplitude (asserted structurally here via the shared timing, not the peak scale itself,
    // which computed style can't report independent of a live animation frame).
    const cardProps = await animationProperties(
      page,
      "question-feed-card-pulse"
    );
    expect(cardProps.name).not.toBe("none");
    expect(cardProps.duration).toBe("0.48s");
    expect(cardProps.delay).toBe("0.24s");
    expect(cardProps.timingFunction).toBe("cubic-bezier(0.34, 1.45, 0.64, 1)");
  });

  test("under prefers-reduced-motion, the words and hero card render statically (no animation)", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: cardDocument1,
              candidates: [printingCandidate1, printingCandidate2],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 3,
              confirmable: 0,
              contested: 0,
              fresh: 3,
            },
          },
          { status: 200 }
        )
      ),
      ...defaultHandlers
    );
    // Explicit, not relying on playwright.config.ts's project default, so this assertion is
    // self-contained and keeps passing even if that default ever changes.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await loadPageWithDefaultBackend(page, "whatsthat");

    for (const { testId } of WORD_TEST_IDS) {
      const props = await animationProperties(page, testId);
      expect(props.name).toBe("none");
    }
    const cardProps = await animationProperties(
      page,
      "question-feed-card-pulse"
    );
    expect(cardProps.name).toBe("none");

    // Words are still fully visible at rest size (reduced-motion is "don't pop", not "don't
    // render") - and the card reveal shows art immediately with no "?" overlay to wait past.
    for (const { testId } of WORD_TEST_IDS) {
      await expect(page.getByTestId(testId)).toBeVisible();
    }
    await expect(
      page.getByTestId("question-feed-reveal-overlay")
    ).not.toBeVisible();
  });

  test("a new card re-arms the word/card animation by remounting it", async ({
    page,
    network,
  }) => {
    // A fresh, never-before-seen card identifier on EVERY fetch (not just alternating between
    // two fixed cards) - deliberately robust against Next's dev-mode `reactStrictMode` double-
    // invoking the initial mount effect (so this endpoint may already be hit more than once
    // before the user ever clicks Skip): whichever fetch count the page happens to have
    // settled on initially, the NEXT one (triggered by Skip below) is still guaranteed to be a
    // genuinely different card, so the test never has to assume which literal fetch count
    // corresponds to "before" vs. "after" the click.
    let fetchCount = 0;
    network.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        fetchCount += 1;
        return HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: { ...cardDocument1, identifier: `card-${fetchCount}` },
              candidates: [printingCandidate1, printingCandidate2],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 3,
              confirmable: 0,
              contested: 0,
              fresh: 3,
            },
          },
          { status: 200 }
        );
      }),
      ...defaultHandlers
    );
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await loadPageWithDefaultBackend(page, "whatsthat");
    await expect(page.getByTestId("whatsthat-words")).toBeVisible();

    // Mark the settled-initial card's WHAT'S element so a stale (not remounted) node would
    // still carry this marker after Skip - proving the words container is genuinely re-keyed/
    // remounted (wtc-redesign-spec.md W9's "re-arm by keying on the item id"), not just
    // visually the same.
    await page
      .getByTestId("whatsthat-word-WHATS")
      .evaluate((el) => el.setAttribute("data-marker", "before-skip"));

    await page.getByTestId("question-feed-skip").click();
    // `revealed` resets to false on every genuinely new item (see QuestionFeed.tsx's fetch
    // effect), so the reveal overlay reappearing after Skip - regardless of which fetch count
    // the page had settled on before the click - confirms a fresh item actually landed.
    await expect(
      page.getByTestId("question-feed-reveal-overlay")
    ).toBeVisible();

    await expect(page.getByTestId("whatsthat-word-WHATS")).not.toHaveAttribute(
      "data-marker",
      "before-skip"
    );
  });

  // Owner blocker (post-#310 live review, "the pulse doesn't sync with the pop") - the whole
  // sequence (blue-cover fade, word pop, card pulse) must not start until the subject card's
  // own image has actually loaded, not merely once the surrounding React tree has mounted.
  // A route interception that deliberately delays the image response is the only way to prove
  // the gate holds - every other fixture in this file uses an empty mediumThumbnailUrl (no
  // real network request at all), so this test gives the card a real, interceptable URL
  // instead, specifically so the delay is real and not just a fast/instant mock resolution.
  test("the animation sequence does not start until the card image actually loads", async ({
    page,
    network,
  }) => {
    const DELAYED_IMAGE_URL = `${localBackendURL}/delayed-card-image.png`;
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: {
                ...cardDocument1,
                mediumThumbnailUrl: DELAYED_IMAGE_URL,
              },
              candidates: [printingCandidate1, printingCandidate2],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 3,
              confirmable: 0,
              contested: 0,
              fresh: 3,
            },
          },
          { status: 200 }
        )
      ),
      ...defaultHandlers
    );

    // Holds the card image's own response until releaseImage() is called below - a real
    // network delay, not a fake timer, so this proves the gate against actual load timing.
    let releaseImage: () => void = () => {};
    const imageGate = new Promise<void>((resolve) => {
      releaseImage = resolve;
    });
    await page.route(DELAYED_IMAGE_URL, async (route) => {
      await imageGate;
      await route.fulfill({ path: "public/blank.png" });
    });

    await page.emulateMedia({ reducedMotion: "no-preference" });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Before the image resolves: every one of the three synchronized animations must still be
    // paused - none may have started counting down (delay included), per the shared
    // `imageLoaded`-gated `$playing`/`playing` prop (see QuestionFeed.tsx's own comment on
    // `onCardImageSettled`).
    for (const { testId } of WORD_TEST_IDS) {
      const playState = await page
        .getByTestId(testId)
        .evaluate((el) => window.getComputedStyle(el).animationPlayState);
      expect(playState).toBe("paused");
    }
    const cardPlayStateBefore = await page
      .getByTestId("question-feed-card-pulse")
      .evaluate((el) => window.getComputedStyle(el).animationPlayState);
    expect(cardPlayStateBefore).toBe("paused");
    // The cover must still be up - `revealed` can't have flipped true with no load event to
    // trigger it.
    await expect(
      page.getByTestId("question-feed-reveal-overlay")
    ).toBeVisible();

    // Release the image response - only now should the sequence be allowed to start.
    releaseImage();

    for (const { testId } of WORD_TEST_IDS) {
      await expect
        .poll(() =>
          page
            .getByTestId(testId)
            .evaluate((el) => window.getComputedStyle(el).animationPlayState)
        )
        .toBe("running");
    }
    await expect
      .poll(() =>
        page
          .getByTestId("question-feed-card-pulse")
          .evaluate((el) => window.getComputedStyle(el).animationPlayState)
      )
      .toBe("running");
  });
});
