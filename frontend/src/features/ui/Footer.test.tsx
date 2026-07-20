import { render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, noBackend } from "@/common/test-constants";
import { backendInfo } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import Footer from "./Footer";

const sourceDisclosureText =
  "Card data comes from Scryfall. Card images are hosted by their " +
  "original uploaders — ProxyPrints indexes them, it doesn't store them.";

function renderFooter(backend: { url: string | null }) {
  const store = setupStore({ backend });
  render(
    <Provider store={store}>
      <Footer />
    </Provider>
  );
}

describe("Footer", () => {
  it("renders the source-disclosure line alongside the existing links (issue #170)", async () => {
    server.use(backendInfo);
    renderFooter(localBackend);

    const disclosure = await screen.findByTestId("footer-source-disclosure");
    expect(disclosure).toHaveTextContent(sourceDisclosureText);

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("About")).toBeInTheDocument();
    expect(screen.getByText("Privacy Policy")).toBeInTheDocument();
  });

  it("still renders the source-disclosure line with no remote backend configured", () => {
    renderFooter(noBackend);

    expect(screen.getByTestId("footer-source-disclosure")).toHaveTextContent(
      sourceDisclosureText
    );
  });
});
