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

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// the Search Settings modal (openSearchSettingsModal) is the same self-contained, unforked
// component DisplayPage.tsx's own toolbar mounts (see DisplayPage.spec.ts's own precedent test),
// reachable directly with no other DOM changes needed.

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

test.describe("show mature content toggle", () => {
  test("defaults to hiding, and toggling removes NSFW from the search's excluded tags", async ({
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
      settingsModal.getByText("Hiding Mature Content")
    ).toBeVisible();

    await settingsModal.getByText("Hiding Mature Content").click();
    await expect(
      settingsModal.getByText("Showing Mature Content")
    ).toBeVisible();

    // saving re-triggers search; the request body must no longer exclude NSFW
    const searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    const searchRequest = await searchRequestPromise;
    expect(
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags
    ).not.toContain("NSFW");
  });

  test("toggling back re-adds the NSFW exclusion exactly once", async ({
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

    // round 1: show mature content and save (saving an unchanged config triggers no search,
    // so the two directions are asserted across two save rounds)
    let settingsModal = await openSearchSettingsModal(page);
    await settingsModal.getByText("Hiding Mature Content").click();
    let searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    let searchRequest = await searchRequestPromise;
    expect(
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags
    ).not.toContain("NSFW");

    // round 2: hide it again - the exclusion returns, exactly once
    settingsModal = await openSearchSettingsModal(page);
    await settingsModal.getByText("Showing Mature Content").click();
    await expect(
      settingsModal.getByText("Hiding Mature Content")
    ).toBeVisible();
    searchRequestPromise = page.waitForRequest((request) =>
      request.url().includes("editorSearch")
    );
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    searchRequest = await searchRequestPromise;
    const excludesTags =
      searchRequest.postDataJSON().searchSettings.filterSettings.excludesTags;
    expect(excludesTags.filter((tag: string) => tag === "NSFW")).toHaveLength(
      1
    );
  });
});
