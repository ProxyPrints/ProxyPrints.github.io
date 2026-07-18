import { expect } from "@playwright/test";

import {
  defaultHandlers,
  whoamiAnonymousDiscordEnabled,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// The Moderation tab itself (Reports/Drives sub-tabs) is covered separately - see
// ModerationTab.spec.ts. This file is just the AuthWidget's login/logout links, now mounted
// in the navbar (docs/proposals/proposal-g-user-accounts-saved-decks.md decision 6) and
// rendered on every page - exercised here via /editor specifically (rather than /whatsthat,
// where the widget used to live pre-relocation) to prove it's no longer page-specific.
test.describe("auth links", () => {
  test("anonymous user with Discord disabled sees no login link", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers); // defaultHandlers includes whoamiAnonymous
    await loadPageWithDefaultBackend(page, "editor");

    await expect(page.getByTestId("auth-widget")).not.toBeVisible();
  });

  test("anonymous user with Discord enabled sees a login link that round-trips", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymousDiscordEnabled, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "editor");

    const login = page.getByTestId("auth-widget-login");
    await expect(login).toBeVisible();
    const href = await login.getAttribute("href");
    expect(href).toContain("/accounts/discord/login/?next=");
    expect(href).toContain(encodeURIComponent("editor"));
  });

  test("signed-in non-moderator gets a logout link", async ({
    page,
    network,
  }) => {
    network.use(whoamiSignedInNotModerator, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "editor");

    await expect(page.getByTestId("auth-widget-logout")).toBeVisible();
  });
});
