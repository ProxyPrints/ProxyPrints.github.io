import { expect } from "@playwright/test";

import { cardDocument2, cardDocument3 } from "@/common/test-constants";
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
// per-slot). Reached entirely through the real /editor -> Finish footer flow, same as every
// other post-Proposal-H display suite (the classic /editor route is fully unrouted).

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

  test("appears for a project still riding the default cardback; dismissing it (✕) still proceeds (OWNER AMENDMENT 1), and a second attempt this session is silent (CB1)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await page.getByTestId("finish-footer-print-export").click();

    const gate = page.getByTestId("pre-print-cardback-gate");
    await expect(gate).toBeVisible();
    await expect(gate).toContainText("default cardback");
    await expect(gate.getByTestId("cardback-gate-use-current")).toBeVisible();

    // OWNER AMENDMENT 1 - dismiss (the header's own ✕) is NOT a cancel; it behaves exactly like
    // "Use current & continue" and the print attempt proceeds.
    await gate.getByLabel("Close").click();
    await page.waitForURL(/\/print/, { timeout: 30_000 });
    await expect(page.getByRole("tab", { name: "PDF" })).toBeVisible();

    // Back to the editor (a real reload, same tab/session - sessionStorage survives this even
    // though the in-memory project itself doesn't, so re-importing is needed before a second
    // print attempt can be made at all). CB1: at most once per session, so no second gate -
    // the suppression key is keyed on project identity (unsaved -> one fixed bucket), not
    // project CONTENT, so a freshly re-imported project is still covered by it.
    await page.goto("/editor?server=http://127.0.0.1:8000", {
      waitUntil: "domcontentloaded",
    });
    await importTextOnEditorLanding(page, "my search query");
    await expect(page.getByTestId("finish-footer-print-export")).toBeVisible();
    await page.getByTestId("finish-footer-print-export").click();
    await expect(page.getByTestId("pre-print-cardback-gate")).toHaveCount(0);
    await page.waitForURL(/\/print/, { timeout: 30_000 });
  });
});

test.describe("Cardback apply-all + set-default prompt (SPEC-cardback-pdfwait.md §C.2, PKG1b)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("rail (per-slot) entry stays per-slot with a never-pre-checked trap-guard, and the sheet's flip icon flags the resulting custom back; the toolbar (project-wide) entry then shows the affected slot's thumbnails + count, and Apply to all/Set default both work independently", async ({
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

    // --- rail entry: give slot 1 a deliberately-custom back (cardDocument2) ---
    await sheetSlots.nth(0).click();
    const railControl = page.getByTestId("slot-cardback-control");
    await expect(railControl).toBeVisible();
    await railControl.getByTestId("slot-cardback-choose").click();

    const railPicker = page.getByTestId("slot-cardback-picker");
    await expect(railPicker).toBeVisible();
    await railPicker.getByAltText(cardDocument2.name).click();

    const railPrompt = page.getByTestId("cardback-apply-prompt");
    await expect(railPrompt).toBeVisible();
    // Per-slot copy, count = 1 (only slot 2 still differs from the just-picked cardDocument2).
    await expect(
      railPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Apply to all (1)");
    await expect(
      railPrompt.getByTestId("cardback-apply-prompt-trapnote")
    ).toContainText("never pre-checked");
    // Never pre-checked - the button itself hasn't flipped to a done state.
    await expect(
      railPrompt.getByTestId("cardback-apply-all-button")
    ).not.toHaveText(/✓/);
    // No skip link on the rail entry (the rail is already the "no modal, ever" surface).
    await expect(
      railPrompt.getByTestId("cardback-apply-prompt-not-now")
    ).toHaveCount(0);

    // Deliberately DON'T apply-all here - "per-slot pick stays per-slot" is the whole point.
    // Slot 1's flip icon now carries the custom-cardback indicator dot; slot 2's does not
    // (still following the deck default).
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

    // --- toolbar entry: project-wide pick of a THIRD cardback ---
    // A dedicated testid, not a name-based locator - a slot's own "⟲" flip button can now ALSO
    // carry "cardback" in its accessible name (this same round's OWNER AMENDMENT 3 indicator),
    // which makes any Cardback-name-based locator ambiguous/fragile.
    await page.getByTestId("cardback-toolbar-button").click();
    const cardbackModal = page.getByTestId("cardback-grid-selector");
    await expect(cardbackModal).toBeVisible();
    await cardbackModal.getByAltText(cardDocument3.name).click();

    const toolbarPrompt = cardbackModal.getByTestId("cardback-apply-prompt");
    await expect(toolbarPrompt).toBeVisible();
    // OWNER AMENDMENT 2/OQ-B - the affected (still-custom) slot's thumbnails render above the
    // count line, and the count names it explicitly.
    const thumbnails = toolbarPrompt.getByTestId(
      "cardback-apply-prompt-thumbnails"
    );
    await expect(thumbnails).toBeVisible();
    await expect(thumbnails).toContainText("Slot 1");
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Apply to all (1)");
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-prompt-not-now")
    ).toBeVisible();

    // Apply to all - overrides slot 1's deliberately-custom back too (override-with-count, OQ-B).
    await toolbarPrompt.getByTestId("cardback-apply-all-button").click();
    await expect(
      toolbarPrompt.getByTestId("cardback-apply-all-button")
    ).toHaveText("Applied to all ✓");

    // Set as my default cardback - independent of the apply-all choice, seam-mocked (Annex A-2 -
    // no real persistence layer exists yet), but the UI's own done-state is real.
    await toolbarPrompt.getByTestId("cardback-set-default-button").click();
    await expect(
      toolbarPrompt.getByTestId("cardback-set-default-button")
    ).toHaveText("Default set ✓");

    await cardbackModal.getByRole("button", { name: "Close" }).last().click();
    await expect(cardbackModal).not.toBeVisible();

    // The sheet reflects the override - toggling to the back view shows cardDocument3 on BOTH
    // slots now (the button's own current label - "Showing: Fronts" - toggles TO backs on click).
    await page.getByText("Showing: Fronts").click();
    await expect(sheetSlots.nth(0).locator("img")).toHaveAttribute(
      "alt",
      cardDocument3.name
    );
    await expect(sheetSlots.nth(1).locator("img")).toHaveAttribute(
      "alt",
      cardDocument3.name
    );
    // Slot 1's custom-cardback indicator is gone - it's no longer different from the deck
    // default (the flip icon/indicator rendering is independent of which face is on screen).
    await expect(
      sheetSlots
        .nth(0)
        .getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toHaveCount(0);
  });
});
