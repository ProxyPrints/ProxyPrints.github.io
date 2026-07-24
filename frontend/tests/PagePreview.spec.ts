import { expect, Page } from "@playwright/test";

import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { navigateToPrintPDFTab } from "./test-utils";

// Parked-spec port wave (2026-07-24, issue #272). Re-homed onto the standalone /print route
// (D10, pages/print.tsx) - see PDFGenerator.spec.ts's own module comment for the full rationale
// (this file exercises the identical PDFGenerator.tsx mount, unchanged by the route swap).
//
// Ported selectively, not verbatim - deduped against the unified page's own sheet coverage
// (DisplayPage.spec.ts/OrphanRendering.spec.ts, both dozens of `page-preview-slot` assertions
// against the SAME PagePreview.tsx component, just mounted directly on /editor's sheet region
// rather than behind the Print page's PDF tab). None of this file's 3 tests turned out to be a
// true duplicate once checked against that existing coverage - all 3 ported as-is (see this PR's
// own body for the full dedup table):
//   - "shows the fast DOM preview by default..." asserts the `page-preview` CONTAINER testid,
//     which neither DisplayPage.spec.ts nor OrphanRendering.spec.ts ever reference (both only
//     ever assert against individual `page-preview-slot` children) - not a duplicate.
//   - "toggling to exact preview switches to the pdf.js canvas render, and back" exercises
//     `preview-mode-toggle`, which only exists on PDFGenerator.tsx's own mount - DisplayPage's
//     sheet has no toggle at all (it's permanently in fast-preview mode). Print-page-only
//     behavior, not portable elsewhere, not a duplicate.
//   - "the fast preview reflows live when page margins change..." exercises the "Spacing &
//     Margins" NumericField section, which is also PDFGenerator.tsx-only - DisplayPage has no
//     margin controls of its own (grep-confirmed: "Spacing & Margins"/"page margin" only appear
//     in PDFGenerator.tsx). Not a duplicate.
//
// Generous file-level timeout (not the 30s default) - navigateToPrintPDFTab's own retry against
// /print's cold-compile race (test-utils.ts's own comment) needs headroom beyond a single 30s
// test timeout to actually get a second attempt in, same precedent PDFGenerator.spec.ts uses.
test.describe.configure({ timeout: 60_000 });

const addCardAndOpenPDFTab = async (page: Page) =>
  navigateToPrintPDFTab(page, "my search query");

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
