import { expect } from "@playwright/test";

import {
  cardbacksServerError,
  cardbacksTwoOtherResults,
  cardbacksTwoResults,
  cardDocumentsServerError,
  cardDocumentsThreeResults,
  defaultHandlers,
  dfcPairsServerError,
  importSitesServerError,
  newCardsFirstPageServerError,
  sampleCardsServerError,
  searchResultsOneResult,
  searchResultsServerError,
  sourceDocumentsOneResult,
  sourceDocumentsServerError,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  getErrorToast,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Parity wave 2 (2026-07-23, issue #272): the 3 tests below (DFCPairs/importSites/sampleCards)
// used openImportTextModal/getAddCardsMenu to OPEN the classic grid's "Add Cards" dropdown, which
// has no equivalent on the unified page - but that click was only ever a means to mount
// ImportText.tsx/ImportURL.tsx, whose own `useGetDFCPairsQuery`/`useGetSampleCardsQuery`/
// `useGetImportSitesQuery` hooks fire the instant those components mount, not on any particular
// click. DisplayPage's empty-project landing (`loadPageWithDefaultBackend`'s default "editor" -
// see DisplayPage.tsx's own `ImportColumns`) mounts `ImportText` AND `ImportURL` unconditionally
// (the URL accordion tab is `defaultActiveKey="url"`, open from the start) - so all three fetches
// already fire on plain page load, same as the already-unskipped `/2/cards`/`/2/sources` tests
// right above them. No interaction step needed at all - `interactionFn: null`, like those.

test.describe("error reporting toasts", () => {
  async function assertErrorToast(
    page: any,
    network: any,
    name: string,
    handlers: any[],
    interactionFn: (() => Promise<void>) | null = null
  ) {
    network.use(...handlers, ...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    // Do any extra setup the test needs to do to trigger the error
    if (interactionFn != null) {
      await interactionFn();
    }

    const errorToast = await getErrorToast(page);

    // Assert the toast's reported error name and message
    await expect(errorToast).toBeVisible();
    await expect(errorToast.getByText(name)).toBeVisible();
    await expect(
      errorToast.getByText("A message that describes the error")
    ).toBeVisible();

    // Dismiss the toast, then assert that it no longer exists
    await errorToast.getByLabel("Close").click();
    await expect(page.getByText("An Error Occurred")).not.toBeVisible();
  }

  test("/3/editorSearch", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "3/editorSearch",
      [
        cardDocumentsThreeResults,
        cardbacksTwoResults,
        sourceDocumentsOneResult,
        searchResultsServerError,
      ],
      async () => {
        await importTextOnEditorLanding(page, "mountain");
      }
    );
  });

  test("/2/cards", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/cards",
      [
        cardDocumentsServerError,
        cardbacksTwoOtherResults,
        sourceDocumentsOneResult,
        searchResultsOneResult,
      ],
      null
    );
  });

  test("/2/sources", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/sources",
      [
        cardDocumentsThreeResults,
        cardbacksTwoResults,
        sourceDocumentsServerError,
        searchResultsOneResult,
      ],
      null
    );
  });

  test("/2/DFCPairs", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/DFCPairs",
      [
        cardDocumentsThreeResults,
        cardbacksTwoResults,
        sourceDocumentsOneResult,
        searchResultsOneResult,
        dfcPairsServerError,
      ],
      null
    );
  });

  test("/2/cardbacks", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/cardbacks",
      [
        cardDocumentsThreeResults,
        cardbacksServerError,
        sourceDocumentsOneResult,
        searchResultsOneResult,
      ],
      null
    );
  });

  test("/2/importSites", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/importSites",
      [
        cardDocumentsThreeResults,
        cardbacksTwoResults,
        sourceDocumentsOneResult,
        searchResultsOneResult,
        importSitesServerError,
      ],
      null
    );
  });

  test("/2/sampleCards", async ({ page, network }) => {
    await assertErrorToast(
      page,
      network,
      "2/sampleCards",
      [
        cardDocumentsThreeResults,
        cardbacksTwoResults,
        sourceDocumentsOneResult,
        searchResultsOneResult,
        sampleCardsServerError,
      ],
      null
    );
  });

  test("/2/newCardsFirstPage", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      newCardsFirstPageServerError,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "new");

    const errorToast = await getErrorToast(page);
    await expect(errorToast).toBeVisible();
    await expect(errorToast.getByText("2/newCardsFirstPage")).toBeVisible();
  });
});
