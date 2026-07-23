import { expect } from "@playwright/test";

import {
  cardDocumentsSelectVersionMixedResults,
  castImplicitVoteSuccess,
  defaultHandlers,
  retractImplicitVoteSuccess,
  searchResultsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { openSelectVersionSection } from "./test-utils";

/**
 * Permanent CSS-fidelity guard for the /display left rail
 * (docs/proposals/mockups/proposal-h/SPEC-display-left-rail.md - SOURCE OF TRUTH for every
 * literal value asserted below; that file's own §D.0 (theme tokens) and §D.1 (binding element
 * table) are where these numbers come from, and its §J "Source map addendum" section documents
 * where each one currently resolves from in the codebase (component-scoped inline style vs. a
 * styled-component descendant selector vs. a genuinely global Bootstrap/theme default) - update
 * BOTH files in the same change if a spec value ever changes, they're deliberately kept in
 * lockstep, not just accurate at write time.
 *
 * WHY THIS EXISTS: PR #352 shipped several of the spec's density-table rows as "done" in the
 * spec's own prose while the actual CSS still fell through to Bootstrap's global defaults (the
 * `AutofillCollapse` header's stock `0.5rem 1rem` instead of the rail's `7px 10px`; `gap-1`/
 * `gap-2` instead of the mockup's literal `6px`; the Sources accordion's bulk-action row and list
 * surface using unthemed Bootstrap defaults instead of the approved dark tokens) - then had to
 * separately fix its own regression in a follow-up commit. That fix-round commit's own message is
 * the exact failure mode this spec exists to make permanently visible: "several density-table
 * values never actually landed as CSS despite being documented as done." Every assertion below
 * reads REAL computed styles (`toHaveCSS`, backed by `getComputedStyle`), never class names or
 * inline-style source text - the same discipline `DisplaySlotStates.spec.ts` already follows for
 * the sheet's own dark-state colors - so a future edit that silently reverts one of these values
 * to a Bootstrap/global default fails this spec instead of shipping unnoticed.
 *
 * O1 fix round (corrected SPEC-display-left-rail.md §A/§D.1, 2026-07-23, owner-approved): the
 * spec's own §A flagged a SECOND recurrence of the same failure mode - `.rail-head`/`.artist-line`/
 * `.sources` and the (previously nonexistent) Select Version wrapper boundary all used or lacked
 * an explicit divider colour, several of them the ambiguous Bootstrap `.border-bottom` utility
 * (`--bs-border-color` resolves inconsistently in the compiled CSS). Normalized to the one
 * explicit `#16202b` = `rgb(22, 32, 43)` value `.d14` already used - every assertion below that
 * reads a `border-bottom`/`border` colour is this round's addition, same discipline as the rest of
 * this guard.
 */

test.describe("Display left rail CSS fidelity guard (SPEC-display-left-rail.md)", () => {
  test.describe.configure({ timeout: 60_000 });

  const railFidelityHandlers = [
    cardDocumentsSelectVersionMixedResults,
    sourceDocumentsOneResult,
    searchResultsSelectVersionMixedResults,
    // The Attributes rail section fetches tag consensus the moment a slot is selected regardless
    // of whether it's ever opened - see DisplayPage.spec.ts's own identical comment.
    tagConsensusTwoUnresolvedTags,
    submitTagVoteResolvesToApply,
    castImplicitVoteSuccess,
    retractImplicitVoteSuccess,
    ...defaultHandlers,
  ];

  test("promoted zone, Select Version, and the unified filter/grid resolve the spec's literal §0/§2 values, not Bootstrap defaults", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);
    await expect(page.getByTestId("display-rail-content")).toBeVisible();

    // RailHeader `.rail-head` (§2: "p-2 (8px)" -> "padding:8px 10px, no bottom margin"). O1 fix
    // round (corrected SPEC-display-left-rail.md §D.1, 2026-07-23, owner-approved): the divider
    // used to be the unthemed Bootstrap `.border-bottom` utility - normalized to the explicit
    // `#16202b` = rgb(22, 32, 43) hairline every rail block boundary now shares.
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "padding",
      "8px 10px"
    );
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 32, 43)"
    );

    // `.artist-line` (§2: "px-2 py-1 (8/4)" -> "padding:8px 10px"; §0 promoted zone surface is
    // $dark/$input-bg, #22303f = rgb(34, 48, 63)). O1 (as above) - normalized border-bottom.
    const artistLine = page.getByTestId("display-artist-section").locator("..");
    await expect(artistLine).toHaveCSS("padding", "8px 10px");
    await expect(artistLine).toHaveCSS("background-color", "rgb(34, 48, 63)");
    await expect(artistLine).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 32, 43)"
    );

    // D14 confidence band `.d14` (§2: "margin:6px 0;padding:6px 8px;border-radius:6px chip" ->
    // "margin:0;padding:8px 10px, full-width band, border-bottom" - kills the floating-chip
    // inset margin; §3: confidence-chip surface #2b3e50 = rgb(43, 62, 80)).
    const d14 = page.getByTestId("display-confidence-element");
    await expect(d14).toBeVisible();
    await expect(d14).toHaveCSS("margin", "0px");
    await expect(d14).toHaveCSS("padding", "8px 10px");
    await expect(d14).toHaveCSS("background-color", "rgb(43, 62, 80)");
    await expect(d14).toHaveCSS("border-bottom", "1px solid rgb(22, 32, 43)");

    // Select Version wrapper (§2: "px-2 pt-2 (8/8-top)" -> "padding:8px 10px"). O1 fix round
    // (corrected SPEC-display-left-rail.md §D.1, 2026-07-23) - this wrapper gained a
    // block-boundary hairline it never had before (mockup: `.sv{border-bottom:1px solid
    // var(--divider)}`), normalized straight to `#16202b`.
    const selectVersionWrapper = page
      .locator(".select-version-heading")
      .locator("..");
    await expect(selectVersionWrapper).toHaveCSS("padding", "8px 10px");
    await expect(selectVersionWrapper).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 32, 43)"
    );

    // Unified Frame+Treatment filter fieldset (§6/§2: "padding:6px 8px; margin-bottom:6px"; §0
    // raised surface #22303f = rgb(34, 48, 63)). O1 fix round (corrected SPEC-display-left-rail.md
    // §D.1, 2026-07-23, owner-approved): border normalized from the unthemed `rgba(0,0,0,.22)` to
    // the `#16202b` rail-boundary hairline every other block boundary now shares.
    const fieldset = page.getByTestId("funnel-unified-filter");
    await expect(fieldset).toBeVisible();
    await expect(fieldset).toHaveCSS("padding", "6px 8px");
    await expect(fieldset).toHaveCSS("margin-bottom", "6px");
    await expect(fieldset).toHaveCSS("background-color", "rgb(34, 48, 63)");
    await expect(fieldset).toHaveCSS("border", "1px solid rgb(22, 32, 43)");

    // The fieldset's own last `.ufilter .row` (Frame + Treatment sharing one row) and the
    // continuous `.vgrid` result grid (§7/§2) both use the mockup's literal "gap:6px" - no exact
    // Bootstrap spacing-scale match (`gap-1`=4px, `gap-2`=8px).
    await expect(page.getByTestId("funnel-frame-treatment-row")).toHaveCSS(
      "gap",
      "6px"
    );
    await expect(page.getByTestId("select-version-continuous-grid")).toHaveCSS(
      "gap",
      "6px"
    );

    // Filters disclosure toggle (§8's "buttons-look-like-buttons" audit - a real button, not
    // underlined text) - tightened to font-size:0.75rem/12px (owner fix round, "the buttons are
    // too big"). OPEN ITEM (corrected SPEC-display-left-rail.md §A/§D.1's ".btn-sm (all)" row,
    // 2026-07-23): the corrected spec's own binding table calls for a return to Bootstrap's real
    // `sm` metrics (14px/4px 8px) across every rail `.btn-sm`, but flags that exact row itself
    // as "needs owner sign-off" (the denser-vs-standard tradeoff) rather than folding it into O1's
    // separately-confirmed divider normalization - and it directly conflicts with this file's own
    // adjacent, more specific "the buttons are too big" owner directive already shipped as this
    // very assertion. Left AS SHIPPED (12px) pending an explicit owner call on that one row - see
    // this task's own report for the flag; every OTHER binding value in this spec's D.1 table is
    // implemented.
    const filtersToggle = page.getByTestId("funnel-filters-toggle");
    await expect(filtersToggle).toHaveCSS("font-size", "12px");
    expect(await filtersToggle.evaluate((el) => el.tagName)).toBe("BUTTON");
  });

  test("AutofillCollapse headers, Slot Actions, and the Sources accordion resolve the spec's literal §2/§4 values once expanded", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);
    await expect(page.getByTestId("display-rail-content")).toBeVisible();

    // AutofillCollapse header in the rail (§2: Superhero's stock `.card-header` "0.5rem 1rem"
    // (8/16) -> rail-scoped "padding:7px 10px") - the header is always rendered regardless of
    // collapse state, so no click is needed first. This is the exact regression PR #352's own
    // fix-round commit describes: documented in the spec from the start, never actually landed
    // as CSS the first time.
    const cardDetailsHeader = page
      .locator(".card-header")
      .filter({ hasText: "Card Details" });
    await expect(cardDetailsHeader).toHaveCSS("padding", "7px 10px");

    // Slot Actions button stack (§2/§8: "button stack gap:6px", not `gap-2`'s 8px) - its content
    // is gated behind the Collapse animation, so expand the section first.
    await page
      .locator(".card-header")
      .filter({ hasText: "Slot Actions" })
      .click();
    const slotActions = page.getByTestId("display-slot-actions-section");
    await expect(slotActions).toBeVisible();
    await expect(slotActions).toHaveCSS("gap", "6px");

    // Sources accordion (§4) - the bulk-action row and list surface: the mockup's own literal
    // `.src-bulk{gap:6px;margin-bottom:6px}` and `.src-list{border:1px solid var(--border);
    // background:var(--raised)}` (rgba(0,0,0,.22) / #22303f) - neither has an exact Bootstrap
    // spacing/border-color match, and the raised surface is otherwise Bootstrap's stock `.border`
    // gray, not the theme's own raised token. O1 fix round (corrected SPEC-display-left-rail.md
    // §D.1/§A, 2026-07-23, owner-approved) - the accordion's own outer `.sources` wrapper used to
    // carry the unthemed Bootstrap `.border-bottom` utility; normalized to the `#16202b`
    // rail-boundary hairline (the sources list's own inner border stays `rgba(0,0,0,.22)`
    // unchanged, per the spec's own D.1 table - only the outer block boundary was ambiguous).
    await expect(page.getByTestId("display-sources-accordion")).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 32, 43)"
    );
    await page
      .getByTestId("display-sources-accordion")
      .locator(".card-header")
      .click();
    const bulkRow = page
      .getByTestId("display-sources-enable-all")
      .locator("..");
    await expect(bulkRow).toHaveCSS("gap", "6px");
    await expect(bulkRow).toHaveCSS("margin-bottom", "6px");
    const sourcesList = page.getByTestId("display-sources-list");
    await expect(sourcesList).toHaveCSS(
      "border",
      "1px solid rgba(0, 0, 0, 0.22)"
    );
    await expect(sourcesList).toHaveCSS("background-color", "rgb(34, 48, 63)");
  });
});
