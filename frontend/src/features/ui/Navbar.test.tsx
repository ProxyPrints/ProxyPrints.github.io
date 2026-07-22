import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { localBackend } from "@/common/test-constants";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import {
  whoamiAnonymous,
  whoamiAnonymousDiscordEnabled,
  whoamiModerator,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import ProjectNavbar from "./Navbar";

// The unified /display route is real production functionality behind this flag - the nav's
// own Editor link is additionally gated on it (see Navbar.tsx's own comment on why), so it
// needs to be on for these tests to see the link at all, mirroring playwright.config.ts's own
// webServer.env setting for the exact same reason.
process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED = "true";

const routerRoute = { current: "/editor" };
jest.mock("next/router", () => ({
  useRouter: () => ({
    route: routerRoute.current,
    pathname: routerRoute.current,
    push: jest.fn(),
  }),
}));

// useAnyBackendConfigured (Editor's own gate) also checks a Local Folder backend, which needs
// a ClientSearchContext - a stub Proxy is enough for that check to resolve without a real
// worker (same pattern Footer.test.tsx uses for the same context, via BackendConfig).
const stubClientSearchContext = {
  clientSearchService: new Proxy(
    {},
    { get: () => () => Promise.resolve(undefined) }
  ) as unknown as ClientSearchService,
  forceUpdate: () => undefined,
  forceUpdateValue: 0,
};

function renderNavbar() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <ClientSearchContextProvider value={stubClientSearchContext}>
        <ProjectNavbar />
      </ClientSearchContextProvider>
    </Provider>
  );
}

describe("Navbar - nav+footer redesign (N1-N7)", () => {
  beforeEach(() => {
    routerRoute.current = "/editor";
  });

  it("renders exactly the five surfaces (Editor, What's That Card?, Wiki, Sources, auth) and nothing the redesign cut", async () => {
    server.use(whoamiAnonymous);
    renderNavbar();

    expect(await screen.findByRole("link", { name: "Editor" })).toHaveAttribute(
      "href",
      "/display"
    );
    expect(
      screen.getByRole("link", { name: "What's That Card?" })
    ).toHaveAttribute("href", "/whatsthat");
    expect(screen.getByRole("link", { name: "Wiki" })).toHaveAttribute(
      "href",
      "/guide"
    );
    expect(screen.getByRole("button", { name: /Sources/ })).toBeInTheDocument();

    // N5 - cut entirely, no new home in the nav itself.
    expect(
      screen.queryByRole("link", { name: "What's New?" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Explore" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "My Decks" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Contributions" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Guide" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Download" })
    ).not.toBeInTheDocument();
    // The old classic-editor label/route - "Editor" now names /display instead (N2).
    expect(screen.queryByText("Display (beta)")).not.toBeInTheDocument();
  });

  // N3 - the label that used to tip the crowded left row into a wrapping navbar-height overflow.
  it("keeps What's That Card? on one line (white-space: nowrap)", async () => {
    server.use(whoamiAnonymous);
    renderNavbar();

    const link = await screen.findByRole("link", {
      name: "What's That Card?",
    });
    expect(link).toHaveStyle({ whiteSpace: "nowrap" });
  });

  it("signed-out: shows the one-line Discord Sign in pill, no user-menu dropdown", async () => {
    server.use(whoamiAnonymousDiscordEnabled);
    renderNavbar();

    const login = await screen.findByTestId("auth-widget-login");
    expect(login).toBeInTheDocument();
    expect(login).toHaveStyle({ whiteSpace: "nowrap" });
    expect(screen.queryByTestId("auth-widget-toggle")).not.toBeInTheDocument();
  });

  it("signed-in, non-moderator: opens a compact user-menu dropdown with Sign out but no Moderator entry", async () => {
    server.use(whoamiSignedInNotModerator);
    renderNavbar();

    const toggle = await screen.findByTestId("auth-widget-toggle");
    expect(toggle).toHaveTextContent("somebody");
    expect(screen.queryByTestId("auth-widget-logout")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(await screen.findByTestId("auth-widget-logout")).toBeInTheDocument();
    expect(
      screen.queryByTestId("auth-widget-moderator")
    ).not.toBeInTheDocument();
  });

  it("signed-in moderator: the dropdown also carries a Moderator entry", async () => {
    server.use(whoamiModerator);
    renderNavbar();

    const toggle = await screen.findByTestId("auth-widget-toggle");
    expect(toggle).toHaveTextContent("mod");

    await userEvent.click(toggle);

    expect(await screen.findByTestId("auth-widget-logout")).toBeInTheDocument();
    expect(screen.getByTestId("auth-widget-moderator")).toHaveAttribute(
      "href",
      "/whatsthat"
    );
  });
});
