import { expect } from "@playwright/test";

import { cardDocument1, printingCandidate1 } from "@/common/test-constants";
import {
  defaultHandlers,
  questionFeedConfirmSuggestion,
  questionFeedIdentifyPrinting,
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
  test("at a mobile viewport, the mystery card renders above the answer candidates, not below them", async ({
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
