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

    // Choose Image is open by default; the other four sections start collapsed - per the
    // owner's accordion amendment (design doc §2).
    await expect(
      page.getByText("The candidate/version picker", { exact: false })
    ).toBeVisible();
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).not.toBeVisible();
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

    await page.getByRole("heading", { name: "Attributes" }).click();
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
    await page.getByRole("heading", { name: "Attributes" }).click();
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).toBeVisible();

    // Selecting the other real slot swaps the rail's whole subtree - Attributes should be back
    // to collapsed, not still expanded from the last slot.
    await slots.nth(1).click();
    await expect(
      page.getByText("Attribute chips (AttributeChipPanel)", { exact: false })
    ).not.toBeVisible();
    await expect(
      page.getByText("The candidate/version picker", { exact: false })
    ).toBeVisible();
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
});
