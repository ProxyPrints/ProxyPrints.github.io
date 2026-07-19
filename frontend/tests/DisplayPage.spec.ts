import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { cardDocument8, localBackendURL } from "@/common/test-constants";
import {
  cardDocumentsNoResults,
  cardDocumentsThreeResults,
  cardDocumentsWithCanonicalCards,
  cardDocumentsWithResolvedPrintingMatch,
  defaultHandlers,
  searchResultsDegradedPrinting,
  searchResultsNoResults,
  searchResultsResolvedPrintingMatch,
  searchResultsThreeResults,
  searchResultsUnresolvedCanonicalImport,
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

  test("shows an empty-state message and a link back to the editor when the project has no cards", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Head to the editor" })
    ).toBeVisible();
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
    await expect(page.getByTestId("display-page-indicator")).toContainText(
      "Page 1 of 1"
    );
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
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).not.toBeVisible();
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
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).toBeVisible();
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
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).toBeVisible();

    // Selecting the other real slot swaps the rail's whole subtree - Attributes should be back
    // to collapsed, not still expanded from the last slot.
    await slots.nth(1).click();
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).not.toBeVisible();
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

  test("the requested-printing badge shows the plain style for a resolved, non-degraded printing-specific import", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithResolvedPrintingMatch,
      sourceDocumentsOneResult,
      searchResultsResolvedPrintingMatch,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 Lightning Bolt (2ED) 162");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    const badge = page.getByTestId("display-printing-badge");
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
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 my search query (XYZ) 999");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();

    const badge = page.getByTestId("display-printing-badge");
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
});
