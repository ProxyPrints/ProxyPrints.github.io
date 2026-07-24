import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
  cardDocument4,
  cardDocument5,
} from "@/common/test-constants";
import {
  cardbacksOneOtherResult,
  cardDocumentsSixResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  dfcPairsMatchingCards1And4,
  searchResultsForDFCMatchedCards1And4,
  searchResultsSixResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  changeQueries,
  enableDisplayFuzzySearch,
  ensureDisplayFace,
  expectDisplaySheetSlotState,
  expectDisplaySheetSlotToExist,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayChangeQueryModal,
} from "./test-utils";

// Parity wave 2 (2026-07-23, issue #272): ported onto the unified `/editor` page. The classic
// grid opened this modal by clicking a slot's own query text; ChangeQueryModal.tsx itself is
// unchanged (still globally mounted, Modals.tsx) - only how it's reached differs, via the shared
// CardSlotContextMenu's "Change Query" action (openDisplayChangeQueryModal, test-utils.ts).
//
// Dropped, not ported: the 3 multi-slot-selection tests ("plural text when multiple front slots
// are selected", "updates all fronts and backs for a multi-slot selection", "not shown when any
// one of the selected slots already has the DFC back query") depended on the classic grid's
// checkbox multi-select + SelectedImagesRibbon's own "Change Query" trigger - bulk multi-select
// has no equivalent on the unified page (issue #272 item 6, still not built; SelectedImagesRibbon
// itself is parked, not ported, this same wave - see this PR's own description). The single-slot
// DFC prompt/submission/condition/fuzzy-search/checkbox-reset coverage below is unaffected and
// fully proves the same underlying logic.
test.describe("ChangeQueryModal tests", () => {
  test("change one card's query", async ({ page, network }) => {
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
    const modal = await openDisplayChangeQueryModal(page, 1);
    await expect(
      modal.getByLabel("change-selected-image-queries-text")
    ).toHaveValue("query 1");
    await changeQueries(page, "query 2");

    // expect the slot to have changed from card 1 to card 2
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument2.name);
  });
});

const dfcHandlers = [
  cardDocumentsSixResults,
  cardbacksOneOtherResult,
  sourceDocumentsOneResult,
  searchResultsForDFCMatchedCards1And4,
  dfcPairsMatchingCards1And4,
  ...defaultHandlers,
] as const;

test.describe("ChangeQueryModal DFC pair tests", () => {
  test.describe("DFC prompt visibility", () => {
    test("DFC prompt not shown when query has no DFC match", async ({
      page,
      network,
    }) => {
      // defaultHandlers includes dfcPairsNoResults, so no DFC pairs are active
      network.use(
        cardDocumentsThreeResults,
        sourceDocumentsOneResult,
        searchResultsSixResults,
        ...defaultHandlers
      );
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "query 1");

      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("query 2");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).not.toBeVisible();
    });

    test("DFC prompt shown with correct singular text when one front slot is selected", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).toBeVisible();
      // Singular phrasing
      await expect(
        modal.getByText(/update the back of this slot to/i)
      ).toBeVisible();
      // DFC back query name is present in the prompt
      await expect(
        modal.getByText(new RegExp(cardDocument4.name, "i"))
      ).toBeVisible();
      // Checkbox label is singular
      await expect(modal.getByLabel("Update back")).toBeVisible();
      // Checkbox is unchecked by default
      await expect(modal.getByLabel("Update back")).not.toBeChecked();
    });
  });

  test.describe("submission behaviour", () => {
    test("submitting without the DFC checkbox only updates the front query", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument3.name);
      await expectDisplaySheetSlotState(page, 1, "back", cardDocument5.name);
      // expectDisplaySheetSlotState's own back-face check above leaves the sheet showing backs -
      // reset to fronts before right-clicking, since openDisplayChangeQueryModal's context menu
      // reads whichever face is currently displayed.
      await ensureDisplayFace(page, "front");

      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await expect(
        modal.getByText("matches a double-faced card pair")
      ).toBeVisible();
      // Leave checkbox unchecked and submit
      await page.getByLabel("change-selected-image-queries-submit").click();

      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
      // Back must remain unchanged
      await expectDisplaySheetSlotState(page, 1, "back", cardDocument5.name);
    });

    test("submitting with the DFC checkbox updates both front and back queries", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await modal.getByLabel("Update back").check();
      await page.getByLabel("change-selected-image-queries-submit").click();

      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
      await expectDisplaySheetSlotState(page, 1, "back", cardDocument4.name);
    });
  });

  test.describe("DFC prompt conditions", () => {
    test("DFC prompt not shown when the selected slot is a back face", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      // Open the Change Query modal for the back slot - openDisplayChangeQueryModal's own
      // right-click reads whichever face is currently displayed.
      await ensureDisplayFace(page, "back");
      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).not.toBeVisible();
    });

    test("DFC prompt not shown when the back query already equals the DFC back", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      // Importing via text with DFC pairs active auto-sets the back to "Card 4"
      await importTextOnEditorLanding(page, "my search query");
      await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
      await expectDisplaySheetSlotState(page, 1, "back", cardDocument4.name);

      // Now open the modal and type the same DFC front query again
      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      // The back already has the DFC back query — condition 3 fails, prompt must not appear
      await expect(
        modal.getByText("matches a double-faced card pair")
      ).not.toBeVisible();
    });
  });

  test.describe("fuzzy search", () => {
    test("DFC prompt shown for a prefix query when fuzzy search is enabled", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      await enableDisplayFuzzySearch(page);

      const modal = await openDisplayChangeQueryModal(page, 1);
      // "my search" is a prefix of the DFC front key "my search query"
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).toBeVisible();
    });

    test("DFC prompt not shown for a prefix query when precise search is in use", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      // Precise (non-fuzzy) search is the default — no need to configure it
      const modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).not.toBeVisible();
    });
  });

  test.describe("checkbox state", () => {
    test("DFC checkbox resets to unchecked when the modal reopens", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "card 3");

      // Open the modal, trigger the DFC prompt, check the box, then close without submitting
      let modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await modal.getByLabel("Update back").check();
      await expect(modal.getByLabel("Update back")).toBeChecked();
      await modal.getByLabel("Close").click();

      // Reopen the modal and trigger the DFC prompt again
      modal = await openDisplayChangeQueryModal(page, 1);
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      // The checkbox must have been reset
      await expect(modal.getByLabel("Update back")).not.toBeChecked();
    });
  });
});
