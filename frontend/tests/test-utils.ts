import { expect, Locator, Page } from "@playwright/test";
import { readFile } from "fs/promises";

export const configureBackend = async (page: Page, url: string) => {
  await page.getByLabel("configure-server-btn").click();
  await page.getByRole("textbox", { name: "backend-url" }).click();
  await page.getByRole("textbox", { name: "backend-url" }).fill(url);
  await page.getByRole("button", { name: "submit-backend-url" }).click();
  await expect(
    page.getByTestId("backend-offcanvas").getByRole("alert")
  ).toContainText(`You\'re connected to ${url}`);
  await page
    .getByTestId("backend-offcanvas")
    .getByRole("button", { name: "Close" })
    .click();
};

export const configureDefaultBackend = async (page: Page) =>
  configureBackend(page, "http://127.0.0.1:8000");

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`), not the classic grid `ProjectEditor` this helper used to
// assume. The old "editor" special-case (click "Choose Art", wait for "Your project is empty at
// the moment.") described that classic page's own onboarding flow and no longer applies to
// anything reachable by URL - the classic page is fully unrouted (component kept in-tree, not
// deleted; see pages/editor.tsx's own comment). Callers that still depend on that classic-only
// onboarding/DOM (many pre-swap suites do) are the swap's own known, tracked test-suite
// regression - see this swap's PR description for the full list and rationale, not silently
// worked around here.
export const loadPageWithDefaultBackend = async (
  page: Page,
  pageName: string = "editor"
) => {
  await page.goto(`/${pageName}?server=http://127.0.0.1:8000`);
};

// "What's New?" was cut from the nav entirely (N5) - /new itself still exists, just
// nav-unreachable, so this goes there directly by URL instead of clicking a now-gone nav link.
export const navigateToNew = async (page: Page) =>
  await page.goto("/new?server=http://127.0.0.1:8000");

export const getAddCardsMenu = (page: Page) => {
  return page
    .getByTestId("right-panel")
    .getByText("Add Cards", { exact: false });
};

export const openAddCardsDropdown = async (page: Page) => {
  const textButton = page.getByRole("button", { name: " Text" });
  if (await textButton.isVisible()) {
    return;
  }
  // this looks stupid but actually prevents our tests from being flaky.
  // sometimes playwright is too "fast" (?) and clicking the button doesn't open the dropdown.
  // (the rare human comment amongst the AI slop)
  await expect(async () => {
    await getAddCardsMenu(page).click();
    await expect(textButton).toBeVisible();
  }).toPass({ timeout: 10_000 });
};

export const openImportTextModal = async (page: Page) => {
  await openAddCardsDropdown(page);
  const textButton = await page.getByRole("button", { name: " Text" }).click();
};

// The unified editor's (`/editor`, post-swap - see loadPageWithDefaultBackend's own comment)
// empty-project landing renders its `import-text` textbox directly, with no "Add Cards"
// dropdown to open first (unlike `importText` above, which is the classic grid editor's own
// flow and no longer reachable by URL) - see DisplayPage.spec.ts's own empty-landing tests for
// the precedent this mirrors.
export const importTextOnEditorLanding = async (page: Page, text: string) => {
  await page.getByRole("textbox", { name: "import-text" }).fill(text);
  await page.getByRole("button", { name: "import-text-submit" }).click();
  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeVisible();
};

// Card-detail modal ecosystem parity port (2026-07-23, issue #272 wave 1). The classic editor
// opened the real, unforked `CardDetailedViewModal` (`data-testid="detailed-view"`) by clicking
// ANY card image in the grid. On the unified `/editor` page that same click behaviour
// (`showDetailedViewOnClick`, `Card.tsx`) is suppressed everywhere a `cardOnClick` handler is
// also wired - which is every `EditorCard` mount on this page except one: the Browse-mode catalog
// tiles `CatalogBrowseResults.tsx` renders have no `cardOnClick` at all, so clicking one still
// opens the real modal, unmodified. (Sheet slots select the rail instead; Select Version's own
// candidate tiles select an image instead - neither opens this modal any more.) This helper
// re-runs the caller's own already-mocked query through Browse mode and opens that result's
// detail view - the KNOWN fix this whole cluster needed (2026-07-23 triage): the unified page's
// left rail ALSO renders "Card details" text verbatim, lowercased, in its offcanvas dialog title
// and edge-handle button (both present in the DOM regardless of viewport/rail state) - a bare
// `getByText("Card Details")` (case-insensitive substring match by default) hit a 3-way
// strict-mode collision. Scoping to the modal's own `detailed-view` testid (NOT a heading role -
// react-bootstrap's `Modal.Title` renders a styled `<div>`, not a real heading element) resolves
// it once, here, for the whole cluster - consolidated out of near-duplicate helpers previously
// declared separately in ArtistSupportLink/VotePickers/ReportCard/AddCardToFavorites' own spec
// files (each still assuming the classic grid's plain "click the grid image" flow).
export const openDetailedView = async (
  page: Page,
  query: string,
  cardIdentifier: string
) => {
  await page.getByTestId("display-search-mode-browse").click();
  await page.getByTestId("display-browse-search-input").fill(query);
  const tile = page.getByTestId(`catalog-browse-tile-${cardIdentifier}`);
  await expect(tile).toBeVisible();
  await tile.locator("img").click();
  await expect(
    page.getByTestId("detailed-view").getByText("Card Details")
  ).toBeVisible();
};

