import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1, cardDocument2 } from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsOneResultCorrectSearchq,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  closeDetailedView,
  expectDisplaySheetSlotStates,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDetailedView,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// AddCardToProjectForm is unforked and mounted the same way the rest of the card-detail modal
// cluster reaches it (Browse mode - see openDetailedView's own module comment, test-utils.ts).
// Per-slot assertions ported via expectDisplaySheetSlotStates - see that helper's own comment for
// why dropping the selectedImage/totalImages numeric checks doesn't weaken what this test actually
// verifies (the right card landing in the right slot, the right number of times).

test.describe("AddCardToProjectForm tests", () => {
  for (const quantity of [1, 2, 3]) {
    test(`adding ${quantity} card(s) to project through detailed view`, async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsThreeResults,
        cardbacksTwoOtherResults,
        sourceDocumentsOneResult,
        searchResultsOneResultCorrectSearchq,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      // Add initial card to project
      await importTextOnEditorLanding(
        page,
        `card one${SelectedImageSeparator}${cardDocument1.identifier}`
      );

      await expectDisplaySheetSlotStates(
        page,
        [{ slot: 1, name: cardDocument1.name }],
        [{ slot: 1, name: cardDocument2.name }]
      );

      // Open the detail view (via Browse mode) for the same card already in the project
      await openDetailedView(page, "card one", cardDocument1.identifier);

      // Fill in the quantity - scoped to the modal itself, since Browse mode's own catalog tile
      // (still in the DOM behind the modal) mounts its own, unforked AddCardToProjectForm too
      // (CatalogBrowseResults.tsx's own "+Add" affordance) - a bare page-wide locator collides
      // with both.
      const detailedView = page.getByTestId("detailed-view");
      const quantityInput = detailedView.getByAltText(
        "Quantity of card to add to project"
      );
      await quantityInput.clear();
      await quantityInput.fill(quantity.toString());

      // Add to project
      await detailedView
        .getByRole("button", { name: "Add to Project" })
        .click();

      // Close the detailed view
      await closeDetailedView(page);

      // openDetailedView's own Browse-mode route (test-utils.ts) left the shared Add/Browse
      // toggle on Browse - the center region renders catalog results, not the print-sheet stack,
      // while that's active (DisplayPage.tsx's own module comment), so the sheet assertions below
      // need Add mode back first.
      await page.getByTestId("display-search-mode-add").click();

      // Verify that the cards were added (original slot + new slots)
      const expectedFronts = [{ slot: 1, name: cardDocument1.name }];
      const expectedBacks = [{ slot: 1, name: cardDocument2.name }];

      for (let i = 0; i < quantity; i++) {
        expectedFronts.push({ slot: i + 2, name: cardDocument1.name });
        expectedBacks.push({ slot: i + 2, name: cardDocument2.name });
      }

      await expectDisplaySheetSlotStates(page, expectedFronts, expectedBacks);
    });
  }
});
