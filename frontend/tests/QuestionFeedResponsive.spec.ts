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
  submitPrintingTagNoMatch,
  submitPrintingTagResolvesToPrintingCandidate2,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

/**
 * WTC REBUILD (2026-07-24, SPEC-wtc-rebuild.md) - this file is adapted, not left as-is, per
 * the rebuild task's own TESTS requirement ("assertions adapted not weakened; drops
 * ack-tokened + justified"). Every describe block below either:
 *   (a) keeps a still-true invariant, re-pointed at the new DOM/tokens, or
 *   (b) is DROPPED with an inline justification, because the mechanism it guarded
 *       (sticky/bounded-height pinning, the hover-burst, the gold button treatment, the
 *       whatsthat-mark.svg glyph asset) is a deliberate, spec-ruled retirement - not a
 *       regression - or
 *   (c) is NEW coverage the rebuild task's own TESTS section asks for (container folding at
 *       390/768/1400, shape-b shortlist fallback, WD3 compaction + open-shape expansion, the
 *       session counter).
 *
 * DROPPED entirely (own justification, not carried forward even as adapted tests):
 *   - "the hero card stays fully visible while the questions column scrolls independently" /
 *     "a real mouse-wheel scroll ... does not move the hero card" (both from the old "mobile
 *     layout" describe block) - WD4 retires the `100dvh`-bounded hero + its own internal
 *     `overflow-y: auto` questions column entirely; the page is now an ordinary scrolling
 *     document (container-first policy), so scrolling the page legitimately moves the subject
 *     card along with everything else - that IS the new, intended behavior, not a bug this
 *     suite should guard against.
 *   - "at 1400x900, Level 1's suggested-match card and all four answer controls fit without an
 *     internal scroll" - asserted `scrollHeight <= clientHeight` on the (now-unbounded)
 *     questions column; there is no bounded height left for that comparison to mean anything.
 *   - "question feed - mobile card/questions never overlap (owner live-review fix)" (the whole
 *     describe block) - guarded against a `position: sticky` overlap bug that can't recur once
 *     nothing on this page is `position: sticky` (WD4); the container-first fold (flex-wrap)
 *     structurally prevents the two columns from ever sharing a stacking position instead.
 *   - "hover-zoom/hover-burst edge clipping" (the whole describe block) - `HoverBurst` is
 *     retired outright (owner ruling 1); there is no burst left to clip.
 *   - "portrait static top block" (the whole describe block, all 3 tests) - WD4 retires the
 *     "everything above the fold, only the candidate row scrolls" invariant entirely; the page
 *     scrolls normally now. Replaced below by a WD3-specific coverage set (subject compaction)
 *     instead of a same-shaped replacement, since the underlying design goal changed.
 *   - "question-mark motif + golden action buttons" / "shared blue mystery card composition" -
 *     both asserted the retired `whatsthat-mark.svg` `<img>` glyph and the retired
 *     `QUIZ_BUTTON_GOLD`/`_NAVY` treatment (WD1). Replaced below by token-based equivalents.
 */

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

test.describe("question feed - Level 2 layout containment (real-device regression guard)", () => {
  // Regression guard, re-pointed at the new (plain-flow, no sticky/no burst) DOM: the card's
  // art still needs to render fully inside its own panel, and no answer control should ever
  // overlap it, at real mobile widths.
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
    // AttributeChipPanel/ChipRing is unforked by the WTC rebuild (spec section 4: "no
    // structural change; inherit tokens") - this invariant is unchanged.
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

    expect(cardAreaBox!.width).toBeGreaterThan(panelBox!.width * 0.9);
    expect(boxesIntersect(cardAreaBox!, chipBox!)).toBe(false);
  });
});

