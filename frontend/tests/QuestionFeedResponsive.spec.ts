import type { NetworkFixture } from "@msw/playwright";
import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { getWorkerImageURL } from "@/common/image";
import {
  cardDocument1,
  localBackendURL,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedConfirmSuggestion,
  questionFeedIdentifyPrinting,
  submitPrintingTagResolvesToPrintingCandidate2,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

function buildRoute(route: string) {
  return `${localBackendURL}/${route}`;
}

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

function isContainedWithin(
  inner: { x: number; y: number; width: number; height: number },
  outer: { x: number; y: number; width: number; height: number },
  tolerancePx = 1
): boolean {
  return (
    inner.x >= outer.x - tolerancePx &&
    inner.y >= outer.y - tolerancePx &&
    inner.x + inner.width <= outer.x + outer.width + tolerancePx &&
    inner.y + inner.height <= outer.y + outer.height + tolerancePx
  );
}

const MOBILE_WIDTHS = [360, 390, 412];

test.describe("question feed - Level 2 layout reconciliation (real-device regression guard)", () => {
  // Regression guard for the mechanism that survived PR #55: Level 1 was fixed (StaticCardPanel),
  // but Level 2 - the far more common, default screen (every identify_printing item, plus every
  // NOT SURE/NO drop from Level 1) - kept the identical sticky-plus-negative-z-index CardPanel
  // unchanged, so the same real-device compositing failure persisted there. CardPanel is now
  // position: static below the md breakpoint (768px) - these tests assert that directly via
  // bounding-box math at three real device widths, none of which this sandbox's Chromium would
  // have failed even before the fix (the bug is cross-engine/real-mobile-only), so this is a
  // structural regression guard, not proof the original symptom is gone on-device.
  for (const width of MOBILE_WIDTHS) {
    test(`at ${width}px, the card is contained in its panel and no control overlaps it`, async ({
      page,
      network,
    }) => {
      network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
      await page.setViewportSize({ width, height: 844 });
      await loadPageWithDefaultBackend(page, "whatsthat");

      const cardPanel = page.getByTestId("question-feed-card-panel");
      const cardImage = page.getByAltText(cardDocument1.name);
      await expect(cardImage).toBeVisible();

      const panelBox = await cardPanel.boundingBox();
      const imageBox = await cardImage.boundingBox();
      expect(panelBox).not.toBeNull();
      expect(imageBox).not.toBeNull();
      // Item 3 (height-reservation hypothesis): the card's layout box must equal its visual
      // box - a sticky element whose reserved flow position and pinned visual position have
      // diverged would fail this containment check the moment it's stuck.
      expect(isContainedWithin(imageBox!, panelBox!)).toBe(true);

      const candidateButton = page.locator(
        `[data-card-identifier="${printingCandidate1.identifier}"]`
      );
      const controls = [
        page.getByTestId("question-feed-filter-toggle"),
        page.getByTestId("question-feed-no-match"),
        page.getByTestId("question-feed-custom-art"),
        page.getByTestId("question-feed-skip"),
        candidateButton,
      ];
      for (const control of controls) {
        await expect(control).toBeVisible();
        const controlBox = await control.boundingBox();
        expect(controlBox).not.toBeNull();
        expect(boxesIntersect(panelBox!, controlBox!)).toBe(false);
      }
    });
  }

  test("at 360px with the attribute-chip filter expanded, the ring collapses to a stack instead of squeezing the card", async ({
    page,
    network,
  }) => {
    // Regression guard for the second mechanism found in this pass: ChipRing (the PR #21-era
    // chip-ring, still reachable via Level 2's opt-in "Filter by attribute" disclosure) had no
    // responsive behavior at all - its flanking left/right chip columns were always auto-sized
    // to their own content while the card's own column was the only flexible one, so at narrow
    // widths the card was squeezed to whatever width was left over. Below the sm breakpoint
    // (576px) the ring now collapses to a single vertical stack instead.
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 360, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await page.getByTestId("question-feed-filter-toggle").click();

    const cardPanel = page.getByTestId("question-feed-card-panel");
    const cardArea = page.getByTestId("attribute-chip-card-area");
    const fullArtChip = page.getByTestId("attribute-chip-Full Art");
    await expect(fullArtChip).toBeVisible();

    const panelBox = await cardPanel.boundingBox();
    const cardAreaBox = await cardArea.boundingBox();
    const chipBox = await fullArtChip.boundingBox();
    expect(panelBox).not.toBeNull();
    expect(cardAreaBox).not.toBeNull();
    expect(chipBox).not.toBeNull();

    // The card's own grid area must render at its full natural width, not squeezed between
    // two flanking chip columns - a stacked ring gives it the same width as the panel it sits
    // in, since it's the only column left once the ring collapses. Measured against
    // CardArea's own box (not the mocked <img>'s rendered box) because this environment's
    // fixture images use an empty src, which Chromium renders at a small intrinsic fallback
    // size regardless of the CSS width/aspect-ratio set on it - checking the <img> pixel size
    // here would test image-loading behavior, not the grid layout this change actually fixed.
    expect(cardAreaBox!.width).toBeGreaterThan(panelBox!.width * 0.9);
    // No chip overlaps the card's own grid area - the ring never re-forms below sm.
    expect(boxesIntersect(cardAreaBox!, chipBox!)).toBe(false);
  });
});

// identify_printing lands straight on Level 2 (the candidate grid) - confirm_suggestion's
// Level 1 has no grid to reorder at all, so it's not a fit for this ordering check anymore
// (see QuestionFeed.spec.ts for Level 1's own coverage).
test.describe("question feed - mobile layout", () => {
  // Mobile-row fix round (owner live-review) - the card no longer renders ABOVE the candidates
  // in a vertical stack at all; it renders BESIDE them (its own compact grid column to the
  // left - see HeroGrid's mobile grid-template-areas in QuestionFeed.tsx), the same axis
  // relationship as the desktop test below rather than the pre-fix mobile stack. The `y`
  // assertion below still holds either way for a different, still-true reason: the card has
  // no badge/prompt text stacked above it the way the candidate grid does, so its top edge
  // still lands at/above the candidate grid's own top edge - but the ORIGINAL rationale (card
  // reachable "before" the candidates in scroll/stacking order) no longer describes the real
  // mechanism, so this comment is corrected rather than left to imply a layout this page no
  // longer has. See "mobile card/questions never overlap" below for the actual regression
  // guard the fix round needed.
  test("at a mobile viewport, the mystery card's top edge is not pushed below the candidate grid's own top edge", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(cardImage).toBeVisible();
    await expect(suggestedCandidate).toBeVisible();

    const cardBox = await cardImage.boundingBox();
    const candidateBox = await suggestedCandidate.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(candidateBox).not.toBeNull();
    // The card must be reachable without scrolling past every answer option first - its top
    // edge should render above (a smaller y than) the candidate grid's.
    expect(cardBox!.y).toBeLessThan(candidateBox!.y);
  });

  test("at desktop width, the card renders to the left of the candidates (quiz-reveal hero axis flip, issue #305)", async ({
    page,
    network,
  }) => {
    // wtc-redesign-spec.md's W1 "axis flip" - the subject card + starburst are now the left
    // hero column and every question surface (including this candidate grid) renders to the
    // right of it, reversing the pre-#305 candidates-left/card-right layout this test used to
    // assert.
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    // default chromium project viewport (800x600) is already >= the md breakpoint
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(cardImage).toBeVisible();
    await expect(suggestedCandidate).toBeVisible();

    const cardBox = await cardImage.boundingBox();
    const candidateBox = await suggestedCandidate.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(candidateBox).not.toBeNull();
    expect(cardBox!.x).toBeLessThan(candidateBox!.x);
  });

  test("at desktop width, the hero card stays fully visible while the questions column scrolls independently (owner pinning addendum)", async ({
    page,
    network,
  }) => {
    // The card's own grid cell never scrolls (see HeroQuestionsArea/HeroCardArea in
    // QuestionFeed.tsx) - scrolling the questions column's own scrollbar must not move the
    // card at all, not even by a few px.
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    await expect(cardImage).toBeVisible();
    const boxBeforeScroll = await cardImage.boundingBox();
    expect(boxBeforeScroll).not.toBeNull();

    await page.getByTestId("question-feed-questions-area").evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });

    const boxAfterScroll = await cardImage.boundingBox();
    expect(boxAfterScroll).not.toBeNull();
    expect(boxAfterScroll).toEqual(boxBeforeScroll);
  });

  // Fix round (PR #305/#308 owner review) - the test above only ever scrolled
  // HeroQuestionsArea's OWN scrollbar directly via `el.scrollTop`, which is exactly the gap
  // that let this invariant pass in CI while failing live: on the live site, the outer
  // "document" (in practice Layout.tsx's fixed-position, overflow-y: scroll
  // ContentContainer - see that component's own comment) had genuine leftover overflow of its
  // own (StarburstBackground's real padding/margin plus Footer's whole height were never
  // subtracted from the hero's old max-height calc), so a completely ordinary mouse-wheel
  // scroll anywhere on the page - not just inside the questions box - moved the WHOLE page,
  // hero card included. A real `page.mouse.wheel()` (not a targeted `el.scrollTop` write)
  // reproduces exactly what a live user's scroll gesture does, and checking
  // ContentContainer's own `scrollTop` alongside the card's position pins down which
  // container actually (didn't) move.
  test("a real mouse-wheel scroll over the page does not move the hero card or scroll the outer content container", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardImage = page.getByAltText(cardDocument1.name);
    await expect(cardImage).toBeVisible();
    const boxBeforeScroll = await cardImage.boundingBox();
    expect(boxBeforeScroll).not.toBeNull();

    // Wheel over the hero card area itself (not inside the questions column's own scrollbox) -
    // this is what a real user's mouse would do if they scrolled while looking at the card.
    const cardBox = boxBeforeScroll!;
    await page.mouse.move(
      cardBox.x + cardBox.width / 2,
      cardBox.y + cardBox.height / 2
    );
    await page.mouse.wheel(0, 2000);
    await page.waitForTimeout(200);

    const boxAfterScroll = await cardImage.boundingBox();
    expect(boxAfterScroll).toEqual(boxBeforeScroll);

    const contentContainerScrollTop = await page
      .getByTestId("content-container")
      .evaluate((el) => el.scrollTop);
    expect(contentContainerScrollTop).toBe(0);
  });

  // Owner blocker (post-#310 live review) - the sliced WHAT'S/THAT/CARD? word stack rendered
  // far larger than wtc-mockup.html's own approved proportion (measured directly off that file
  // with its demo-only scale transform removed: 164px total for all three words at 1280px wide,
  // versus 220px live), and since #310 bounded the WHOLE hero to one viewport-height row
  // (HeroGrid's own `grid-template-rows: auto minmax(0, 1fr)` - the `auto` row sizes to
  // HeroWordsArea's own content height, which comes directly out of the `questions` row's
  // budget), every extra pixel the words claimed was one HeroQuestionsArea didn't get. At
  // 1400x900 this left even Level 1 (suggested-match card + all four answer controls, no
  // candidate grid to scroll) short by ~140px, forcing an internal scroll that clipped the
  // card mid-view - exactly the "not even the simplest case fits" symptom this guards against.
  // See WhatsThatWords.tsx's Word component for the sizing fix itself.
  test("at 1400x900, Level 1's suggested-match card and all four answer controls fit without an internal scroll", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 1400, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("question-feed-level1-yes")).toBeVisible();

    const questionsArea = page.getByTestId("question-feed-questions-area");
    const overflow = await questionsArea.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    // scrollHeight is defined as never less than clientHeight (a box with room to spare still
    // reports the two as equal, not scrollHeight < clientHeight) - so this only ever proves
    // "no overflow", never "how much margin" on its own. That's fine here: the assertion this
    // task actually asked for is exactly "no internal scroll", i.e. scrollHeight <= clientHeight.
    expect(overflow.scrollHeight).toBeLessThanOrEqual(overflow.clientHeight);

    const referenceImage = page.getByTestId(
      "question-feed-level1-reference-image"
    );
    const yes = page.getByTestId("question-feed-level1-yes");
    const notSure = page.getByTestId("question-feed-level1-not-sure");
    const no = page.getByTestId("question-feed-level1-no");
    const skip = page.getByTestId("question-feed-level1-skip");

    for (const control of [referenceImage, yes, notSure, no, skip]) {
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      // Fully within the 900px-tall viewport, not merely "visible" per Playwright's own
      // visibility check (which only requires a non-zero intersection, not full containment).
      expect(box!.y + box!.height).toBeLessThanOrEqual(900);
      expect(box!.y).toBeGreaterThanOrEqual(0);
    }
  });
});

