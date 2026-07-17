import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsFourResults,
  cardDocumentsOneResult,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsFourResults,
  searchResultsOneResult,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  expectCardGridSlotState,
  importText,
  loadPageWithDefaultBackend,
  openCardSlotGridSelector,
  selectDropdownOption,
  selectSlot,
} from "../test-utils";

test.describe("CardSlot visual tests", () => {
  test("card slot with single search result, no image selected", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(page, "my search query");
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await expect(page.getByTestId("front-slot0")).toMatchAriaSnapshot(`
      - button "Slot 1 select-front0 More options":
        - paragraph: Slot 1
        - button "select-front0"
        - button "More options"
      - img "Card 1"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - paragraph: 1 / 1
    `);
  });

  test("card slot with single search result, slot selected", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(page, "my search query");
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await selectSlot(page, 1, "front");

    await expect(page.getByTestId("front-slot0")).toMatchAriaSnapshot(`
      - button "Slot 1 select-front0 More options":
        - paragraph: Slot 1
        - button "select-front0"
        - button "More options"
      - img "Card 1"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - paragraph: 1 / 1
    `);
  });

  test("card slot with single search result, image selected", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);

    await expect(page.getByTestId("front-slot0")).toMatchAriaSnapshot(`
      - button "Slot 1 select-front0 More options":
        - paragraph: Slot 1
        - button "select-front0"
        - button "More options"
      - img "Card 1"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - paragraph: 1 / 1
    `);
  });

  test("card slot with multiple search results, image selected", async ({
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

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 3);

    await expect(page.getByTestId("front-slot0")).toMatchAriaSnapshot(`
      - button "Slot 1 select-front0 More options":
        - paragraph: Slot 1
        - button "select-front0"
        - button "More options"
      - img "Card 1"
      - img "Card 2"
      - img "Card 3"
      - text: Card 1
      - paragraph: /Source 1 \\[\\d+ DPI\\]/
      - button "1 / 3"
      - button "❮"
      - button "❯"
    `);
  });

  test("card slot grid selector, cards grouped together", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsFourResults,
      sourceDocumentsThreeResults,
      searchResultsFourResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );

    await openCardSlotGridSelector(page, 1, "front", 1, 4);

    await expect(page.getByTestId("front-slot0-grid-selector"))
      .toMatchAriaSnapshot(`
        - text: Select Version — 4 results
        - button " Filters"
        - button "Close"
        - heading "Jump to Version" [level=5]
        - button "":
          - heading "" [level=5]
        - heading "View" [level=5]
        - button "":
          - heading "" [level=5]
        - text: Group by
        - button "None":
          - list:
            - listitem:
              - text: None
              - button "Remove None"
            - listitem: Choose...
          - text: ""
        - text: Card display style
        - button "Compressed Relaxed"
        - heading "Sort" [level=5]
        - button "":
          - heading "" [level=5]
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - heading "Filter" [level=5]
        - button "":
          - heading "" [level=5]
        - text: "Min resolution: 0 DPI"
        - slider: "0"
        - text: "/Max resolution: \\\\d+ DPI/"
        - slider: /\\d+/
        - text: "/File size: Up to \\\\d+ MB/"
        - slider: /\\d+/
        - text: Languages
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - text: Tags which cards must have at least one of
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - text: Tags which cards must not have
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - heading "Mature Content" [level=5]
        - text: Cards the community has confirmed as NSFW are hidden from search by default. This switch drives the NSFW entry in the tag filter above — they're the same setting.
        - button "Showing Mature Content Hiding Mature Content"
        - heading "Community-Confirmed Printing Attributes" [level=5]
        - text: These filters only affect cards with a printing the community has confirmed via voting. Cards without a confirmed printing are unknowns, not mismatches — they're never hidden by these filters.
        - button "Full Art Only Include All Art"
        - button "Borderless Only Include All Borders"
        - button "Disable all drives"
        - table:
          - rowgroup:
            - row "Active Name":
              - columnheader "Active"
              - columnheader "Name"
              - columnheader
              - columnheader
          - rowgroup:
            - button "On Off Source 1":
              - cell "On Off":
                - button "On Off"
              - cell "Source 1"
              - cell
              - cell
            - button "On Off Source 2":
              - cell "On Off":
                - button "On Off"
              - cell "Source 2"
              - cell
              - cell
            - button "On Off Source 3":
              - cell "On Off":
                - button "On Off"
              - cell "Source 3"
              - cell
              - cell
        - button "Card 1":
          - img "Card 1"
        - button "Card 2":
          - img "Card 2"
        - button "Card 3":
          - img "Card 3"
        - button "Card 4":
          - img "Card 4"
        - button "Close"
      `);
  });

  test("card slot grid selector, cards faceted by source", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsFourResults,
      sourceDocumentsThreeResults,
      searchResultsFourResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );

    const gridSelector = await openCardSlotGridSelector(page, 1, "front", 1, 4);

    // Toggle on "Facet by Source"
    const groupByDropdown = gridSelector
      .locator(".react-dropdown-tree-select")
      .first();
    await selectDropdownOption(groupByDropdown, "Source");

    await expect(page.getByTestId("front-slot0-grid-selector"))
      .toMatchAriaSnapshot(`
        - text: Select Version — 4 results
        - button " Filters"
        - button "Close"
        - heading "Jump to Version" [level=5]
        - button "":
          - heading "" [level=5]
        - heading "View" [level=5]
        - button "":
          - heading "" [level=5]
        - text: Group by
        - button "Source":
          - list:
            - listitem:
              - text: Source
              - button "Remove Source"
            - listitem: Choose...
          - text: ""
        - button " Collapse All"
        - text: Card display style
        - button "Compressed Relaxed"
        - heading "Sort" [level=5]
        - button "":
          - heading "" [level=5]
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - heading "Filter" [level=5]
        - button "":
          - heading "" [level=5]
        - text: "Min resolution: 0 DPI"
        - slider: "0"
        - text: "/Max resolution: \\\\d+ DPI/"
        - slider: /\\d+/
        - text: "/File size: Up to \\\\d+ MB/"
        - slider: /\\d+/
        - text: Languages
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - text: Tags which cards must have at least one of
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - text: Tags which cards must not have
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: ""
        - heading "Mature Content" [level=5]
        - text: Cards the community has confirmed as NSFW are hidden from search by default. This switch drives the NSFW entry in the tag filter above — they're the same setting.
        - button "Showing Mature Content Hiding Mature Content"
        - heading "Community-Confirmed Printing Attributes" [level=5]
        - text: These filters only affect cards with a printing the community has confirmed via voting. Cards without a confirmed printing are unknowns, not mismatches — they're never hidden by these filters.
        - button "Full Art Only Include All Art"
        - button "Borderless Only Include All Borders"
        - button "Disable all drives"
        - table:
          - rowgroup:
            - row "Active Name":
              - columnheader "Active"
              - columnheader "Name"
              - columnheader
              - columnheader
          - rowgroup:
            - button "On Off Source 1":
              - cell "On Off":
                - button "On Off"
              - cell "Source 1"
              - cell
              - cell
            - button "On Off Source 2":
              - cell "On Off":
                - button "On Off"
              - cell "Source 2"
              - cell
              - cell
            - button "On Off Source 3":
              - cell "On Off":
                - button "On Off"
              - cell "Source 3"
              - cell
              - cell
        - heading "Source 1" [level=3]
        - heading "4 versions" [level=6]
        - button "":
          - heading "" [level=5]
        - button "Card 1":
          - img "Card 1"
        - button "Card 2":
          - img "Card 2"
        - button "Card 3":
          - img "Card 3"
        - button "Card 4":
          - img "Card 4"
        - button "Close"
      `);
  });
});
