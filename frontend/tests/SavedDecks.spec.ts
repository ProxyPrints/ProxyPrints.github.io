import { expect } from "@playwright/test";

import { noProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { defaultHandlers, whoamiSignedInNotModerator } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Proposal G, PR4b - real-browser smoke coverage for the pieces most reliant on jsdom-absent
// browser behavior (WebCrypto is polyfilled in jest; here it's the real thing) and for the
// nav-gated visibility this feature depends on.
test.describe("saved decks", () => {
  test("editor shows the Save action and breadcrumb once signed in", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiSignedInNotModerator,
      noProfileHandler(),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "editor");

    await expect(page.getByTestId("saved-deck-breadcrumb")).toHaveText(
      "Unsaved project"
    );
    // the project is empty at this point in loadPageWithDefaultBackend, so Save is disabled
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  test("My Decks nav entry is hidden for an anonymous session", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers); // defaultHandlers includes whoamiAnonymous
    await loadPageWithDefaultBackend(page, "editor");

    await expect(
      page.getByRole("link", { name: "My Decks" })
    ).not.toBeVisible();
  });

  test("My Decks nav entry appears once signed in, and the page prompts to unlock", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiSignedInNotModerator,
      noProfileHandler(),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "editor");

    await page.getByRole("link", { name: "My Decks" }).click();
    await expect(
      page.getByText(
        "You haven't saved any decks yet - save your current project from the editor to get started."
      )
    ).toBeVisible();
  });
});