// Owner live-review fix ("STICKY OVERLAP: on scroll, the subject card COVERS the questions on
// mobile") - confirmed live via a real Pixel 7 portrait screenshot + getBoundingClientRect()
// diff (this task's own report): the old mobile layout stacked "words"/"card"/"questions" in
// one column with HeroCardArea's own `position: sticky; z-index: 5` bar riding on top of
// HeroQuestionsArea as the page scrolled - the two areas shared the same horizontal space by
// construction, so the sticky card was always going to end up geometrically nested inside the
// questions box's own bounds once scrolled (not a flaky edge case - guaranteed by the shared-
// column geometry). The fix gives the card its own disjoint grid COLUMN beside the questions
// (see QuestionFeed.tsx's HeroGrid/HeroCardArea) - this is the direct regression guard for that:
// a real `page.mouse.wheel()` scroll (not a targeted `el.scrollTop` write - see the desktop
// pinning test above for why that distinction matters), then an axis-aligned bounding-box
// intersection check between the card's own area and the questions area, both before AND after
// scrolling. Uses a dozen synthetic candidates (not the default fixture's two) specifically to
// force the page tall enough to need a real scroll - the live bug only manifested once there
// was enough candidate content to scroll past.
test.describe("question feed - mobile card/questions never overlap (owner live-review fix)", () => {
  test("at portrait mobile width, the card and the questions area never intersect, before or after a real scroll", async ({
    page,
    network,
  }) => {
    const manyCandidates = Array.from({ length: 12 }, (_, i) => ({
      ...printingCandidate1,
      identifier: `overlap-guard-candidate-${i}`,
      collectorNumber: `${i}`,
    }));
    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: cardDocument1,
              candidates: manyCandidates,
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 12,
              confirmable: 0,
              contested: 0,
              fresh: 12,
            },
          },
          { status: 200 }
        )
      ),
      ...defaultHandlers
    );
    await page.setViewportSize({ width: 390, height: 700 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const cardArea = page.getByTestId("question-feed-hero-card-area");
    const questionsArea = page.getByTestId("question-feed-questions-area");
    await expect(cardArea).toBeVisible();
    await expect(questionsArea).toBeVisible();

    const assertNoOverlap = async () => {
      const cardBox = (await cardArea.boundingBox())!;
      const questionsBox = (await questionsArea.boundingBox())!;
      expect(cardBox).not.toBeNull();
      expect(questionsBox).not.toBeNull();
      // Standard axis-aligned bounding-box (AABB) intersection test - true iff the two boxes
      // overlap on BOTH axes; edge-touching counts as NOT intersecting, matching how two
      // adjacent, non-overlapping columns normally abut each other.
      const intersects =
        cardBox.x < questionsBox.x + questionsBox.width &&
        cardBox.x + cardBox.width > questionsBox.x &&
        cardBox.y < questionsBox.y + questionsBox.height &&
        cardBox.y + cardBox.height > questionsBox.y;
      expect(intersects).toBe(false);
    };

    await assertNoOverlap();

    await page.mouse.wheel(0, 1500);
    await page.waitForTimeout(300);

    await assertNoOverlap();
  });
});