export const closeDetailedView = async (page: Page) => {
  await page.getByTestId("detailed-view").getByLabel("Close").click();
  await expect(page.getByTestId("detailed-view")).not.toBeVisible();
};

// Proposal H parity port (2026-07-23, issue #272 wave 1): the classic grid's `front-slot`/
// `back-slot` testids (and the "N / M" selected/total-image fraction `CardSlot.tsx` rendered
// inline on each one) have no equivalent on the unified page - `PagePreview.tsx` renders each
// sheet slot as a plain, un-testid'd `<img alt={cardName}>`, with no inline candidate-count
// readout at all (that signal, where it exists, lives one layer deeper - the slot's own rail -
// and isn't reconstructable slot-by-slot without opening each one individually, which these
// import-cluster tests never needed to do before). These two helpers port the part that IS
// cleanly available: which named card is showing, for a given (1-based, row-major) sheet slot and
// face. `selectedImage`/`totalImages` numeric assertions are dropped, not silently - every
// fixture in this suite gives each result-set index its own distinct `name` (Card 1/2/3/...), so
// asserting the right NAME landed in the right slot already fully captures what those counts were
// standing in for (which specific candidate got auto-selected); see this port's own report for
// the one place that stops being true.
export const ensureDisplayFace = async (page: Page, face: "front" | "back") => {
  const wantLabel = face === "front" ? "Showing: Fronts" : "Showing: Backs";
  const otherLabel = face === "front" ? "Showing: Backs" : "Showing: Fronts";
  if (await page.getByText(otherLabel).isVisible()) {
    await page.getByText(otherLabel).click();
  }
  await expect(page.getByText(wantLabel)).toBeVisible();
};

export const expectDisplaySheetSlotState = async (
  page: Page,
  slot: number,
  face: "front" | "back",
  cardName: string
) => {
  await ensureDisplayFace(page, face);
  const sheetSlot = page.getByTestId("page-preview-slot").nth(slot - 1);
  await expect(sheetSlot.locator("img")).toHaveAttribute("alt", cardName);
};

interface DisplaySheetSlotAssertion {
  slot: number;
  name: string;
}

export const expectDisplaySheetSlotStates = async (
  page: Page,
  fronts: Array<DisplaySheetSlotAssertion>,
  backs: Array<DisplaySheetSlotAssertion>
) => {
  for (const { slot, name } of fronts) {
    await expectDisplaySheetSlotState(page, slot, "front", name);
  }
  for (const { slot, name } of backs) {
    await expectDisplaySheetSlotState(page, slot, "back", name);
  }
  // leave face state as fronts, matching expectCardGridSlotStates' own toggle-back convention
  await ensureDisplayFace(page, "front");
};

// Every sheet position renders a `page-preview-slot` div regardless of whether it's a real
// project member (PagePreview.tsx's own comment: "every cell gets a slot, only some get an
// <img>"), so an unfilled/no-query "gap" slot (a real project member with nothing resolved for it
// yet) is indistinguishable at a glance from a genuinely-past-the-end-of-the-deck empty grid cell
// - neither renders an `<img>`. Clicking through to the rail disambiguates: only a real project
// member selects it (`display-rail-header` shows "Slot N"); a past-the-end grid position ignores
// the click (DisplayPage.tsx's own onSlotClick guard) and the rail stays idle.
export const expectDisplaySheetSlotToExist = async (
  page: Page,
  slot: number
) => {
  await page
    .getByTestId("page-preview-slot")
    .nth(slot - 1)
    .click();
  await expect(page.getByTestId("display-rail-header")).toContainText(
    `Slot ${slot}`
  );
};

