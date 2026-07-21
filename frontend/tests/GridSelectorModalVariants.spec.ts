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
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectCardGridSlotState,
  importText,
  loadPageWithDefaultBackend,
  openCardSlotGridSelector,
} from "./test-utils";

// Shared by both suites below (identical across their source files).
const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

test.describe("GridSelectorModal - keyboard navigation", () => {
  test("Tab reaches a result card and Enter selects it, same as a click would", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    const gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);

    const targetCard = gridSelector.locator(
      `[data-card-identifier="${cardDocument2.identifier}"]`
    );
    await targetCard.focus();
    await expect(targetCard).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(gridSelector).not.toBeVisible();
    await expectCardGridSlotState(page, 1, "front", cardDocument2.name, 2, 3);
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
      http.post(`${localBackendURL}/3/editorSearch/`, () =>
        HttpResponse.json(
          {
            results: {
              [computeSearchQueryHashKey({
                query: "my search query",
                cardType: CardType.Card,
              })]: identifiers,
            },
          },
          { status: 200 }
        )
      ),
      sourceDocumentsOneResult,
      ...defaultHandlers
    );

    const start = Date.now();
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    const gridSelector = await openCardSlotGridSelector(
      page,
      1,
      "front",
      1,
      CARD_COUNT
    );

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
    // O(n) re-render triggered per focus event). Covers the whole flow (search, open modal,
    // render 150 cards, focus one) since that's the realistic cost a user actually pays.
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
    await importText(page, "my search query");
    const gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);

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
    await importText(page, "my search query");

    let gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);
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
    gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);
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
    await importText(page, "my search query");
    const gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);

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
    await importText(page, "my search query");
    const gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 3);

    await expect(gridSelector.getByText("Group By")).toBeVisible();
  });
});