// Fix round (PR #305/#308 owner review) - HeroQuestionsArea's overflow-y: auto (needed for the
// pinning fix above) forces overflow-x: auto too (CSS's own "visible computes to auto once the
// other axis isn't visible" rule), which silently re-clips the candidate grid's hover-zoom/
// hover-burst (both deliberately built with no overflow: hidden of their own - see
// cardPanel.tsx) right at this box's edges - worst on the left, where the first column in
// every row sits flush against it with no buffer at all.
test.describe("question feed - hover-zoom/hover-burst edge clipping (owner live report)", () => {
  test("hovering the leftmost candidate in a row does not get clipped by the scroll container's edge", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const leftmostCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    const containerBox = await page
      .getByTestId("question-feed-questions-area")
      .boundingBox();
    expect(containerBox).not.toBeNull();

    await leftmostCandidate.locator("img").first().hover();
    // matches ZoomableThumbnail's own 0.15s transition and HoverBurst's 0.18s transition
    // (cardPanel.tsx) - long enough for both to settle at their hovered size.
    await page.waitForTimeout(250);

    const imgBox = await leftmostCandidate.locator("img").first().boundingBox();
    const burstBox = await leftmostCandidate
      .locator(".hover-burst")
      .boundingBox();
    expect(imgBox).not.toBeNull();
    expect(burstBox).not.toBeNull();

    // Horizontal-only containment - vertical clipping at the top/bottom of this box is its
    // intended scrolling behaviour; only left/right clipping (this box never scrolls
    // sideways) is the reported "sheared" bug. A tolerance of 1px absorbs subpixel rounding
    // from the transform-scaled hover state.
    const tolerance = 1;
    expect(imgBox!.x).toBeGreaterThanOrEqual(containerBox!.x - tolerance);
    expect(imgBox!.x + imgBox!.width).toBeLessThanOrEqual(
      containerBox!.x + containerBox!.width + tolerance
    );
    expect(burstBox!.x).toBeGreaterThanOrEqual(containerBox!.x - tolerance);
    expect(burstBox!.x + burstBox!.width).toBeLessThanOrEqual(
      containerBox!.x + containerBox!.width + tolerance
    );
  });
});

