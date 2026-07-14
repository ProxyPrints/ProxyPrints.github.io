import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  reportCardRateLimited,
  reportCardSuccess,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectCardGridSlotState,
  importText,
  loadPageWithDefaultBackend,
} from "./test-utils";

const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(page.getByText("Card Details")).toBeVisible();
};

const setUpCardAndOpenModal = async (page: any) => {
  await loadPageWithDefaultBackend(page);
  await importText(
    page,
    `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
  );
  await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
  await openDetailedView(page, cardDocument1.name);
};

test.describe("report card flow", () => {
  test("reporting via a reason chip lands and thanks the user", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      reportCardSuccess,
      ...defaultHandlers
    );
    await setUpCardAndOpenModal(page);

    await page.getByTestId("report-card-button").click();
    await expect(page.getByTestId("report-card-panel")).toBeVisible();
    await page.getByTestId("report-chip-nsfw").click();
    await expect(page.getByTestId("report-card-thanks")).toBeVisible();
  });

  test("Other requires free text and submits it", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      reportCardSuccess,
      ...defaultHandlers
    );
    await setUpCardAndOpenModal(page);

    await page.getByTestId("report-card-button").click();
    await page.getByTestId("report-chip-other").click();
    await expect(page.getByTestId("report-submit-other")).toBeDisabled();
    await page
      .getByTestId("report-other-text")
      .fill("the corners are cut off");
    await page.getByTestId("report-submit-other").click();
    await expect(page.getByTestId("report-card-thanks")).toBeVisible();
  });

  test("hitting the rate limit shows a polite toast", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      reportCardRateLimited,
      ...defaultHandlers
    );
    await setUpCardAndOpenModal(page);

    await page.getByTestId("report-card-button").click();
    await page.getByTestId("report-chip-nsfw").click();
    await expect(page.getByText("Report limit reached")).toBeVisible();
    // the panel stays open - nothing was recorded
    await expect(page.getByTestId("report-card-panel")).toBeVisible();
  });
});
