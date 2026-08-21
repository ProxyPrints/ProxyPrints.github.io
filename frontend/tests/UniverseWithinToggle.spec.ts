import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectDisplaySheetSlotState,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openSearchSettingsModal,
} from "./test-utils";

// Mirrors MatureContentToggle.spec.ts's own structure - Universe Within is the same kind of
// on/off convenience shortcut over excludesTags, just for the external-ip tag instead of NSFW.

// saving search settings only re-triggers a search when the project has queries to re-run,
// so each test imports one card first
const loadPageWithOneCard = async (page: any) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(
    page,
    `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
  );
  await expectDisplaySheetSlotState(page, 1, "front", cardDocument1.name);
};

test.describe("universe within toggle", () => {
  test("defaults to showing original art, and toggling adds external-ip to the search's excluded tags", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithOneCard(page);

    const settingsModal = await openSearchSettingsModal(page);
    await expect(
      settingsModal.getByText("Showing Original Magic Art")
    ).toBeVisible();

    await settingsModal.getByText("Showing Original Magic Art").click();
    await expect(
      settingsModal.getByText("Hiding External IP Art")
    ).toBeVisible();

    // saving re-triggers search; the request body must now exclude external-ip
    const searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    const searchRequest = await searchRequestPromise;
    expect(
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags
    ).toContain("external-ip");
  });

  test("toggling back removes the external-ip exclusion exactly once", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithOneCard(page);

    // round 1: hide external IP art and save (saving an unchanged config triggers no search,
    // so the two directions are asserted across two save rounds)
    let settingsModal = await openSearchSettingsModal(page);
    await settingsModal.getByText("Showing Original Magic Art").click();
    let searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    let searchRequest = await searchRequestPromise;
    expect(
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags
    ).toContain("external-ip");

    // round 2: show it again - the exclusion is gone
    settingsModal = await openSearchSettingsModal(page);
    await settingsModal.getByText("Hiding External IP Art").click();
    await expect(
      settingsModal.getByText("Showing Original Magic Art")
    ).toBeVisible();
    searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    searchRequest = await searchRequestPromise;
    const excludesTags =
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags;
    expect(
      excludesTags.filter((tag: string) => tag === "external-ip")
    ).toHaveLength(0);
  });
});
