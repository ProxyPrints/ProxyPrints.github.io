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
import { importText, loadPageWithDefaultBackend } from "./test-utils";

// Issue #275 (proposal-h-display-layout-spec.md ADDENDUM D9/D10) - the /display Finish footer
// (FinishFooter.tsx: co-equal "Save Deck"/"Print / Export ->", the draft-backed-up note) and its
// D9(3) pre-print save gate (PrePrintSaveGate.tsx). These are real, new user journeys - not just
// selector renames of the old three-button "Prepare Print" stack these replace (that stack's own
// dedicated coverage, DisplayPageExport.spec.ts, is retired alongside it - its subject no longer
// exists on this page; PDFGenerator.spec.ts already covers the underlying pipeline mechanics
// unchanged, since PDF generation now lives solely on the Print page via the same unforked
// PDFGenerator.tsx).

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

const goToDisplay = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importText(page, "my search query");
  await page.getByRole("link", { name: "Display (beta)" }).click();
  await expect(page.getByTestId("display-page")).toBeVisible();
};

test.describe("/display Finish footer (issue #275)", () => {
  test("anonymous: shows a sign-in link in place of Save Deck, and Print / Export navigates straight to the Print page", async ({
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

    await footer.getByTestId("finish-footer-print-export").click();

    // No save gate for an anonymous session (D9(3): "authenticated AND dirty" gates the prompt) -
    // straight through to the Print page.
    await expect(page).toHaveURL(/\/print/);
    await expect(page.getByRole("tab", { name: "PDF" })).toBeVisible();
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

  test("authenticated + dirty: Print / Export shows the save gate; choosing Save unlocks, saves, and lands on the Print page", async ({
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

    await page
      .getByTestId("display-finish-footer")
      .getByTestId("finish-footer-print-export")
      .click();

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

    // Persistence resolves -> THEN navigation - D9(3)c, "saving gates PDF; PDF never gates
    // saving" the other way around.
    await expect(page).toHaveURL(/\/print/);
    await expect(page.getByRole("tab", { name: "PDF" })).toBeVisible();
    expect(saveDeckRequests).toHaveLength(1);
  });

  test("authenticated + dirty: Skip on the save gate navigates to the Print page without saving", async ({
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

    await page
      .getByTestId("display-finish-footer")
      .getByTestId("finish-footer-print-export")
      .click();

    const gate = page.getByTestId("pre-print-save-gate-modal");
    await expect(gate).toBeVisible();
    await gate.getByTestId("pre-print-save-gate-skip").click();

    await expect(page).toHaveURL(/\/print/);
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

    await page.getByTestId("page-preview-slot").first().click();
    await page
      .getByRole("heading", { name: "Slot Actions", exact: true })
      .click();
    await page.getByTestId("display-slot-action-delete").click();

    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    const banner = page.getByTestId("display-restore-draft-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("1 card");

    await banner.getByTestId("display-restore-draft-accept").click();

    await expect(page.getByTestId("display-empty-state")).toHaveCount(0);
    // Every grid position still renders a `page-preview-slot` placeholder (8, this page's own
    // default Letter/Borderless/3.175mm-bleed 4x2 capacity) regardless of how many are filled -
    // only the resolved `<img>` count reflects the actually-restored member (DisplayPage.spec.ts's
    // own established pattern for this same distinction).
    await expect(
      page.getByTestId("page-preview-slot").locator("img")
    ).toHaveCount(1);
  });
});
