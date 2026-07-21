import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
  cardDocument8,
  localBackendURL,
} from "@/common/test-constants";
import {
  cardbacksTwoResults,
  cardDocumentsNoResults,
  cardDocumentsThreeResults,
  cardDocumentsWithCanonicalCards,
  cardDocumentsWithResolvedPrintingMatch,
  defaultHandlers,
  searchResultsDegradedPrinting,
  searchResultsNoResults,
  searchResultsResolvedPrintingMatch,
  searchResultsThreeResults,
  searchResultsThreeResultsPlusCard2SelfQuery,
  searchResultsUnresolvedCanonicalImport,
  sourceDocumentsOneResult,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importText,
  loadPageWithDefaultBackend,
  openSearchSettingsModal,
} from "./test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  // The Attributes rail section (AutofillCollapse keeps every section mounted, not just the
  // expanded one - same reason ChooseImageSection's own search fires unconditionally on slot
  // select) fetches tag consensus the moment a slot is selected, whether or not the user ever
  // opens Attributes - every test below that selects a slot needs this mocked, not just the
  // ones that expand the section.
  tagConsensusTwoUnresolvedTags,
  ...defaultHandlers,
];

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

const REFERENCE_CANDIDATE = {
  identifier: "xyz-001-printing",
  canonicalId: "canonical-xyz-001",
  expansionCode: "xyz",
  expansionName: "XYZ Set",
  collectorNumber: "001",
  artist: "Some Artist",
  smallThumbnailUrl: "https://example.com/small-ref.png",
  mediumThumbnailUrl: "https://example.com/medium-ref.png",
  fullArt: false,
  isBorderless: false,
  frame: "2015",
  borderColor: "black",
  isShowcase: false,
  isExtendedArt: false,
  isEtched: false,
};

