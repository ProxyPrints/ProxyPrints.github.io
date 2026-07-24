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
  openDetailedView,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page.
// CardDetailedViewModal (the shared, unforked component this whole cluster exercises) is reached
// via Browse mode - see openDetailedView's own module comment (test-utils.ts) for why that's the
// one surface on this page that still opens it, and the "Card details" text-collision fix that
// cluster needed. Its own "Canonical Aritst" table row is what this file's own assertions target
// (docs/features/artist-support-links.md). Surface 2 (the /whatsthat post-answer moment) is
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
    await openDetailedView(page, "my search query", cardDocument1.identifier);

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
    await openDetailedView(page, "my search query", cardDocument1.identifier);

    await expect(page.getByTestId("artist-support-link")).toHaveCount(0);
    await expect(
      page.locator("tr", { hasText: "Canonical Aritst" })
    ).toContainText("Unknown");
  });
});
