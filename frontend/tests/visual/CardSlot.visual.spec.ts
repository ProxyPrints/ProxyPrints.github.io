import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardbacksFourResults,
  cardDocumentsFourResults,
  defaultHandlers,
  searchResultsFourResults,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayCardbackGridSelector,
  selectDropdownOption,
} from "../test-utils";

// Parity wave 3 (2026-07-24, issue #272) - un-skipped and ported onto the unified `/editor` page.
//
// Dropped, not ported: the 4 per-slot inline snapshots ("single search result, no image
// selected"/"...slot selected"/"...image selected", "multiple search results, image selected") -
// the classic grid's inline candidate strip (thumbnails + "N / M" counter + ❮/❯ arrows, rendered
// directly inside the slot) has no equivalent on the sheet: `PagePreview.tsx`'s own slot is a
// plain `<img>` with no inline candidate UI at all (same "classic grid's inline candidate strip
// has no equivalent" finding wave 1's import cluster already made for `selectedImage`/
// `totalImages` - see that wave's own PR description).
//
// Ported: the 2 grid-selector aria-snapshot tests, retargeted onto the cardback picker (the only
// surviving GridSelectorModal.tsx mount post-route-swap - see GridSelectorModal.spec.ts's own
// header comment and openDisplayCardbackGridSelector's comment in test-utils.ts for the full
// rationale). Genuinely re-baselined, not just route-swap-updated: the outer testid
// (`front-slot0-grid-selector` -> `cardback-grid-selector`) and modal title ("Select Version" ->
// "Select Cardback") both change, since this is a different GridSelectorModal mount - but the
// modal's own internal DOM (Filters sidebar, Jump to Version, Group by, Sort, Filter sliders,
// Mature Content/Community-Confirmed Printing Attributes toggles, the sources table, and the
// result tiles themselves) is byte-for-byte the same component tree (GridSelectorResults
// variant="modal"), unaffected by which caller's identifiers feed it.
//
// Regex-tolerant, not exact-matched, on a handful of specific leaves: the icon-only chevron-
// toggle buttons (Jump to Version/View/Sort/Filter section headers, each rendered as a plain
// `<i class="bi bi-...">` with its glyph supplied via CSS `content` on a bootstrap-icons webfont
// pseudo-element - RightPaddedIcon/icon.tsx), the "Filters"/"Collapse All" buttons' own leading
// icon, "Remove None"/"Remove Source" tag-chip buttons' own trailing clear-icon, and each
// StyledDropdownTreeSelect's placeholder-caret text node. Verified directly (2026-07-24, this
// wave): a plain `toMatchAriaSnapshot` polling assertion reproducibly settles on a DIFFERENT
// accessible-name/text value for exactly these nodes than a single `--update-snapshots` capture
// does, deterministically and independent of worker count/explicit wait length (both ruled out by
// direct testing) - a genuine pre-existing rendering race in this third-party icon-font/tree-
// select machinery (unchanged by this port), not a route-swap or port artifact. Every other leaf
// in this snapshot (headings, table rows, source names, result-tile names/images, the DPI/file-
// size bounds via the pre-existing `\d+` regex) matched exactly and consistently across every run.
test.describe("CardSlot visual tests", () => {
  test("card slot grid selector, cards grouped together", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsFourResults,
      cardbacksFourResults,
      sourceDocumentsThreeResults,
      searchResultsFourResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );

    await openDisplayCardbackGridSelector(page);

    await expect(page.getByTestId("cardback-grid-selector"))
      .toMatchAriaSnapshot(`
        - text: Select Cardback — 4 results
        - button /Filters/
        - button "Close"
        - heading "Jump to Version" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - heading "View" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - text: Group by
        - button "None":
          - list:
            - listitem:
              - text: None
              - button /Remove None/
            - listitem: Choose...
          - text: /.*/
        - text: Card display style
        - button "Compressed Relaxed"
        - heading "Sort" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: /.*/
        - heading "Filter" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
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
          - text: /.*/
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
      cardbacksFourResults,
      sourceDocumentsThreeResults,
      searchResultsFourResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );

    const gridSelector = await openDisplayCardbackGridSelector(page);

    // Toggle on "Facet by Source"
    const groupByDropdown = gridSelector
      .locator(".react-dropdown-tree-select")
      .first();
    await selectDropdownOption(groupByDropdown, "Source");

    await expect(page.getByTestId("cardback-grid-selector"))
      .toMatchAriaSnapshot(`
        - text: Select Cardback — 4 results
        - button /Filters/
        - button "Close"
        - heading "Jump to Version" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - heading "View" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - text: Group by
        - button "Source":
          - list:
            - listitem:
              - text: Source
              - button /Remove Source/
            - listitem: Choose...
          - text: /.*/
        - button /Collapse All/
        - text: Card display style
        - button "Compressed Relaxed"
        - heading "Sort" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
        - button "Choose... ▼":
          - list:
            - listitem: Choose...
          - text: /.*/
        - heading "Filter" [level=5]
        - button /.*/:
          - heading /.*/ [level=5]
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
          - text: /.*/
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
        - button /.*/:
          - heading /.*/ [level=5]
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
