import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType, PrintingTagStatus, SourceType } from "@/common/schema_types";
import {
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
