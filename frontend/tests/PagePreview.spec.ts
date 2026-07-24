import { expect, Page } from "@playwright/test";

import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`); the classic grid `ProjectEditor` this file's own setup
// depends on (via testids/interaction patterns like `front-slot`/`back-slot`/`common-cardback`/
// the "Add Cards" right-panel dropdown/the classic "Print!" tab, or a component with no rendered
// equivalent on the new page yet - see issue #272's own tracked parity gaps) is fully unrouted,
// not just delisted from the nav. Skipped here rather than deleted (component files themselves
// are untouched, per this swap's own scope) or silently left red - porting this coverage to
// DisplayPage's DOM is real, non-mechanical work tracked against #272, not done as part of the
// route swap itself (the owner's directive was to proceed with the swap regardless of the
// checklist's open items).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Proposal H switchover (2026-07-23): tests classic /editor-only UI, now unrouted - see issue #272"
  );
});

const addCardAndOpenPDFTab = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "my search query");
  await page.getByRole("tab", { name: "Print!" }).click();
  await page.getByRole("tab", { name: "PDF" }).click();
};

test.describe("PDFGenerator - fast page preview (Proposal A)", () => {
  test("shows the fast DOM preview by default, with a slot rendered and no spinner", async ({
    page,
    network,
  }) => {
    network.use(
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await addCardAndOpenPDFTab(page);

    // Fast preview is instant - no debounce, no PDF-render round trip - so it should already
    // be visible without waiting for any spinner to resolve.
    await expect(page.getByTestId("page-preview")).toBeVisible();
    await expect(page.getByTestId("page-preview-slot").first()).toBeVisible();
  });

  test("toggling to exact preview switches to the pdf.js canvas render, and back", async ({
    page,
    network,
  }) => {
    network.use(
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await addCardAndOpenPDFTab(page);

    await expect(page.getByTestId("page-preview")).toBeVisible();
    await expect(page.getByTestId("preview-mode-toggle")).toHaveText(
      "Switch to exact PDF preview"
    );

    await page.getByTestId("preview-mode-toggle").click();
    await expect(page.getByTestId("page-preview")).toHaveCount(0);
    await expect(page.getByTestId("preview-mode-toggle")).toHaveText(
      "Switch to fast preview"
    );

    await page.getByTestId("preview-mode-toggle").click();
    await expect(page.getByTestId("page-preview")).toBeVisible();
  });

  test("the fast preview reflows live when page margins change, without a spinner", async ({
    page,
    network,
  }) => {
    network.use(
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await addCardAndOpenPDFTab(page);

    // A4, default 5mm margins, 0 bleed, 0 spacing settles to a 3x3 grid - wait for that
    // steady state rather than reading the count on first paint, which can race the initial
    // layout before state has fully settled.
    await expect
      .poll(() => page.getByTestId("page-preview-slot").count())
      .toBe(9);
    const initialSlotCount = await page
      .getByTestId("page-preview-slot")
      .count();

    await page.getByText("Spacing & Margins").click();
    // NumericField renders <Form.Label> and <Form.Control> as plain siblings with no
    // htmlFor/id association, so getByLabel can't resolve it - target the input immediately
    // following the label text via a CSS sibling combinator instead.
    const marginTop = page.locator(
      'label:text-is("Page margin top (mm)") ~ input'
    );
    await expect(marginTop).toBeVisible();
    await marginTop.fill("80");
    await expect(marginTop).toHaveValue("80");
    await marginTop.press("Tab");

    await expect
      .poll(() => page.getByTestId("page-preview-slot").count(), {
        timeout: 10_000,
      })
      .toBeLessThan(initialSlotCount);
  });
});
