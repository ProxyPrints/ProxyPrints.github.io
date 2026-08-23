import { expect, Page } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import {
  existingProfileHandler,
  getSavedDecksHandler,
} from "@/features/savedDecks/cryptoTestHandlers";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  whoamiAnonymous,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  completePdfExportToDisk,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Issue #275 (proposal-h-display-layout-spec.md ADDENDUM D9/D10) - the /display Finish footer
// (FinishFooter.tsx: "Save Deck", the Export dropdown, the draft-backed-up note) and its D9(3)
// pre-export save gate (PrePrintSaveGate.tsx).
//
// Editor export rescue (docs/features/pdf-generator.md's "Page cut guide lines, Google Drive
// save, and retiring the Finish footer's own print route") - the footer's separate co-equal
// "Print / Export ->" button (which used to client-side navigate to /print) is gone; PDF export
// lives solely in the Export dropdown's own "PDF" item (DisplayExportPDF.tsx), and its Download/
// Save-to-Drive buttons now run the same D9(3) gate sequence this file's own tests below drive
// (draft flush -> cardback reminder -> save-before-export prompt) before the export itself runs
// in place, no navigation anywhere.

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor is the unified page directly now
// (post-swap), so this helper populates it via the editor landing's own inline importer rather
// than hopping here from a separate classic /editor page via a nav-link click.
const goToDisplay = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "my search query");
  await expect(page.getByTestId("display-page")).toBeVisible();
};

// Opens the Export dropdown - the editor's own export entry point, now that FinishFooter.tsx no
// longer has a separate Print/Export button and PDF is a direct download action with no settings
// step of its own.
const openExportMenu = async (page: Page) => {
  const footer = page.getByTestId("display-finish-footer");
  await footer.getByTestId("display-export-menu-toggle").click();
  return footer;
};

test.describe("/display Finish footer (issue #275)", () => {
  test.describe.configure({ mode: "serial", timeout: 60_000 });

  test("anonymous: shows a sign-in link in place of Save Deck, no Print/Export button, and PDF export runs in place after the cardback gate (no save gate)", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...oneCardHandlers);
    await goToDisplay(page);

    const footer = page.getByTestId("display-finish-footer");
    await expect(
      footer.getByTestId("finish-footer-save-deck-signin")
    ).toBeVisible();
    await expect(footer.getByTestId("finish-footer-save-deck")).toHaveCount(0);
    // The old co-equal Print/Export button is gone entirely - PDF export lives solely in the
    // Export dropdown now (see this file's own module comment).
    await expect(footer.getByTestId("finish-footer-print-export")).toHaveCount(
      0
    );

    await openExportMenu(page);

    await footer.getByTestId("display-export-pdf-button").click();

    // Cardback flow round (SPEC-cardback-pdfwait.md §C.1) - a fresh project is still "riding
    // the untouched default" cardback, so the reminder gate fires before the (absent, for an
    // anonymous session) save gate / the export itself. "Use current & continue" is the
    // equivalent of this test's own old "no save gate, straight through" assertion.
    const cardbackGate = page.getByTestId("pre-print-cardback-gate");
    await expect(cardbackGate).toBeVisible();
    await cardbackGate.getByTestId("cardback-gate-use-current").click();

    const download = await completePdfExportToDisk(page);
    expect(download.suggestedFilename()).toBe("cards.pdf");
  });

  test("authenticated: shows the Save Deck button and, once a draft has backed up, the compact note", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([]),
      ...oneCardHandlers
    );
    await goToDisplay(page);

    const footer = page.getByTestId("display-finish-footer");
    await expect(footer.getByTestId("finish-footer-save-deck")).toBeVisible();
    await expect(
      footer.getByTestId("finish-footer-save-deck-signin")
    ).toHaveCount(0);

    // F1's debounced auto-backup (800ms) - the compact note only appears once a write has
    // actually happened this session.
    await expect(footer.getByTestId("finish-footer-draft-note")).toBeVisible({
      timeout: 5_000,
    });
  });

  test("authenticated + dirty: PDF export shows the save gate; choosing Save unlocks, saves, and the export still runs", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    const saveDeckRequests: Array<any> = [];
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([]),
      http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
        saveDeckRequests.push(await request.json());
        return HttpResponse.json({ key: "new-deck-key" }, { status: 200 });
      }),
      ...oneCardHandlers
    );
    await goToDisplay(page);

    const footer = await openExportMenu(page);

    await footer.getByTestId("display-export-pdf-button").click();

    // Cardback flow round (SPEC-cardback-pdfwait.md §C.1) - the reminder gate runs BEFORE the
    // save gate (a deck-completeness decision precedes the persistence one).
    const cardbackGate = page.getByTestId("pre-print-cardback-gate");
    await expect(cardbackGate).toBeVisible();
    await cardbackGate.getByTestId("cardback-gate-use-current").click();

    const gate = page.getByTestId("pre-print-save-gate-modal");
    await expect(gate).toBeVisible();
    await gate.getByTestId("pre-print-save-gate-save").click();

    // Crypto session starts locked this "session" (a fresh page load) - Save routes through
    // Unlock first, exactly like the toolbar's own Save button would.
    await page.getByLabel("unlock-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "Unlock" }).click();

    const saveModal = page.getByTestId("save-deck-modal");
    await expect(saveModal).toBeVisible();
    await page.getByLabel("save-deck-name").fill("My Print Test Deck");
    await saveModal.getByRole("button", { name: "Save", exact: true }).click();

    // Persistence resolves -> THEN the export itself runs - D9(3)c, "saving gates PDF; PDF never
    // gates saving" the other way around.
    const download = await completePdfExportToDisk(page);
    expect(download.suggestedFilename()).toBe("cards.pdf");
    expect(saveDeckRequests).toHaveLength(1);
  });

  test("authenticated + dirty: Skip on the save gate runs the export without saving", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    let saveDeckCalls = 0;
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([]),
      http.post("http://127.0.0.1:8000/2/saveDeck/", () => {
        saveDeckCalls += 1;
        return HttpResponse.json({ key: "unused" }, { status: 200 });
      }),
      ...oneCardHandlers
    );
    await goToDisplay(page);

    const footer = await openExportMenu(page);

    await footer.getByTestId("display-export-pdf-button").click();

    // Cardback flow round (SPEC-cardback-pdfwait.md §C.1) - the reminder gate runs BEFORE the
    // save gate (a deck-completeness decision precedes the persistence one).
    const cardbackGate = page.getByTestId("pre-print-cardback-gate");
    await expect(cardbackGate).toBeVisible();
    await cardbackGate.getByTestId("cardback-gate-use-current").click();

    const gate = page.getByTestId("pre-print-save-gate-modal");
    await expect(gate).toBeVisible();
    await gate.getByTestId("pre-print-save-gate-skip").click();

    const download = await completePdfExportToDisk(page);
    expect(download.suggestedFilename()).toBe("cards.pdf");
    expect(saveDeckCalls).toBe(0);
  });
});

