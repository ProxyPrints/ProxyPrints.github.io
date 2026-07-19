import { expect } from "@playwright/test";

import { defaultHandlers } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Homepage panel (frontend-polish package, queued item 2) - "confessing what the site is."
// Gating logic itself (hidden without a remote backend) is unit-tested directly in
// HomepagePanel.test.tsx, since simulating a Local-Folder-only session end to end here would
// need new Playwright infra this task didn't otherwise require. This covers the real-browser
// surface: both CTAs render with a remote backend configured (the default test setup) and
// actually navigate on click - not just that they render with the right href (see
// docs/lessons.md's nested-anchor lesson for why a click-through, not just an href assertion,
// is the test that actually catches a broken link).
test.describe("homepage panel", () => {
  test("renders both CTAs and the catalog-stats slot", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(page.getByTestId("homepage-panel")).toBeVisible();
    await expect(
      page.getByTestId("homepage-panel-whatsthat-link")
    ).toBeVisible();
    await expect(
      page.getByTestId("homepage-panel-mydecks-link")
    ).toBeVisible();
    await expect(
      page.getByTestId("homepage-panel-catalog-stats-slot")
    ).toContainText("coming soon");
  });

  test("clicking 'What's That Card?' actually navigates to /whatsthat", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await page.getByTestId("homepage-panel-whatsthat-link").click();
    await expect(page).toHaveURL(/\/whatsthat/);
  });

  test("clicking 'My Decks' actually navigates to /myDecks", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await page.getByTestId("homepage-panel-mydecks-link").click();
    await expect(page).toHaveURL(/\/myDecks/);
  });
});
