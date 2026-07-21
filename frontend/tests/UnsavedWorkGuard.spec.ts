import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

// Priority bug report: navigating editor -> /display with cards selected appeared to trigger the
// unsaved-work guard, blocking the primary path into /display. Diagnosis (see
// ProjectEditor.tsx's and chunkErrorRecovery.ts's own comments for the full writeup): the
// editor -> /display transition is ALREADY a normal client-side next/link nav (Navbar.tsx) that
// correctly preserves the Redux store - the real, narrower trigger was the app's own chunk-load-
// error recovery reload (chunkErrorRecovery.ts) firing the guard as a false positive when a
// target route's JS chunk failed to fetch. This file covers both the happy path (no false
// positive on a normal transition) and the guard's own genuine-exit behavior (still fires for a
// real reload), so a regression on either side is caught.
test.describe("Unsaved-work guard (priority bug fix)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("editor -> /display with cards selected does not show any dialog, and the same deck renders on arrival", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    let dialogAppeared = false;
    page.on("dialog", (dialog) => {
      dialogAppeared = true;
      void dialog.dismiss();
    });

    await page.getByRole("link", { name: "Display (beta)" }).click();

    // A real navigation, not just a same-page state change - waitForURL fails outright if the
    // click never actually left /editor, which is exactly the failure mode a regression here
    // would produce.
    await page.waitForURL("**/display");
    await expect(page.getByTestId("display-page")).toBeVisible();
    // Same deck, not an empty /display that merely happened not to show a dialog - the store
    // genuinely survived the transition, matching the client-side-nav diagnosis. D18
    // (proposal-h-display-layout-spec.md) - the default 14.5mm row gutter drops A4 landscape from
    // 4x2 (8) to 4x1 (4) at today's still-live 5mm margins/3.048mm bleed (D5/D6 margin/bleed
    // defaults haven't landed).
    await expect(page.getByTestId("page-preview-slot")).toHaveCount(4);

    expect(dialogAppeared).toBe(false);
  });

  test("a genuine exit (reloading the editor tab) still warns when the project has cards - the guard itself is unchanged for real exits", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    let dialogType: string | null = null;
    page.on("dialog", (dialog) => {
      dialogType = dialog.type();
      // Dismiss (not accept) - stay on /editor so the rest of this test, and any test that
      // happens to run after it against the same worker, isn't left on a half-reloaded page.
      void dialog.dismiss();
    });

    // A real full-page reload (not a next/link transition) - the same category of event as a
    // tab close or address-bar navigation as far as ProjectEditor's beforeunload listener is
    // concerned, none of which the priority-bug fix is meant to touch. Dismissing the dialog
    // above cancels the reload itself, so page.reload()'s own navigation promise never settles -
    // a short explicit timeout (not this test's whole budget) is what actually ends the wait;
    // what's being asserted is that the dialog appeared at all, not whether reload() as a
    // Node-side promise resolved cleanly.
    await page.reload({ timeout: 5_000 }).catch(() => {});

    expect(dialogType).toBe("beforeunload");
  });
});
