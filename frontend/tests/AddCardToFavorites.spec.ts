import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectCardGridSlotState,
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

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

const closeDetailedView = async (page: any) => {
  await page.getByTestId("detailed-view").getByLabel("Close").click();
  await expect(page.getByText("Card Details")).not.toBeVisible();
};

test.describe("AddCardToFavorites tests", () => {
  test("renders Add to Favorites button when card is not a favorite", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await openDetailedView(page, cardDocument1.name);

    const button = page.getByRole("button", { name: /Add to Favorites/i });
    await expect(button).toBeVisible();
    await expect(button).toHaveClass(/btn-outline-info/);
  });

  test("adding card to favorites", async ({ page, network }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await openDetailedView(page, cardDocument1.name);

    // Initially shows "Add to Favorites"
    const button = page.getByRole("button", { name: /Add to Favorites/i });
    await expect(button).toBeVisible();

    // Click the button
    await button.click();

    // Should update to show "Remove from Favorites"
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();

    // Should show notification
    await expect(page.getByText("Added to Favorites")).toBeVisible();
    await expect(
      page.getByText(`Added ${cardDocument1.name} to your favorites!`)
    ).toBeVisible();

    // Button should have info variant (not outline)
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toHaveClass(/btn-info/);
  });

  test("removing card from favorites", async ({ page, network }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await openDetailedView(page, cardDocument1.name);

    // First add to favorites
    const addButton = page.getByRole("button", { name: /Add to Favorites/i });
    await addButton.click();
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();

    // Now remove from favorites
    const removeButton = page.getByRole("button", {
      name: /Remove from Favorites/i,
    });
    await removeButton.click();

    // Should update to show "Add to Favorites"
    await expect(
      page.getByRole("button", { name: /Add to Favorites/i })
    ).toBeVisible();

    // Should show notification
    await expect(page.getByText("Removed from Favorites")).toBeVisible();
    await expect(
      page.getByText(`Removed ${cardDocument1.name} from your favorites.`)
    ).toBeVisible();

    // Button should have outline-info variant
    await expect(
      page.getByRole("button", { name: /Add to Favorites/i })
    ).toHaveClass(/btn-outline-info/);
  });

  test("toggling favorite status multiple times", async ({ page, network }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await openDetailedView(page, cardDocument1.name);

    // First click: Add to favorites
    await page.getByRole("button", { name: /Add to Favorites/i }).click();
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();

    // Second click: Remove from favorites
    await page.getByRole("button", { name: /Remove from Favorites/i }).click();
    await expect(
      page.getByRole("button", { name: /Add to Favorites/i })
    ).toBeVisible();

    // Third click: Add to favorites again
    await page.getByRole("button", { name: /Add to Favorites/i }).click();
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();
  });

  test("favorites state persists after closing and reopening detailed view", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    // Open detailed view and add to favorites
    await openDetailedView(page, cardDocument1.name);
    await page.getByRole("button", { name: /Add to Favorites/i }).click();
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();

    // Close the detailed view
    await closeDetailedView(page);

    // Reopen the detailed view
    await openDetailedView(page, cardDocument1.name);

    // Should still show as a favorite
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Remove from Favorites/i })
    ).toHaveClass(/btn-info/);
  });
});
