import { expect } from "@playwright/test";

import { FaceSeparator, SelectedImageSeparator } from "@/common/constants";
import { cardDocument5 } from "@/common/test-constants";
import {
  cardDocumentsSixResults,
  defaultHandlers,
  searchResultsSixResults,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  expectCardSlotToExist,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "../test-utils";

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

test.describe("InvalidIdentifiersModal visual tests", () => {
  test("invalid identifiers modal displays the appropriate data", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `2x query 1${SelectedImageSeparator}123\n1 query 2${FaceSeparator}query 3${SelectedImageSeparator}456`
    );
    await expectCardSlotToExist(page, 1);
    await expectCardSlotToExist(page, 2);
    await expectCardSlotToExist(page, 3);

    // Bring up the modal
    const alertText = page.getByText("Your project specified", {
      exact: false,
    });
    await alertText.locator("..").getByText("Review Invalid Cards").click();
    await expect(
      page.getByText("Invalid Cards", { exact: true })
    ).toBeVisible();

    // Take screenshot of the modal content
    const modalText = page.getByText(
      "Some card versions you specified couldn't be found",
      { exact: false }
    );
    await expect(modalText.locator("..").locator("..")).toMatchAriaSnapshot(`
      - text: Invalid Cards
      - button "Close"
      - paragraph: "Some card versions you specified couldn't be found. This typically happens when:"
      - list:
        - listitem: You had selected an image, then disabled its source in Search Settings, or
        - listitem: The creator of the image removed it from their repository (even if they reuploaded it later).
      - paragraph: The versions we couldn't find are tabulated below for your reference. The cards in these slots have defaulted to the first versions we found when searching the database.
      - paragraph: Dismiss this warning by clicking the Acknowledge button below.
      - separator
      - table:
        - rowgroup:
          - row "Slot Face Query Identifier":
            - columnheader "Slot"
            - columnheader "Face"
            - columnheader "Query"
            - columnheader "Identifier"
        - rowgroup:
          - row /1 Front query 1 \\d+/:
            - cell "1"
            - cell "Front"
            - cell "query 1":
              - code: query 1
            - cell /\\d+/:
              - code: /\\d+/
          - row /2 Front query 1 \\d+/:
            - cell "2"
            - cell "Front"
            - cell "query 1":
              - code: query 1
            - cell /\\d+/:
              - code: /\\d+/
          - row /3 Back query 3 \\d+/:
            - cell "3"
            - cell "Back"
            - cell "query 3":
              - code: query 3
            - cell /\\d+/:
              - code: /\\d+/
      - button "Close"
      - button "Acknowledge"
    `);
  });
});