// Proposal H, Step 1 (docs/proposals/proposal-h-unified-display-page.md) - the /display route's
// page shell: toolbar, live sheet, slot selection, and the rail's accordion skeleton. Reaches
// /display via the navbar link (client-side navigation) rather than page.goto("/display", ...)
// directly, so the cards imported on /editor survive into the new page - a hard navigation
// would otherwise lose the in-memory Redux project state between the two pages.
test.describe("DisplayPage (Proposal H, Step 1)", () => {
  // Whichever test in this file is first to actually hit /display pays Next dev mode's
  // on-demand page-compile cost for a brand-new route (this one transitively pulls in
  // @react-pdf/renderer via PDF.tsx's getPageSizeMM/computeLayout imports) - comfortably over
  // the default 30s test timeout was observed for that first hit specifically, with every
  // later test in the same run fast since the dev server (shared across this file's tests)
  // stays warm. Real production builds pre-compile every route, so this cost is a dev-mode/
  // first-touch artifact of this being a brand-new page, not a runtime perf issue.
  test.describe.configure({ timeout: 60_000 });

  // Issue #238 (design doc §4.1) - the empty-state used to be just a message plus a plain link
  // back to /editor; it now mounts the same inline import surfaces AddCardsPanel uses on the
  // classic editor's own "Add Cards" tab, so a project can be started on /display directly.
  test("shows the inline import surfaces (not a link back to the editor) when the project has no cards", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "import-text" })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "import-text-submit" })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Import a File or URL" })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "XML" })).toBeVisible();
    await expect(page.getByRole("button", { name: "CSV" })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Head to the editor" })
    ).toHaveCount(0);
  });

  test("submitting the inline text importer on the empty-state landing starts a project and lands directly on the sheet+rail layout", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();

    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("my search query");
    await page.getByRole("button", { name: "import-text-submit" }).click();

    await expect(page.getByTestId("display-empty-state")).toHaveCount(0);
    await expect(page.getByTestId("display-page")).toBeVisible();
    await expect(page.getByTestId("display-sheet-indicator")).toContainText(
      "Sheet 1 of 1"
    );
    await expect(page.getByTestId("page-preview-slot")).toHaveCount(8);

    // The rail starts idle - selecting the newly-imported slot swaps it in, exactly as it would
    // for a deck that arrived via /editor instead (§4.1 step 3: onImportComplete has nothing to
    // switch to here since there's no separate tab, just this one layout re-rendering itself).
    await expect(page.getByTestId("display-rail-idle")).toBeVisible();
    await page.getByTestId("page-preview-slot").first().click();
    await expect(page.getByTestId("display-rail-header")).toContainText(
      "Slot 1"
    );
  });

  test("renders a live 4x2 sheet of the imported deck and starts with the rail idle", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-page")).toBeVisible();
    await expect(page.getByTestId("display-sheet-indicator")).toContainText(
      "Sheet 1 of 1"
    );
    await expect(page.getByTestId("display-sheet-wrapper")).toHaveCount(1);
    // A4 landscape at the default bleed edge greedy-fits to 4 columns x 2 rows - see the
    // design doc's §1 for the computeLayout() math this matches.
    await expect(page.getByTestId("page-preview-slot")).toHaveCount(8);
    await expect(page.getByTestId("display-rail-idle")).toBeVisible();
  });

  test("selecting a slot swaps the rail from idle to that slot's header + accordion, defaulting to Choose Image open", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await page.getByTestId("page-preview-slot").first().click();

    await expect(page.getByTestId("display-rail-idle")).not.toBeVisible();
    const railHeader = page.getByTestId("display-rail-header");
    await expect(railHeader).toBeVisible();
    await expect(railHeader).toContainText("Slot 1");
    await expect(railHeader).toContainText("front");

    // Compressed view (viewSettingsSlice's real, hardcoded default) renders only the bare card
    // image - no per-card "Option N" text - so toggle it off first, same precedent as
    // CardSlot.spec.ts's own version-picker test.
    await page.getByText("Compressed").click();

    // Choose Image is open by default (real candidate grid, wired in PR 2a); the other four
    // sections start collapsed - per the owner's accordion amendment (design doc §2).
    await expect(page.getByText("Option 1")).toBeVisible();
    await expect(page.getByRole("button", { name: /Filters/ })).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Full Art")).not.toBeVisible();
  });

  test("selecting a candidate image in Choose Image updates the sheet's slot immediately", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    const sheetSlot = page.getByTestId("page-preview-slot").first();
    await sheetSlot.click();
    // Compressed view (the default) hides "Option N" text entirely - see the previous test.
    await page.getByText("Compressed").click();
    // searchResultsThreeResults (mocks/handlers.ts) resolves "my search query" to
    // [cardDocument1, cardDocument2, cardDocument3] in that order - Option 1 is cardDocument1.
    await page.getByText("Option 2").click();

    await expect(sheetSlot.locator("img")).toHaveAttribute("alt", "Card 2");
    // The rail's own header (identity text) reflects the same real-time selection - same Redux
    // state, same render path, not a separate source of truth.
    await expect(page.getByTestId("display-rail-header")).toContainText(
      "Card 2"
    );
  });

  test("the embedded Choose Image section has no OverflowCol-style forced scroll region (would double-scroll inside the rail)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    // Compressed view (the default) hides "Option N" text entirely - see the earlier tests.
    await page.getByText("Compressed").click();

    const candidateCard = page.getByText("Option 1");
    await expect(candidateCard).toBeVisible();
    // GridSelectorResults' "modal" variant wraps this in an OverflowCol, which sets
    // overflow-y: scroll unconditionally - a second, competing scroll region nested inside the
    // rail's own already-scrolling container (see DisplayPage.tsx's RailWrapper). The "embedded"
    // variant must render a plain Col instead, with no ancestor up to the rail itself forcing
    // its own scroll.
    const hasNestedScrollAncestor = await candidateCard.evaluate((el) => {
      let node: HTMLElement | null = el.parentElement;
      while (node != null) {
        if (getComputedStyle(node).overflowY === "scroll") {
          return true;
        }
        if (node.dataset.testid === "display-rail") {
          break;
        }
        node = node.parentElement;
      }
      return false;
    });
    expect(hasNestedScrollAncestor).toBe(false);
  });

  test("clicking a collapsed section's header expands it", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    await page
      .getByRole("heading", { name: "Attributes", exact: true })
      .click();
    await expect(page.getByTestId("attribute-chip-Full Art")).toBeVisible();
  });

  test("selecting a different slot resets the accordion back to its default (Choose Image open again)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    // 2 slots, not 1 - clicking a grid position with no real project slot behind it (this
    // page's own click handler ignores those, since there's nothing there to select) would
    // leave the previous selection in place and falsely pass this test either way.
    await importText(page, "2x my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    const slots = page.getByTestId("page-preview-slot");
    await slots.first().click();
    // Compressed view (the default) hides "Option N" text entirely - see the earlier tests.
    // This is a global view setting, not slot-specific state, so toggling it once here holds
    // for the rest of the test (including after selecting the second slot below).
    await page.getByText("Compressed").click();
    await page
      .getByRole("heading", { name: "Attributes", exact: true })
      .click();
    await expect(page.getByTestId("attribute-chip-Full Art")).toBeVisible();

    // Selecting the other real slot swaps the rail's whole subtree - Attributes should be back
    // to collapsed, not still expanded from the last slot.
    await slots.nth(1).click();
    await expect(page.getByTestId("attribute-chip-Full Art")).not.toBeVisible();
    await expect(page.getByText("Option 1")).toBeVisible();
  });

  test("the Fronts/Backs toggle button reflects the shared frontsVisible view setting", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByText("Showing: Fronts")).toBeVisible();
    await page.getByText("Showing: Fronts").click();
    await expect(page.getByText("Showing: Backs")).toBeVisible();
  });

  test("toggling Guides shows and hides the cut-line overlay", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    const guidesToggle = page.getByLabel("Guides");
    await expect(guidesToggle).toBeChecked();
    await expect(
      page.getByTestId("page-preview-cut-line").first()
    ).toBeVisible();

    await guidesToggle.uncheck();
    await expect(page.getByTestId("page-preview-cut-line")).toHaveCount(0);
  });

  // Issue #239 (design doc §5's SearchSettings row) - the toolbar previously had no way to reach
  // precise/fuzzy search type, DPI/file-size filters, or source reordering at all on this page.
  // The same self-contained modal ProjectEditor.tsx already mounts is relocated here unmodified -
  // this test only needs to confirm it opens from the toolbar and that a change made through it
  // actually persists via the shared searchSettingsSlice, not that the modal's own internals work
  // (SearchSettings.visual.spec.ts and the settings-specific unit tests already cover that).
  test("the Search Settings toolbar button opens the same modal the classic editor uses, and a change made through it persists via the shared searchSettingsSlice", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    const settingsModal = await openSearchSettingsModal(page);
    await expect(
      settingsModal.getByRole("heading", { name: "Search Type" })
    ).toBeVisible();

    // getDefaultSearchSettings defaults fuzzySearch to false (Precise), so the toggle's whole
    // clickable surface (both labels render inside one button - see SearchTypeSettings.tsx) is
    // currently sitting in its "off"/Precise position; clicking anywhere on it flips to Fuzzy.
    const searchTypeToggle = settingsModal.getByRole("button", {
      name: "Fuzzy (Forgiving) Search Precise Search",
    });
    await expect(searchTypeToggle).not.toHaveClass(/btn-success/);
    await searchTypeToggle.click();
    await settingsModal.getByRole("button", { name: "Save Changes" }).click();
    await expect(page.getByTestId("search-settings")).not.toBeVisible();

    // Re-opening confirms the change actually round-tripped through searchSettingsSlice/
    // localStorage rather than only ever living in the modal's own local component state.
    const reopened = await openSearchSettingsModal(page);
    await expect(
      reopened.getByRole("button", {
        name: "Fuzzy (Forgiving) Search Precise Search",
      })
    ).toHaveClass(/btn-success/);
  });

  // Issue #240 (design doc §5's CommonCardback row) - the toolbar previously had no way to reach
  // the project-wide cardback picker at all on this page (only the classic editor's own right
  // panel could). CardbackToolbarButton (CommonCardback.tsx) reuses
  // MemoizedCommonCardbackGridSelector's existing GridSelectorModal verbatim - this test only
  // needs to confirm it opens from the toolbar and that a selection made through it actually
  // updates the shared project cardback (visible via a back-face slot on the sheet), not that the
  // grid selector's own internals work (already covered by CardSlot.spec.ts's cardback tests).
  test("the Cardback toolbar button opens the same project-wide cardback picker the classic editor uses, and a selection made through it updates back-face slots on the sheet", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    // A plain text query with no explicit back face falls back to the project cardback - the
    // fetchCardbacks.fulfilled listener (listenerMiddleware.ts) auto-selects the first cardback
    // in the list once cardbacksTwoResults resolves, so this starts on cardDocument1.
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    await page.getByText("Showing: Fronts").click();
    const backSheetSlot = page.getByTestId("page-preview-slot").first();
    await expect(backSheetSlot.locator("img")).toHaveAttribute(
      "alt",
      cardDocument1.name
    );

    await page.getByRole("button", { name: "Cardback" }).click();
    const cardbackModal = page.getByTestId("cardback-grid-selector");
    await expect(cardbackModal).toBeVisible();
    await cardbackModal.getByAltText(cardDocument2.name).click();
    await expect(cardbackModal).not.toBeVisible();

    // The back-face slot on the sheet now reflects the newly selected cardback, confirming the
    // selection round-tripped through the shared projectSlice.cardback state, not just the modal's
    // own local component state.
    await expect(backSheetSlot.locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
  });

  // Issue #241 (design doc §5's export-beyond-PDF row) - the toolbar previously had no way to
  // reach XML/Card Images/Decklist export at all on this page (only the classic editor's own
  // "Download" dropdown could). DisplayExportMenu.tsx composes the same unchanged Dropdown.Items;
  // this test only needs to confirm the menu opens and lists them - the items' own download
  // behaviour is already covered by ExportXML.spec.ts/ExportDecklist.spec.ts/
  // ExportImages.test.tsx against the classic editor's identical, unforked components.
  test("the Export ▾ toolbar menu lists XML, Card Images, and Decklist", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-toolbar")).toBeVisible();
    await page.getByTestId("display-export-menu-toggle").click();
    const exportMenu = page.getByTestId("display-export-menu");
    await expect(exportMenu).toBeVisible();
    await expect(exportMenu.getByTestId("export-xml-button")).toBeVisible();
    await expect(exportMenu.getByText("Card Images")).toBeVisible();
    await expect(
      exportMenu.getByTestId("export-decklist-button")
    ).toBeVisible();
  });

  test("the requested-printing badge shows the plain style for a resolved, non-degraded printing-specific import", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithResolvedPrintingMatch,
      sourceDocumentsOneResult,
      searchResultsResolvedPrintingMatch,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 Lightning Bolt (2ED) 162");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    const badge = page.getByTestId("requested-printing-badge");
    await expect(badge).toBeVisible();
    await expect(badge).toContainText("2ED 162");
    await expect(badge).toHaveAttribute("data-degraded", "false");
    await expect(badge).not.toHaveAttribute("title");
  });

  test("the requested-printing badge switches to a distinct degraded style - verified via actual computed styles, not just class names - when the backend reports the printing filter as degraded", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsDegradedPrinting,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 my search query (XYZ) 999");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    const badge = page.getByTestId("requested-printing-badge");
    await expect(badge).toBeVisible();
    await expect(badge).toContainText("XYZ 999");
    await expect(badge).toHaveAttribute("data-degraded", "true");
    await expect(badge).toHaveAttribute("title", /closest available match/);
    await expect(badge.locator("i.bi-exclamation-triangle-fill")).toBeVisible();

    // Bootswatch's Superhero theme hardcodes some component colors past the CSS-variable layer
    // (the theming caveat from PR #91) - reading getComputedStyle is the only way to actually
    // confirm the browser renders a distinct, visibly-warning color here, rather than trusting
    // that the bg-warning class "should" look right from its definition alone.
    const backgroundColor = await badge.evaluate(
      (element) => getComputedStyle(element).backgroundColor
    );
    const [red, green, blue] = backgroundColor.match(/\d+/g)!.map(Number);
    expect(blue).toBeLessThan(Math.min(red, green) - 20);
  });

  test("the Confirm? affordance mounts in the rail's always-visible header (same component CardSlot.tsx mounts, adapted only via onOpenGridSelector) and YES submits the same vote", async ({
    page,
    network,
  }) => {
    let submittedBody: Record<string, unknown> = {};
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        submittedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            resolvedPrinting: REFERENCE_CANDIDATE,
            isNoMatch: false,
            voteTally: [],
          },
          { status: 200 }
        );
      }),
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    const header = page.getByTestId("display-rail-header");
    const yesButton = header.getByTestId("deckbuilder-confirm-yes");
    await expect(yesButton).toBeDisabled();

    await header.getByTestId("deckbuilder-confirm-badge").hover();
    await expect(header.getByTestId("deckbuilder-compare-pin")).toBeVisible();
    await expect(yesButton).toBeEnabled();

    await yesButton.click();

    await expect
      .poll(() => submittedBody.printingIdentifier)
      .toBe(REFERENCE_CANDIDATE.identifier);
    expect(submittedBody.voteSurface).toBe("deckbuilder");
    await expect(
      header.getByTestId(`deckbuilder-confirm-${cardDocument8.identifier}`)
    ).toHaveCount(0);
  });

  test("the Confirm? affordance's NO expands the Choose Image accordion section instead of opening a modal (the rail has no modal to open)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    // Choose Image is open by default - collapse it first so NO's "expand it" effect is
    // observable, rather than trivially already true.
    await page
      .getByRole("heading", { name: "Choose Image", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: /Filters/ })
    ).not.toBeVisible();

    const header = page.getByTestId("display-rail-header");
    await header.getByTestId("deckbuilder-confirm-badge").hover();
    const noButton = header.getByTestId("deckbuilder-confirm-no");
    await expect(noButton).toBeEnabled();
    await noButton.click();

    await expect(page.getByRole("button", { name: /Filters/ })).toBeVisible();
  });

  test("a slot with no resolved image shows its query text on the sheet instead of a blank hole (item 1, owner's hands-on review)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsNoResults,
      sourceDocumentsOneResult,
      searchResultsNoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "an unfindable card");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    const sheetSlot = page.getByTestId("page-preview-slot").first();
    await expect(sheetSlot.locator("img")).toHaveCount(0);
    const label = sheetSlot.getByTestId("page-preview-empty-slot-label");
    await expect(label).toBeVisible();
    await expect(label).toContainText("an unfindable card");
  });

  test("a deck spanning multiple sheets renders as one continuous vertical stack, with the far-off sheet deferred until scrolled into view (Item 3, flat scroll + virtualization)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    // 20 slots at 8-per-sheet (the same 4x2 A4-landscape default the other tests rely on)
    // chunks into 3 sheets: 8, 8, 4.
    await importText(page, "20x my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-page")).toBeVisible();
    const sheetWrappers = page.getByTestId("display-sheet-wrapper");
    await expect(sheetWrappers).toHaveCount(3);
    await expect(page.getByTestId("display-sheet-indicator")).toContainText(
      "Sheet 1 of 3"
    );

    // The last sheet starts well outside RenderIfVisible's visibleOffset band at this scroll
    // position - it hasn't been asked to mount any real card images yet, which is the whole
    // point of sheet-level virtualization (see this page's own module comment). PagePreview
    // always renders one page-preview-slot div per grid position regardless of how many are
    // actually filled (see PagePreview.tsx - every cell gets a slot, only some get an <img>), so
    // "not mounted at all" means zero of *either*, not just zero filled ones.
    const lastSheet = sheetWrappers.last();
    await expect(lastSheet.getByTestId("page-preview-slot")).toHaveCount(0);
    await expect(lastSheet.locator("img")).toHaveCount(0);

    // The page's real scroll container is Layout.tsx's fixed-position, overflow-y:scroll
    // ContentContainer, not the window/body (see docs/lessons.md's sticky/z-index entry) - so
    // window.scrollTo() here would silently no-op. scrollIntoViewIfNeeded() finds whichever
    // ancestor actually scrolls and moves it, which is what's needed regardless of which
    // element that turns out to be.
    await lastSheet.scrollIntoViewIfNeeded();

    // Now mounted: the full 4x2 grid's worth of slot divs (8, same as every other sheet), but
    // only 4 of them are real project slots (20 cards - 8 - 8 already placed on the first two
    // sheets) - the remaining 4 grid cells on this last sheet render empty, same as the
    // baseline single-sheet "leaves a slot empty" case.
    await expect(lastSheet.getByTestId("page-preview-slot")).toHaveCount(8);
    await expect(lastSheet.locator("img")).toHaveCount(4);
    await expect(page.getByTestId("display-sheet-indicator")).toContainText(
      "Sheet 3 of 3"
    );
  });

  // Proposal H pane migration, left-panel unification (issue #164) - the four rail sections that
  // were stubs before this pass: Attributes, Print Options, Artist, Slot Actions.

  test("the Attributes section casts a real tag vote when a chip is tapped", async ({
    page,
    network,
  }) => {
    let submittedTagName: string | undefined;
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      tagConsensusTwoUnresolvedTags,
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as { tagName: string };
        submittedTagName = body.tagName;
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: 1,
            netPolarity: 1,
            tally: [{ polarity: 1, count: 1 }],
          },
          { status: 200 }
        );
      }),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    await page
      .getByRole("heading", { name: "Attributes", exact: true })
      .click();

    const chip = page.getByTestId("attribute-chip-Full Art");
    await expect(chip).toHaveAttribute("data-chip-state", "untouched");
    await chip.click();

    await expect(chip).toHaveAttribute("data-chip-state", "positive");
    await expect.poll(() => submittedTagName).toBe("Full Art");
  });

  test("the Print Options section shows a bleed override select for an eligible (Google Drive) card", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    await page
      .getByRole("heading", { name: "Print Options", exact: true })
      .click();

    const select = page.getByTestId(
      `bleed-override-select-${cardDocument8.identifier}`
    );
    await expect(select).toBeVisible();
    await expect(select).toHaveValue("auto");

    await select.selectOption("force-bleed");
    await expect(select).toHaveValue("force-bleed");
  });

  test("the Artist section shows a support link for a card with a known canonical artist", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    await page.getByRole("heading", { name: "Artist", exact: true }).click();

    const link = page.getByTestId("artist-support-link");
    await expect(link).toBeVisible();
    await expect(link).toContainText("Alpha Artist");
    await expect(link).toHaveAttribute(
      "href",
      "https://www.mtgartistconnection.com/artist/Alpha%20Artist"
    );
  });

  test("the Slot Actions section's Delete removes the slot and returns the rail to idle", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    // 2 slots, not 1 - deleting the only slot in the project would make it empty and swap the
    // whole page to the empty-state view (a different, already-covered case) rather than
    // leaving the sheet showing one fewer filled slot, which is what this test actually checks.
    await importText(page, "2x my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    await page
      .getByRole("heading", { name: "Slot Actions", exact: true })
      .click();

    await expect(
      page.getByTestId("page-preview-slot").locator("img")
    ).toHaveCount(2);
    await page.getByTestId("display-slot-action-delete").click();

    await expect(page.getByTestId("display-rail-idle")).toBeVisible();
    await expect(
      page.getByTestId("page-preview-slot").locator("img")
    ).toHaveCount(1);
  });

  // Issue #267 (design doc ADDENDUM D12/F9/F10, owner's locked comment on #267) - the one
  // genuinely-new journey this PR adds: toggling the populated-state search bar into Browse
  // mode queries the catalog (the same doSearch/3-editorSearch machinery a slot's own query
  // uses - see CatalogBrowseResults.tsx's own module comment), renders results in the center
  // region behind the "Print sheets"/"Browse results" switch, and each result's inline
  // "+Add"/"Add to Project" affordance (AddCardToProjectForm, unforked) actually lands a new
  // slot in the deck.
  test("toggling the search bar to Browse mode searches the catalog, shows results in the center region, and Add to Project adds a result to the deck", async ({
    page,
    network,
  }) => {
    // searchResultsThreeResultsPlusCard2SelfQuery (not the plain searchResultsThreeResults every
    // other test in this file uses): AddCardToProjectForm's own "+Add" line
    // (`${quantity} ${cardDocument.searchq}${SelectedImageSeparator}${cardDocument.identifier}`)
    // gives the new slot cardDocument2's OWN query ("card 2"), and listenerMiddleware.ts's
    // "ensure selected images are valid" listener re-checks every selectedImage against its own
    // query's search results on every fetchSearchResults.fulfilled - a canned mock keyed only to
    // "my search query" resolves "card 2" to an empty result set and immediately deselects the
    // image AddCardToProjectForm just set. This mock adds the second hash key so "card 2" itself
    // resolves to [cardDocument2.identifier] too - the same trap AddCardToProjectForm.spec.ts's
    // own precedent avoids via searchResultsOneResultCorrectSearchq.
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResultsPlusCard2SelfQuery,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    // One slot to start - the project already has cardDocument1 (the first of
    // searchResultsThreeResults' three identifiers) selected for it.
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();

    await expect(page.getByTestId("display-page")).toBeVisible();
    await expect(
      page.getByTestId("page-preview-slot").locator("img")
    ).toHaveCount(1);

    // Add mode is the default - the center region shows the print-sheet stack, not browse
    // results, and the search bar mounts ImportText's own inline variant.
    await expect(page.getByTestId("import-text-inline")).toBeVisible();
    await expect(page.getByTestId("catalog-browse-results")).toHaveCount(0);

    await page.getByTestId("display-search-mode-browse").click();

    // Toggling the search bar's own mode also flips the center region's switch (one shared
    // isBrowseMode state, not two independent ones - see DisplayPage.tsx's own comment).
    await expect(page.getByTestId("import-text-inline")).toHaveCount(0);
    await expect(page.getByTestId("display-browse-search-input")).toBeVisible();
    await expect(page.getByTestId("catalog-browse-results")).toBeVisible();
    // The print-sheet stack is not rendered at all while browsing (not just visually hidden) -
    // matches the mockup's own body.browse toggling behaviour.
    await expect(page.getByTestId("display-sheet-wrapper")).toHaveCount(0);

    await page
      .getByTestId("display-browse-search-input")
      .fill("my search query");

    const browseResults = page.getByTestId("catalog-browse-results");
    await expect(
      browseResults.getByTestId(
        `catalog-browse-tile-${cardDocument1.identifier}`
      )
    ).toBeVisible();
    await expect(
      browseResults.getByTestId(
        `catalog-browse-tile-${cardDocument2.identifier}`
      )
    ).toBeVisible();
    await expect(
      browseResults.getByTestId(
        `catalog-browse-tile-${cardDocument3.identifier}`
      )
    ).toBeVisible();

    // Add the SECOND catalog result (not the one already in the deck) via its inline
    // AddCardToProjectForm - the same "+Add" path CardDetailedViewModal already exposes.
    await browseResults
      .getByTestId(`catalog-browse-tile-${cardDocument2.identifier}`)
      .getByRole("button", { name: /Add to Project/ })
      .click();

    // Switch back to the sheet view (the same shared toggle, from either control) to confirm the
    // newly-added card actually landed in the deck, not just a client-side notification.
    await page.getByTestId("display-center-view-sheets").click();
    await expect(page.getByTestId("catalog-browse-results")).toHaveCount(0);
    const slotImages = page.getByTestId("page-preview-slot").locator("img");
    await expect(slotImages).toHaveCount(2);
    await expect(slotImages.last()).toHaveAttribute("alt", cardDocument2.name);
  });
});

