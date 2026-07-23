import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  expectCardGridSlotState,
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

test.describe("CardDetailedViewModal visual tests", () => {
  test("card detailed view modal structure", async ({ page, network }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await page.getByAltText(cardDocument1.name).click();
    await expect(page.getByText("Card Details")).toBeVisible();
    await expect(page.getByText("English")).toBeVisible();
    await expect(page.getByText("Not yet resolved")).toBeVisible();

    await expect(page.getByTestId("detailed-view")).toMatchAriaSnapshot(`
      - text: Card Details
      - button "Close"
      - img "Card 1"
      - heading "Card 1" [level=4]
      - table:
        - rowgroup:
          - row "Source Name Source 1":
            - rowheader "Source Name"
            - cell "Source 1"
          - row "Source Type Google Drive":
            - rowheader "Source Type"
            - cell "Google Drive"
          - row "Class Card":
            - rowheader "Class"
            - cell "Card"
          - row "Identifier 1c4M-sK9gd0Xju0NXCPtqeTW_DQTldVU5":
            - rowheader "Identifier"
            - cell "1c4M-sK9gd0Xju0NXCPtqeTW_DQTldVU5":
              - code: 1c4M-sK9gd0Xju0NXCPtqeTW_DQTldVU5
          - row "Language English":
            - rowheader "Language"
            - cell "English"
          - row "Tags Untagged":
            - rowheader "Tags"
            - cell "Untagged"
          - row /Resolution \\d+ DPI/:
            - rowheader "Resolution"
            - cell /\\d+ DPI/
          - row /Date Created 1st January, \\d+/:
            - rowheader "Date Created"
            - cell /1st January, \\d+/
          - row /Date Modified 1st January, \\d+/:
            - rowheader "Date Modified"
            - cell /1st January, \\d+/
          - row /File Size \\d+ MB/:
            - rowheader "File Size"
            - cell /\\d+ MB/
      - button " Download Image"
      - spinbutton: "1"
      - button " Add to Project"
      - button "Close"
    `);
  });
});