// Mobile funnel pass - thumb-native tap targets. WCAG 2.5.5 (Target Size, AA) and Apple's HIG
// both call for a 44px minimum touch target; Bootstrap's own default .btn height (~38px) and
// the attribute chips' original padding (~30px) both fell short. These assert the real,
// measured height of each control class the funnel uses for answering a question, not just
// that a CSS rule exists - a min-height declaration overridden elsewhere (e.g. a conflicting
// Bootstrap utility class) wouldn't be caught by a stylesheet-only check.
test.describe("question feed - tap target sizes (mobile funnel pass)", () => {
  test("Level 1's stacked answer buttons meet the 44px floor", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    for (const testId of [
      "question-feed-level1-yes",
      "question-feed-level1-not-sure",
      "question-feed-level1-no",
      "question-feed-level1-skip",
    ]) {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });

  test("Level 2's filter toggle and exit buttons meet the 44px floor", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const toggleBox = await page
      .getByTestId("question-feed-filter-toggle")
      .boundingBox();
    expect(toggleBox).not.toBeNull();
    expect(toggleBox!.height).toBeGreaterThanOrEqual(44);

    for (const testId of [
      "question-feed-no-match",
      "question-feed-custom-art",
      "question-feed-skip",
    ]) {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });

  test("attribute chips meet the 44px floor once the filter panel is expanded", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-filter-toggle").click();
    const firstChip = page
      .locator('[data-testid^="attribute-chip-"][data-chip-state]')
      .first();
    await expect(firstChip).toBeVisible();
    const box = await firstChip.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.width).toBeGreaterThanOrEqual(44);
  });
});

