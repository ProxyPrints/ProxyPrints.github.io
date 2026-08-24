import { expect } from "@playwright/test";

import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
} from "@/common/test-constants";
import {
  cardbacksThreeResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  completePdfExportToDisk,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Cardback flow round (SPEC-cardback-pdfwait.md §C, PKG1) - the no-cardback reminder gate (1a)
// and the apply-all/set-default prompt from both entries (1b, toolbar = project-wide, rail =
// per-slot). The reminder gate is reached through the real /editor -> Export dropdown -> PDF ->
// Download flow (the gate now wraps DisplayExportPDF.tsx's own buttons, not a navigation - see
// docs/features/pdf-generator.md's "Page cut guide lines, Google Drive save, and retiring the
// Finish footer's own print route"); the classic /editor route is still fully unrouted.
//
// R9 (editor-repass round, item 2) - the per-slot (left rail) picker is now the shared
// CardbackSwatchStrip with NO apply/set-default affordances (the old never-pre-checked
// trap-guard prompt is retired with it), and the toolbar (right rail) Carton section is the
// same strip + two plain buttons, with the full GridSelectorModal reachable via
// "Browse all cardbacks…" (its inline apply prompt - thumbnails + count + done states - is
// unchanged and asserted through that path below).

const threeCardHandlers = [
  cardDocumentsThreeResults,
  cardbacksThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  tagConsensusTwoUnresolvedTags,
  ...defaultHandlers,
];

test.describe("Cardback reminder gate (SPEC-cardback-pdfwait.md §C.1, PKG1a)", () => {
  test.describe.configure({ mode: "serial", timeout: 60_000 });

  test("appears for a project still riding the default cardback; dismissing it (✕) still proceeds with the export (OWNER AMENDMENT 1), and a second attempt this session is silent (CB1)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    const clickExportPDFDownload = async () => {
      await page.getByTestId("display-export-menu-toggle").click();
      await page.getByTestId("display-export-pdf-button").click();
    };

    await clickExportPDFDownload();

    const gate = page.getByTestId("pre-print-cardback-gate");
    await expect(gate).toBeVisible();
    await expect(gate).toContainText("default cardback");
    await expect(gate.getByTestId("cardback-gate-use-current")).toBeVisible();

    // OWNER AMENDMENT 1 - dismiss (the header's own ✕) is NOT a cancel; it behaves exactly like
    // "Use current & continue" and the export attempt proceeds.
    await gate.getByLabel("Close").click();
    const download = await completePdfExportToDisk(page);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // CB1: at most once per session, so a second export attempt (same tab/session, no reload -
    // the suppression key is keyed on project identity, not project CONTENT, so the still-live
    // project is still covered by it) shows no gate at all.
    await clickExportPDFDownload();
    await expect(page.getByTestId("pre-print-cardback-gate")).toHaveCount(0);
    const secondDownload = await completePdfExportToDisk(page);
    expect(secondDownload.suggestedFilename()).toBe("cards.pdf");
  });

  test("choosing a cardback from the gate's swatch strip picks it project-wide and still proceeds with the export (R9)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await page.getByTestId("display-export-menu-toggle").click();
    await page.getByTestId("display-export-pdf-button").click();

    const gate = page.getByTestId("pre-print-cardback-gate");
    await expect(gate).toBeVisible();
    await gate.getByTestId("cardback-gate-choose").click();

    // R9 - the gate's own body swaps to the shared swatch strip (the retired grid-selector
    // modal mount is gone); a pick proceeds with the export (OWNER AMENDMENT 1 still applies).
    const gateStrip = gate.getByTestId("cardback-gate-strip");
    await expect(gateStrip).toBeVisible();
    await gateStrip.getByAltText(cardDocument2.name).click();
    await expect(gate).toHaveCount(0);
    const download = await completePdfExportToDisk(page);
    expect(download.suggestedFilename()).toBe("cards.pdf");
  });
});