export const expectDisplaySheetSlotToNotExist = async (
  page: Page,
  slot: number
) => {
  await expect(
    page
      .getByTestId("page-preview-slot")
      .nth(slot - 1)
      .locator("img")
  ).toHaveCount(0);
};

// The populated-project toolbar's compact search-bar row (ImportText's "inline" variant, no
// Submit button of its own - a plain browser form submit fires on Enter, see ImportText.tsx's own
// comment) - the unified page's equivalent of importText's "add more cards to a non-empty
// project" step above.
export const importTextInline = async (page: Page, text: string) => {
  const field = page.getByRole("textbox", { name: "import-text-inline" });
  await field.fill(text);
  await field.press("Enter");
  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeVisible();
};

export const importText = async (page: Page, text: string) => {
  await openImportTextModal(page);
  await page.getByRole("textbox", { name: "import-text" }).fill(text);
  await page.getByRole("button", { name: "import-text-submit" }).click();
  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeVisible();
};

// Issue #167 (Select Version section) - navigates to the unified /editor page with a slot
// selected, so its always-open Select Version surface (and the rest of the promoted/demoted rail
// content around it) is on screen. Shared by SelectVersionSection.spec.ts (issue #167's own
// behavior coverage, currently skipped pending its own #272 port - see that file's header) and
// DisplayLeftRailFidelity.spec.ts (SPEC-display-left-rail.md's permanent CSS-fidelity guard - see
// that file's own module comment) so both drive the identical navigation path rather than each
// re-deriving it. Ported (2026-07-23, Proposal H route swap) from the pre-swap classic-editor
// flow: `openAddCardsDropdown`'s "Add Cards" menu doesn't exist on the unified page's
// empty-project landing (that's populated-project-only UI, mounted in the toolbar), and the old
// "Editor" nav-link click targeted the separate /display route, which is now just a redirect
// shim back to /editor (pages/display.tsx) - both replaced with `importTextOnEditorLanding`'s
// direct landing-page textbox, matching every other wave-1-ported test's own setup
// (DisplayPage.spec.ts).
export const openSelectVersionSection = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "my search query");
  await page.getByTestId("page-preview-slot").first().click();
  // The rail always renders compressed tiles now (editor-completion package, E4/L9 - the
  // toggle is gone entirely, hard-pinned true) - no "Compressed" click needed any more.
};

// Parked-spec port wave (2026-07-24, issue #272; PDFGenerator/PagePreview/PostExportContribution-
// Prompt specs). PDF generation now lives solely on the standalone /print route (D10,
// pages/print.tsx) - the classic grid's own "Print!" tab this helper used to click through
// (ProjectEditor.tsx's own PrintPanel) no longer exists anywhere reachable. The unified page's
// Finish footer button is the one live entry point (mirrors UnsavedWorkGuard.spec.ts's and
// DisplayFinishFooter.spec.ts's own precedent for this exact transition) - `whoamiAnonymous` is
// part of `defaultHandlers`, so this always lands straight on /print with no pre-print save gate
// to dismiss first. FinishedMyProject's default tab is "pringleprints", not "pdf"
// (FinishedMyProject.tsx) - the PDF tab always needs an explicit click even though its own nav
// item is already visible immediately.
//
// The click+waitForURL step is wrapped in a `toPass` retry (same resilience pattern
// `openAddCardsDropdown` above already established for this suite) rather than a single
// generous-timeout attempt - observed directly (2026-07-24, verifying this port at 4 parallel
// workers) failing with a bare `net::ERR_ABORTED` on the FIRST attempt under worker contention
// (three separate spec files - this one, PDFGenerator.spec.ts, PostExportContributionPrompt.spec.ts
// - all racing to first-hit /print's cold on-demand dev-mode compile simultaneously, the same
// characteristic DisplayFinishFooter.spec.ts's own `mode: "serial"` comment documents, just not
// fully solved by that file-local fix once MULTIPLE files contend for the same route). A retried
// click safely re-fires `router.push("/print")` if the first attempt's navigation never actually
// landed - idempotent either way.
export const navigateToPrintPDFTab = async (page: Page, query: string) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, query);
  await expect(async () => {
    await page.getByTestId("finish-footer-print-export").click();
    await page.waitForURL(/\/print/, { timeout: 15_000 });
  }).toPass({ timeout: 45_000 });
  await page.getByRole("tab", { name: "PDF" }).click();
};

