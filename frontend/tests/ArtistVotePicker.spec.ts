import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  canonicalArtist1,
  canonicalArtist2,
  cardDocument1,
} from "@/common/test-constants";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  submitArtistVoteResolvesToCanonicalArtist1,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

test.describe("ArtistVotePicker tests", () => {
  test("shows the attribute-voting panel once printing consensus is unresolved, listing candidate artists", async ({
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
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    // longer than the default 5s: showing this panel is gated behind a chain of fetches
    // (printing consensus resolves -> CardDetailedViewModal re-renders -> the panel mounts
    // -> its own two children each fire their own fetch), which is slower than a single
    // round trip even against these MSW mocks.
    const panel = page.getByTestId("attribute-voting-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    const artistPicker = page.getByTestId("artist-vote-picker");
    await expect(artistPicker.getByText(canonicalArtist1.name)).toBeVisible();
    await expect(artistPicker.getByText(canonicalArtist2.name)).toBeVisible();
    await expect(artistPicker.getByText("Unknown artist")).toBeVisible();
  });

  test("submitting a vote for an artist updates the shown consensus", async ({
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
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      submitArtistVoteResolvesToCanonicalArtist1,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const artistPicker = page.getByTestId("artist-vote-picker");
    await expect(artistPicker.getByText("Not yet resolved")).toBeVisible();

    await artistPicker.getByText(canonicalArtist1.name).click();

    await expect(page.getByText("Vote submitted")).toBeVisible();
    await expect(
      page
        .getByTestId("artist-vote-consensus")
        .getByText(`Current consensus: ${canonicalArtist1.name}`)
    ).toBeVisible();
  });
});