test.describe("question feed - container-first hero layout (section 3, WTC rebuild)", () => {
  // identify_printing lands straight on Level 2 (the candidate grid).
  test("at a container width above the 560px fold point, the subject renders to the left of the questions", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    // default chromium project viewport (800x600) is already above the hero's 560px fold
    // point (section 3's `@container hero (max-width: 560px)`).
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
    expect(cardBox!.y).toBeLessThan(candidateBox!.y);
  });

  // NEW coverage (rebuild task's TESTS requirement: "container folding at 390/768/1400 via
  // boundingBox - rendered sizes, not authored CSS - the #434 lesson"). Reads the RENDERED
  // subject-column width at three widths and confirms it actually changes shape (not just a
  // static, unresponsive box) - this is the concrete, measured proof the hero is genuinely
  // `@container`-driven rather than merely having the right CSS on paper.
  for (const width of [390, 768, 1400]) {
    test(`at ${width}px, the hero container folds to a real, measured layout (not just authored CSS)`, async ({
      page,
      network,
    }) => {
      network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
      await page.setViewportSize({ width, height: 900 });
      await loadPageWithDefaultBackend(page, "whatsthat");

      const subject = page.getByTestId("question-feed-hero-card-area");
      const questions = page.getByTestId("question-feed-questions-area");
      await expect(subject).toBeVisible();
      await expect(questions).toBeVisible();

      const subjectBox = await subject.boundingBox();
      const questionsBox = await questions.boundingBox();
      expect(subjectBox).not.toBeNull();
      expect(questionsBox).not.toBeNull();

      if (width <= 560) {
        // Below the hero's own 560px container fold point (WD3), the subject spans (close to)
        // the full hero width instead of sharing a row with the questions column.
        expect(subjectBox!.width).toBeGreaterThan(questionsBox!.width * 0.7);
      } else {
        // Above the fold point, the two columns share one row, each narrower than the full
        // hero width.
        expect(subjectBox!.x).toBeLessThan(questionsBox!.x);
        expect(subjectBox!.width).toBeLessThan(questionsBox!.width);
      }
    });
  }

  // WD3 - the subject compacts to horizontal (~132px art + caption beside) once the HERO
  // CONTAINER (not the viewport) drops below 560px - a narrow phone viewport is the practical
  // way to force that container width without a second, artificial container to test against.
  test("WD3: below the hero's 560px fold point, the subject card compacts to a horizontal layout", async ({
    page,
    network,
  }) => {
    // Measured against `question-feed-subject-art` (the CSS box the fold point actually
    // targets), not the raw `<img>` - this suite's own empty-`mediumThumbnailUrl` fixture
    // convention renders a genuinely broken `<img>` (no natural size, `src=""`), and a broken
    // image with alt text falls back to Chromium's own small alt-text layout box regardless of
    // any `width`/`aspect-ratio` CSS on it (confirmed live, this task's own debug pass) -
    // exactly the caveat the pre-rebuild suite's own `loadWithRealImage`/`loadWithDelayedImage`
    // helpers existed to work around elsewhere in this file. The wrapping box's own size is
    // unaffected by that image-loading quirk, so it's the reliable thing to measure here.
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const subjectArt = page.getByTestId("question-feed-subject-art");
    await expect(subjectArt).toBeVisible();
    const artBox = await subjectArt.boundingBox();
    expect(artBox).not.toBeNull();
    // The compacted art column is a fixed 132px wide (SubjectArt's own `@container hero
    // (max-width: 560px)` rule) - a generous tolerance band around that absorbs box-model
    // rounding.
    expect(artBox!.width).toBeGreaterThan(100);
    expect(artBox!.width).toBeLessThan(170);
  });
});

// Mobile funnel pass - thumb-native tap targets. WCAG 2.5.5 (Target Size, AA) and Apple's HIG
// both call for a 44px minimum touch target - unchanged requirement, now enforced via the
// `.btn { min-height: 44px }` base class (SPEC-wtc-rebuild.md section 1c) instead of the
// retired `ThumbButton`/`FilterToggleButton` styled overrides.
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