export async function expectCardSlotToExist(page: Page, slot: number) {
  await expect(page.getByTestId(`front-slot${slot - 1}`)).toContainText(
    `Slot ${slot}`
  );
  await expect(page.getByTestId(`back-slot${slot - 1}`)).toContainText(
    `Slot ${slot}`
  );
}

export async function expectCardSlotToNotExist(page: Page, slot: number) {
  await expect(page.getByTestId(`front-slot${slot - 1}`)).not.toBeVisible();
  await expect(page.getByTestId(`back-slot${slot - 1}`)).not.toBeVisible();
}

export const expectCardSlotState = async (
  page: Page,
  testId: string,
  cardName?: string,
  selectedImage?: number,
  totalImages?: number
) => {
  await expect(page.getByTestId(testId)).toContainText(
    cardName ?? "Your search query"
  );
  if (selectedImage !== undefined && totalImages !== undefined) {
    await expect(page.getByTestId(testId)).toContainText(
      `${selectedImage} / ${totalImages}`
    );
  }
};

export const expectCardbackSlotState = async (
  page: Page,
  cardName?: string,
  selectedImage?: number,
  totalImages?: number
) =>
  expectCardSlotState(
    page,
    "common-cardback",
    cardName,
    selectedImage,
    totalImages
  );

export const expectCardGridSlotState = async (
  page: Page,
  slot: number,
  face: "front" | "back",
  cardName?: string,
  selectedImage?: number,
  totalImages?: number
) => {
  const testId = `${face}-slot${slot - 1}`;
  await expect(page.getByTestId(testId)).toContainText(`Slot ${slot}`);
  await expectCardSlotState(page, testId, cardName, selectedImage, totalImages);
};

type CardSlotAssertion = {
  slot: number;
  name: string;
  selectedImage: number;
  totalImages: number;
};

export const getToggleFaceButton = async (page: Page) =>
  page.getByRole("button", { name: "Switch to", exact: false });

export const toggleFace = async (page: Page) => {
  const btn = await getToggleFaceButton(page);
  // it seems like sometimes the import XML modal doesn't dismiss properly
  // so to avoid the modal intercepting click events, just force the click
  // yes this is hacky. you're more than welcome to try fixing this.
  await btn.click({ force: true });
};

export const expectCardGridSlotStates = async (
  page: Page,
  fronts: Array<CardSlotAssertion>,
  backs: Array<CardSlotAssertion>
) => {
  for (const { slot, name, selectedImage, totalImages } of fronts) {
    const testId = `front-slot${slot - 1}`;
    await expect(page.getByTestId(testId)).toContainText(`Slot ${slot}`);
    await expectCardSlotState(page, testId, name, selectedImage, totalImages);
  }

  await toggleFace(page);

  for (const { slot, name, selectedImage, totalImages } of backs) {
    const testId = `back-slot${slot - 1}`;
    await expect(page.getByTestId(testId)).toContainText(`Slot ${slot}`);
    await expectCardSlotState(page, testId, name, selectedImage, totalImages);
  }

  await toggleFace(page);
};

export const openImportCSVModal = async (page: Page) => {
  await openAddCardsDropdown(page);
  await page.getByRole("button", { name: "CSV", exact: false }).click();
};

export const importCSV = async (page: Page, fileContents: string) => {
  await openImportCSVModal(page);
  const fileInput = page
    .getByLabel("import-csv")
    .locator('input[type="file"]')
    .first();

  // Create a temporary file with the CSV content
  const buffer = Buffer.from(fileContents);
  await fileInput.setInputFiles({
    name: "test.csv",
    mimeType: "text/csv",
    buffer: buffer,
  });

  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeVisible();
};

export const openImportXMLModal = async (page: Page) => {
  await openAddCardsDropdown(page);
  await page.getByRole("button", { name: "XML", exact: false }).click();
  return page.getByTestId("import-xml");
};

export const importXML = async (
  page: Page,
  fileContents: string,
  useXMLCardback: boolean = true
) => {
  const modal = await openImportXMLModal(page);

  if (!useXMLCardback) {
    await modal.getByText("Use XML Cardback").click();
  }

  const fileInput = modal.locator('input[type="file"]').first();

  // Create a temporary file with the XML content
  const buffer = Buffer.from(fileContents);
  await fileInput.setInputFiles({
    name: "test.xml",
    mimeType: "text/xml;charset=utf-8",
    buffer: buffer,
  });

  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeAttached();
};

