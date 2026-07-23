import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { canonicalArtist1, cardDocument1 } from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  cardDocumentsOneResultWithCanonicalArtist,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
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

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

// Artist Support Links v1, surface 1: the Card Detail Modal's "Canonical Aritst" row (see
// docs/features/artist-support-links.md). Surface 2 (the /whatsthat post-answer moment) is
// covered in QuestionFeed.spec.ts.
test.describe("Artist Support Link - Card Detail Modal", () => {
  test("a known canonical artist renders as an Artist Support Link, built deterministically from their name", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResultWithCanonicalArtist,
      cardbacksTwoOtherResults,
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
    await openDetailedView(page, cardDocument1.name);

    const link = page.getByTestId("artist-support-link");
    await expect(link).toBeVisible();
    await expect(link).toContainText(canonicalArtist1.name);
    await expect(link).toHaveAttribute(
      "href",
      `https://www.mtgartistconnection.com/artist/${encodeURIComponent(
        canonicalArtist1.name
      )}`
    );
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("no canonical artist known: plain 'Unknown' text, no link", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
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
    await openDetailedView(page, cardDocument1.name);

    await expect(page.getByTestId("artist-support-link")).toHaveCount(0);
    await expect(
      page.locator("tr", { hasText: "Canonical Aritst" })
    ).toContainText("Unknown");
  });
});