// Owner review round on top of the "mobile card/questions never overlap" fix above (own header
// comment) - that fix put the card in its own disjoint column beside a horizontally-scrolling
// answer row, which the owner found wasted space and let the question prompt clip behind the
// card, with "None of these" left inside the scrollable candidate area (below the fold on a
// real device). This restructure (QuestionFeed.tsx's `Level2NarrowGrid`, cardPanel.tsx's
// height-capped `CardPanel`/`StaticCardPanel`) stacks the card ABOVE the questions again, caps
// its height (~32vh) so a STATIC top block (card, name/badge/question text, the "Filter by
// attribute"/"None of these"/"Art matches"/"Skip" action row) plus the scrollable candidate row
// below it both fit a real phone viewport with no scrolling anywhere. Desktop/landscape (>= md)
// is untouched - only these narrow-width assertions are new.
//
// Pixel 7's own CSS viewport (412x839 - Playwright's own `devices["Pixel 7"]` descriptor;
// `page.setViewportSize` rather than full device emulation since `devices["Pixel 7"]` bundles a
// `defaultBrowserType` that can't be set at describe/test scope - project-level only - and
// nothing else in this describe block needs the rest of the device profile, e.g. touch/UA).
// Every other fixture in this file uses the empty-`mediumThumbnailUrl` convention (a genuine,
// non-empty <img> is needed here - the card's own height cap is expressed as a max-width derived
// from a target vh, which only manifests once the <img> actually sizes itself via its own
// width: 100%/aspect-ratio CSS; an empty-src image renders at a small, fixed intrinsic fallback
// size regardless of that CSS, confirmed via a real Playwright measurement in this task's own
// report) - mirrors WhatsThatWordsAnimation.spec.ts's own CDN-route-intercept pattern for the
// identical reason.
const PIXEL_7_VIEWPORT = { width: 412, height: 839 };