// Import cluster parity port (2026-07-23, issue #272 wave 1). DisplayPage's EMPTY-project landing
// (`display-empty-state`) mounts the bare `ImportCSV`/`ImportXML` components verbatim (DisplayPage
// module comment: "the same plain ImportText/ImportURL/ImportXML/ImportCSV components
// ProjectEditor.tsx's own AddCardsPanel mounts") directly inline inside a collapsed "Import a File
// or URL" Accordion - not behind the classic "Add Cards" dropdown-triggered modal
// openImportCSVModal/openImportXMLModal open (that dropdown only mounts once the project already
// has a member - see openDisplayToolbarAddCardsDropdown below for that non-empty-project path).
// The underlying `TextFileDropzone` `label`s ("import-csv"/"import-xml") are identical either way
// - only how you REACH the form differs.
export const importCSVOnEmptyLanding = async (
  page: Page,
  fileContents: string
) => {
  await page.getByRole("button", { name: "CSV", exact: false }).click();
  const fileInput = page
    .getByLabel("import-csv")
    .locator('input[type="file"]')
    .first();
  const buffer = Buffer.from(fileContents);
  await fileInput.setInputFiles({
    name: "test.csv",
    mimeType: "text/csv",
    buffer: buffer,
  });
  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeVisible();
};

export const importXMLOnEmptyLanding = async (
  page: Page,
  fileContents: string,
  useXMLCardback: boolean = true
) => {
  await page.getByRole("button", { name: "XML", exact: false }).click();
  if (!useXMLCardback) {
    await page.getByText("Use XML Cardback").click();
  }
  const fileInput = page
    .getByLabel("import-xml")
    .locator('input[type="file"]')
    .first();
  const buffer = Buffer.from(fileContents);
  await fileInput.setInputFiles({
    name: "test.xml",
    mimeType: "text/xml;charset=utf-8",
    buffer: buffer,
  });
  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeAttached();
};

// The non-empty-project counterpart of the two helpers above: once a project has at least one
// member, DeckInputLanding (and its inline CSV/XML accordion) is no longer rendered at all -
// DisplayPage's populated toolbar mounts `<Import />` instead, the SAME "Add Cards" dropdown
// (Text/XML/CSV/URL, unforked) the classic grid's own right panel used (DisplayPage module
// comment: "the existing Import.tsx dropdown ... mounted verbatim"). Only the surrounding
// container differs (`display-toolbar` here vs. `right-panel` there) - openAddCardsDropdown/
// getAddCardsMenu above stay untouched (their own callers, e.g. Toasts.spec.ts's still-skipped
// assertions, target the classic container specifically) rather than generalized to cover both.
export const openDisplayToolbarAddCardsDropdown = async (page: Page) => {
  const textButton = page.getByRole("button", { name: " Text" });
  if (await textButton.isVisible()) {
    return;
  }
  await expect(async () => {
    await page
      .getByTestId("display-toolbar")
      .getByText("Add Cards", { exact: false })
      .click();
    await expect(textButton).toBeVisible();
  }).toPass({ timeout: 10_000 });
};

export const importXMLFromToolbar = async (
  page: Page,
  fileContents: string,
  useXMLCardback: boolean = true
) => {
  await openDisplayToolbarAddCardsDropdown(page);
  await page.getByRole("button", { name: "XML", exact: false }).click();
  const modal = page.getByTestId("import-xml");

  if (!useXMLCardback) {
    await modal.getByText("Use XML Cardback").click();
  }

  const fileInput = modal.locator('input[type="file"]').first();
  const buffer = Buffer.from(fileContents);
  await fileInput.setInputFiles({
    name: "test.xml",
    mimeType: "text/xml;charset=utf-8",
    buffer: buffer,
  });

  await expect(
    page.locator('span:has-text("Loading your cards...")')
  ).not.toBeAttached();
};

export const downloadXML = async (page: Page): Promise<[string, string]> => {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: " Download" }).click();
  await page.getByTestId("export-xml-button").click();
  const download = await downloadPromise;
  const path = await download.path();
  if (!path) throw new Error("Download path is null");
  const content = await readFile(path, "utf-8");
  return [content, download.suggestedFilename()];
};

export const downloadDecklist = async (
  page: Page
): Promise<[string, string]> => {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: " Download" }).click();
  await page.getByTestId("export-decklist-button").click();
  const download = await downloadPromise;
  const path = await download.path();
  if (!path) throw new Error("Download path is null");
  const content = await readFile(path, "utf-8");
  return [content, download.suggestedFilename()];
};