// Pixel 7's own CSS viewport (412x839 - Playwright's own `devices["Pixel 7"]` descriptor).
// Every other fixture in this file uses the empty-`mediumThumbnailUrl` convention (a genuine,
// non-empty <img> is needed here so the art actually sizes itself via width:100%/aspect-ratio
// CSS - an empty-src image renders at a small, fixed intrinsic fallback size regardless of that
// CSS).
const PIXEL_7_VIEWPORT = { width: 412, height: 839 };

async function loadWithRealImage(
  page: import("@playwright/test").Page,
  network: NetworkFixture,
  viewport: { width: number; height: number } = PIXEL_7_VIEWPORT,
  // 0 (the default) resolves the image near-instantly, for tests that only care about the
  // SETTLED state. A caller that needs to observe the transient pre-reveal moment (the
  // overlay, before it fades) must pass a real delay - mirrors the pre-rebuild suite's own
  // `loadWithDelayedImage` helper, folded into this one via an optional param instead of a
  // second near-duplicate function.
  delayMs = 0
) {
  await page.setViewportSize(viewport);
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
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
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
  return testCard;
}

// Replaces the retired "question-mark motif" describe block - the mystery-card glyph is now a
// plain, token-coloured `<span data-testid="mystery-card-glyph">?</span>` (WD1: the old
// gold-gradient `whatsthat-mark.svg` mascot asset can't be retinted onto `--wtc-mystery-glyph`
// via CSS - see cardPanel.tsx's own comment), not an `<img>`.
test.describe("question feed - mystery-card glyph (WTC rebuild, retires the whatsthat-mark.svg mascot)", () => {
  test("the hero reveal overlay renders the shared '?' glyph as token-coloured text before the card reveals", async ({
    page,
    network,
  }) => {
    // A deliberate route delay holds the pre-reveal moment open long enough to assert against
    // reliably - against this suite's own fast local mock server, an undelayed route routinely
    // already resolves (and therefore un-mounts the overlay) before the assertion below runs.
    await loadWithRealImage(page, network, { width: 1280, height: 900 }, 1500);
    const overlay = page.getByTestId("question-feed-reveal-overlay");
    await expect(overlay).toBeVisible();
    const glyph = overlay.getByTestId("mystery-card-glyph");
    await expect(glyph).toHaveText("?");
  });

  test("the candidate grid's mystery-card placeholders carry the SAME shared glyph component as the hero card", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 1280, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const glyph = page
      .locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
      .getByTestId("mystery-card-glyph");
    await expect(glyph).toHaveText("?");
  });

  test("every quiz action button reads its colour LIVE from the --text token, not a hardcoded gold/navy literal", async ({
    page,
    network,
  }) => {
    // WD1 retires QUIZ_BUTTON_GOLD/_NAVY entirely - `.btn.secondary`'s colour now comes from
    // `var(--text)`. Deliberately NOT asserted against a literal rgb() here: `--bs-body-color`
    // (the `--text` fallback's own runtime source, see whatsthat.tsx's WtcTokenScope) is
    // ALREADY emitted by the current Superhero theme on master today (independent of whether
    // the in-flight Tokyo-11 branch has merged yet - confirmed live, #ebebeb pre-merge) - a
    // literal-rgb assertion would only ever be true post-merge. Proving the button's colour is
    // LIVE-DERIVED from the `--text` custom property (not a hardcoded literal baked into the
    // component) is the actually-portable assertion: change the token, the button changes too.
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await page.setViewportSize({ width: 1280, height: 900 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    const before = await page
      .getByTestId("question-feed-no-match")
      .evaluate((el) => window.getComputedStyle(el).color);
    expect(before).not.toBe("rgb(248, 212, 43)"); // the retired QUIZ_BUTTON_GOLD literal

    // Walks up from the button to the ancestor that DEFINES --text (WtcTokenScope, the page's
    // own token-bridge root - see whatsthat.tsx) and overrides it there via an inline style
    // (which always outranks a non-!important stylesheet rule for that same element/property),
    // then re-reads the button's colour - proving it's a live var() reference cascading down
    // from that scope, not a value baked into the component at build time.
    const after = await page
      .getByTestId("question-feed-no-match")
      .evaluate((btn) => {
        let el: HTMLElement | null = btn as HTMLElement;
        let definer: HTMLElement | null = null;
        while (el) {
          const own = window.getComputedStyle(el).getPropertyValue("--text");
          const parentOwn = el.parentElement
            ? window
                .getComputedStyle(el.parentElement)
                .getPropertyValue("--text")
            : "";
          if (own.trim() !== "" && own.trim() !== parentOwn.trim()) {
            definer = el;
            break;
          }
          el = el.parentElement;
        }
        if (definer == null) return null;
        definer.style.setProperty("--text", "rgb(1, 2, 3)");
        return window.getComputedStyle(btn).color;
      });
    expect(after).toBe("rgb(1, 2, 3)");
  });

  test("a selected Level 3 attribute chip reads --accent (purple), not the retired gold treatment", async ({
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
    const selectedColor = await selectedChip.evaluate(
      (el) => window.getComputedStyle(el).color
    );
    // --accent's Tokyo-11 fallback value (#bb9af7) - see whatsthat.tsx's WtcTokenScope.
    expect(selectedColor).toBe("rgb(187, 154, 247)");
    expect(selectedColor).not.toBe("rgb(18, 64, 99)"); // the retired QUIZ_BUTTON_NAVY literal
  });
});

// NEW coverage (rebuild task's TESTS requirement: "shape-b shortlist fallback"/ANNEX B) -
// shape b degrades to shape d (open-ended, "tricky one" framing) when the served item carries
// no candidates at all - the UI-only side of the `survivor_pks`/#433 dependency (the backend
// serve-time downgrade itself is out of this frontend task's scope, per ANNEX B).
test.describe("question feed - shape (d) open-ended fallback (ANNEX B)", () => {
  test("a zero-candidate identify_printing item renders the dashed 'tricky one' framing, not the neutral pick grid", async ({
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
              candidates: [],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 1,
              confirmable: 0,
              contested: 0,
              fresh: 1,
            },
          },
          { status: 200 }
        )
      ),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("question-feed-tier-badge")).toHaveClass(
      /hard/
    );
    await expect(page.getByText(/harder ones/i)).toBeVisible();
    // "None of these"/Skip still work in this degraded shape - the UI is agnostic to which
    // path satisfied the shortlist (ANNEX B).
    await expect(page.getByTestId("question-feed-no-match")).toBeVisible();
    await expect(page.getByTestId("question-feed-skip")).toBeVisible();
  });
});

// NEW coverage (rebuild task's TESTS requirement: "session counter increments") - WD6/owner
// ruling 2's quiet "N tagged this session" affordance.
test.describe("question feed - session counter (WD6, quiet reward affordance)", () => {
  test("the session counter increments after a real vote is cast, and is not persisted across a reload", async ({
    page,
    network,
  }) => {
    let feedFetchCount = 0;
    network.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return HttpResponse.json(
          {
            item: {
              type: "identify_printing",
              card: { ...cardDocument1, identifier: `card-${feedFetchCount}` },
              candidates: [printingCandidate1],
              tagConfidence: {},
            },
            remainingEstimate: {
              total: 2,
              confirmable: 0,
              contested: 0,
              fresh: 2,
            },
          },
          { status: 200 }
        );
      }),
      submitPrintingTagNoMatch,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const counter = page.getByTestId("question-feed-session-counter");
    await expect(counter).toContainText("0 tagged this session");

    await page.getByTestId("question-feed-no-match").click();
    await expect(counter).toContainText("1 tagged this session");

    // Not persisted (no localStorage) - a real reload resets it, matching "this session" only.
    await page.reload();
    await expect(
      page.getByTestId("question-feed-session-counter")
    ).toContainText("0 tagged this session");
  });
});
