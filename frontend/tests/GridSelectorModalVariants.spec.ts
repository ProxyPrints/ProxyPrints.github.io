import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType, PrintingTagStatus, SourceType } from "@/common/schema_types";
import {
  cardDocument1,
  cardDocument2,
  localBackendURL,
  sourceDocument1,
} from "@/common/test-constants";
import {
  cardbacksThreeResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayCardbackGridSelector,
} from "./test-utils";

// Parity wave 3 (2026-07-24, issue #272) - un-skipped and ported onto the unified `/editor` page,
// same retarget as GridSelectorModal.spec.ts (see that file's own header comment and
// openDisplayCardbackGridSelector's comment in test-utils.ts for the full rationale): the only
// surviving GridSelectorModal.tsx mount post-route-swap is CardbackToolbarButton's project-wide
// cardback picker, reachable only once the project is non-empty - every test below runs one plain
// import first purely to populate the project before the right rail/gear button/Cardback trigger
// exist at all (DisplayPage.tsx's own `isProjectEmpty` early-return).
const threeCardHandlers = [
  cardDocumentsThreeResults,
  cardbacksThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

test.describe("GridSelectorModal - keyboard navigation", () => {
  test("Tab reaches a result card and Enter selects it, same as a click would (cardback flow round: the modal now stays open with the apply/default prompt)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    const gridSelector = await openDisplayCardbackGridSelector(page);

    const targetCard = gridSelector.locator(
      `[data-card-identifier="${cardDocument2.identifier}"]`
    );
    await targetCard.focus();
    await expect(targetCard).toBeFocused();
    await page.keyboard.press("Enter");

    // Cardback flow round (SPEC-cardback-pdfwait.md §C.2) - the toolbar entry's pick no longer
    // auto-closes the modal (the apply-all/set-default prompt renders inline in this SAME modal
    // instead), so a keyboard-driven select is confirmed the same way a click-driven one now is.
    await expect(
      gridSelector.getByTestId("cardback-apply-prompt")
    ).toBeVisible();
  });
});

test.describe("GridSelectorModal - large grid keyboard-focus perf", () => {
  test("keyboard-focusing a card in a 150-card grid completes quickly", async ({
    page,
    network,
  }) => {
    const CARD_COUNT = 150;
    const identifiers = Array.from(
      { length: CARD_COUNT },
      (_, i) => `synthetic-card-${i}`
    );
    const results: Record<string, unknown> = {};
    identifiers.forEach((identifier, i) => {
      results[identifier] = {
        identifier,
        cardType: CardType.Card,
        name: `Synthetic Card ${i}`,
        priority: 0,
        source: sourceDocument1.key,
        sourceName: sourceDocument1.name,
        sourceId: sourceDocument1.pk,
        sourceVerbose: sourceDocument1.name,
        sourceType: SourceType.GoogleDrive,
        dpi: 300,
        searchq: "synthetic",
        extension: "png",
        dateCreated: "1st January, 2000",
        dateModified: "1st January, 2000",
        size: 1_000_000,
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
        language: "EN",
        tags: [],
        printingTagStatus: PrintingTagStatus.Unresolved,
      };
    });

    network.use(
      http.post(`${localBackendURL}/2/cards/`, () =>
        HttpResponse.json({ results }, { status: 200 })
      ),
      // The cardback picker's own endpoint - simpler than the classic cluster's
      // `3/editorSearch/` hash-key wrapping, since `2/cardbacks` returns the identifier list
      // directly.
      http.post(`${localBackendURL}/2/cardbacks`, () =>
        HttpResponse.json({ cardbacks: identifiers }, { status: 200 })
      ),
      // A plain, cheap import used only to populate the project (see this file's own module
      // comment) - one throwaway result, unrelated to the 150-card cardback set above.
      http.post(`${localBackendURL}/3/editorSearch/`, () =>
        HttpResponse.json(
          {
            results: {
              [computeSearchQueryHashKey({
                query: "my search query",
                cardType: CardType.Card,
              })]: [cardDocument1.identifier],
            },
          },
          { status: 200 }
        )
      ),
      sourceDocumentsOneResult,
      ...defaultHandlers
    );

    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    const start = Date.now();
    const gridSelector = await openDisplayCardbackGridSelector(page);

    // Index 15 is within CardsGroupedTogether's `initialVisible={visualIndex < 20}` window,
    // so this doesn't depend on fighting the grid's own scroll-triggered virtualization -
    // the point is measuring keyboard-focus responsiveness against a 150-card DOM, not
    // against the virtualization mechanism itself.
    const targetCard = gridSelector.locator(
      '[data-card-identifier="synthetic-card-15"]'
    );
    await targetCard.focus();
    await expect(targetCard).toBeFocused();
    const elapsedMs = Date.now() - start;

    // Generous bound - this isn't a tight perf budget, just a regression guard against the
    // keyboard-focus change accidentally making a large grid noticeably janky (e.g. an
    // O(n) re-render triggered per focus event). Covers opening the picker, rendering 150
    // cards, and focusing one - the timer starts AFTER the throwaway import above (unlike the
    // classic cluster's version) so it measures the same "open a big grid, focus a card" cost
    // without folding in this port's own extra populate-the-project step.
    expect(elapsedMs).toBeLessThan(15_000);
  });
});

