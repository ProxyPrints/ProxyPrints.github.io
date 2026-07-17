import { expect } from "@playwright/test";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
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
