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
  expectCardGridSlotStates,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`); the classic grid `ProjectEditor` this file's own setup
// depends on (via testids/interaction patterns like `front-slot`/`back-slot`/`common-cardback`/
// the "Add Cards" right-panel dropdown/the classic "Print!" tab, or a component with no rendered
// equivalent on the new page yet - see issue #272's own tracked parity gaps) is fully unrouted,
// not just delisted from the nav. Skipped here rather than deleted (component files themselves
// are untouched, per this swap's own scope) or silently left red - porting this coverage to
// DisplayPage's DOM is real, non-mechanical work tracked against #272, not done as part of the
// route swap itself (the owner's directive was to proceed with the swap regardless of the
// checklist's open items).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Proposal H switchover (2026-07-23): tests classic /editor-only UI, now unrouted - see issue #272"
  );
});

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

      await expectCardGridSlotStates(
        page,
        [
          {
            slot: 1,
            name: cardDocument1.name,
            selectedImage: 1,
            totalImages: 1,
          },
        ],
        [
          {
            slot: 1,
            name: cardDocument2.name,
            selectedImage: 1,
            totalImages: 2,
          },
        ]
      );

      // Click on the card to open detailed view
      await page.getByAltText(cardDocument1.name).click();
      await expect(page.getByText("Card Details")).toBeVisible();

      // Fill in the quantity
      const quantityInput = page.getByAltText(
        "Quantity of card to add to project"
      );
      await quantityInput.clear();
      await quantityInput.fill(quantity.toString());

      // Add to project
      await page.getByRole("button", { name: "Add to Project" }).click();

      // Close the detailed view
      await page.getByTestId("detailed-view").getByLabel("Close").click();

      // Verify that the cards were added (original slot + new slots)
      const expectedFronts = [
        {
          slot: 1,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        },
      ];
      const expectedBacks = [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ];

      for (let i = 0; i < quantity; i++) {
        expectedFronts.push({
          slot: i + 2,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        });
        expectedBacks.push({
          slot: i + 2,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        });
      }

      await expectCardGridSlotStates(page, expectedFronts, expectedBacks);
    });
  }
});
