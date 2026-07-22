import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, noBackend } from "@/common/test-constants";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { backendInfo, tagsNoResults } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import Footer from "./Footer";

const sourceDisclosureText =
  "Card data comes from Scryfall. Card images are hosted by their " +
  "original uploaders — ProxyPrints indexes them, it doesn't store them.";

// Footer's own "Sources" button (new, N8) opens the same BackendConfig offcanvas the navbar's
// Sources button does - BackendConfig unconditionally mounts LocalFolderBackendConfig, which
// needs a ClientSearchContext (Layout.tsx provides a real one app-wide; a stub is enough here,
// same pattern Card.test.tsx already uses for the same context).
// A Proxy rather than hand-enumerating every ClientSearchService method BackendConfig's
// LocalFolderBackendConfig/GoogleDriveBackendConfig subtrees call in their mount-time
// useEffects (getLocalFilesDirectoryHandle, getDirectoryIndexSize, ...) - every call resolves
// to undefined, which is enough for this offcanvas to mount without throwing; nothing here
// asserts on local-folder/Google Drive indexing behavior itself.
const stubClientSearchService = new Proxy(
  {},
  { get: () => () => Promise.resolve(undefined) }
) as unknown as ClientSearchService;

const stubClientSearchContext = {
  clientSearchService: stubClientSearchService,
  forceUpdate: () => undefined,
  forceUpdateValue: 0,
};

function renderFooter(backend: { url: string | null }) {
  const store = setupStore({ backend });
  render(
    <Provider store={store}>
      <ClientSearchContextProvider value={stubClientSearchContext}>
        <Footer />
      </ClientSearchContextProvider>
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

    // Reddit/Discord are backend-gated - both are present in the mocked backendInfo above.
    expect(await screen.findByText("Reddit")).toBeInTheDocument();
    expect(await screen.findByText("Discord")).toBeInTheDocument();
  });

  it("still renders the source-disclosure line with no remote backend configured", () => {
    renderFooter(noBackend);

    expect(screen.getByTestId("footer-source-disclosure")).toHaveTextContent(
      sourceDisclosureText
    );
  });

  // Nav+footer redesign (2026-07-22, N8) - the new three-tier footer: Contributions/Wiki cut
  // from the navbar land here as ordinary links, "Sources" opens the same BackendConfig
  // offcanvas the navbar's own Sources button does, Terms is a new /about anchor, and the
  // chilli_axe credit links to their GitHub only (no Buy-Me-a-Coffee button - the owner
  // explicitly declined one in the footer; components/Coffee.tsx elsewhere is untouched).
  it("renders the site links the navbar dropped, plus Terms and the chilli_axe credit", () => {
    renderFooter(localBackend);

    const contributions = screen.getByText("Contributions");
    expect(contributions).toHaveAttribute("href", "/contributions");

    const wiki = screen.getByText("Wiki");
    expect(wiki).toHaveAttribute("href", "/guide");

    const terms = screen.getByText("Terms");
    expect(terms).toHaveAttribute("href", "/about#terms-of-use");

    const credit = screen.getByTestId("footer-chilli-axe-credit");
    expect(credit).toHaveAttribute("href", "https://github.com/chilli-axe");

    expect(screen.queryByText(/buy me a coffee/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/support chilli_axe/i)).not.toBeInTheDocument();
  });

  it("Sources opens the BackendConfig offcanvas", async () => {
    // BackendConfig's GoogleDriveBackendConfig sub-tree fires a tags query on mount -
    // unrelated to what this test asserts on, just needs a handler so MSW doesn't warn.
    server.use(tagsNoResults);
    renderFooter(localBackend);

    expect(screen.queryByText("Configure Sources")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("footer-sources-button"));
    expect(await screen.findByText("Configure Sources")).toBeInTheDocument();
    // Flushes LocalFolderBackendConfig's own post-transition-mount effect (it resolves the
    // stubbed clientSearchService promise a tick after the offcanvas becomes visible) so it
    // doesn't fire an act() warning after this test has already finished.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
});
