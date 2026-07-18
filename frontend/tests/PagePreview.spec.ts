import { expect, Page } from "@playwright/test";

import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const addCardAndOpenPDFTab = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importText(page, "my search query");
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
