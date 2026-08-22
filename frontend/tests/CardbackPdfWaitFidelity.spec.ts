import { expect } from "@playwright/test";

import { cardDocument2 } from "@/common/test-constants";
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
  ensureDisplayRightRailOpen,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openPDFExportSettingsAndClickDownload,
} from "./test-utils";

/**
 * CSS-fidelity guard for SPEC-cardback-pdfwait.md's binding token table (§E), self-verification
 * for the cardback flow + PDF-wait experience round. Every assertion reads REAL computed styles
 * (`toHaveCSS`, backed by `getComputedStyle`), matching this repo's own established discipline
 * (DisplayLeftRailFidelity.spec.ts's own module comment). Runs at BOTH 1400px and 390px per the
 * spec's own §H verification matrix - layout differs, but the token VALUES (color/border/font)
 * are viewport-independent, so most assertions are shared between the two `test()` bodies below,
 * not duplicated per-viewport tables.
 *
 * Not exhaustive against every row in §E - a representative, binding sample of the round's N
 * (introduced-this-round) elements across the two subsections still reachable from a populated
 * project (E.1 gate / E.2 grid+prompt), covering every DISTINCT colour token they introduce.
 * E.3 (progress bar) / E.4 (game embed) covered PDFGenerator.tsx's own /print wait experience,
 * reached by navigating there with a populated project - the editor export rescue retired that
 * navigation (DisplayExportPDF.tsx's Download button runs the export in place, no wait-panel
 * UI of its own) and left no other client path to a populated /print, so that pair was dropped
 * rather than ported; see .github/coverage-acks.txt for the same-shaped ack this file's own
 * E.1/E.2 companion (CardbackFlow.spec.ts) already recorded for its own removed-navigation tests.
 *
 * Tokyo-11 re-theme (2026-07-24, owner ruling - see docs/features/theming.md): this file's own
 * colour literals were re-derived from the #302 palette to Tokyo-11 in the same pass that
 * re-derived DisplayLeftRailFidelity.spec.ts's - tokens and spec tables move together, same
 * discipline. `CardbackApplyPrompt.tsx`/`useCardbackReminderGate.tsx`/`PDFWaitPanel.tsx` (all
 * landed via #431, after the original Tokyo-11 sweep) carried their own hardcoded #302-derived
 * literals that sweep hadn't reached yet - fixed onto `var(--bs-*)`/`var(--theme-*)` token
 * references in the same pass as this file's assertions, per-row comments below.
 */

const threeCardHandlers = [
  cardDocumentsThreeResults,
  cardbacksThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  tagConsensusTwoUnresolvedTags,
  ...defaultHandlers,
];

