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
  enableFuzzySearch,
  expectCardGridSlotState,
  expectCardSlotToExist,
  importText,
  loadPageWithDefaultBackend,
  openChangeQueryModal,
  selectSlot,
  toggleFace,
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

test.describe("ChangeQueryModal tests", () => {
  test("change one card's query", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `query 1${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardSlotToExist(page, 1);
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    // change query - type in "query 2"
    const modal = await openChangeQueryModal(
      page,
      "front-slot0",
      cardDocument1.name
    );
    await expect(
      modal.getByLabel("change-selected-image-queries-text")
    ).toHaveValue("query 1");
    await changeQueries(page, "query 2");

    // expect the slot to have changed from card 1 to card 2
    await expectCardGridSlotState(page, 1, "front", cardDocument2.name, 1, 1);
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
      await importText(page, "query 1");

      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument1.name
      );
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
      await importText(page, "card 3");

      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
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

    test("DFC prompt shown with correct plural text when multiple front slots are selected", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importText(page, "2x card 3");

      await selectSlot(page, 1, "front");
      await selectSlot(page, 2, "front");
      await page.getByText("Change Query").click();
      const modal = page.getByTestId("change-query-modal");

      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      await expect(
        modal.getByText("matches a double-faced card pair")
      ).toBeVisible();
      // Plural phrasing
      await expect(
        modal.getByText(/update the backs of the selected slots to/i)
      ).toBeVisible();
      // Checkbox label is plural
      await expect(modal.getByLabel("Update backs")).toBeVisible();
    });
  });

  test.describe("submission behaviour", () => {
    test("submitting without the DFC checkbox only updates the front query", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importText(page, "card 3");
      await expectCardGridSlotState(page, 1, "front", cardDocument3.name, 1, 1);
      await expectCardGridSlotState(page, 1, "back", cardDocument5.name, 1, 1);

      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await expect(
        modal.getByText("matches a double-faced card pair")
      ).toBeVisible();
      // Leave checkbox unchecked and submit
      await page.getByLabel("change-selected-image-queries-submit").click();

      await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
      // Back must remain unchanged
      await expectCardGridSlotState(page, 1, "back", cardDocument5.name, 1, 1);
    });

    test("submitting with the DFC checkbox updates both front and back queries", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importText(page, "card 3");

      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await modal.getByLabel("Update back").check();
      await page.getByLabel("change-selected-image-queries-submit").click();

      await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
      await expectCardGridSlotState(page, 1, "back", cardDocument4.name, 1, 1);
    });

    test("submitting with the DFC checkbox updates all fronts and backs for a multi-slot selection", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importText(page, "2x card 3");

      await selectSlot(page, 1, "front");
      await selectSlot(page, 2, "front");
      await page.getByText("Change Query").click();
      const modal = page.getByTestId("change-query-modal");

      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await modal.getByLabel("Update backs").check();
      await page.getByLabel("change-selected-image-queries-submit").click();

      await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
      await expectCardGridSlotState(page, 2, "front", cardDocument1.name, 1, 1);
      await expectCardGridSlotState(page, 1, "back", cardDocument4.name, 1, 1);
      await expectCardGridSlotState(page, 2, "back", cardDocument4.name, 1, 1);
    });
  });

  test.describe("DFC prompt conditions", () => {
    test("DFC prompt not shown when the selected slot is a back face", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      await importText(page, "card 3");

      // Open the Change Query modal for the back slot
      await toggleFace(page);
      const modal = await openChangeQueryModal(
        page,
        "back-slot0",
        cardDocument5.name
      );
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
      await importText(page, "my search query");
      await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
      await expectCardGridSlotState(page, 1, "back", cardDocument4.name, 1, 1);

      // Now open the modal and type the same DFC front query again
      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument1.name
      );
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      // The back already has the DFC back query — condition 3 fails, prompt must not appear
      await expect(
        modal.getByText("matches a double-faced card pair")
      ).not.toBeVisible();
    });

    test("DFC prompt not shown when any one of the selected slots already has the DFC back query", async ({
      page,
      network,
    }) => {
      network.use(...dfcHandlers);
      await loadPageWithDefaultBackend(page);
      // Slot 1: DFC import → back is already "Card 4"
      // Slot 2: plain import → back is project cardback (Card 5)
      await importText(page, "1x my search query\n1x card 3");
      await expectCardGridSlotState(page, 1, "back", cardDocument4.name, 1, 1);

      await selectSlot(page, 1, "front");
      await selectSlot(page, 2, "front");
      await page.getByText("Change Query").click();
      const modal = page.getByTestId("change-query-modal");

      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      // Slot 1's back already equals the DFC back — prompt must not appear for either slot
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
      await importText(page, "card 3");

      await enableFuzzySearch(page);

      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
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
      await importText(page, "card 3");

      // Precise (non-fuzzy) search is the default — no need to configure it
      const modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
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
      await importText(page, "card 3");

      // Open the modal, trigger the DFC prompt, check the box, then close without submitting
      let modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");
      await modal.getByLabel("Update back").check();
      await expect(modal.getByLabel("Update back")).toBeChecked();
      await modal.getByLabel("Close").click();

      // Reopen the modal and trigger the DFC prompt again
      modal = await openChangeQueryModal(
        page,
        "front-slot0",
        cardDocument3.name
      );
      await modal
        .getByLabel("change-selected-image-queries-text")
        .fill("my search query");

      // The checkbox must have been reset
      await expect(modal.getByLabel("Update back")).not.toBeChecked();
    });
  });
});