test.describe("Cardback apply-all + set-default (SPEC-cardback-pdfwait.md §C.2, PKG1b; R9 strip round)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("rail (per-slot) entry picks per-slot via the shared swatch strip - no apply/set-default affordances and no trap-guard prompt any more - and the sheet's flip icon flags the resulting custom back", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    // Two slots, both fronts resolving to cardDocument1 - cardbacksThreeResults' own
    // fetchCardbacks.fulfilled listener auto-seeds BOTH slots' backs to its first entry
    // (cardDocument1), so both start on the (non-explicit) project default.
    await importTextOnEditorLanding(page, "my search query\nmy search query");

    const sheetSlots = page.getByTestId("page-preview-slot");
    await expect(sheetSlots.nth(0).locator("img")).toBeVisible();
    await expect(sheetSlots.nth(1).locator("img")).toBeVisible();

    // --- rail entry: give slot 0 a deliberately-custom back (cardDocument2) via the strip ---
    await sheetSlots.nth(0).click();
    const railControl = page.getByTestId("slot-cardback-control");
    await expect(railControl).toBeVisible();
    await railControl.getByTestId("slot-cardback-choose").click();

    const railPicker = page.getByTestId("slot-cardback-picker");
    await expect(railPicker).toBeVisible();
    // R9 - the strip's swatches are real <img> (alt = card name), same alt-text discipline as
    // the retired embedded results grid; scoped to the picker since the right rail's own strip
    // shows the same cardbacks.
    await railPicker.getByAltText(cardDocument2.name).click();

    // The picker closes on pick, and no apply/set-default prompt follows anywhere (R9 retires
    // the per-slot prompt outright - there is no per-slot trap-guard to assert any more).
    await expect(railPicker).toHaveCount(0);
    await expect(page.getByTestId("cardback-apply-prompt")).toHaveCount(0);

    // Slot 0's flip icon now carries the custom-cardback indicator dot; slot 1's does not
    // (still following the deck default) - the per-slot pick stays per-slot.
    await expect(
      sheetSlots
        .nth(0)
        .getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toBeVisible();
    await expect(
      sheetSlots
        .nth(1)
        .getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toHaveCount(0);
  });

  test("project-wide entry (now in the left rail): a swatch pick never touches a per-slot custom back, and Apply to all names its blast radius and skips protected slots (Rule A/B)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query\nmy search query");

    const sheetSlots = page.getByTestId("page-preview-slot");
    await expect(sheetSlots.nth(0).locator("img")).toBeVisible();
    await expect(sheetSlots.nth(1).locator("img")).toBeVisible();

    // Precondition: slot 0 gets a deliberately custom back (cardDocument2) - a manually-changed
    // back is one of Rule B's three protected sources, so it must survive every apply below.
    await sheetSlots.nth(0).click();
    const slotControl = page.getByTestId("slot-cardback-control");
    await slotControl.getByTestId("slot-cardback-choose").click();
    await page
      .getByTestId("slot-cardback-picker")
      .getByAltText(cardDocument2.name)
      .click();

    // --- project-wide entry: left-rail subject-matter round moved this out of the right
    //     (print/export) rail entirely - it now lives beside the per-slot control above, and
    //     only renders once a slot is selected (slot 0 already is, from the step above). ---
    const projectSection = page.getByTestId("cardback-rail-control");
    await expect(projectSection).toBeVisible();
    const projectStrip = page.getByTestId("cardback-rail-strip");
    await expect(projectStrip).toBeVisible();
    // The project default (cardDocument1) is the selected swatch; the custom slot-0 back
    // (cardDocument2) is not. aria-pressed lives on the swatch <button>, not the <img>
    // getByAltText resolves to - target the button by its accessible name instead.
    await expect(
      projectStrip.getByRole("button", { name: cardDocument1.name })
    ).toHaveAttribute("aria-pressed", "true");
    // No apply prompt until a swatch is actually picked (Rule A - never a pre-armed action).
    await expect(
      projectSection.getByTestId("cardback-apply-prompt")
    ).toHaveCount(0);

    // A project-wide pick via the strip (cardDocument3) bulk-replaces the slot that was
    // following the project default (slot 1); the per-slot custom back (slot 0) is untouched -
    // unchanged §C.2 bulk-replace behaviour, now exercised from the left rail.
    await projectStrip.getByAltText(cardDocument3.name).click();
    await page.getByTestId("display-view-toggle-backs").click();
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
    await expect(sheetSlots.nth(1).locator("img")).toHaveAttribute(
      "alt",
      cardDocument3.name
    );

    // Picking surfaces the SAME CardbackApplyPrompt the modal's own footer uses (Rule A) - and
    // it correctly identifies slot 0 as protected (manually changed) rather than "would
    // override": the bulk-replace above already caught up every slot that was following the
    // old default, so there is nothing left for "Apply to all" to change here - a real,
    // meaningful (0), not a stub.
    const applyPrompt = projectSection.getByTestId("cardback-apply-prompt");
    await expect(applyPrompt).toBeVisible();
    const thumbnails = applyPrompt.getByTestId(
      "cardback-apply-prompt-thumbnails"
    );
    await expect(thumbnails).toBeVisible();
    await expect(thumbnails).toContainText("Slot 1");
    const applyAllButton = applyPrompt.getByTestId("cardback-apply-all-button");
    const setDefaultButton = applyPrompt.getByTestId(
      "cardback-set-default-button"
    );
    await expect(applyAllButton).toHaveText("Apply to all (0)");

    // Rule B regression guard: clicking Apply to all must leave the protected back alone.
    await applyAllButton.click();
    await expect(applyAllButton).toHaveText("Applied to all ✓");
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
    await expect(
      sheetSlots
        .nth(0)
        .getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toBeVisible();

    await setDefaultButton.click();
    await expect(setDefaultButton).toHaveText("Default set ✓");

    // --- Browse all cardbacks… still opens the same GridSelectorModal; its inline apply prompt
    //     (thumbnails + count + done states, OWNER AMENDMENT 2/OQ-B) is unchanged, and now
    //     shares the exact same protection logic. Picking cardDocument1 here makes slot 0's
    //     back (cardDocument2, untouched throughout) differ from the project cardback again, so
    //     it's named as protected once more - proving the guarantee holds across both entry
    //     points, not just the rail's own strip. ---
    await page.getByTestId("cardback-browse-all-button").click();
    const cardbackModal = page.getByTestId("cardback-grid-selector");
    await expect(cardbackModal).toBeVisible();
    await cardbackModal.getByAltText(cardDocument1.name).click();

    const modalPrompt = cardbackModal.getByTestId("cardback-apply-prompt");
    await expect(modalPrompt).toBeVisible();
    const modalThumbnails = modalPrompt.getByTestId(
      "cardback-apply-prompt-thumbnails"
    );
    await expect(modalThumbnails).toBeVisible();
    await expect(modalThumbnails).toContainText("Slot 1");
    // Slot 1 (currently cardDocument3, was just bulk-replaced along with the pick above to
    // cardDocument1) is not protected and already matches - only slot 0 is named.
    await expect(modalThumbnails).not.toContainText("Slot 2");
    await expect(
      modalPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Apply to all (0)");

    await cardbackModal.getByRole("button", { name: "Close" }).last().click();
    await expect(cardbackModal).not.toBeVisible();

    // Slot 0's protected custom back has survived every apply action above, untouched.
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
  });
});
