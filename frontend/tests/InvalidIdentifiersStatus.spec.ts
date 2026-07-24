import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  cardDocument1,
  cardDocument2,
  cardDocument5,
} from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsOneResult,
  searchResultsSixResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  changeQueries,
  expectDisplaySheetSlotState,
  expectDisplaySheetSlotToExist,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayChangeQueryModal,
} from "./test-utils";

// Parity wave 2 (2026-07-23, issue #272): ported onto the unified `/editor` page.
// InvalidIdentifiersStatus.tsx itself is unchanged and unforked - DisplayPage.tsx's own comment
// (issue #267 D13): "mounted unmodified in both the populated-state action bar and the
// empty-project DeckInputLanding" - only the RIGHT-RAIL Status row (a separate, still-unbuilt
// placement - issue #272 item 2's own remaining scope) is missing; the landing/search-bar half
// this file exercises already works today.
test.describe("InvalidIdentifiersStatus tests", () => {
  const testCases = [
    {
      query: `my search query${SelectedImageSeparator}${cardDocument1.identifier}`,
      problematicImageCount: 0,
    },
    {
      query: `my search query${SelectedImageSeparator}garbage`,
      problematicImageCount: 1,
    },
    {
      query: `2 my search query${SelectedImageSeparator}garbage`,
      problematicImageCount: 2,
    },
    {
      query: `my search query${SelectedImageSeparator}${cardDocument1.identifier}\nmy search query${SelectedImageSeparator}garbage`,
      problematicImageCount: 1,
    },
  ];

  for (const { query, problematicImageCount } of testCases) {
    test(`invalid identifiers status is displayed appropriately (${query}, ${problematicImageCount})`, async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsOneResult,
        sourceDocumentsOneResult,
        searchResultsOneResult,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      await importTextOnEditorLanding(page, query);
      await expectDisplaySheetSlotToExist(page, 1);
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

      if (problematicImageCount > 0) {
        const warningText = await page
          .getByText("Your project specified", { exact: false })
          .textContent();
        expect(warningText).toBe(
          `Your project specified ${problematicImageCount} card version${
            problematicImageCount != 1 ? "s" : ""
          } which couldn't be found.`
        );
      } else {
        await expect(
          page.getByText("Your project specified", { exact: false })
        ).not.toBeVisible();
      }
    });
  }

  test("invalid identifiers status is not displayed when changing query", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `query 1${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectDisplaySheetSlotToExist(page, 1);
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

    // change query - type in "query 2"
    await openDisplayChangeQueryModal(page, 1);
    await changeQueries(page, "query 2");
    // expect the slot to have changed from card 1 to card 2
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument2.name);

    // expect the invalid card warning to *not* have been raised
    await expect(
      page.getByText("Your project specified", { exact: false })
    ).not.toBeVisible();
  });
});
