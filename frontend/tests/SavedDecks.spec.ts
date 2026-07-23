import { expect } from "@playwright/test";
import * as fs from "fs/promises";
import { http, HttpResponse } from "msw";
import * as os from "os";
import * as path from "path";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { CardType } from "@/common/schema_types";
import {
  buildMockSavedDeckSummary,
  existingProfileHandler,
  getSavedDecksHandler,
  noProfileHandler,
} from "@/features/savedDecks/cryptoTestHandlers";
import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

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

  // Nav+footer redesign (2026-07-22, N5) - My Decks was cut from the nav entirely (it now lives
  // in the homepage panel's own CTA and the editor landing, not a top-bar link), regardless of
  // auth state - this used to be two auth-gated tests ("hidden for anonymous"/"appears once
  // signed in"); now it's one test confirming the nav-link is gone unconditionally, with the
  // substantive "page prompts to unlock" assertion reached by direct navigation instead of a
  // nav-link click, since there's no nav link left to click.
  test("My Decks has no nav entry regardless of auth (cut per nav redesign), but the page itself still prompts to unlock once signed in", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiSignedInNotModerator,
      noProfileHandler(),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "editor");

    await expect(
      page.getByRole("link", { name: "My Decks" })
    ).not.toBeVisible();

    await loadPageWithDefaultBackend(page, "myDecks");
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
    await page.getByRole("link", { name: "Editor" }).click();

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
    await page.getByRole("link", { name: "Editor" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    await expect(
      page.getByTestId("display-toolbar").getByTestId("saved-deck-breadcrumb")
    ).not.toBeVisible();
    await expect(
      page.getByTestId("display-toolbar").getByRole("button", { name: "Save" })
    ).not.toBeVisible();
  });

  // Issue #268 (design doc §5/§6 rows S1-S3, landing cohesion with saved decks) - a signed-in
  // session with a saved deck sees it right on the empty-project /display landing, beside the
  // paste-a-decklist input, and can load it in place without ever visiting /myDecks. Reaches
  // /display via page.goto (loadPageWithDefaultBackend's default pageName), since the whole point
  // is the landing shown on a direct, fresh visit - unlike the toolbar tests above, there's no
  // prior /editor project to carry over.
  test("display landing shows saved decks beside the paste input; loading one populates the project", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    const namedDeck = await buildMockSavedDeckSummary(
      "deck-landing-1",
      "deck",
      {
        version: 2,
        name: "Boros Burn",
        members: [
          {
            front: {
              query: { query: "my search query", cardType: CardType.Card },
            },
            back: null,
          },
        ],
        cardback: null,
        manualOverrides: {},
        finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
        revision: 1,
        modifiedAt: "2026-01-01T00:00:00.000Z",
      },
      profile.masterKey,
      { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
    );
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([namedDeck]),
      ...threeCardHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();

    // Trigger-timing fix: the panel mounting (a saved deck exists) must NOT auto-prompt the
    // passphrase unlock on its own - the page's own paste-a-decklist/import inputs need to stay
    // usable immediately, unblocked by an unrequested modal. Unlock only fires once the user
    // deliberately engages the saved-decks affordance below - see useLoadSavedDeck.ts's own
    // `autoPromptOnLock` module comment for the full rationale (MyDecksPage keeps the auto-prompt
    // since arriving at /myDecks is itself the deliberate engagement; this landing panel doesn't).
    await expect(page.getByLabel("unlock-passphrase")).not.toBeVisible();
    await page.getByRole("button", { name: "Unlock my saved decks" }).click();
    await page.getByLabel("unlock-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "Unlock" }).click();

    const panel = page.getByTestId("saved-decks-landing-panel");
    await expect(panel.getByTestId("landing-named-decks-list")).toContainText(
      "Boros Burn"
    );
    await panel.getByRole("button", { name: "Load" }).click();

    await expect(page.getByTestId("display-empty-state")).toHaveCount(0);
    await expect(page.getByTestId("display-page")).toBeVisible();
    // D1/D4/D5/D6 (proposal-h-display-layout-spec.md, issue #286) - Letter landscape + Borderless
    // margins + 3.175mm bleed + D18's spacing lands the spec's own 4x2 (8) grid.
    await expect(page.getByTestId("page-preview-slot")).toHaveCount(8);
  });

  // Regression coverage for the trigger-timing bugfix (owner-reported: the unlock modal was
  // auto-popping on plain /display entry, gating the whole page - including the unrelated
  // paste-a-decklist/import inputs - behind a Cancel click). Documentary screenshots of both
  // states live in the PR body.
  test("display landing entry never gates the page behind the unlock modal; the modal only opens once the user deliberately engages saved decks", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    const namedDeck = await buildMockSavedDeckSummary(
      "deck-landing-2",
      "deck",
      {
        version: 2,
        name: "Mono Green Ramp",
        members: [],
        cardback: null,
        manualOverrides: {},
        finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
        revision: 1,
        modifiedAt: "2026-01-01T00:00:00.000Z",
      },
      profile.masterKey,
      { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
    );
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([namedDeck]),
      ...threeCardHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();

    // Page entry: no modal, and the ordinary import surfaces are immediately usable.
    await expect(page.getByTestId("unlock-modal")).toHaveCount(0);
    const listImport = page.getByRole("textbox", { name: "import-text" });
    await expect(listImport).toBeVisible();
    await expect(listImport).toBeEditable();
    await page.screenshot({
      path: path.join(os.tmpdir(), "saved-decks-page-entry-no-modal.png"),
    });

    // Deliberate engagement: the panel's own "Unlock my saved decks" affordance.
    await page.getByRole("button", { name: "Unlock my saved decks" }).click();
    await expect(page.getByTestId("unlock-modal")).toBeVisible();
    await page.screenshot({
      path: path.join(
        os.tmpdir(),
        "saved-decks-unlock-modal-on-engagement.png"
      ),
    });
  });

  // PR-6, post-v1 "deck portability" (docs/proposals/proposal-g-user-accounts-saved-decks.md) -
  // real-browser coverage for the one piece jsdom can't exercise faithfully: an actual file
  // download (Export) and an actual <input type="file"> selection (Import), both driven by the
  // browser's real WebCrypto rather than jest's jsdom polyfill.
  test("Export my decks downloads a bundle the standalone tool's own wire format understands", async ({
    page,
    network,
  }) => {
    const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
    const namedDeck = await buildMockSavedDeckSummary(
      "deck-1",
      "deck",
      {
        version: 2,
        name: "Standard Aggro",
        members: [],
        cardback: null,
        manualOverrides: {},
        finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
        revision: 1,
        modifiedAt: "2026-01-01T00:00:00.000Z",
      },
      profile.masterKey,
      { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
    );
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(profile),
      getSavedDecksHandler([namedDeck]),
      ...defaultHandlers
    );
    // My Decks has no nav entry since the redesign (N5) - navigate directly by URL.
    await loadPageWithDefaultBackend(page, "myDecks");

    await page.getByLabel("unlock-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "Unlock" }).click();
    await expect(page.getByTestId("named-decks-list")).toContainText(
      "Standard Aggro"
    );

    // Documentary screenshot of the shipped Export/Import UI (see PR body for the path).
    await page.screenshot({
      path: path.join(os.tmpdir(), "pr6-my-decks-export-import.png"),
    });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("export-my-decks").click(),
    ]);
    const downloadPath = await download.path();
    const bundleText = await fs.readFile(downloadPath, "utf-8");
    const bundle = JSON.parse(bundleText);
    expect(bundle.formatVersion).toEqual(1);
    expect(bundle.decks).toHaveLength(1);
    expect(bundle.cryptoProfile.kdfIterations).toEqual(TEST_ITERATIONS);
  });

  test("Import decks persists every deck in a selected export file as new, under the current session's key", async ({
    page,
    network,
  }) => {
    const bundleProfile = await createCryptoProfile(
      "the bundle's own passphrase",
      TEST_ITERATIONS
    );
    const currentProfile = await createCryptoProfile(
      PASSPHRASE,
      TEST_ITERATIONS
    );
    const { buildExportBundle, serializeExportBundle } = await import(
      "@/features/savedDecks/deckExportImport"
    );
    const { bytesToBase64 } = await import("@/common/savedDeckCrypto");
    const importedDeck = await buildMockSavedDeckSummary(
      "imported-deck",
      "deck",
      {
        version: 2,
        name: "Imported Deck",
        members: [],
        cardback: null,
        manualOverrides: {},
        finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
        revision: 2,
        modifiedAt: "2025-01-01T00:00:00.000Z",
      },
      bundleProfile.masterKey,
      { createdAt: "2025-01-01", updatedAt: "2025-01-02" }
    );
    const bundle = buildExportBundle(
      {
        exists: true,
        salt: bytesToBase64(bundleProfile.salt),
        kdfIterations: bundleProfile.iterations,
        passphraseWrappedMasterKey: bytesToBase64(
          bundleProfile.passphraseWrapped.wrapped
        ),
        passphraseWrappedMasterKeyNonce: bytesToBase64(
          bundleProfile.passphraseWrapped.nonce
        ),
        recoveryWrappedMasterKey: bytesToBase64(
          bundleProfile.recoveryWrapped.wrapped
        ),
        recoveryWrappedMasterKeyNonce: bytesToBase64(
          bundleProfile.recoveryWrapped.nonce
        ),
      },
      [importedDeck]
    );
    const bundleFilePath = path.join(os.tmpdir(), "pr6-import-fixture.json");
    await fs.writeFile(bundleFilePath, serializeExportBundle(bundle));

    const saveDeckRequests: Array<any> = [];
    network.use(
      whoamiSignedInNotModerator,
      existingProfileHandler(currentProfile),
      getSavedDecksHandler([]),
      http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
        saveDeckRequests.push(await request.json());
        return HttpResponse.json(
          { key: `new-${saveDeckRequests.length}` },
          { status: 200 }
        );
      }),
      ...defaultHandlers
    );
    // My Decks has no nav entry since the redesign (N5) - navigate directly by URL.
    await loadPageWithDefaultBackend(page, "myDecks");

    await page.getByLabel("unlock-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "Unlock" }).click();
    await expect(page.getByTestId("open-import-decks")).toBeEnabled();

    await page.getByTestId("open-import-decks").click();
    await page.getByLabel("import-file").setInputFiles(bundleFilePath);
    await expect(page.getByText("1 deck found")).toBeVisible();
    await page
      .getByLabel("import-passphrase")
      .fill("the bundle's own passphrase");
    await page.getByRole("button", { name: "Import", exact: true }).click();

    await expect(page.getByText("Imported 1 deck as new.")).toBeVisible();
    expect(saveDeckRequests).toHaveLength(1);
    expect(saveDeckRequests[0].key).toBeNull();
  });
});