test.describe("GridSelectorModal - autofocus", () => {
  test("focuses the Filters toggle button (not a hidden input) when Jump to Version is collapsed", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    const gridSelector = await openDisplayCardbackGridSelector(page);

    // Jump to Version is collapsed by default (viewSettingsSlice's initial state) - the old
    // code tried to focus its input regardless, which silently failed since a collapsed
    // (but still-mounted) input can't actually receive focus in a real browser.
    await expect(
      gridSelector.getByRole("button", { name: /Filters/ })
    ).toBeFocused();
  });

  test("focuses the actual Jump to Version input once that section is genuinely visible", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    let gridSelector = await openDisplayCardbackGridSelector(page);
    await gridSelector
      .getByRole("heading", { name: "Jump to Version" })
      .click();
    // Two "Close" buttons exist (the header's icon-only X and the footer's text button) -
    // the footer one is unambiguous via its visible text content.
    await gridSelector
      .getByRole("button", { name: "Close", exact: true })
      .last()
      .click();
    await expect(gridSelector).not.toBeVisible();

    // Reopen - jumpToVersionVisible is Redux state, not reset by closing the modal, so this
    // second open should find the section already expanded and genuinely focus the input.
    gridSelector = await openDisplayCardbackGridSelector(page);
    await expect(
      gridSelector.getByPlaceholder("1", { exact: true })
    ).toBeFocused();
  });
});

test.describe("GridSelectorModal - mobile filters default", () => {
  test("at a mobile viewport, filters are hidden by default and results get the full width", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    const gridSelector = await openDisplayCardbackGridSelector(page);

    await expect(gridSelector.getByText("Group By")).not.toBeVisible();
    await expect(
      gridSelector.getByRole("button", { name: /Filters/ })
    ).toBeVisible();

    const firstCard = gridSelector
      .locator(`[data-card-identifier="${cardDocument1.identifier}"]`)
      .first();
    const cardBox = await firstCard.boundingBox();
    expect(cardBox).not.toBeNull();
    // With filters hidden, a result card should span most of the 390px viewport width, not
    // be squeezed into a ~6-column-of-12 half-screen split.
    expect(cardBox!.width).toBeGreaterThan(150);
  });

  test("at desktop width, filters remain visible by default (unaffected by the mobile change)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    // default chromium project viewport (800x600) is above the sm breakpoint
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    const gridSelector = await openDisplayCardbackGridSelector(page);

    await expect(gridSelector.getByText("Group By")).toBeVisible();
  });
});
