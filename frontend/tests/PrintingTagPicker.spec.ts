import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  cardDocument1,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  submitPrintingTagResolvesToPrintingCandidate1,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

test.describe("PrintingTagPicker tests", () => {
  test("shows unresolved consensus and lists candidate printings", async ({
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

    await expect(
      page.getByTestId("detailed-view").getByText("Who's That Planeswalker?")
    ).toBeVisible();
    await expect(page.getByText("Not yet resolved")).toBeVisible();

    const picker = page.getByTestId("printing-tag-picker");
    await expect(
      picker.getByText(
        `${printingCandidate1.expansionCode.toUpperCase()} ${
          printingCandidate1.collectorNumber
        }`
      )
    ).toBeVisible();
    await expect(
      picker.getByText(
        `${printingCandidate2.expansionCode.toUpperCase()} ${
          printingCandidate2.collectorNumber
        }`
      )
    ).toBeVisible();
    await expect(picker.getByAltText("None of these match")).toBeVisible();
    await expect(picker.getByText("No match")).toBeVisible();
  });

  test("submitting a vote for a printing updates the shown consensus", async ({
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
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importText(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const picker = page.getByTestId("printing-tag-picker");
    await expect(page.getByText("Not yet resolved")).toBeVisible();

    await picker
      .getByText(
        `${printingCandidate1.expansionCode.toUpperCase()} ${
          printingCandidate1.collectorNumber
        }`
      )
      .click();

    await expect(page.getByText("Vote submitted")).toBeVisible();
    await expect(
      page
        .getByTestId("printing-tag-consensus")
        .getByText(
          `Current consensus: ${printingCandidate1.expansionCode.toUpperCase()} ${
            printingCandidate1.collectorNumber
          }`
        )
    ).toBeVisible();
  });
});
