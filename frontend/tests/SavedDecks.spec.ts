import { expect } from "@playwright/test";

import { noProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

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

  // Issue #165, Proposal G save integration into Proposal H's unified display page (docs/
  // proposals/proposal-h-unified-display-page.md) - the exact same SavedDeckPanel the editor's
  // right panel mounts, wired into /display's own toolbar (see DisplayPage.tsx's own comment for
  // why this is a props-level reuse, not a fork). Reaches /display via the navbar link (client-
  // side navigation), not page.goto("/display", ...) directly, so the cards imported on /editor
  // survive into the new page - same precedent as DisplayPage.spec.ts's own tests.
  test("display toolbar shows the Save action and breadcrumb once signed in", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiSignedInNotModerator,
      noProfileHandler(),
      ...threeCardHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    await expect(
      page.getByTestId("display-toolbar").getByTestId("saved-deck-breadcrumb")
    ).toHaveText("Unsaved project");
    await expect(
      page.getByTestId("display-toolbar").getByRole("button", { name: "Save" })
    ).toBeEnabled();
  });

  test("display toolbar hides the Save action and breadcrumb for an anonymous session", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers); // defaultHandlers includes whoamiAnonymous
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    await expect(
      page.getByTestId("display-toolbar").getByTestId("saved-deck-breadcrumb")
    ).not.toBeVisible();
    await expect(
      page.getByTestId("display-toolbar").getByRole("button", { name: "Save" })
    ).not.toBeVisible();
  });
});
