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
// IS the unified page, /display only redirects there). A later transition this test protected
// against - the Finish footer's own "Print / Export ->" button doing a client-side
// `router.push("/print")` while cards were present - no longer exists at all: PDF export now runs
// in place from the editor's own Export dropdown (see docs/features/pdf-generator.md's "Page cut
// guide lines, Google Drive save, and retiring the Finish footer's own print route"), so there is
// no more editor -> /print navigation to guard against a false-positive dialog on. The happy-path
// test below now exercises that same class of regression against the export flow that replaced
// it - a real download completing with no beforeunload dialog appearing along the way.
test.describe("Unsaved-work guard (priority bug fix)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("editor: exporting a PDF with cards selected does not show any dialog, and the export completes", async ({
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

    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 30_000 }),
      (async () => {
        await page.getByTestId("display-export-menu-toggle").click();
        await page.getByTestId("display-export-pdf-button").click();

        // Cardback flow round (SPEC-cardback-pdfwait.md §C.1) - a fresh project is still riding
        // the untouched default cardback, so the reminder gate fires first; "Use current &
        // continue" proceeds with the export itself.
        const cardbackGate = page.getByTestId("pre-print-cardback-gate");
        await expect(cardbackGate).toBeVisible();
        await cardbackGate.getByTestId("cardback-gate-use-current").click();
      })(),
    ]);
    // A real download completed with the deck's own card, not an empty/failed export that
    // merely happened not to show a dialog - the store genuinely stayed populated in place
    // (no navigation ever happens for this flow any more).
    expect(download.suggestedFilename()).toBe("cards.pdf");

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
