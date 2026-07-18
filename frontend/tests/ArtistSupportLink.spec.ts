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
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

// Artist Support Links v1, surface 1: the Card Detail Modal's "Canonical Aritst" row (see
// docs/features/artist-support-links.md). Surface 2 (the /whatsthat post-answer moment) is
// covered in QuestionFeedArtistAndTag.spec.ts.
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

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const link = page.getByTestId("artist-support-link");
    await expect(link).toBeVisible();
    await expect(link).toContainText(canonicalArtist1.name);
    await expect(link).toHaveAttribute(
      "href",
      `https://www.mtgartistconnection.com/artist/${encodeURIComponent(canonicalArtist1.name)}`
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

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    await expect(page.getByTestId("artist-support-link")).toHaveCount(0);
    await expect(page.locator("tr", { hasText: "Canonical Aritst" })).toContainText(
      "Unknown"
    );
  });
});