// Export content-correctness parity port (2026-07-23, issue #272 wave 1). The classic grid's
// "Download" dropdown (downloadXML/downloadDecklist above) has no equivalent on the unified page -
// DisplayExportMenu.tsx composes the exact same unchanged Dropdown.Items behind a differently-
// named trigger instead (`display-export-menu-toggle`/`display-export-menu`, DisplayPage.tsx's own
// toolbar - see DisplayPage.spec.ts's own "Export ▾ toolbar menu" precedent test). The download
// functions/`export-xml-button`/`export-decklist-button` items themselves are unchanged either way
// - only how the menu is opened differs.
export const downloadXMLFromDisplayToolbar = async (
  page: Page
): Promise<[string, string]> => {
  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId("display-export-menu-toggle").click();
  await page.getByTestId("export-xml-button").click();
  const download = await downloadPromise;
  const path = await download.path();
  if (!path) throw new Error("Download path is null");
  const content = await readFile(path, "utf-8");
  return [content, download.suggestedFilename()];
};

export const downloadDecklistFromDisplayToolbar = async (
  page: Page
): Promise<[string, string]> => {
  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId("display-export-menu-toggle").click();
  await page.getByTestId("export-decklist-button").click();
  const download = await downloadPromise;
  const path = await download.path();
  if (!path) throw new Error("Download path is null");
  const content = await readFile(path, "utf-8");
  return [content, download.suggestedFilename()];
};

export function normaliseString(text: string): string {
  return text.replaceAll(" ", "").replaceAll("\n", "").replaceAll("\r", "");
}

export const openChangeQueryModal = async (
  page: Page,
  cardSlotTestId: string,
  cardName: string
) => {
  await page.getByTestId(cardSlotTestId).getByText(cardName).click();
  return page.getByTestId("change-query-modal");
};

// ChangeQueryModal parity port (2026-07-23, issue #272 wave 2). The classic grid opened this
// modal by clicking a slot's own query text (openChangeQueryModal above); the unified page has
// no per-slot query text to click - `ChangeQueryModal` itself is unchanged and still mounted
// globally (Modals.tsx), reachable instead via the shared `CardSlotContextMenu` (right-click a
// sheet slot -> "Change Query", DisplayPage.tsx's own handleSlotContextMenu - "no new action,
// just three more ways to reach it on /display" per that file's own comment). Right-clicking
// reads whichever face is currently displayed (`activeFace`), so a caller wanting the back slot's
// modal must call `ensureDisplayFace(page, "back")` first, same as `expectDisplaySheetSlotState`.
export const openDisplayChangeQueryModal = async (page: Page, slot: number) => {
  await page
    .getByTestId("page-preview-slot")
    .nth(slot - 1)
    .click({ button: "right" });
  await page
    .getByTestId("card-slot-context-menu")
    .getByText("Change Query")
    .click();
  return page.getByTestId("change-query-modal");
};

// CardSlot cluster parity port (2026-07-24, issue #272 wave 3). Right-clicking a sheet slot opens
// the same `card-slot-context-menu` `openDisplayChangeQueryModal` above already reaches - this is
// the generic form, for callers that want to pick a DIFFERENT menu item (Delete/Duplicate) rather
// than always clicking "Change Query".
export const openDisplaySlotContextMenu = async (page: Page, slot: number) => {
  await page
    .getByTestId("page-preview-slot")
    .nth(slot - 1)
    .click({ button: "right" });
  const menu = page.getByTestId("card-slot-context-menu");
  await expect(menu).toBeVisible();
  return menu;
};

// The sheet slot's own visible "..." menu cue (`page-preview-slot-menu-cue`, aria-label "Open
// card menu", PagePreview.tsx's D22) is the direct equivalent of the classic grid's 3-dot
// `more-select-options` button - both open the identical `card-slot-context-menu`
// (CardSlotMenuActions.ts's shared action list, "one menu, two triggers"). Distinct from
// openDisplaySlotContextMenu above (right-click) only in which trigger fires it - the resulting
// menu and its items are the same either way.
export const openDisplaySlotMenu = async (page: Page, slot: number) => {
  await page
    .getByTestId("page-preview-slot")
    .nth(slot - 1)
    .getByTestId("page-preview-slot-menu-cue")
    .click();
  const menu = page.getByTestId("card-slot-context-menu");
  await expect(menu).toBeVisible();
  return menu;
};

export const changeQueries = async (page: Page, query: string) => {
  const textField = page.getByLabel("change-selected-image-queries-text");
  await textField.clear();
  if (query !== "") {
    await textField.fill(query);
  }
  await page.getByLabel("change-selected-image-queries-submit").click();
};

