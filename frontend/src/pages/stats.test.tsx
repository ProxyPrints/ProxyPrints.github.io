/**
 * The cache-miss handling this task's directive requires (item 5): the endpoint is cache-only
 * and returns a fully-shaped, all-zero blob with `generatedAt: null` on a miss, never a 500 -
 * this page must render a clean "not computed yet" state on that, never an empty chart, never a
 * spinner forever, and never the zeroed panels presented as real data.
 */
import { render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, noBackend } from "@/common/test-constants";
import {
  backendInfo,
  catalogStatsCurrentRatio,
  catalogStatsNotComputedYet,
  tagsNoResults,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { CatalogStatsBody } from "./stats";

function renderBody(backend: { url: string | null }) {
  const store = setupStore({ backend });
  render(
    <Provider store={store}>
      <CatalogStatsBody />
    </Provider>
  );
}

describe("CatalogStatsBody (pages/stats.tsx)", () => {
  it("renders the no-backend default without a remote backend configured", () => {
    renderBody(noBackend);
    expect(screen.getByText("No Server Configured")).toBeInTheDocument();
  });

  it("renders a 'not computed yet' state on a cache miss (generatedAt: null), never zeroed panels presented as real data", async () => {
    server.use(catalogStatsNotComputedYet);
    renderBody(localBackend);

    expect(
      await screen.findByTestId("stats-not-computed-yet")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("participation-panel")).not.toBeInTheDocument();
    // Not rendered as if 0 confirmable/contested/etc were real, honest numbers.
    expect(screen.queryByTestId("stats-generated-at")).not.toBeInTheDocument();
  });

  it("renders the real panels plus generatedAt once the cache is warm", async () => {
    // The populated state also mounts ContributionGuidelines (useGetTagsQuery()) and Footer
    // (useGetBackendInfoQuery()) - both mocked here too so neither trips jest.setup.ts's
    // onUnhandledRequest: "error".
    server.use(catalogStatsCurrentRatio, tagsNoResults, backendInfo);
    renderBody(localBackend);

    expect(
      await screen.findByTestId("participation-panel")
    ).toBeInTheDocument();
    expect(screen.getByTestId("catalog-composition-panel")).toBeInTheDocument();
    expect(
      screen.getByTestId("contributions-over-time-panel")
    ).toBeInTheDocument();
    expect(screen.getByTestId("skip-breakdown-panel")).toBeInTheDocument();
    expect(screen.getByTestId("run-history-panel")).toBeInTheDocument();

    // Freshness is always shown once real - "generatedAt" is visible so a reader can judge how
    // stale the numbers are (the cache is warmed hourly, never live-aggregated per request).
    expect(screen.getByTestId("stats-generated-at")).toBeInTheDocument();
    expect(
      screen.queryByTestId("stats-not-computed-yet")
    ).not.toBeInTheDocument();

    // The headline call-to-action is `confirmable`, not a completion percentage.
    expect(screen.getByTestId("participation-confirmable")).toHaveTextContent(
      "103,687"
    );
    expect(screen.getByText("103,687")).toBeInTheDocument();
  });
});
