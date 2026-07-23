/**
 * Foreign-order resilience Phase 1 (issue #324) - end-to-end coverage for the owner's own
 * 2026-07-23 high-priority repro: importing a reference to a Drive file ID this catalog has
 * never indexed must render an orphan tile (badge, image, "find this card" search still live),
 * not silently drop the selection or land it in the Invalid Cards modal.
 */

import { expect } from "@playwright/test";

import { defaultHandlers } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectCardSlotToExist,
  importText,
  importXML,
  loadPageWithDefaultBackend,
  toggleFace,
} from "./test-utils";

// A syntactically real-looking Drive file ID this catalog's mocked backend never returns from
// /2/cards/ or /3/editorSearch/ (see defaultHandlers - cardDocumentsNoResults/
// searchResultsNoResults) - exercises the genuinely-unresolved-forever path, not a race with a
// mock that happens to resolve it eventually.
const orphanId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
const orphanBackId = "1LrVX0pUcye9n_0RtaDNVl2xPrQgn7CYf";

test.describe("orphan rendering (issue #324)", () => {
  test("the owner's exact reported text-import line registers and renders an orphan tile", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    await importText(page, `1x Kharn [mpc:${orphanId}]`);

    await expectCardSlotToExist(page, 1);
    const frontSlot = page.getByTestId("front-slot0");
    // The stand-in name comes from the parsed SearchQuery, which - same as every other text
    // import - lowercases the query text (processQuery); "Kharn" the user typed, "kharn" here
    // is expected, not a bug.
    await expect(frontSlot).toContainText("kharn");
    await expect(frontSlot.getByTestId("orphan-badge")).toBeVisible();
    await expect(frontSlot.getByTestId("orphan-badge")).toHaveText("Your file");

    // Never lands in the Invalid Cards flow - the whole point of this feature.
    await expect(page.getByText("Review Invalid Cards")).not.toBeVisible();

    // Wait for the real direct-from-Google fetch to actually resolve before screenshotting -
    // otherwise the shot just captures the spinner mid-flight. The extra fixed wait lets the
    // image's own 0.3s CSS opacity fade-in (card-img-fade-in) finish too, purely cosmetic.
    await expect(frontSlot.getByRole("status")).not.toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-text-import-desktop.png",
    });
  });

  test("an XML order referencing an unindexed front id and an unindexed implicit cardback (the reported b:null case) renders both as orphans", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    await importXML(
      page,
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
    );

    await expectCardSlotToExist(page, 1);
    const frontSlot = page.getByTestId("front-slot0");
    await expect(frontSlot.getByTestId("orphan-badge")).toBeVisible();

    // No <backs> element covers this slot, so parseXmlImport falls back to the order's own
    // root-level <cardback> - the exact "b:null" mechanism from the owner's screenshot (see
    // ImportXML.test.ts's own comment on this). That fallback is per-slot (back-slot0's own
    // selectedImage) - it's a SEPARATE concept from the shared "Common Cardback" panel (which
    // only reflects state.project.cardback, auto-selected from the indexed cardbacks list, and
    // stays empty here since the mocked backend has none) - so the back-slot0 tile is what's
    // under test, not Common Cardback. The small viewport this suite runs at collapses the
    // editor to a front/back toggle, so it must be switched to before back-slot0 is visible.
    await toggleFace(page);
    const backSlot = page.getByTestId("back-slot0");
    await expect(backSlot.getByTestId("orphan-badge")).toBeVisible();
    await expect(backSlot.getByRole("status")).not.toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-xml-import-backs-desktop.png",
    });
    await toggleFace(page);

    await expect(page.getByText("Review Invalid Cards")).not.toBeVisible();
    await expect(frontSlot.getByRole("status")).not.toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: "test-results/orphan-xml-import-desktop.png",
    });
  });
});
