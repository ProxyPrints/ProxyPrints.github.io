import { render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend } from "@/common/test-constants";
import { setupStore } from "@/store/store";

import { HomepagePanel } from "./HomepagePanel";

function renderPanel(backend: { url: string | null }) {
  const store = setupStore({ backend });
  render(
    <Provider store={store}>
      <HomepagePanel />
    </Provider>
  );
}

describe("HomepagePanel", () => {
  it("renders both CTAs and the catalog-stats slot once a remote backend is configured", () => {
    renderPanel(localBackend);

    expect(screen.getByTestId("homepage-panel")).toBeInTheDocument();

    const whatsThatLink = screen.getByTestId("homepage-panel-whatsthat-link");
    expect(whatsThatLink).toHaveAttribute("href", "/whatsthat");

    const myDecksLink = screen.getByTestId("homepage-panel-mydecks-link");
    expect(myDecksLink).toHaveAttribute("href", "/myDecks");

    expect(
      screen.getByTestId("homepage-panel-catalog-stats-slot")
    ).toBeInTheDocument();
  });

  it("renders nothing without a remote backend configured (matches Navbar's own gating for these routes)", () => {
    renderPanel({ url: null });

    expect(screen.queryByTestId("homepage-panel")).not.toBeInTheDocument();
  });
});
