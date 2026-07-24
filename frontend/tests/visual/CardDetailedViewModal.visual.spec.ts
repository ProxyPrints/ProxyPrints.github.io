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
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDetailedView,
} from "../test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// CardDetailedViewModal (the shared, unforked component this aria snapshot targets) is reached
// via Browse mode - see openDetailedView's own module comment (test-utils.ts) for why that's the
// one surface on this page that still opens it. The snapshot itself DID need re-baselining - see
// the fix-round comment further down for why (real, unrelated content drift while this file sat
// skipped, not a route-swap DOM difference).

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
    await openDetailedView(page, "my search query", cardDocument1.identifier);

    await expect(page.getByText("English")).toBeVisible();
    await expect(page.getByText("Not yet resolved")).toBeVisible();
    // Fix round (2026-07-23, this port): toMatchAriaSnapshot asserts the container's full
    // accessibility tree, not a partial/contains match - AttributeVotingPanel (VotePickers.spec.ts's
    // own precedent notes this is gated behind a chain of fetches slower than a single round trip)
    // mounts asynchronously once printing consensus resolves unresolved, same as "Not yet
    // resolved" above; waiting for its own heading here avoids a race between that panel finishing
    // its mount and the snapshot assertion running.
    await expect(
      page.getByRole("heading", { name: "Who's the artist?" })
    ).toBeVisible({ timeout: 10000 });

    // Fix round (2026-07-23, this port) - real baseline drift, unrelated to the route swap
    // itself: this modal has grown three real features since this snapshot was last verified
    // green (Add to Favorites/AddCardToFavorites.spec.ts, Report this card/ReportCard.spec.ts,
    // What's That Card?/PrintingTagsBlock+AttributeVotingPanel - VotePickers.spec.ts), none of
    // which this file's own snapshot had ever captured. Regenerated from the real, current, fully-
    // settled DOM (`ariaSnapshot()` printed directly, once "Who's the artist?" above confirmed
    // AttributeVotingPanel had finished mounting) rather than hand-edited. The full-res left-column
    // image's own loading spinner (`status: Loading...`, `MemoizedCardImage`'s `showSpinner`) is
    // the one node deliberately left out below - genuinely present in this sandbox (no real network
    // egress to the CDN host these mock fixtures point `smallThumbnailUrl`-less cards at, so the
    // image request never resolves) but not a meaningful assertion for this test, and liable to
    // flip absent wherever the image genuinely does load in time (e.g. a real CI runner with
    // internet egress) - `toMatchAriaSnapshot` tolerates a top-level node being skipped like this
    // (confirmed empirically: a snapshot omitting both it and the `img` line straight after it
    // still matched), unlike genuinely reordering/omitting something nested inside an otherwise-
    // asserted subtree (e.g. the table's own rows), which it does not.
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
          - row "Resolution 1200 DPI":
            - rowheader "Resolution"
            - cell "1200 DPI"
          - row "Date Created 1st January, 2000":
            - rowheader "Date Created"
            - cell "1st January, 2000"
          - row "Date Modified 1st January, 2000":
            - rowheader "Date Modified"
            - cell "1st January, 2000"
          - row "File Size 10 MB":
            - rowheader "File Size"
            - cell "10 MB"
          - row "Canonical Card Unknown":
            - rowheader "Canonical Card"
            - cell "Unknown"
          - row "Canonical Aritst Unknown":
            - rowheader "Canonical Aritst"
            - cell "Unknown"
      - button " Download Image"
      - button " Add to Favorites"
      - spinbutton: "1"
      - button " Add to Project"
      - button " Report this card"
      - separator
      - heading "What's That Card?" [level=5]
      - paragraph: Help us figure out which real-world printing this card is!
      - text: Not yet resolved
      - textbox "Search for a different card..."
      - button "None of these match No match":
        - img "None of these match"
        - text: No match
      - button "abc 1 ABC 1 Some Artist":
        - img "abc 1"
        - text: ABC 1 Some Artist
      - button "xyz 42 XYZ 42 Another Artist":
        - img "xyz 42"
        - text: XYZ 42 Another Artist
      - separator
      - heading "Who's the artist?" [level=6]
      - text: Loading current consensus...
      - textbox "Search for an artist..."
      - button "Unknown artist"
      - heading "Do any of these tags apply?" [level=6]
      - button "Close"
    `);
  });
});
