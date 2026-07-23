import { expect } from "@playwright/test";

import { cardDocument15, cardDocument16 } from "@/common/test-constants";
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
 *
 * Machine-diff fix round (2026-07-23): a throwaway computed-style diff against the corrected
 * mockup (session tmp dir, not committed) caught 63 further mismatches the O1 pass didn't reach -
 * mostly Bootstrap body-default (16px) font-size fall-throughs on bespoke rail classnames that had
 * never had their own font-size rule at all. Every UNAMBIGUOUS row (a literal §D.1 value with no
 * design judgment involved) is fixed and asserted below; three rows the diff also flagged
 * (`AutofillCollapse` header background hex, the Source toggle's pill-vs-switch shape, and the
 * `.btn-sm` 12px/14px row) were deliberately held back for an explicit owner ruling on the
 * original round - all three are now RESOLVED per that ruling (owner confirmed the corrected
 * mockup is the binding reference for all three) and are fixed + asserted below too, in the same
 * round as this comment.
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

    // Machine-diff fix round (§D.1: ".rail-head .slot" 14px/700, ".rail-head .name" 15px +
    // margin-top:1px) - neither had its own font-size at all, so both fell through to the
    // Bootstrap body default (16px). Fixed as component-scoped inline styles on these exact two
    // nodes (not a new `.rail-head .slot`/`.rail-head .name` RailRoot selector) - `.slot`/`.name`
    // are bare classnames that could in principle appear elsewhere, per the #400 rule.
    const railHeaderSlot = page
      .getByTestId("display-rail-header")
      .locator("> div")
      .nth(0);
    await expect(railHeaderSlot).toHaveCSS("font-size", "14px");
    const railHeaderName = page
      .getByTestId("display-rail-header")
      .locator("> div")
      .nth(1);
    await expect(railHeaderName).toHaveCSS("font-size", "15px");
    await expect(railHeaderName).toHaveCSS("margin-top", "1px");

    // `.artist-line` (§2: "px-2 py-1 (8/4)" -> "padding:8px 10px"; §0 promoted zone surface is
    // $dark/$input-bg, #22303f = rgb(34, 48, 63)). O1 (as above) - normalized border-bottom.
    // Machine-diff fix round (§D.1: ".artist-line" 13px) - the Bootstrap `small` utility this
    // wrapper used to carry (0.875em -> 14px off a 16px parent) was close but not the spec's own
    // exact literal value; replaced with an explicit `font-size:13px` inline style.
    const artistLine = page.getByTestId("display-artist-section").locator("..");
    await expect(artistLine).toHaveCSS("padding", "8px 10px");
    await expect(artistLine).toHaveCSS("background-color", "rgb(34, 48, 63)");
    await expect(artistLine).toHaveCSS("font-size", "13px");
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
    // Machine-diff fix round (§D.1: ".select-version-heading" 14px/600) - had margin/padding/
    // font-weight already but no font-size rule, so it fell through to the Bootstrap body
    // default (16px).
    await expect(page.locator(".select-version-heading")).toHaveCSS(
      "font-size",
      "14px"
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

    // Machine-diff fix round (§D.1: "Tile ✓ canonical tag"/"Tile Alt tag" 7px/800,
    // rgba(...,.92)) - was 8px / alpha .9. cardDocument15 (resolved/canonical) and cardDocument16
    // (custom-art/non-canonical) are both present in this fixture (cardDocumentsSelectVersionMixedResults).
    const canonCornerTag = page.getByTestId(
      `select-version-tile-corner-${cardDocument15.identifier}`
    );
    await expect(canonCornerTag).toHaveCSS("font-size", "7px");
    await expect(canonCornerTag).toHaveCSS(
      "background-color",
      "rgba(92, 184, 92, 0.92)"
    );
    const altCornerTag = page.getByTestId(
      `select-version-tile-corner-${cardDocument16.identifier}`
    );
    await expect(altCornerTag).toHaveCSS("font-size", "7px");
    await expect(altCornerTag).toHaveCSS(
      "background-color",
      "rgba(91, 192, 222, 0.92)"
    );

    // Ghost "+N" expand tile (§D.1: "Ghost \"+N\" tile" ... dashed outline) - a real `<button>`
    // (buttons-look-like-buttons audit), so without an explicit reset it carried the browser's
    // own UA-stylesheet button padding instead of the spec's flush zero.
    const ghostTiles = page.locator('[data-testid^="select-version-ghost-"]');
    if ((await ghostTiles.count()) > 0) {
      await expect(ghostTiles.first()).toHaveCSS("padding", "0px");
    }

    // Filters disclosure toggle (§8's "buttons-look-like-buttons" audit - a real button, not
    // underlined text). Machine-diff fix round + owner ruling (2026-07-23): the corrected spec's
    // own ".btn-sm (all)" binding row (14px/4px 8px) supersedes this file's earlier "the buttons
    // are too big" shrink (0.75rem/12px, 0.2rem 0.5rem) for THIS control specifically - owner
    // confirmed the corrected mockup is the binding reference for this row too. `CompactButton`
    // (SelectVersionResults.tsx) has exactly one call site (this button), so the fix is already
    // component-scoped; it does NOT touch `CompactToggleButton`/`CompactLinkButton`/
    // `TreatmentChip`, which bind to their own distinct, still-in-force spec rows ("Filter
    // segment group .seg" 11px, "Treatment tri-state chip" 11px).
    const filtersToggle = page.getByTestId("funnel-filters-toggle");
    await expect(filtersToggle).toHaveCSS("font-size", "14px");
    await expect(filtersToggle).toHaveCSS("padding", "4px 8px");
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
    // Machine-diff fix round + owner ruling (2026-07-23): the corrected mockup is the binding
    // reference for this row too - #4E5D6B (rgb(78, 93, 107)) is DELIBERATE for the card-header
    // token specifically, distinct from the #4e5d6c $secondary/panel token used elsewhere in the
    // rail (D14 seticon, Card body). This REVERTS PR #400's own "correction" of this same value
    // to #4e5d6c - do not "fix" it back again, see AutofillCollapse.tsx's own comment at this
    // exact line and SPEC-display-left-rail.md §D.0.
    await expect(cardDetailsHeader).toHaveCSS(
      "background-color",
      "rgb(78, 93, 107)"
    );
    // The stray Bootstrap `border-light` utility (tinting this header's own border `$light`/
    // `#abb6c2`, a visibly pale line on the dark rail) is removed entirely - no spec anywhere
    // calls for a light-coloured header border. What remains is Bootstrap Card's own stock
    // themed border (not a deliberate rail token, so not pinned to a literal value here).
    await expect(cardDetailsHeader).not.toHaveCSS(
      "border-bottom-color",
      "rgb(171, 182, 194)"
    );

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

    // Machine-diff fix round (§D.1: "Sources filter input" 14px, padding:6px 10px) - `Form.Control`
    // is a genuinely global Bootstrap classname, so this is fixed via an inline style on this one
    // input (component-scoped) rather than a `.form-control` RailRoot selector, which would be
    // exactly the sitewide-clobber pattern the #400 rule retired `.card-header` for.
    const sourcesFilter = page.getByTestId("display-sources-filter");
    await expect(sourcesFilter).toHaveCSS("font-size", "14px");
    await expect(sourcesFilter).toHaveCSS("padding", "6px 10px");

    // Machine-diff fix round (§D.1: "Source row" bottom rgba(0,0,0,.22)) - the plain Bootstrap
    // `.border-bottom` utility here resolved to the theme's ambiguous `--bs-border-color`
    // (`#ced4da`), not the spec's own explicit value - fixed inline, component-scoped to each row.
    const sourceRow = page.getByTestId("display-sources-row-0");
    await expect(sourceRow).toHaveCSS(
      "border-bottom",
      "1px solid rgba(0, 0, 0, 0.22)"
    );

    // Machine-diff fix round + owner ruling (2026-07-23): the react-bootstrap-toggle library's
    // stock look is a sliding single-label switch; restyled (scoped to `.rail-source-toggle`,
    // this exact accordion's own Toggle mounts only) into the corrected mockup's static two-cell
    // segmented control - both On/Off labels always visible, each carrying its own §D.1 colour
    // ("Source toggle ... on #df6919/#fff; off #4e5d6c/#8fa0b0; #6b7d8e border"). Every OTHER
    // react-bootstrap-toggle mount sitewide is unaffected (unscoped selector, untouched CSS).
    const toggleOuter = sourceRow.locator(".rail-source-toggle");
    await expect(toggleOuter).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(toggleOuter).toHaveCSS(
      "border",
      "1px solid rgb(107, 125, 142)"
    );
    const toggleOn = sourceRow.locator(".toggle-on");
    await expect(toggleOn).toHaveCSS("background-color", "rgb(223, 105, 25)");
    await expect(toggleOn).toHaveCSS("color", "rgb(255, 255, 255)");
    const toggleOff = sourceRow.locator(".toggle-off");
    await expect(toggleOff).toHaveCSS("background-color", "rgb(78, 93, 108)");
    await expect(toggleOff).toHaveCSS("color", "rgb(143, 160, 176)");
  });
});
