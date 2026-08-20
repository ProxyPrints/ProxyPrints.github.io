import { expect } from "@playwright/test";

import { cardDocument1, sourceDocument1 } from "@/common/test-constants";
import {
  cardbacksOneResult,
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  expectDisplaySheetSlotState,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplaySearchSettingsModal,
} from "../test-utils";

// Parity wave 2 (2026-07-23, issue #272): ported onto the unified `/editor` page.
// SearchSettings.tsx itself is unchanged and unforked (DisplayPage.tsx's own comment: "the same
// self-contained trigger-button-plus-modal ProjectEditor.tsx already mounts, relocated here
// unmodified") - only how it's reached differs (openDisplaySearchSettingsModal, test-utils.ts).
test.describe("SearchSettings visual tests", () => {
  test("search settings modal structure", async ({ page, network }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksOneResult,
      sourceDocumentsThreeResults,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // Wait for sources to be fetched by importing a card
    await importTextOnEditorLanding(page, "my search query");
    await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);

    const searchSettings = await openDisplaySearchSettingsModal(page);
    await expect(searchSettings.getByText(sourceDocument1.name)).toBeVisible();

    // Wait until all spinners have finished loading
    await expect(page.locator(".spinner")).toHaveCount(0);

    await expect(searchSettings).toMatchAriaSnapshot(`
      - text: Search Settings
      - button "Close"
      - heading "Search Type" [level=5]
      - text: Configure how closely the search results should match your query.
      - button "Fuzzy (Forgiving) Search Precise Search"
      - button "Filters Apply to Cardbacks Include All Cardbacks"
      - separator
      - heading "Filters" [level=5]
      - text: "Configure the DPI (dots per inch) and file size ranges the search results must be within. At a fixed physical size, a higher DPI yields a higher resolution print. Print resolution has a practical ceiling, though — beyond a certain point, a higher DPI print will look the same as a lower one. Min resolution: 0 DPI"
      - slider: "0"
      - text: "/Max resolution: \\\\d+ DPI/"
      - slider: /\\d+/
      - text: "/File size: Up to \\\\d+ MB/"
      - slider: /\\d+/
      - text: Languages
      - group "Languages":
        - checkbox "English"
        - text: English
        - checkbox "French"
        - text: French
      - text: Tags which cards must have at least one of
      - button "Choose... ▼":
        - list:
          - listitem: Choose...
        - text: /.*/
      - text: Tags which cards must not have
      - button "Choose... ▼":
        - list:
          - listitem: Choose...
        - text: /.*/
      - heading "Mature Content" [level=5]
      - text: Cards the community has confirmed as NSFW are hidden from search by default. This switch drives the NSFW entry in the tag filter above — they're the same setting.
      - button "Showing Mature Content Hiding Mature Content"
      - heading "Universe Within" [level=5]
      - text: Show only cards using original Magic art, hiding cards the community has tagged as borrowing art from an external, non-Magic property. This switch drives the External IP entry in the tag filter above — they're the same setting.
      - button "Showing Original Magic Art Hiding External IP Art"
      - heading "Community-Confirmed Printing Attributes" [level=5]
      - text: These filters only affect cards with a printing the community has confirmed via voting. Cards without a confirmed printing are unknowns, not mismatches — they're never hidden by these filters.
      - button "Full Art Only Include All Art"
      - button "Borderless Only Include All Borders"
      - separator
      - heading "Contributors" [level=5]
      - text: Configure the contributors to include in the search results.
      - list:
        - listitem: Drag & drop them to change the order they're searched in.
        - listitem: Use the arrows to send a source to the top or bottom.
      - button "Disable all drives"
      - table:
        - rowgroup:
          - row "Active Name":
            - columnheader "Active"
            - columnheader "Name"
            - columnheader
            - columnheader
        - rowgroup:
          - button "On Off Source 1   ":
            - cell "On Off":
              - button "On Off"
            - cell "Source 1"
            - cell " "
            - cell ""
          - button "On Off Source 2   ":
            - cell "On Off":
              - button "On Off"
            - cell "Source 2"
            - cell " "
            - cell ""
          - button "On Off Source 3   ":
            - cell "On Off":
              - button "On Off"
            - cell "Source 3"
            - cell " "
            - cell ""
      - button "Close Without Saving"
      - button "Save Changes"
    `);
  });
});
