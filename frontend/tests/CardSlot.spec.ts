import { expect } from "@playwright/test";

import { FaceSeparator, SelectedImageSeparator } from "@/common/constants";
import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
} from "@/common/test-constants";
import {
  cardbacksTwoResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsOneResult,
  searchResultsSixResults,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  changeQueries,
  expectDisplaySheetSlotState,
  expectDisplaySheetSlotToExist,
  expectDisplaySheetSlotToNotExist,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayCardbackGridSelector,
  openDisplayChangeQueryModal,
  openDisplaySlotContextMenu,
  openDisplaySlotMenu,
} from "./test-utils";

// Parity wave 3 (2026-07-24, issue #272) - un-skipped and ported onto the unified `/editor` page.
//
// Dropped, not ported (10 of the classic file's 25 tests):
// - "switching to the next/previous image in a CardSlot" + "switching images...wraps around" (3
//   tests) - the classic grid's inline ❯/❮ cycling arrows have no equivalent anywhere on the
//   unified page. Per-slot image picking now goes entirely through the rail's own Select Version
//   section (SelectVersionSection.spec.ts) - a browse-and-click surface with no "next/previous"
//   concept (let alone wrap-around) to port this specific behavior onto.
// - "selecting an image in a CardSlot via the grid selector" - investigated, left dropped, not
//   silently weakened: this test's real payload is docs/features/card-dom-api.md's contract (the
//   `data-card-*` attributes + `mpc:card-selected` event getCardDataAttributes/
//   getCardSelectedEventDetail, common/cardDom.ts, produce). Confirmed by grep
//   (src/common/cardDom.ts's own callers): Card.tsx, CardSlot.tsx, and CardDetailedViewModal.tsx
//   all wire it - PagePreview.tsx (the unified page's own sheet-slot renderer) does not, at all.
//   This is a genuine, undocumented product gap (the DOM API contract is silently unimplemented
//   for the primary display of a project's cards on /editor post-swap), not something a test port
//   can paper over - flagged in this PR's own body for the owner, same as wave 1's CardImageStates
//   gap.
// - "double clicking the select button selects all slots for the same query" + both shift-click
//   multi-select tests + "the most recently selected card is tracked correctly" (4 tests) - bulk
//   multi-select has no unified-page equivalent (issue #272 item 6, still not built - the same gap
//   SelectedImagesRibbon.spec.ts is parked against, not ported, in every prior wave).
// - requested-printing badge "shows the plain style..." / "switches to the degraded style..." (2
//   tests) - already covered verbatim by DisplayPage.spec.ts's own two badge tests, against the
//   identical shared RequestedPrintingBadge component mounted in the rail header (the sheet slot
//   itself never renders this badge - PagePreviewSlotContent carries no such field at all).
//   Porting again here would just duplicate coverage, same precedent as wave 2's
//   DeckbuilderConfirmAffordance.spec.ts drop. The third badge test (the "absent" case) is NOT
//   covered elsewhere and is ported below.
// - "changing a card slot's query" - NOT counted in the 10 above; it's ported below, but note its
//   assertions are near-identical to ChangeQueryModal.spec.ts's own "change one card's query"
//   (wave 2) - kept here (not dropped) since this file's own describe block is the more natural
//   home for basic query-mutation coverage and the duplication is cheap, unlike the badge case
//   above which duplicates two entire fixture sets.
//
// Ported (15 tests): every remaining test retargets the classic `front-slot`/`back-slot`/
// `common-cardback`/3-dot-dropdown testids onto the sheet's own `page-preview-slot` +
// `page-preview-slot-menu-cue` (openDisplaySlotMenu, test-utils.ts - the sheet's own visible
// "..." menu cue is the direct equivalent of the classic 3-dot button, both open the identical
// `card-slot-context-menu`) / right-click (openDisplaySlotContextMenu) / the cardback picker
// (openDisplayCardbackGridSelector, wave 3's own GridSelectorModal.spec.ts port).
test.describe("CardSlot", () => {
  test("deleting a CardSlot", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

    const menu = await openDisplaySlotMenu(page, 1);
    await menu.getByText("Delete").click();

    await expectDisplaySheetSlotToNotExist(page, 1);
  });

  test("deleting multiple CardSlots", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `3x my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectDisplaySheetSlotToExist(page, 1);
    await expectDisplaySheetSlotToExist(page, 2);
    await expectDisplaySheetSlotToExist(page, 3);

    let menu = await openDisplaySlotMenu(page, 1);
    await menu.getByText("Delete").click();
    menu = await openDisplaySlotMenu(page, 2);
    await menu.getByText("Delete").click();

    await expectDisplaySheetSlotToExist(page, 1);
    await expectDisplaySheetSlotToNotExist(page, 2);
    await expectDisplaySheetSlotToNotExist(page, 3);
  });

  test("duplicating a CardSlot", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
    await expectDisplaySheetSlotToNotExist(page, 2);

    const menu = await openDisplaySlotMenu(page, 1);
    await menu.getByText("Duplicate").click();

    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
    await expectDisplaySheetSlotState(page, 2, "front", cardDocument1.name);
  });

  test("duplicating a CardSlot inserts the copy immediately after the original", async ({
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
      `query 1${SelectedImageSeparator}${cardDocument1.identifier}\nquery 2${SelectedImageSeparator}${cardDocument2.identifier}`
    );
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
    await expectDisplaySheetSlotState(page, 2, "front", cardDocument2.name);

    const menu = await openDisplaySlotMenu(page, 1);
    await menu.getByText("Duplicate").click();

    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
    await expectDisplaySheetSlotState(page, 2, "front", cardDocument1.name);
    await expectDisplaySheetSlotState(page, 3, "front", cardDocument2.name);
  });

  test("CardSlot uses cardbacks as search results for backs with no search query", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoResults,
      sourceDocumentsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(page, "my search query");
    await expectDisplaySheetSlotState(page, 1, "back", cardDocument1.name);
  });

  test("CardSlot defaults to project cardback for backs with no search query", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoResults,
      sourceDocumentsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // Import a front-only member first - DisplayPage.tsx's own `isProjectEmpty` early-return
    // means the toolbar/rail/Cardback button don't exist at all until a member does, unlike the
    // classic grid's always-visible right-panel swatch (which this test used to set the
    // cardback via BEFORE ever importing anything).
    await importTextOnEditorLanding(page, FaceSeparator);
    await expectDisplaySheetSlotState(page, 1, "back", cardDocument1.name);

    // Change the project cardback via the picker.
    const gridSelector = await openDisplayCardbackGridSelector(page);
    await gridSelector
      .locator(`[data-card-identifier="${cardDocument2.identifier}"]`)
      .click();

    await expectDisplaySheetSlotState(page, 1, "back", cardDocument2.name);
  });

  test("changing a card slot's query", async ({ page, network }) => {
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
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

    await openDisplayChangeQueryModal(page, 1);
    await changeQueries(page, "query 2");
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument2.name);
  });

  test("clearing a card slot's query", async ({ page, network }) => {
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
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

    await openDisplayChangeQueryModal(page, 1);
    await changeQueries(page, "");

    // The member survives with an empty query - PagePreview falls back to "Slot 1" and renders
    // no <img> at all (DisplayPage.tsx's own `name: cardDocument?.name ?? "Slot N"` fallback) -
    // the sheet's equivalent of the classic grid's undefined-name assertion.
    await expectDisplaySheetSlotToExist(page, 1);
    await expect(
      page.getByTestId("page-preview-slot").nth(0).locator("img")
    ).toHaveCount(0);
  });

  test("changing a card slot's query doesn't affect a different slot", async ({
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
      `query 1${SelectedImageSeparator}${cardDocument1.identifier}\nquery 2${SelectedImageSeparator}${cardDocument2.identifier}`
    );
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
    await expectDisplaySheetSlotState(page, 2, "front", cardDocument2.name);

    await openDisplayChangeQueryModal(page, 1);
    await changeQueries(page, "query 3");

    await expectDisplaySheetSlotState(page, 1, "front", cardDocument3.name);
    await expectDisplaySheetSlotState(page, 2, "front", cardDocument2.name);
  });

  test("CardSlot automatically selects the first search result", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(page, "my search query");

    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
  });

  test("CardSlot automatically deselects invalid image then selects the first search result", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // Import with an invalid identifier (cardDocument2 is not in search results)
    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument2.identifier}`
    );

    // Should automatically deselect the invalid image and select the first result
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
  });

  test.describe("right-click context menu (Proposal C part (a))", () => {
    test("right-clicking a CardSlot opens the same actions as the 3-dot dropdown, positioned at the cursor", async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsThreeResults,
        sourceDocumentsOneResult,
        searchResultsThreeResults,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      await importTextOnEditorLanding(
        page,
        `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
      );
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

      const contextMenu = await openDisplaySlotContextMenu(page, 1);
      await expect(contextMenu.getByText("Change Query")).toBeVisible();
      await expect(contextMenu.getByText("Duplicate")).toBeVisible();
      await expect(contextMenu.getByText("Delete")).toBeVisible();
    });

    test("selecting Delete from the context menu deletes the slot, matching the 3-dot dropdown's own Delete", async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsThreeResults,
        sourceDocumentsOneResult,
        searchResultsThreeResults,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      await importTextOnEditorLanding(
        page,
        `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
      );
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

      const contextMenu = await openDisplaySlotContextMenu(page, 1);
      await contextMenu.getByText("Delete").click();

      await expectDisplaySheetSlotToNotExist(page, 1);
    });

    test("clicking outside the context menu closes it without triggering an action", async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsThreeResults,
        sourceDocumentsOneResult,
        searchResultsThreeResults,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      await importTextOnEditorLanding(
        page,
        `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
      );
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

      const contextMenu = await openDisplaySlotContextMenu(page, 1);
      await expect(contextMenu).toBeVisible();

      // A plain left-click well away from the menu and the slot itself.
      await page.mouse.click(5, 5);

      await expect(
        page.getByTestId("card-slot-context-menu")
      ).not.toBeVisible();
      await expectDisplaySheetSlotToExist(page, 1);
    });
  });

  // Item (c) of the frontend-polish package - the same RequestedPrintingBadge.tsx component
  // DisplayPage.tsx's rail header shows (see its own equivalent tests in DisplayPage.spec.ts).
  // Only the "absent" case is ported here - see this file's own module comment for why the
  // plain/degraded cases are dropped as duplicate coverage.
  test.describe("requested-printing badge", () => {
    test("shows nothing when the slot's query names no specific printing", async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsThreeResults,
        sourceDocumentsOneResult,
        searchResultsThreeResults,
        tagConsensusTwoUnresolvedTags,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);

      await importTextOnEditorLanding(page, "my search query");
      await page.getByTestId("page-preview-slot").first().click();

      await expect(page.getByTestId("requested-printing-badge")).toHaveCount(0);
    });
  });
});