// Issue #266 (docs' /display responsive layout spec, §4/§6 R2/R6) - the phone-tier journey that
// gates the whole #231 switchover decision: "tapping a card highlights it but surfaces nothing"
// (the owner's own repro) is fixed by the left rail becoming a real bottom-sheet drawer below
// `lg`, opened on slot tap. Scoped to its own describe block with `test.use({ viewport })` rather
// than a new Playwright `projects[]` entry - the existing `chromium` project's own configured
// 800x600 viewport (playwright.config.ts's `contextOptions.viewport`) is never actually applied
// (`contextOptions` isn't a real Playwright TestOptions field - the effective viewport for every
// other test in this repo is `devices["Desktop Chrome"]`'s own 1280x720, i.e. Desktop tier, both
// rails always inline - confirmed by inspecting the real rendered Offcanvas classes/computed
// style at that viewport). `test.use({ viewport })` at describe level is unaffected by that dead
// config and reliably narrows just this one test - not a whole new CI-matrix dimension re-running
// every spec at a phone size. Filed as its own troubleshooting.md entry, not fixed here - fixing
// the stale 800x600 intent would change the effective viewport (and therefore breakpoint tier) of
// every existing DisplayPage test in this file, well beyond this PR's #266 scope.
test.describe("DisplayPage - phone viewport (issue #266)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("tapping a card on a phone-width viewport opens the left rail as a bottom-sheet drawer showing that slot's details", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    // Straight to /display's own inline importer (design doc §4.1's `DeckInputLanding`), not via
    // the navbar's "Display (beta)" link - at this viewport, Navbar.tsx's own responsive collapse
    // hides nav links behind a hamburger toggle, which is that component's own concern, not
    // anything this test is about.
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("my search query");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();

    // Fit-to-width (§2): the whole landscape sheet is visible, not clipped to a fixed-width
    // render wider than the viewport - the owner's own "only the middle cards visible" repro.
    const sheetRegion = page.getByTestId("display-sheet-region");
    const regionBox = await sheetRegion.boundingBox();
    expect(regionBox).not.toBeNull();
    expect(regionBox?.width ?? Infinity).toBeLessThanOrEqual(390);
    await expect(page.getByTestId("page-preview-slot")).toHaveCount(8);

    // Closed by default at this viewport - only opens once a slot is tapped.
    const rail = page.getByTestId("display-rail");
    await expect(rail).not.toBeInViewport();

    // Live report (commit 85bd3a37, deployed): `toBeInViewport()` above is an aria/intersection
    // check, not a literal geometry one - it stayed green even while the R5 fix below was missing
    // (see LeftRailOffcanvas's own comment), since a merely-shrunken-but-still-open sheet is a
    // different bug than a genuinely visible-when-closed one. Assert the actual bounding box
    // instead: Bootstrap's `.offcanvas-bottom` (closed, no `.show`) is `position: fixed; bottom: 0;
    // transform: translateY(100%)` - its box's own top edge must sit at/after the viewport's own
    // bottom edge, i.e. not one visible pixel of it inside the 844px-tall viewport.
    const closedBox = await rail.boundingBox();
    expect(closedBox).not.toBeNull();
    expect(closedBox?.y ?? -Infinity).toBeGreaterThanOrEqual(844);

    await page.getByTestId("page-preview-slot").first().click();

    // Now visible as a real drawer (react-bootstrap's portaled Offcanvas), showing the tapped
    // slot's own header - not just "highlights it but surfaces nothing" (issue #266's repro).
    await expect(rail).toBeInViewport();
    await expect(page.getByTestId("display-rail-header")).toContainText(
      "Slot 1"
    );

    // The design doc's own 72vh (see docs/proposals/proposal-h-display-layout-spec.md's R5 row,
    // and the approved mockup's `.rail-left{height:72vh}` rule) - not Bootstrap's stock 30vh
    // ($offcanvas-vertical-height default), which is what the live report's "mostly non visible"
    // sliver actually was: a real, in-viewport, but far-too-short drawer.
    const openBox = await rail.boundingBox();
    expect(openBox).not.toBeNull();
    const expectedHeight = 0.72 * 844;
    expect(openBox?.height ?? 0).toBeGreaterThan(expectedHeight - 20);
    expect(openBox?.height ?? Infinity).toBeLessThan(expectedHeight + 20);

    // Dismissible (design doc §4.1's bottom-sheet - react-bootstrap's own Offcanvas keyboard
    // handling, unmodified here). Checked via the dialog role rather than `rail` (the shared
    // data-testid) - below its inline breakpoint, Offcanvas keeps BOTH a static, CSS-hidden node
    // (needed so `responsive` has something to swap to) and, only while genuinely open, a second,
    // portal-rendered dialog node sharing the same data-testid - a plain testid locator would hit
    // Playwright's strict-mode "resolved to 2 elements" once both exist, which briefly happens
    // again mid-close (the portal node lingers for its own exit transition).
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("dialog", { name: "Card details and art selection" })
    ).toHaveCount(0);
  });
});
