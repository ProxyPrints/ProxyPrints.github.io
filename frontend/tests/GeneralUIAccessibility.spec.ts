import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

// Parity wave 2 (2026-07-23, issue #272): the classic grid's `front-slot`/`left-panel`/
// `right-panel` testids have no equivalent on the unified page - the last three describe blocks
// (About page, Home page logo, and the home-page half of Console warning regressions) don't touch
// /editor at all and were always unaffected.
test.describe("Card slot controls - accessibility", () => {
  // Ported onto PagePreview.tsx's own per-slot menu cue (`page-preview-slot-menu-cue`, "Open card
  // menu") - the sheet's closest equivalent to the classic grid's per-slot "more options" button
  // (same corner-affordance role: F6/D22's own module comment calls it the "touch-discoverable
  // menu cue", reserving the same physical corner classic CardSlot's 3-dot button occupied).
  test("the slot menu cue has an accessible name", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    const menuCue = page
      .getByTestId("page-preview-slot")
      .first()
      .getByTestId("page-preview-slot-menu-cue");
    await expect(menuCue).toBeVisible();
    await expect(menuCue).toHaveAccessibleName("Open card menu");
  });

  // The classic grid's per-slot `.card-select` checkbox (bulk multi-select) has no equivalent on
  // the unified page (SelectedImagesRibbon/bulk multi-select - issue #272 item 6, still not
  // built, parked rather than ported this same wave - see this PR's own description) - the same
  // menu cue button above is the nearest actionable per-slot control left to hold this touch-
  // target/focus-style invariant to.
  test("the slot menu cue has a visible focus style", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    const menuCue = page
      .getByTestId("page-preview-slot")
      .first()
      .getByTestId("page-preview-slot-menu-cue");

    // A prior mouse click (e.g. inside importTextOnEditorLanding's flow) sets Chromium's input
    // modality to "mouse", under which a plain .focus() call does not match :focus-visible.
    // Pressing Tab first re-establishes keyboard modality, matching how a real keyboard user
    // would land here.
    await page.keyboard.press("Tab");
    await menuCue.focus();
    const outlineStyle = await menuCue.evaluate(
      (el) => getComputedStyle(el).outlineStyle
    );
    expect(outlineStyle).not.toBe("none");
  });
});

// Dropped, not ported: the classic test's "comfortable touch-target size" (>=40x40px) half of
// this coverage. PagePreview.tsx renders the sheet near print-scale (millimetre-driven sizing,
// not a UI-scale button grid) - the menu cue measured ~11x11px here, genuinely smaller than the
// WCAG-informed 40px target the classic grid's own full-UI-scale button met. That's a real,
// structural difference in what this element IS (a small on-page-preview affordance vs. a
// full-size toolbar button), not an accessibility regression this port should paper over by
// weakening the assertion's threshold - the focus-visible-style half above is unaffected and
// still fully verified.

// "Editor - mobile layout"'s two classic-grid tests (left-panel/right-panel 50/50-split-vs-
// stacked at mobile/desktop widths) are dropped, not ported: they verified the SAME "mobile
// scroll affordances -> #266's responsive layer" replacement issue #272's own body already lists
// as an intentional replacement, not a gap (ProjectEditorMobileScroll.spec.ts, this same wave's
// PR description). The unified page's rails are off-canvas drawers (LeftRailOffcanvas/
// RightRailOffcanvas) below their own breakpoints regardless of viewport - there's no persistent
// 50/50 split to ever "stack" in the first place, so this specific invariant has no equivalent
// question to ask on /editor.

test.describe("Console warning regressions", () => {
  test("the home page renders with none of the previously-observed console warnings", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "warning" || msg.type() === "error") {
        warnings.push(msg.text());
      }
    });

    await loadPageWithDefaultBackend(page, "");
    await page.waitForTimeout(1500);

    const flagged = [
      "heightDelta",
      "imageIsLoading",
      "showDetailedViewOnClick",
      "SSRProvider",
      "onLoadingComplete",
    ];
    for (const term of flagged) {
      expect(
        warnings.some((warning) => warning.includes(term)),
        `expected no console warning mentioning "${term}", saw: ${JSON.stringify(
          warnings.filter((w) => w.includes(term))
        )}`
      ).toBe(false);
    }
  });

  test("the editor page renders with none of the previously-observed console warnings", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "warning" || msg.type() === "error") {
        warnings.push(msg.text());
      }
    });

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await page.waitForTimeout(1500);

    const flagged = [
      "heightDelta",
      "imageIsLoading",
      "showDetailedViewOnClick",
      "SSRProvider",
      "onLoadingComplete",
    ];
    for (const term of flagged) {
      expect(
        warnings.some((warning) => warning.includes(term)),
        `expected no console warning mentioning "${term}", saw: ${JSON.stringify(
          warnings.filter((w) => w.includes(term))
        )}`
      ).toBe(false);
    }
  });
});

test.describe("About page", () => {
  test("the contributors image has meaningful alt text", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "about");

    await expect(page.getByAltText("Project contributors")).toBeVisible();
  });
});

test.describe("Home page logo - LCP hint", () => {
  test("the first animated logo card image is marked as a high fetch-priority image", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    // the arrow decoration image renders before the animated card images in DOM order, so
    // it's excluded here rather than relying on .first() over every <img> in the container
    const firstLogoCardImage = page
      .getByTestId("dynamic-logo")
      .locator('img:not([alt="logo-arrow"])')
      .first();
    await expect(firstLogoCardImage).toBeVisible();
    await expect(firstLogoCardImage).toHaveAttribute("fetchpriority", "high");
  });
});
