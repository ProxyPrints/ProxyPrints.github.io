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
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 30_000 }),
      gate.getByLabel("Close").click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");

    // CB1: at most once per session, so a second export attempt (same tab/session, no reload -
    // the suppression key is keyed on project identity, not project CONTENT, so the still-live
    // project is still covered by it) shows no gate at all.
    const [secondDownload] = await Promise.all([
      page.waitForEvent("download", { timeout: 30_000 }),
      clickExportPDFDownload(),
    ]);
    await expect(page.getByTestId("pre-print-cardback-gate")).toHaveCount(0);
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
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 30_000 }),
      gateStrip.getByAltText(cardDocument2.name).click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
    await expect(gate).toHaveCount(0);
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

  test("toolbar (project-wide) entry: the right rail's swatch strip + its two plain buttons apply and remember independently, and Browse all cardbacks… still opens the full modal with the unchanged apply prompt", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query\nmy search query");

    const sheetSlots = page.getByTestId("page-preview-slot");
    await expect(sheetSlots.nth(0).locator("img")).toBeVisible();
    await expect(sheetSlots.nth(1).locator("img")).toBeVisible();

    // Toolbar entry precondition: slot 0 gets a deliberately custom back (cardDocument2) so the
    // strip-pick assertion below can prove a project-wide pick never touches a per-slot custom
    // back. (The modal prompt's own "would override" count is re-seeded separately later - the
    // strip's apply-all wipes this custom back first, and the modal's pick auto-retargets every
    // slot still following the project cardback, so only a freshly re-created custom back can
    // survive long enough to be counted.)
    await sheetSlots.nth(0).click();
    const slotControl = page.getByTestId("slot-cardback-control");
    await slotControl.getByTestId("slot-cardback-choose").click();
    await page
      .getByTestId("slot-cardback-picker")
      .getByAltText(cardDocument2.name)
      .click();

    // --- toolbar entry: the section is the strip + two plain buttons (R9) ---
    const toolbarSection = page.getByTestId("cardback-rail-control");
    await expect(toolbarSection).toBeVisible();
    const toolbarStrip = page.getByTestId("cardback-rail-strip");
    await expect(toolbarStrip).toBeVisible();
    // Both the project default (cardDocument1) and the custom slot-0 back (cardDocument2) start
    // unselected in this strip - the selected swatch is the project cardback itself. aria-pressed
    // lives on the swatch <button>, not the <img> getByAltText resolves to - target the button by
    // its accessible name (the same title/aria-label the swatch sets) instead.
    await expect(
      toolbarStrip.getByRole("button", { name: cardDocument1.name })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      toolbarSection.getByTestId("cardback-rail-apply-all-button")
    ).toHaveText("Apply to all card backs");
    await expect(
      toolbarSection.getByTestId("cardback-rail-set-default-button")
    ).toHaveText("Set as my default cardback");

    // A project-wide pick via the strip (cardDocument3) overrides the slot following the
    // project default; the per-slot custom back is untouched.
    await toolbarStrip.getByAltText(cardDocument3.name).click();
    await page.getByTestId("display-view-toggle-backs").click();
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
    await expect(sheetSlots.nth(1).locator("img")).toHaveAttribute(
      "alt",
      cardDocument3.name
    );

    // Apply to all / Set as my default, under the strip, act on the project cardback (now
    // cardDocument3) and flip to done states independently; "Apply to all" overrides the
    // per-slot custom back too.
    const applyAllButton = toolbarSection.getByTestId(
      "cardback-rail-apply-all-button"
    );
    const setDefaultButton = toolbarSection.getByTestId(
      "cardback-rail-set-default-button"
    );
    await applyAllButton.click();
    await expect(applyAllButton).toHaveText("Applied to all ✓");
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument3.name
    );
    // Slot 0's custom-cardback indicator is gone - it no longer differs from the deck default.
    await expect(
      sheetSlots
        .nth(0)
        .getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toHaveCount(0);
    await setDefaultButton.click();
    await expect(setDefaultButton).toHaveText("Default set ✓");

    // R9 - the strip apply-all just normalized BOTH slots to cardDocument3, and the modal's own
    // pick auto-bulk-replaces every slot still following the project cardback (§C.2, unchanged),
    // so re-seeding a custom back here (cardDocument1, != the modal's upcoming cardDocument2
    // pick) is what gives the prompt below a real "would override" count - the same precondition
    // the pre-R9 toolbar test relied on, reached via the per-slot strip instead. The re-pick
    // happens in the fronts view (where slot selection is exercised elsewhere in this suite);
    // the modal section below runs in the backs view like the earlier assertions.
    await page.getByTestId("display-view-toggle-fronts").click();
    await sheetSlots.nth(0).click();
    await page
      .getByTestId("slot-cardback-control")
      .getByTestId("slot-cardback-choose")
      .click();
    await page
      .getByTestId("slot-cardback-picker")
      .getByAltText(cardDocument1.name)
      .click();
    await expect(page.getByTestId("slot-cardback-picker")).toHaveCount(0);
    await page.getByTestId("display-view-toggle-backs").click();

    // --- Browse all cardbacks… still opens the same GridSelectorModal; its inline apply prompt
    //     (thumbnails + count + done states, OWNER AMENDMENT 2/OQ-B) is unchanged. ---
    await page.getByTestId("cardback-browse-all-button").click();
    const cardbackModal = page.getByTestId("cardback-grid-selector");
    await expect(cardbackModal).toBeVisible();
    await cardbackModal.getByAltText(cardDocument2.name).click();

    const toolbarPrompt = cardbackModal.getByTestId("cardback-apply-prompt");
    await expect(toolbarPrompt).toBeVisible();
    // Slot 0's re-seeded custom back (cardDocument1) survives the modal's pick untouched - the
    // pick's §C.2 bulk-replace only retargeted slot 1 (back === old project cardback
    // cardDocument3) to cardDocument2 - so the prompt names exactly that one slot as affected.
    const thumbnails = toolbarPrompt.getByTestId(
      "cardback-apply-prompt-thumbnails"
    );
    await expect(thumbnails).toBeVisible();
    await expect(thumbnails).toContainText("Slot 1");
    await expect(thumbnails).not.toContainText("Slot 2");
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Apply to all (1)");
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-prompt-not-now")
    ).toBeVisible();

    await toolbarPrompt.getByTestId("cardback-apply-all-button").click();
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Applied to all ✓");
    await toolbarPrompt.getByTestId("cardback-set-default-button").click();
    await expect(
      toolbarPrompt.getByTestId("cardback-set-default-button")
    ).toHaveText("Default set ✓");

    await cardbackModal.getByRole("button", { name: "Close" }).last().click();
    await expect(cardbackModal).not.toBeVisible();

    // The sheet reflects the modal's pick - both slots now show cardDocument2's back (the
    // back view is already active from the earlier display-view-toggle-backs switch).
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
    await expect(sheetSlots.nth(1).locator("img")).toHaveAttribute(
      "alt",
      cardDocument2.name
    );
  });
});