export const changeQuery = async (
  page: Page,
  cardSlotTestId: string,
  cardName: string,
  newQuery: string
) => {
  await openChangeQueryModal(page, cardSlotTestId, cardName);
  await changeQueries(page, newQuery);
};

export const selectSlot = async (
  page: Page,
  slot: number,
  face: "front" | "back",
  clickType: "double" | "shift" | null = null
) => {
  const selectLabel = `select-${face}${slot - 1}`;
  const element = page.getByLabel(selectLabel).locator("*").first();

  if (face === "back") {
    await toggleFace(page);
  }
  if (clickType === "double") {
    await element.dispatchEvent("click", { detail: 2 });
  } else if (clickType === "shift") {
    await element.click({ modifiers: ["Shift"] });
  } else {
    await element.click();
  }
  if (face === "back") {
    await toggleFace(page);
  }

  await expect(element).toHaveClass(/bi-check-square/);
};

export const deselectSlot = async (
  page: Page,
  slot: number,
  face: "front" | "back"
) => {
  const selectLabel = `select-${face}${slot - 1}`;
  const element = page.getByLabel(selectLabel).locator("*").first();
  await element.click();
  await expect(element).toHaveClass(/bi-square/);
};

export const openCardSlotGridSelector = async (
  page: Page,
  slot: number,
  face: "front" | "back",
  selectedImage: number,
  totalImages: number
) => {
  expect(totalImages).toBeGreaterThan(1);
  const testId = `${face}-slot${slot - 1}`;
  await expect(page.getByTestId(testId)).toContainText(`Slot ${slot}`);
  await expect(page.getByTestId(testId)).toContainText(
    `${selectedImage} / ${totalImages}`
  );

  await page
    .getByTestId(testId)
    .getByText(`${selectedImage} / ${totalImages}`)
    .click();

  const gridSelector = page.getByTestId(
    `${face}-slot${slot - 1}-grid-selector`
  );
  await expect(gridSelector).toBeVisible();
  return gridSelector;
};

export const clickMoreSelectOptionsDropdown = async (page: Page) => {
  await page.getByTestId("more-select-options").click();
};

export const selectSimilar = async (page: Page) => {
  await page.getByText("Select Similar").click();
};

export const selectAll = async (page: Page) => {
  await page.getByText("Select All").click();
};

export const changeQueryForSelectedImages = async (
  page: Page,
  query: string
) => {
  await page.getByText("Change Query").click();
  await changeQueries(page, query);
};

export const changeImageForSelectedImages = async (
  page: Page,
  cardName: string
) => {
  await page.getByText("Change Version").click();
  await page.getByText("Compressed").click();
  await expect(page.getByText("Option 1")).toBeVisible();
  await page.getByTestId("bulk-grid-selector").getByAltText(cardName).click();
};

export const clearQueriesForSelectedImages = async (page: Page) => {
  await page.getByText("Clear Query").click();
};

export const deleteSelectedImages = async (page: Page) => {
  await page.getByText("Delete Cards").click();
};

export const getErrorToast = async (page: Page) => {
  return page.getByText("An Error Occurred").locator("..").locator("..");
};

export const openSearchSettingsModal = async (page: Page) => {
  await page.getByText(/Search Settings/).click();
  await expect(
    page.getByTestId("search-settings").getByText("Search Settings")
  ).toBeVisible();
  return page.getByTestId("search-settings");
};

export const enableFuzzySearch = async (page: Page) => {
  const settingsModal = await openSearchSettingsModal(page);
  await settingsModal.getByText("Precise Search").click();
  await settingsModal.getByRole("button", { name: "Save Changes" }).click();
};

// SearchSettings parity port (2026-07-23, issue #272 wave 2). SearchSettings.tsx itself is
// unchanged and unforked (DisplayPage.tsx's own comment: "relocated here unmodified") - it just
// lives inside the right rail's Offcanvas (`display-print-settings-rail`) instead of the classic
// toolbar. Below the `xl` breakpoint that Offcanvas starts closed, reachable only via the gear
// button (`display-gear-button`, itself `d-xl-none` - hidden at `xl`+, where the rail is already
// inline instead - playwright.config.ts's own `contextOptions.viewport` override doesn't actually
// take effect, an unrelated pre-existing quirk: Playwright's real viewport for this whole suite is
// devices["Desktop Chrome"]'s stock 1280x720, which IS above `xl`, so the gear button is normally
// hidden and the rail already visible here - conditional click, same `isVisible()`-guard pattern
// as `openAddCardsDropdown`, keeps this helper correct at either width). Once the rail is open,
// openSearchSettingsModal's own `getByText(/Search Settings/)` trigger click still works verbatim
// - no duplicate-heading ambiguity here either (see DisplayPage.tsx's own comment on that button).
export const openDisplaySearchSettingsModal = async (page: Page) => {
  const rail = page.getByTestId("display-print-settings-rail");
  if (!(await rail.isVisible())) {
    await page.getByTestId("display-gear-button").click();
    await expect(rail).toBeVisible();
  }
  return openSearchSettingsModal(page);
};

