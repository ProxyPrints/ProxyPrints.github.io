import { expect } from "@playwright/test";

import {
  catalogStatsCurrentRatio,
  catalogStatsNotComputedYet,
  defaultHandlers,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Proposal F /stats page (docs/features/catalog-stats.md) - the transform of the old
// /contributions page (issue #233, 2026-07-29). Real-browser coverage of: the populated state
// rendering all five panels, the cache-miss "not computed yet" state (never zeroed panels
// presented as real data), the /contributions -> /stats redirect (old bookmarks still work), and
// the nav link restoring /stats to the top nav (N7/N8 reversal).
test.describe("/stats page", () => {
  test("renders all five panels plus generatedAt once the cache is warm", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "stats");

    await expect(page.getByTestId("participation-panel")).toBeVisible();
    await expect(page.getByTestId("catalog-composition-panel")).toBeVisible();
    await expect(
      page.getByTestId("contributions-over-time-panel")
    ).toBeVisible();
    await expect(page.getByTestId("skip-breakdown-panel")).toBeVisible();
    await expect(page.getByTestId("run-history-panel")).toBeVisible();
    await expect(page.getByTestId("stats-generated-at")).toBeVisible();

    // The headline call-to-action is confirmable, not a completion percentage.
    await expect(page.getByTestId("participation-confirmable")).toContainText(
      "103,687"
    );
  });

  test("renders the 'not computed yet' state on a cache miss, never zeroed panels as real data", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsNotComputedYet, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "stats");

    await expect(page.getByTestId("stats-not-computed-yet")).toBeVisible();
    await expect(page.getByTestId("participation-panel")).not.toBeVisible();
  });

  test("visiting the old /contributions URL redirects to /stats", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "contributions");

    await expect(page).toHaveURL(/\/stats/);
    await expect(page.getByTestId("participation-panel")).toBeVisible();
  });

  test("the top nav carries a Stats link that navigates to /stats", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "editor");

    await page.getByRole("link", { name: "Stats" }).click();
    await expect(page).toHaveURL(/\/stats/);
  });
});