test.describe("question feed - portrait static top block (owner live-review)", () => {
  async function loadWithRealImage(
    page: import("@playwright/test").Page,
    network: NetworkFixture
  ) {
    await page.setViewportSize(PIXEL_7_VIEWPORT);
    const testCard = {
      ...cardDocument1,
      mediumThumbnailUrl: "non-empty-sentinel-see-comment-above",
      smallThumbnailUrl: "non-empty-sentinel-see-comment-above",
    };
    process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = "https://cdn.proxyprints.ca";
    const cdnImageURL = getWorkerImageURL(testCard, "small")!;
    const cdnImagePattern = new RegExp(
      `^${cdnImageURL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`
    );
    await page.route(cdnImagePattern, (route) =>
      route.fulfill({ path: "public/whatsthat-icon-192.png" })
    );

    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: testCard,
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
    await loadPageWithDefaultBackend(page, "whatsthat");
    await expect(page.getByAltText(testCard.name)).toBeVisible();
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toBeVisible();
  }

  test("at Pixel 7 portrait, the whole page needs zero vertical scroll to reach every answer control", async ({
    page,
    network,
  }) => {
    await loadWithRealImage(page, network);

    // The outer document itself never needs to scroll - the static top block (wordmark, card,
    // text, action row) plus the scrollable candidate row below it are sized to fit entirely
    // within the viewport (PageColumn/StarburstBackground in whatsthat.tsx now bound height at
    // every width, not just >= md - see that file's own comment).
    const documentScroll = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      clientHeight: document.documentElement.clientHeight,
    }));
    expect(documentScroll.scrollHeight).toBeLessThanOrEqual(
      documentScroll.clientHeight
    );

    // The candidate row is the ONLY genuinely scrollable region Level 2 has (horizontally, via
    // MobileCandidateScroller's own overflow-x: auto) - HeroQuestionsArea's own overflow-y: auto
    // is a defensive fallback for edge cases (own comment, QuestionFeed.tsx), not the intended
    // mechanism, so this asserts it never actually has to engage on the reference viewport.
    const questionsAreaScroll = await page
      .getByTestId("question-feed-questions-area")
      .evaluate((el) => ({
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      }));
    expect(questionsAreaScroll.scrollHeight).toBeLessThanOrEqual(
      questionsAreaScroll.clientHeight
    );
  });

  test("the static action row (Filter by attribute / None of these) renders above the scrollable candidate row, not inside it", async ({
    page,
    network,
  }) => {
    await loadWithRealImage(page, network);

    const filterToggleBox = await page
      .getByTestId("question-feed-filter-toggle")
      .boundingBox();
    const noMatchBox = await page
      .getByTestId("question-feed-no-match")
      .boundingBox();
    const candidateBox = await page
      .locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
      .boundingBox();
    expect(filterToggleBox).not.toBeNull();
    expect(noMatchBox).not.toBeNull();
    expect(candidateBox).not.toBeNull();

    // Both static-row controls render fully ABOVE the candidate row's own top edge - resolving
    // ("Filter by attribute" or "None of these") is always one tap with zero scrolling, never
    // buried below the fold behind the scrollable candidates the way the pre-fix layout left it.
    expect(filterToggleBox!.y + filterToggleBox!.height).toBeLessThanOrEqual(
      candidateBox!.y
    );
    expect(noMatchBox!.y + noMatchBox!.height).toBeLessThanOrEqual(
      candidateBox!.y
    );

    // Both are also within the viewport with no scroll needed to reach them.
    const viewportSize = page.viewportSize()!;
    expect(filterToggleBox!.y + filterToggleBox!.height).toBeLessThanOrEqual(
      viewportSize.height
    );
    expect(noMatchBox!.y + noMatchBox!.height).toBeLessThanOrEqual(
      viewportSize.height
    );
  });

  test("the question text sits directly under the card, not occluded by it or the starburst", async ({
    page,
    network,
  }) => {
    await loadWithRealImage(page, network);

    const cardImage = page.getByAltText(cardDocument1.name);
    const cardBox = await cardImage.boundingBox();
    const badgeBox = await page
      .getByTestId("question-feed-tier-badge")
      .boundingBox();
    const filterToggleBox = await page
      .getByTestId("question-feed-filter-toggle")
      .boundingBox();
    expect(cardBox).not.toBeNull();
    expect(badgeBox).not.toBeNull();
    expect(filterToggleBox).not.toBeNull();

    // The badge (and, transitively, the question text/action row below it) renders entirely
    // below the card's own bottom edge - never behind or overlapping the card art or its
    // starburst, unlike the pre-fix two-column layout this replaces (where the question text
    // ran behind the reference card - see this task's own report for the reported bug).
    expect(badgeBox!.y).toBeGreaterThanOrEqual(cardBox!.y + cardBox!.height);
    expect(filterToggleBox!.y).toBeGreaterThanOrEqual(badgeBox!.y);
  });
});

