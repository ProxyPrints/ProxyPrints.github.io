import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

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
//
// Proposal H switchover (2026-07-23, issues #231/#272) note: the original editor -> /display
// nav-link transition this first test exercised no longer exists as a cross-page hop (/editor now
// IS the unified page, /display only redirects there). The same class of client-side transition
// this test protects against still exists on the unified page itself though - the Finish
// footer's "Print / Export ->" button (PrePrintSaveGate.tsx) does a real client-side
// `router.push("/print")` while cards are present, so that's the transition exercised below now.
test.describe("Unsaved-work guard (priority bug fix)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("editor -> /print with cards selected does not show any dialog, and the deck's cards are the ones sent to print", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    let dialogAppeared = false;
    page.on("dialog", (dialog) => {
      dialogAppeared = true;
      void dialog.dismiss();
    });

    await page.getByTestId("finish-footer-print-export").click();

    // A real navigation, not just a same-page state change - waitForURL fails outright if the
    // click never actually left /editor, which is exactly the failure mode a regression here
    // would produce. Generous explicit timeout - /print's first on-demand dev-mode compile
    // (@react-pdf/renderer transitively, via FinishedMyProject/PDFGenerator) is slow, the same
    // documented cost DisplayPage.spec.ts's own describe.configure covers for /display's first
    // hit; see DisplayFinishFooter.spec.ts's own comment for the same finding against this route.
    await page.waitForURL("**/print", { timeout: 30_000 });
    // Same deck, not an empty print page that merely happened not to show a dialog - the store
    // genuinely survived the transition, matching the client-side-nav diagnosis.
    await expect(page.getByTestId("print-page-empty-state")).toHaveCount(0);

    expect(dialogAppeared).toBe(false);
  });

  test("a genuine exit (reloading the editor tab) still warns when the project has cards - the guard itself is unchanged for real exits", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

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
