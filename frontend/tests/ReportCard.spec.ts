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
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDetailedView,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// ReportCardPanel lives inside CardDetailedViewModal's own "Report" region (ReportBlock,
// CardDetailedViewBody.tsx), reached the same way the rest of this cluster reaches the modal - see
// openDetailedView's own module comment (test-utils.ts) for the Browse-mode route and the "Card
// details" text-collision fix.

const setUpCardAndOpenModal = async (page: any) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(
    page,
    `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
  );
  await openDetailedView(page, "my search query", cardDocument1.identifier);
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

  test("Other requires free text and submits it", async ({ page, network }) => {
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
    await page.getByTestId("report-other-text").fill("the corners are cut off");
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