// Owner review round 2 (live device follow-up on top of the portrait static top block above) -
// three asks: (1) a question-mark motif on every blue "unrevealed" card, fading away together
// with the blue as the card reveals, at every viewport; (2) drop the narrow-width standalone "?"
// if one exists distinct from the wordmark's own glyph; (3) recolour every quiz action button
// gold, since Bootstrap's per-variant colours (grey/red/green/blue) were designed against the
// site's neutral background, not this page's own deep-blue starburst field, and measured out at
// ~2.4:1 contrast for the worst offender - see cardPanel.tsx/QuestionFeed.tsx's own comments.
//
// Only (1) and (3) get new assertions here - (1) turned out to already be implemented (the
// hero reveal overlay already rendered "?" as its own child, fading via the shared parent
// opacity animation - see RevealOverlay's own comment in cardPanel.tsx), so these are a
// regression guard, not new functionality. (2) has no code change: the narrow-width wordmark
// (`whatsthat-composite.svg`) bakes its own "?" mascot glyph directly into the same flattened
// image as the "WHAT'S THAT CARD?" text - there is no separate, distinct "?" DOM element at
// narrow widths to remove without altering the wordmark itself (see this PR's own body for the
// full ambiguity writeup) - so it's deliberately left untouched here, matching
// WhatsThatWordsAnimation.spec.ts's existing narrow/wide wordmark visibility coverage.
test.describe("question feed - question-mark motif + golden action buttons (owner review round 2)", () => {
  // rgb() equivalents of QuestionFeed.tsx's QUIZ_BUTTON_GOLD/QUIZ_BUTTON_NAVY constants -
  // getComputedStyle always resolves to this form regardless of how the source CSS wrote the
  // colour, so asserting against it directly (rather than re-parsing to hex) is both simpler
  // and exactly what a real browser would report.
  const QUIZ_BUTTON_GOLD_RGB = "rgb(248, 212, 43)"; // #f8d42b
  const QUIZ_BUTTON_NAVY_RGB = "rgb(18, 64, 99)"; // #124063

  // A real (non-empty-src) card image resolves near-instantly against this suite's local mock
  // server - fast enough that a plain `loadPageWithDefaultBackend` call routinely already has
  // `revealed: true` (overlay unmounted) by the time an assertion runs, since RevealOverlay's
  // own 0.8s reveal fade has nothing slower to wait on. A deliberate, generous route delay holds
  // the pre-reveal moment open long enough to assert against reliably - mirrors the "portrait
  // static top block" describe block's own `loadWithRealImage` helper above (own comment there
  // explains why a genuinely non-empty src is needed at all), just with an added delay since that
  // helper's own callers only care about the SETTLED state, not the transient pre-reveal one.
  async function loadWithDelayedImage(
    page: import("@playwright/test").Page,
    network: NetworkFixture
  ) {
    const testCard = {
      ...cardDocument1,
      mediumThumbnailUrl: "non-empty-sentinel-see-comment-above",
      smallThumbnailUrl: "non-empty-sentinel-see-comment-above",
    };
    process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = "https://cdn.proxyprints.ca";
    const cdnImageURL = getWorkerImageURL(testCard, "small")!;
    const cdnImagePattern = new RegExp(
      `^${cdnImageURL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`
    );
    await page.route(cdnImagePattern, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      await route.fulfill({ path: "public/whatsthat-icon-192.png" });
    });

    network.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: testCard,
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
    await loadPageWithDefaultBackend(page, "whatsthat");
    await expect(page.getByAltText(testCard.name)).toBeVisible();
  }

  for (const [label, viewport] of [
    ["mobile", PIXEL_7_VIEWPORT],
    ["desktop", { width: 1280, height: 900 }],
  ] as const) {
    test(`the hero reveal overlay renders a '?' motif (not a bare blue box) before the card reveals - ${label}`, async ({
      page,
      network,
    }) => {
      await page.setViewportSize(viewport);
      await loadWithDelayedImage(page, network);
      const overlay = page.getByTestId("question-feed-reveal-overlay");
      await expect(overlay).toBeVisible();
      await expect(overlay).toHaveText("?");
    });
  }

  test("the candidate grid's 'mystery card' placeholders also carry the '?' motif", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 1280, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // ArtPlaceholder's "?" is a CSS ::before pseudo-element, not real DOM text - not directly
    // queryable via getByText/toHaveText, so this reads the pseudo-element's own computed
    // `content` value instead (the standard way to assert generated content in Playwright).
    // ArtPlaceholder is CandidateButton's own immediate child div (JSX: <CandidateButton><
    // ArtPlaceholder>...) - `data-card-identifier` lives on CandidateButton itself (a <button>),
    // so its first `div` descendant is always ArtPlaceholder.
    const placeholderDiv = page
      .locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
      .locator("div")
      .first();
    const pseudoContent = await placeholderDiv.evaluate(
      (el) => window.getComputedStyle(el, "::before").content
    );
    expect(pseudoContent).toBe('"?"');
  });

  test("every quiz action button (Filter toggle / None of these / Art matches / Skip) uses the shared gold treatment, not Bootstrap's default variant colours", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 1280, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    for (const testId of [
      "question-feed-filter-toggle",
      "question-feed-no-match",
    ]) {
      const color = await page
        .getByTestId(testId)
        .evaluate((el) => window.getComputedStyle(el).color);
      expect(color).toBe(QUIZ_BUTTON_GOLD_RGB);
    }
  });

  test("a selected Level 3 attribute chip stays filled gold (not Bootstrap's default blue 'primary'), while an unselected chip stays gold-outlined", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
      ...defaultHandlers
    );
    await page.setViewportSize({ width: 1280, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");
    await page
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
      .click();
    await page.getByTestId("question-feed-level3").waitFor();

    const selectedChip = page.getByTestId(
      "question-feed-level3-chip-White Border"
    );
    await selectedChip.click();
    const selectedStyles = await selectedChip.evaluate((el) => {
      const s = window.getComputedStyle(el);
      return { color: s.color, backgroundColor: s.backgroundColor };
    });
    expect(selectedStyles.backgroundColor).toBe(QUIZ_BUTTON_GOLD_RGB);
    expect(selectedStyles.color).toBe(QUIZ_BUTTON_NAVY_RGB);

    const unselectedChip = page.getByTestId(
      "question-feed-level3-chip-Black Border"
    );
    const unselectedColor = await unselectedChip.evaluate(
      (el) => window.getComputedStyle(el).color
    );
    expect(unselectedColor).toBe(QUIZ_BUTTON_GOLD_RGB);
  });
});
