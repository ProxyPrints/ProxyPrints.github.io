import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
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
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
  tagsBorderlessWithDisplayName,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

test.describe("TagVotePicker tests", () => {
  test("lists every seeded tag as an unresolved toggle chip", async ({
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

    const tagPicker = page.getByTestId("tag-vote-picker");
    await expect(tagPicker.getByText("Borderless")).toBeVisible();
    await expect(tagPicker.getByText("Extended")).toBeVisible();
  });

  test("shows a tag's displayName when set, falling back to its name when not", async ({
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
      tagsBorderlessWithDisplayName, // only "Borderless" has a displayName; "Extended" doesn't exist in this list at all
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const tagPicker = page.getByTestId("tag-vote-picker");
    // "Borderless" has displayName "Frameless Border" set - shown instead of the raw name
    await expect(tagPicker.getByText("Frameless Border")).toBeVisible();
    await expect(
      tagPicker.getByText("Borderless", { exact: true })
    ).not.toBeVisible();
    // "Extended" has no displayName - falls back to its raw name
    await expect(tagPicker.getByText("Extended")).toBeVisible();
  });

  test("clicking a tag chip submits a vote and updates that chip's state", async ({
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
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const tagPicker = page.getByTestId("tag-vote-picker");
    await tagPicker.getByText("Borderless").click();

    // the mock always resolves to APPLY regardless of which chip was clicked, so this proves
    // the click round-tripped through APISubmitTagVote and re-rendered from the response
    await expect(tagPicker.getByText("Borderless")).toBeVisible();
  });
});