for (const viewport of [
  { width: 1400, height: 900, label: "1400px" },
  { width: 390, height: 844, label: "390px" },
]) {
  test.describe(`Cardback flow CSS fidelity (SPEC-cardback-pdfwait.md §E) - ${viewport.label}`, () => {
    test.describe.configure({ timeout: 60_000 });
    // `test.use({ viewport })` at describe level, NOT `page.setViewportSize()` mid-test - the
    // established pattern this repo's own phone-tier coverage relies on (DisplayPage.spec.ts's
    // "phone viewport (issue #266)" describe block's own module comment: the chromium project's
    // configured viewport is dead config, and a mid-test resize can leave viewport-tier-derived
    // component state (`useViewportTier`) stuck at whatever tier it mounted under).
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test(`E.1 gate + E.2 grid/prompt tokens resolve real computed values at ${viewport.label}`, async ({
      page,
      network,
    }) => {
      network.use(...threeCardHandlers);
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "my search query");

      await openPDFExportSettingsAndClickDownload(page);
      const gate = page.getByTestId("pre-print-cardback-gate");
      await expect(gate).toBeVisible();
      // :hover is coordinate-based - the real cursor is still resting wherever the settings
      // modal's Download button was clicked, and at the 390px viewport this gate's own footer
      // renders its "Choose a cardback" button at that same screen position, so it reads as
      // already-hovered (a lighter tint-mix, not $primary) unless the cursor is moved away first.
      // Same gotcha, same fix as ContrastAudit.spec.ts's own "resting" reads and
      // DisplayLeftRailFidelity.spec.ts's post-`.hover()` reset.
      await page.mouse.move(0, 0);

      // E.1 `.mdialog` (real react-bootstrap Modal) - the spec's own table cites the stock
      // Superhero `$modal-content-bg` ($gray-600 #4e5d6c), but PR #425's theme-defaults pass
      // (landed the same day, separately) re-routed EVERY Modal's content bg to
      // `$theme-raised-bg` sitewide - a base-theme move this spec's own binding token
      // couldn't have anticipated, not a regression introduced here. Asserting the CURRENT real
      // shared value (`_theme-tokens.scss`'s `$modal-content-bg: $theme-raised-bg`) - this file's
      // own Modal instances (the reminder gate, the cardback grid selector) are unforked,
      // sitewide Bootstrap chrome, not something this round overrides. Tokyo-11 (2026-07-24):
      // $theme-raised-bg #22303f -> #24283b, rgb(34, 48, 63) -> rgb(36, 40, 59).
      const modalContent = page.locator(".modal-content").first();
      await expect(modalContent).toHaveCSS(
        "background-color",
        "rgb(36, 40, 59)"
      );

      // E.1 `.mfoot` primary button - $primary. Tokyo-11: #df6919 -> #ff9e64,
      // rgb(223, 105, 25) -> rgb(255, 158, 100).
      await expect(gate.getByTestId("cardback-gate-choose")).toHaveCSS(
        "background-color",
        "rgb(255, 158, 100)"
      );

      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 30_000 }),
        gate.getByTestId("cardback-gate-use-current").click(),
      ]);
      expect(download.suggestedFilename()).toBe("cards.pdf");

      // --- E.2, both entries: reopen the editor and drive the toolbar apply prompt. ---
      await page.goto("/editor?server=http://127.0.0.1:8000", {
        waitUntil: "domcontentloaded",
      });
      await importTextOnEditorLanding(page, "my search query");
      await ensureDisplayRightRailOpen(page);
      // R9 (editor-repass round, item 2) - the toolbar's CardbackToolbarButton is retired in
      // favour of the shared CardbackSwatchStrip + two plain buttons; the full grid selector is
      // still reachable via "Browse all cardbacks…", and its inline apply prompt's tokens are
      // asserted below unchanged.
      await page.getByTestId("cardback-browse-all-button").click();
      const cardbackModal = page.getByTestId("cardback-grid-selector");
      await expect(cardbackModal).toBeVisible();
      await cardbackModal.getByAltText(cardDocument2.name).click();

      // R9 - the right rail's Cardback section is now the shared swatch strip
      // (CardbackSwatchStrip). Swatch token (SPEC-editor-repass mockup, strip rows 251-258):
      // 52px wide at 63/88 aspect, 1px $theme-divider border; the SELECTED swatch (the project
      // cardback, still cardDocument1 at this point) carries a 2px $theme-accent outline.
      // Tokyo-11 (2026-07-24): divider #16161e -> rgb(22, 22, 30); accent #7aa2f7 -> #bb9af7,
      // rgb(122, 162, 247) -> rgb(187, 154, 247).
      const railStrip = page.getByTestId("cardback-rail-strip");
      await expect(railStrip).toBeVisible();
      const selectedSwatch = railStrip.locator('[aria-pressed="true"]');
      await expect(selectedSwatch).toHaveCSS("width", "52px");
      await expect(selectedSwatch).toHaveCSS(
        "border",
        "1px solid rgb(22, 22, 30)"
      );
      // The outline SHORTHAND's serialization order is browser-dependent (Chromium emits
      // `outline` color-first: "rgb(187, 154, 247) solid 2px", unlike `border`'s width-first
      // form), so assert the three longhands - exact, order-independent, same tokens.
      await expect(selectedSwatch).toHaveCSS("outline-width", "2px");
      await expect(selectedSwatch).toHaveCSS("outline-style", "solid");
      await expect(selectedSwatch).toHaveCSS(
        "outline-color",
        "rgb(187, 154, 247)"
      );

      const prompt = cardbackModal.getByTestId("cardback-apply-prompt");
      await expect(prompt).toBeVisible();

      // E.2 `.cbprompt` panel - $theme-raised-bg bg, 1px $theme-divider border, left 3px
      // $primary. Tokyo-11: raised-bg rgb(34, 48, 63) -> rgb(36, 40, 59); primary
      // rgb(223, 105, 25) -> rgb(255, 158, 100).
      await expect(prompt).toHaveCSS("background-color", "rgb(36, 40, 59)");
      await expect(prompt).toHaveCSS(
        "border-left",
        "3px solid rgb(255, 158, 100)"
      );

      // E.2 `.applybtn` (primary-tinted, at rest) - transparent bg, 1px $primary border, text.
      // Tokyo-11 simplification (CardbackApplyPrompt.tsx, 2026-07-24): the #302 palette's
      // primary (#df6919) was too dark to read as text, so it needed a separately hand-picked
      // lighter tint (#ffb27d); Tokyo-11's primary (#ff9e64) is already light enough to use
      // DIRECTLY as text colour, so border and text now both resolve to the same
      // rgb(255, 158, 100) - no separate tint literal any more.
      const applyButton = prompt.getByTestId("cardback-apply-all-button");
      await expect(applyButton).toHaveCSS(
        "border",
        "1px solid rgb(255, 158, 100)"
      );
      await expect(applyButton).toHaveCSS("color", "rgb(255, 158, 100)");

      // E.2 `.defbtn` (info-tinted, at rest) - 1px $info border, text. Tokyo-11: same
      // no-separate-tint simplification as `.applybtn` above - $info (#7dcfff) is light enough
      // to use directly; #5bc0de -> #7dcfff, rgb(91, 192, 222)/rgb(143, 215, 234) (border/tint)
      // both collapse to rgb(125, 207, 255).
      const defaultButton = prompt.getByTestId("cardback-set-default-button");
      await expect(defaultButton).toHaveCSS(
        "border",
        "1px solid rgb(125, 207, 255)"
      );
      await expect(defaultButton).toHaveCSS("color", "rgb(125, 207, 255)");

      // Done-state (both buttons share the same green) - $success border/text (same
      // no-separate-tint simplification). Tokyo-11: #5cb85c -> #9ece6a, rgb(92, 184, 92)/
      // rgb(143, 224, 143) both collapse to rgb(158, 206, 106).
      await applyButton.click();
      await expect(applyButton).toHaveCSS(
        "border",
        "1px solid rgb(158, 206, 106)"
      );
      await expect(applyButton).toHaveCSS("color", "rgb(158, 206, 106)");
    });
  });
}
