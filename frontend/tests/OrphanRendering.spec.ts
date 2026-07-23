/**
 * Foreign-order resilience Phase 1 (issue #324) - end-to-end coverage for the owner's own
 * 2026-07-23 high-priority repro: importing a reference to a Drive file ID this catalog has
 * never indexed must render an orphan tile (image, "find this card" search still live), not
 * silently drop the selection or land it in the Invalid Cards modal.
 *
 * Acceptance surface (owner ruling, 2026-07-23 review round): the classic /editor page is a
 * legacy route held behind the route-swap PR #389 - the UNIFIED /display page (nav "Editor")
 * is the only acceptance surface for frontend rendering work, so both cases below run there, not
 * on /editor. The shared parse/import layers (processing.ts, cardDocumentsSlice.ts,
 * listenerMiddleware.ts) are unaffected by which page mounts them - orphan rendering on /display
 * needed NO code change (it already reads `cardDocument.mediumThumbnailUrl`/`isOrphan` off the
 * same shared `cardDocuments` store slice PagePreview.tsx's own sheet-cell renderer uses), so
 * this file is proof, not a fix. Note this is a DIFFERENT rendering path from Card.tsx (the
 * classic editor's own card component, which additionally shows an "orphan-badge" corner label -
 * see Card.test.tsx for that unit-level coverage): PagePreview.tsx (the /display sheet's own
 * renderer) has no badge equivalent today, so no badge assertion appears below - that's a
 * pre-existing, page-scoped gap in the sheet's own visual language, not a regression this file
 * introduces or hides.
 *
 * The classic editor's own "Common Cardback" panel (CommonCardback.tsx, /editor only - /display
 * has no equivalent persistent tile, only the CardbackToolbarButton picker) is covered
 * separately by ImportXML.spec.ts's "brand new project" test, since that panel/bug is
 * editor-specific.
 */

import { expect } from "@playwright/test";

import { defaultHandlers } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// A syntactically real-looking Drive file ID this catalog's mocked backend never returns from
// /2/cards/ or /3/editorSearch/ (see defaultHandlers - cardDocumentsNoResults/
// searchResultsNoResults) - exercises the genuinely-unresolved-forever path, not a race with a
// mock that happens to resolve it eventually.
const orphanId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
const orphanBackId = "1LrVX0pUcye9n_0RtaDNVl2xPrQgn7CYf";

// Whichever test in this file is first to actually hit /display pays Next dev mode's on-demand
// page-compile cost for a brand-new route (DisplayPage.spec.ts's own precedent comment) -
// comfortably over the default 30s test timeout when this file runs in isolation.
test.describe.configure({ timeout: 60_000 });

test.describe("orphan rendering (issue #324) - unified /display page", () => {
  test("the owner's exact reported text-import line registers and renders an orphan tile", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible({
      timeout: 20_000,
    });

    await page
      .getByRole("textbox", { name: "import-text" })
      .fill(`1x Kharn [mpc:${orphanId}]`);
    await page.getByRole("button", { name: "import-text-submit" }).click();

    await expect(page.getByTestId("display-page")).toBeVisible();

    // Never lands in the Invalid Cards flow - the whole point of this feature.
    await expect(page.getByText("Review Invalid Cards")).not.toBeVisible();

    const slot = page.getByTestId("page-preview-slot").first();
    // The stand-in name comes from the parsed SearchQuery, which - same as every other text
    // import - lowercases the query text (processQuery); "Kharn" the user typed, "kharn" here
    // is expected, not a bug.
    const image = slot.locator("img");
    // Generous timeout: this is the same real direct-from-Google fetch URL construction the
    // classic editor's own orphan test waits out, plus this page's own first-compile cost.
    await expect(image).toHaveCount(1, { timeout: 45_000 });
    await expect(image).toHaveAttribute("alt", "kharn");
    await expect(image).toHaveAttribute(
      "src",
      `https://lh4.googleusercontent.com/d/${orphanId}=h800`
    );

    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-text-import-desktop.png",
    });
  });

  test("an XML order referencing an unindexed front id and an unindexed implicit cardback (the reported b:null case) renders both as orphans, including the cardback corner", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "display");
    await expect(page.getByTestId("display-empty-state")).toBeVisible({
      timeout: 20_000,
    });

    await page.getByRole("button", { name: "XML" }).click();
    const fileInput = page
      .getByLabel("import-xml")
      .locator('input[type="file"]')
      .first();
    await fileInput.setInputFiles({
      name: "test.xml",
      mimeType: "text/xml;charset=utf-8",
      buffer: Buffer.from(
        `<order>
          <details>
            <quantity>1</quantity>
            <stock>(S30) Standard Smooth</stock>
            <foil>false</foil>
          </details>
          <fronts>
            <card>
              <id>${orphanId}</id>
              <sourceType>google_drive</sourceType>
              <slots>0</slots>
              <name>Kharn.png</name>
              <query>kharn</query>
            </card>
          </fronts>
          <cardback>${orphanBackId}</cardback>
        </order>`
      ),
    });

    await expect(page.getByTestId("display-page")).toBeVisible();
    await expect(page.getByText("Review Invalid Cards")).not.toBeVisible();

    const slot = page.getByTestId("page-preview-slot").first();
    const frontImage = slot.locator("img");
    await expect(frontImage).toHaveCount(1, { timeout: 45_000 });
    await expect(frontImage).toHaveAttribute(
      "src",
      `https://lh4.googleusercontent.com/d/${orphanId}=h800`
    );

    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-xml-import-desktop.png",
    });

    // No <backs> element covers this slot, so parseXmlImport falls back to the order's own
    // root-level <cardback> - the exact "b:null" mechanism from the owner's screenshot (see
    // ImportXML.test.ts's own comment on this). That fallback is per-slot (back-slot0's own
    // selectedImage), rendered here via the SAME sheet cell once the page is toggled to show
    // backs - the "cardback corner" from the owner's fix request. This is a DIFFERENT concept
    // from the "Common Cardback" panel (ImportXML.spec.ts's own coverage, /editor only).
    await page.getByRole("button", { name: /Showing: Fronts/ }).click();
    const backImage = slot.locator("img");
    await expect(backImage).toHaveCount(1, { timeout: 45_000 });
    await expect(backImage).toHaveAttribute(
      "src",
      `https://lh4.googleusercontent.com/d/${orphanBackId}=h800`
    );

    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-xml-import-backs-desktop.png",
    });
  });
});
