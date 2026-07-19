import { expect } from "@playwright/test";

import {
  defaultHandlers,
  whoamiAnonymousDiscordEnabled,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Regression coverage for a real, silent production bug: Navbar.tsx used to wrap <AuthWidget />
// in <Nav.Link eventKey="auth">, and react-bootstrap's Nav.Link-with-eventKey renders its own
// <a href="#"> around whatever children it's given. AuthWidget already renders a real <a> of its
// own for both states (sign-in/sign-out) - the result was nested anchors, which is invalid HTML
// and let the OUTER <a> silently intercept every click, so the inner Discord/logout link never
// actually navigated. No error was thrown anywhere and the anchor's own href was still correct,
// which is exactly why a render-only assertion ("does the link have the right href?") would have
// passed right through this bug undetected - only a real click-then-observe-navigation test
// catches it. See docs/lessons.md's "components that each correctly render an anchor can compose
// into invalid nested-anchor HTML" entry for the general lesson this generalizes to.
test.describe("Navbar - Discord auth links", () => {
  test("clicking Sign in actually initiates navigation to the login URL (not just renders the right href)", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymousDiscordEnabled, ...defaultHandlers);
    // Real top-level anchor navigation isn't something MSW's service worker intercepts (it has
    // no handler registered for this path anyway) - Playwright's own page.route stands in for a
    // real backend so the navigation completes deterministically instead of hanging/erroring
    // against a login URL nothing is actually listening on in this test environment.
    await page.route("**/accounts/discord/login/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<html></html>" })
    );
    await loadPageWithDefaultBackend(page, "editor");

    const loginLink = page.getByTestId("auth-widget-login");
    await expect(loginLink).toBeVisible();

    await Promise.all([
      page.waitForURL("**/accounts/discord/login/**"),
      loginLink.click(),
    ]);

    expect(page.url()).toContain("/accounts/discord/login/");
  });

  test("clicking Sign out actually initiates navigation to the logout URL (not just renders the right href)", async ({
    page,
    network,
  }) => {
    network.use(whoamiSignedInNotModerator, ...defaultHandlers);
    await page.route("**/accounts/logout/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<html></html>" })
    );
    await loadPageWithDefaultBackend(page, "editor");

    const logoutLink = page.getByTestId("auth-widget-logout");
    await expect(logoutLink).toBeVisible();

    await Promise.all([
      page.waitForURL("**/accounts/logout/**"),
      logoutLink.click(),
    ]);

    expect(page.url()).toContain("/accounts/logout/");
  });
});