export const enableDisplayFuzzySearch = async (page: Page) => {
  const settingsModal = await openDisplaySearchSettingsModal(page);
  await settingsModal.getByText("Precise Search").click();
  await settingsModal.getByRole("button", { name: "Save Changes" }).click();
};

// GridSelectorModal parity port (2026-07-24, issue #272 wave 3). The classic grid opened
// GridSelectorModal.tsx per-SLOT, fed by that slot's own search results (openCardSlotGridSelector
// below). Per-slot picking on the unified page goes through the rail's own Select Version section
// instead (SelectVersionSection.spec.ts's own coverage) - a materially different component with no
// grouping/filters-sidebar/Jump-to-Version UI of its own. The ONE GridSelectorModal instance still
// reachable on this page is CardbackToolbarButton's project-wide cardback picker
// (CommonCardback.tsx's `MemoizedCommonCardbackGridSelector`, testid `cardback-grid-selector`,
// title "Select Cardback") - GridSelectorModal.tsx itself is entirely generic (a bare
// `imageIdentifiers` array + `onClick` callback, doesn't care what the identifiers represent), so
// every grouping/filter/keyboard/autofocus/mobile-viewport behavior this modal exposes is
// identical regardless of which caller's identifiers feed it - this is the full-fidelity instance
// this wave's GridSelectorModal.spec.ts/GridSelectorModalVariants.spec.ts clusters port onto.
// Requires the right rail open first (same isVisible()-guard pattern as
// openDisplaySearchSettingsModal). Also requires a NON-empty project already: DisplayPage.tsx's
// own `if (isProjectEmpty) return <DeckInputLanding ... />` early-return means the toolbar/gear
// button/right rail (and this button inside it) don't exist at all until at least one project
// member does - callers must run an import (e.g. importTextOnEditorLanding) first, the same
// precondition openDisplaySearchSettingsModal's own callers already carry.
export const openDisplayCardbackGridSelector = async (page: Page) => {
  const rail = page.getByTestId("display-print-settings-rail");
  if (!(await rail.isVisible())) {
    await page.getByTestId("display-gear-button").click();
    await expect(rail).toBeVisible();
  }
  await rail.getByRole("button", { name: /Cardback/ }).click();
  const gridSelector = page.getByTestId("cardback-grid-selector");
  await expect(gridSelector).toBeVisible();
  return gridSelector;
};

// Cardback flow round (SPEC-cardback-pdfwait.md) - same isVisible()-guard gear-open pattern as
// openDisplaySearchSettingsModal/openDisplayCardbackGridSelector above, factored out since the
// Finish footer (FinishFooter.tsx, `finish-footer-print-export`) ALSO lives inside the same
// `display-print-settings-rail` Offcanvas - below `xl`, reachable only via the gear button. Every
// existing caller of `finish-footer-print-export` in this suite runs at the default (unset)
// viewport, which resolves to devices["Desktop Chrome"]'s 1280x720 (above `xl`, rail already
// inline - see openDisplaySearchSettingsModal's own comment on why playwright.config.ts's
// `contextOptions.viewport` override is dead config) - this helper is for any caller that
// deliberately narrows below `xl` (e.g. a phone-width `test.use({ viewport })` block).
export const ensureDisplayRightRailOpen = async (page: Page) => {
  const rail = page.getByTestId("display-print-settings-rail");
  if (!(await rail.isVisible())) {
    await page.getByTestId("display-gear-button").click();
    await expect(rail).toBeVisible();
  }
};

/**
 * Open a StyledDropdownTreeSelect and click an option by its exact label text.
 * The container should be the `.react-dropdown-tree-select` element (or a
 * parent that scopes the search).
 */
export const selectDropdownOption = async (
  container: Locator,
  label: string
): Promise<void> => {
  await container.locator(".dropdown-trigger").click();
  await container.getByText(label, { exact: true }).click();
};
