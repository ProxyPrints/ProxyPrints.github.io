import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import { cardDocument2 } from "@/common/test-constants";
import {
  cardbacksThreeResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  questionFeedConfirmSuggestionSingleton,
  searchResultsOneResult,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  ensureDisplayRightRailOpen,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
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
 * (introduced-this-round) elements across all four subsections (E.1 gate / E.2 grid+prompt /
 * E.3 progress bar / E.4 game embed+outro), covering every DISTINCT colour token the round
 * introduces at least once.
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

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);
const imageBucketFailure = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () => new HttpResponse(null, { status: 404 })
);
const delayedImageWorkerSuccess = http.get(
  IMAGE_WORKER_URL_PATTERN,
  async () => {
    await new Promise((resolve) => setTimeout(resolve, 4_000));
    return new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    });
  }
);

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

      await ensureDisplayRightRailOpen(page);
      await page.getByTestId("finish-footer-print-export").click();
      const gate = page.getByTestId("pre-print-cardback-gate");
      await expect(gate).toBeVisible();

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

      await gate.getByTestId("cardback-gate-use-current").click();
      await page.waitForURL(/\/print/, { timeout: 30_000 });

      // --- E.2, both entries: reopen the editor and drive the toolbar apply prompt. ---
      await page.goto("/editor?server=http://127.0.0.1:8000", {
        waitUntil: "domcontentloaded",
      });
      await importTextOnEditorLanding(page, "my search query");
      await ensureDisplayRightRailOpen(page);
      await page.getByTestId("cardback-toolbar-button").click();
      const cardbackModal = page.getByTestId("cardback-grid-selector");
      await expect(cardbackModal).toBeVisible();
      await cardbackModal.getByAltText(cardDocument2.name).click();

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

    test(`E.3 progress bar + E.4 game embed tokens resolve real computed values at ${viewport.label}`, async ({
      page,
      network,
    }) => {
      network.use(
        ...threeCardHandlers.filter(
          (handler) => handler !== searchResultsThreeResults
        ),
        searchResultsOneResult,
        imageBucketFailure,
        delayedImageWorkerSuccess,
        questionFeedConfirmSuggestionSingleton
      );
      await loadPageWithDefaultBackend(page);
      await importTextOnEditorLanding(page, "my search query");
      await ensureDisplayRightRailOpen(page);
      await page.getByTestId("finish-footer-print-export").click();
      await page
        .getByTestId("pre-print-cardback-gate")
        .getByTestId("cardback-gate-use-current")
        .click();
      await page.waitForURL(/\/print/, { timeout: 30_000 });
      await page.getByRole("tab", { name: "PDF" }).click();

      await page.getByRole("button", { name: "Generate PDF" }).click();

      // E.3 `.progressbox` - $theme-raised-bg bg, 1px $theme-divider border. Tokyo-11: raised-bg
      // rgb(34, 48, 63) -> rgb(36, 40, 59); divider rgb(22, 32, 43) -> rgb(22, 22, 30).
      const progressBox = page.getByTestId("pdf-progress");
      await expect(progressBox).toBeVisible({ timeout: 15_000 });
      await expect(progressBox).toHaveCSS(
        "background-color",
        "rgb(36, 40, 59)"
      );
      await expect(progressBox).toHaveCSS(
        "border",
        "1px solid rgb(22, 22, 30)"
      );

      // E.4 `.gameembed` frame - $theme-raised-bg bg, 1px $theme-divider border (same Tokyo-11
      // remapping as `.progressbox` above).
      const embed = page.getByTestId("pdf-wait-game");
      await expect(embed).toBeVisible({ timeout: 15_000 });
      await expect(embed).toHaveCSS("background-color", "rgb(36, 40, 59)");
      await expect(embed).toHaveCSS("border", "1px solid rgb(22, 22, 30)");

      // E.4 `.geband` build ribbon - #0b1520 bg. NOT a theme token (a bespoke near-black literal,
      // out of the Tokyo-11 sweep's scope - same as PagePreview.tsx's `.compare` panel
      // background) - unchanged by this re-theme.
      await expect(page.getByTestId("pdf-wait-game-ribbon")).toHaveCSS(
        "background-color",
        "rgb(11, 21, 32)"
      );

      // E.4 `.tbtn.yes` (ThumbButton, QuestionFeed's own shipped idiom, reproduced verbatim) -
      // min-height 44px floor.
      const yesButton = embed.getByTestId("question-feed-level1-yes");
      await expect(yesButton).toBeVisible({ timeout: 15_000 });
      const yesHeight = await yesButton.evaluate(
        (el) => el.getBoundingClientRect().height
      );
      expect(yesHeight).toBeGreaterThanOrEqual(44);
    });
  });
}
