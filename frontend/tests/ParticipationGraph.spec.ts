import { expect } from "@playwright/test";

import {
  catalogStatsCurrentRatio,
  catalogStatsNotComputedYet,
  catalogStatsPostSweep,
  defaultHandlers,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Homepage front-page graph (Proposal F item 4, 2026-07-29 coordinator amendment) - real-browser
// coverage complementing ParticipationGraph.test.tsx's own fixture-parametrised regression guard.
// Real-browser wiring only here (does the homepage actually mount/gate the graph correctly); the
// "no percentage against total, reads correctly under both ratios" assertions live in the Jest
// test since they don't need a browser.
test.describe("homepage participation graph", () => {
  test("renders once the catalog-stats cache is warm, and links to /stats and /whatsthat", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(page.getByTestId("participation-graph")).toBeVisible();
    await expect(
      page.getByTestId("participation-graph-human-votes-total")
    ).toContainText("237");

    await page.getByRole("link", { name: "See the full stats" }).click();
    await expect(page).toHaveURL(/\/stats/);
  });

  test("also renders under the post-sweep ratio (worse human/machine ratio)", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsPostSweep, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(page.getByTestId("participation-graph")).toBeVisible();
    // distinctHumanVoters/humanVotes.total held flat post-sweep, per the amendment.
    await expect(
      page.getByTestId("participation-graph-distinct-voters")
    ).toContainText("11");
  });

  test("renders nothing on a cache miss (not a graph full of zeroes)", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsNotComputedYet, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(page.getByTestId("participation-graph")).not.toBeVisible();
  });
});