test.describe("/display local draft auto-backup + restore nudge (issue #275)", () => {
  test("emptying the project resurfaces a restore nudge for the just-backed-up draft, and Restore rehydrates it", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...oneCardHandlers);
    await goToDisplay(page);

    // Wait for F1's debounced write, then empty the project via the rail's own Delete action -
    // no reload needed: the restore-nudge check re-runs the moment isProjectEmpty flips true,
    // same session.
    await page
      .getByTestId("display-finish-footer")
      .getByTestId("finish-footer-draft-note")
      .waitFor({ timeout: 5_000 });

    // Rail-delegacy round (SPEC-rail-delegacy.md §F item 7/RD5) - Slot Actions is unconditionally
    // visible inside the bottom control stack now, no accordion header to expand first (same
    // pattern as DisplayPage.spec.ts's "the Slot Actions section's Delete removes the slot..."
    // test - the old grey `AutofillCollapse` heading click this test used to need is gone).
    await page.getByTestId("page-preview-slot").first().click();
    await page.getByTestId("display-slot-action-delete").click();

    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    const banner = page.getByTestId("display-restore-draft-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("1 card");

    await banner.getByTestId("display-restore-draft-accept").click();

    await expect(page.getByTestId("display-empty-state")).toHaveCount(0);
    // Every grid position still renders a `page-preview-slot` placeholder (8, this page's own
    // default Letter/Rear-feed/3.175mm-bleed 4x2 capacity) regardless of how many are filled -
    // only the resolved `<img>` count reflects the actually-restored member (DisplayPage.spec.ts's
    // own established pattern for this same distinction).
    await expect(
      page.getByTestId("page-preview-slot").locator("img")
    ).toHaveCount(1);
  });

  // Nav+footer redesign (2026-07-22, N10) - the cloud download-queue counter/manager used to
  // live in the global navbar; cut from there and re-mounted here, beside the existing Export
  // dropdown, since this is where the lightweight XML/Card Images/Decklist downloads it counts
  // actually originate on this page (print.tsx's own mount covers the PDF/desktop-tool side).
  test("the relocated download-manager toggle opens its offcanvas from the Finish footer", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...oneCardHandlers);
    await goToDisplay(page);

    const footer = page.getByTestId("display-finish-footer");
    const toggle = footer.getByTestId("download-manager-toggle");
    await expect(toggle).toBeVisible();

    await expect(page.getByTestId("download-manager-offcanvas")).toHaveCount(0);
    await toggle.click();
    await expect(page.getByTestId("download-manager-offcanvas")).toBeVisible();
  });
});
