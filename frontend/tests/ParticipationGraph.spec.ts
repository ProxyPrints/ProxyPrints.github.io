import { expect } from "@playwright/test";

import {
  catalogStatsAtRevealThreshold,
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

  // 2026-07-29 owner ruling - the "Start with one card" CTA after the hollow dot.
  test("shows a 'Start with one card' button linking to /whatsthat when a backend is configured", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    const cta = page.getByTestId("participation-graph-start-one-card");
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/whatsthat");

    await cta.click();
    await expect(page).toHaveURL(/\/whatsthat/);
  });

  test("hides the 'Start with one card' button on a self-hosted instance with no backend configured", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await page.goto("/");

    await expect(
      page.getByTestId("participation-graph-start-one-card")
    ).toHaveCount(0);
  });

  // 2026-07-29 owner ruling - the threshold-gated human-progress series
  // (features/stats/humanProgressReveal.ts).
  test("reveals the human-progress series once the ratio reaches the threshold", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsAtRevealThreshold, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(page.getByTestId("participation-graph")).toBeVisible();
    await expect(
      page.getByTestId("participation-graph-human-progress")
    ).toBeVisible();
    await expect(
      page.getByTestId("participation-graph-human-progress-bar")
    ).toBeVisible();
    await expect(
      page.getByText(
        "People are keeping up with what the machine routes to them"
      )
    ).toBeVisible();
  });

  test("does not show the human-progress series below the threshold", async ({
    page,
    network,
  }) => {
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    await expect(
      page.getByTestId("participation-graph-human-progress")
    ).toHaveCount(0);
    await expect(page.getByText("The catalog needs human eyes")).toBeVisible();
  });
});
