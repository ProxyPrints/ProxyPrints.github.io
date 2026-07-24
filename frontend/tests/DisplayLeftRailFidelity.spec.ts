import { expect } from "@playwright/test";

import { cardDocument15, cardDocument16 } from "@/common/test-constants";
import {
  cardDocumentsNoResults,
  cardDocumentsSelectVersionMixedResults,
  castImplicitVoteSuccess,
  defaultHandlers,
  retractImplicitVoteSuccess,
  searchResultsNoResults,
  searchResultsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayChangeQueryModal,
  openSelectVersionSection,
} from "./test-utils";

/**
 * Permanent CSS-fidelity guard for the /display left rail. SOURCE OF TRUTH for every literal
 * value asserted below is now a TWO-LAYER stack: SPEC-rail-delegacy.md (§D.1 inherited, §D.2
 * introduced) for anything NOT revised by the editor-polish round, and SPEC-editor-polish.md
 * (§D.1-§D.4/§D.8, the eleven-item + cue consolidated polish round, 2026-07-24) for every row
 * that round REVISES or introduces - each assertion below is comment-linked to whichever spec
 * actually owns its literal value, per row.
 *
 * Editor-polish round changes to this file's OWN assertions (not just new coverage):
 *   - EP5 (REV RD8): the rail-head subject preview grows `66px` -> `116px`.
 *   - EP7 (REV RD2): `.sortsel` `max-width` `150px` -> `172px`; the option list itself is now
 *     client-side (see the new `funnel-sort-select` coverage below, not a re-assertion of the
 *     old `SortByOptions` values).
 *   - EP4 (REV RD5): Slot Actions relocates from the bottom control stack (previously asserted
 *     inside `display-control-stack`) to the rail head's own compact icon row - the control-stack
 *     test below now asserts ONE `.cs-legend` ("Print options" only), and a new rail-head test
 *     asserts the relocated `display-slot-actions-section` instead.
 *   - EP3 (REV): `.src-list`'s own background - `#22303f` -> `#2b3e50` (the de-grey pass moved
 *     the LIST surface itself one step further, while the accordion shell around it and its body
 *     both went `#22303f` - see SourcesAccordion.tsx's own module comment for the full token
 *     breakdown).
 * "More details" (amendment 1, relocates from the rail head to directly under D14) needed NO
 * assertion changes here - every existing assertion queries its `display-rail-more-details-*`
 * testids page-wide, never scoped to `display-rail-header`, so the relocation is invisible to
 * this file's existing coverage; that coverage still exercises real behaviour at the new DOM
 * location.
 *
 * Every assertion below reads REAL computed styles (`toHaveCSS`, backed by `getComputedStyle`),
 * never class names or inline-style source text - the same discipline this guard has followed
 * since PR #352's own regression (several density-table values documented as "done" while the
 * actual CSS still fell through to a Bootstrap/global default).
 *
 * Tokyo-11 re-theme (2026-07-24, owner ruling - see docs/features/theming.md): every colour
 * literal below was re-derived from the OLD #302 palette to the new Tokyo-11 values in
 * `frontend/src/styles/_theme-tokens.scss` - each changed assertion carries its own "Tokyo-11"
 * inline comment noting the old->new hex pair it now asserts. Corner radii are UNCHANGED here -
 * this file's only radius assertion (the D14 `.notthis` pill, `10px`) is the separate
 * `$theme-radius-pill` token, not touched by the Semi-radius `$theme-radius-base`/`-card` swap.
 */

test.describe("Display left rail CSS fidelity guard (SPEC-rail-delegacy.md)", () => {
  test.describe.configure({ timeout: 60_000 });

  const railFidelityHandlers = [
    cardDocumentsSelectVersionMixedResults,
    sourceDocumentsOneResult,
    searchResultsSelectVersionMixedResults,
    tagConsensusTwoUnresolvedTags,
    submitTagVoteResolvesToApply,
    castImplicitVoteSuccess,
    retractImplicitVoteSuccess,
    ...defaultHandlers,
  ];

  test("rail-head (rev #1/#2/#3), D14, Select Version header, and the desktop/tablet float Filters panel resolve the spec's literal §D values, not Bootstrap defaults", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);
    await expect(page.getByTestId("display-rail-content")).toBeVisible();

    // `.rail-head` (§D.1, inherited verbatim) - padding:8px 10px, divider hairline. Tokyo-11:
    // $theme-divider #16202b -> #16161e, rgb(22, 32, 43) -> rgb(22, 22, 30).
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "padding",
      "8px 10px"
    );
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 22, 30)"
    );

    // Rev #3 (RD8), EP5 (SPEC-editor-polish.md §D.1 `.subject`, REV - `66px` -> `116px`) - the
    // subject-card preview, aspect 63/88, a text-tinted `.15`-alpha border (unchanged shape by
    // EP5). Tokyo-11: this border is `rgba(var(--bs-body-color-rgb),.15)`, so it moved with
    // $theme-text #ebebeb -> #c0caf5, rgba(235, 235, 235, .15) -> rgba(192, 202, 245, .15). This
    // fixture's slot has a real selected image, so the ART variant renders (not the dashed empty
    // state).
    const subject = page.getByTestId("display-rail-subject");
    await expect(subject).toBeVisible();
    await expect(subject).toHaveCSS("width", "116px");
    await expect(subject).toHaveCSS(
      "border",
      "1px solid rgba(192, 202, 245, 0.15)"
    );

    // `.idcol .slot`/`.name` (§D.1, inherited) - 14px/700 + face 11px uppercase; name 15px.
    const slotLine = page.getByTestId("display-rail-header").locator(".slot");
    await expect(slotLine).toHaveCSS("font-size", "14px");
    await expect(slotLine).toHaveCSS("font-weight", "700");
    const nameLine = page.getByTestId("display-rail-header").locator(".name");
    await expect(nameLine).toHaveCSS("font-size", "15px");
    await expect(nameLine).toHaveCSS("margin-top", "1px");

    // Rev #1/RD6 - "More details" toggle (§D.2 `.detmore`, 11px, #8fa0b0) starts closed; its body
    // (the whole Card-Details metadata block) is hidden until toggled.
    const moreDetailsToggle = page.getByTestId(
      "display-rail-more-details-toggle"
    );
    await expect(moreDetailsToggle).toHaveCSS("font-size", "11px");
    await expect(moreDetailsToggle).toHaveAttribute("aria-expanded", "false");
    await expect(
      page.getByTestId("display-rail-more-details-body")
    ).toBeHidden();
    await moreDetailsToggle.click();
    const detailsBody = page.getByTestId("display-rail-more-details-body");
    await expect(detailsBody).toBeVisible();
    // Tokyo-11: $theme-divider #16202b -> #16161e, rgb(22, 32, 43) -> rgb(22, 22, 30).
    await expect(detailsBody).toHaveCSS(
      "border-top",
      "1px solid rgb(22, 22, 30)"
    );
    // RD7 - the canonical printing id is NOT repeated in "More details" (it lives once in D14) -
    // the metadata table still carries the OTHER Card Details rows (e.g. a Language row).
    await expect(detailsBody).toContainText("Language");

    // D14 confidence band `.d14` (§D.1, inherited, LOCKED) - unchanged by this round; the
    // canonical printing id ("2X2 · 117"-shaped `.idtext`) lives here, exactly once in the rail.
    // Tokyo-11: $theme-band-bg #2b3e50 -> #222234, rgb(43, 62, 80) -> rgb(34, 34, 52).
    const d14 = page.getByTestId("display-confidence-element");
    await expect(d14).toBeVisible();
    await expect(d14).toHaveCSS("padding", "8px 10px");
    await expect(d14).toHaveCSS("background-color", "rgb(34, 34, 52)");

    // `.artist-line` (§D.1, inherited) - unchanged.
    const artistLine = page.getByTestId("display-artist-section").locator("..");
    await expect(artistLine).toHaveCSS("padding", "8px 10px");
    await expect(artistLine).toHaveCSS("font-size", "13px");

    // Item 2 (RD2) - the Select Version header row `.svhead`: count, Sort `Form.Select`, Filters
    // toggle - replacing the old always-visible funnel-head count+pills bar.
    const svhead = page.getByTestId("svhead");
    await expect(svhead).toBeVisible();
    await expect(svhead).toHaveCSS("font-size", "12px");
    await expect(svhead).toHaveCSS("margin-bottom", "6px");
    // EP7 (SPEC-editor-polish.md §D.4 `.sortsel`, REV RD2) - `max-width` 150px -> 172px; the
    // option list itself is now the five client-side orderings (see the dedicated EP7 test
    // further down in this file, not re-asserted here to keep this test's own scope to sizing).
    const sortSelect = page.getByTestId("funnel-sort-select");
    await expect(sortSelect).toBeVisible();
    await expect(sortSelect).toHaveCSS("font-size", "12px");
    await expect(sortSelect).toHaveCSS("max-width", "172px");
    expect(await sortSelect.evaluate((el) => el.tagName)).toBe("SELECT");

    const filtersToggle = page.getByTestId("funnel-filters-toggle");
    await expect(filtersToggle).toHaveCSS("font-size", "14px");
    await expect(filtersToggle).toHaveCSS("padding", "4px 8px");
    expect(await filtersToggle.evaluate((el) => el.tagName)).toBe("BUTTON");
    await expect(filtersToggle).toHaveAttribute("aria-expanded", "false");

    // Item 2/3/5 (RD4/O3) - at the default (desktop) viewport, opening Filters renders the FLOAT
    // panel (fixed-positioned toward the viewport centre, with a backdrop) - not the phone-only
    // in-rail Collapse.
    await expect(page.getByTestId("filters-panel-inline")).toHaveCount(0);
    await filtersToggle.click();
    await expect(filtersToggle).toHaveAttribute("aria-expanded", "true");
    const floatPanel = page.getByTestId("filters-panel-float");
    await expect(floatPanel).toBeVisible();
    await expect(floatPanel).toHaveCSS("position", "fixed");
    await expect(floatPanel).toHaveCSS("width", "440px");
    await expect(floatPanel).toHaveCSS(
      "border",
      "1px solid rgb(127, 143, 160)"
    );
    await expect(page.getByTestId("filters-panel-scrim")).toBeVisible();

    // O1/RD1 - ONE chip surface inside the panel: the "Filter versions" fieldset (`.fset`, 10px
    // uppercase legend `#8fa0b0`) carries the funnel's own Border/Frame/Treatment chips - no
    // separate `.achip` attribute-vote fieldset exists any more.
    const fieldset = floatPanel.getByTestId("funnel-unified-filter");
    await expect(fieldset).toBeVisible();
    await expect(fieldset.locator(".lg")).toHaveCSS("font-size", "10px");
    await expect(fieldset.locator(".lg")).toHaveText("Filter versions");
    await expect(
      floatPanel.getByTestId("funnel-frame-treatment-row")
    ).toHaveCSS("gap", "6px");

    // The float panel closes via the backdrop click (O3's own "escapes... no stacking hazard"
    // affordance) - clicked at a corner offset since the scrim's own default centre point falls
    // inside the (also roughly-centred) panel itself at this viewport.
    await page
      .getByTestId("filters-panel-scrim")
      .click({ position: { x: 5, y: 5 } });
    await expect(page.getByTestId("filters-panel-float")).toHaveCount(0);

    // Machine-diff-precedent tile styling (§D.1, inherited) - unchanged by this round except
    // colour. Tokyo-11: $theme-success #5cb85c -> #9ece6a, rgba(92, 184, 92, .92) ->
    // rgba(158, 206, 106, .92).
    const canonCornerTag = page.getByTestId(
      `select-version-tile-corner-${cardDocument15.identifier}`
    );
    await expect(canonCornerTag).toHaveCSS("font-size", "7px");
    await expect(canonCornerTag).toHaveCSS(
      "background-color",
      "rgba(158, 206, 106, 0.92)"
    );
    const altCornerTag = page.getByTestId(
      `select-version-tile-corner-${cardDocument16.identifier}`
    );
    await expect(altCornerTag).toHaveCSS("font-size", "7px");
  });

  test("the identify panel band (item 6) and the bottom control stack (item 7) resolve the spec's literal §D.2 values once opened, and the Sources accordion (§D.1, unchanged, not one of the nine) still resolves its own", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);
    await expect(page.getByTestId("display-rail-content")).toBeVisible();

    // Item 6 (RD - "hangs off D14") - `.idhang`/`.idtoggle`/`.idbody` (§D.2): same surface colour
    // as D14 ($theme-band-bg), starts closed, PrintingTagsBlock mounts only once opened.
    // Tokyo-11: #2b3e50 -> #222234, rgb(43, 62, 80) -> rgb(34, 34, 52).
    const identifyPanel = page.getByTestId("display-identify-panel");
    await expect(identifyPanel).toBeVisible();
    await expect(identifyPanel).toHaveCSS(
      "background-color",
      "rgb(34, 34, 52)"
    );
    const identifyToggle = page.getByTestId("display-identify-toggle");
    await expect(identifyToggle).toHaveCSS("font-size", "12px");
    await expect(identifyToggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("display-identify-body")).toBeHidden();
    await identifyToggle.click();
    const identifyBody = page.getByTestId("display-identify-body");
    await expect(identifyBody).toBeVisible();
    // Tokyo-11: $theme-raised-bg #22303f -> #24283b, rgb(34, 48, 63) -> rgb(36, 40, 59).
    await expect(identifyBody).toHaveCSS("background-color", "rgb(36, 40, 59)");
    // PrintingTagsBlock (reused verbatim, item 6/RD1) - the real "What's That Card?" heading.
    await expect(identifyBody).toContainText("What's That Card?");

    // Item 7 (RD5), EP4 (SPEC-editor-polish.md §D.7, REV RD5 - "Slot-Actions group in .cstack:
    // REMOVED") - the bottom `.cstack` keeps ONLY Print Options + Report now; ONE `.cs-legend`
    // (10px uppercase `#8fa0b0`), not two.
    const controlStack = page.getByTestId("display-control-stack");
    await expect(controlStack).toBeVisible();
    await expect(controlStack).toHaveCSS("padding", "8px 10px");
    const legends = controlStack.locator(".cs-legend");
    await expect(legends).toHaveCount(1);
    await expect(legends.first()).toHaveCSS("font-size", "10px");
    await expect(legends.first()).toHaveText("Print options");
    // EP4 - Slot Actions is no longer inside the control stack at all.
    await expect(
      controlStack.getByTestId("display-slot-actions-section")
    ).toHaveCount(0);

    // EP4 (§D.1 `.slotacts-top .iact`) - Slot Actions relocated to the rail head's own compact
    // icon row, beside the subject image; same action set, same per-action testids, just a
    // `32×30` icon button now instead of a full-width labelled one.
    const railHeadSlotActions = page
      .getByTestId("display-rail-header")
      .getByTestId("display-slot-actions-section");
    await expect(railHeadSlotActions).toBeVisible();
    const deleteAction = railHeadSlotActions.getByTestId(
      "display-slot-action-delete"
    );
    await expect(deleteAction).toHaveCSS("width", "32px");
    await expect(deleteAction).toHaveCSS("height", "30px");

    // Report (RD5) - a single `btn-outline-danger` that expands to `ReportCardPanel`'s reason
    // chips in place - `ReportBlock` is reused verbatim, no fork.
    const reportButton = controlStack.getByTestId("report-card-button");
    await expect(reportButton).toBeVisible();
    await reportButton.click();
    await expect(controlStack.getByTestId("report-card-panel")).toBeVisible();

    // Sources accordion (§D.1, inherited, unchanged) - NOT one of the nine removed sections
    // (owner answer #3) - still resolves its own literal values. Tokyo-11: $theme-divider
    // #16202b -> #16161e, rgb(22, 32, 43) -> rgb(22, 22, 30).
    await expect(page.getByTestId("display-sources-accordion")).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 22, 30)"
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
    // EP3 (SPEC-editor-polish.md §D.3, de-grey pass) - the accordion's OWN header/body go
    // $theme-raised-bg (asserted below via `display-sources-accordion`'s own background), while
    // the `.src-list` surface one step further in is $theme-band-bg - see SourcesAccordion.tsx's
    // own module comment for the exact token breakdown this two-tone reflects. Tokyo-11:
    // $theme-band-bg #2b3e50 -> #222234, rgb(43, 62, 80) -> rgb(34, 34, 52).
    const sourcesList = page.getByTestId("display-sources-list");
    await expect(sourcesList).toHaveCSS(
      "border",
      "1px solid rgba(0, 0, 0, 0.22)"
    );
    await expect(sourcesList).toHaveCSS("background-color", "rgb(34, 34, 52)");
    // Tokyo-11: $theme-raised-bg #22303f -> #24283b, rgb(34, 48, 63) -> rgb(36, 40, 59).
    await expect(
      page.getByTestId("display-sources-accordion").locator(".card-header")
    ).toHaveCSS("background-color", "rgb(36, 40, 59)");
  });

  // RD8/rev #3 - the subject-card preview's dashed empty state, and RD7's own dedup guarantee
  // (the printing id is textually present exactly ONCE in the rail: the D14 band's `.idtext`).
  test("the subject preview shows the dashed 'no art selected' empty state for a slot with no resolved image, and the printing id appears exactly once in the rail (D14 only, not repeated in More details)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsNoResults,
      sourceDocumentsOneResult,
      searchResultsNoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "an unfindable card");
    await page.getByTestId("page-preview-slot").first().click();

    await expect(page.getByTestId("display-rail-subject")).toHaveCount(0);
    const emptySubject = page.getByTestId("display-rail-subject-empty");
    await expect(emptySubject).toBeVisible();
    // Tokyo-11: $theme-light is no longer an audited study token, aliased to $theme-text this
    // round (see _theme-tokens.scss's own comment) - #abb6c2 -> #c0caf5, rgb(171, 182, 194) ->
    // rgb(192, 202, 245).
    await expect(emptySubject).toHaveCSS(
      "border",
      "1px dashed rgb(192, 202, 245)"
    );
    await expect(emptySubject).toContainText("No art");

    // No resolved card at all here, so D14/identify/More-details/mismatch all correctly render
    // nothing to identify - confirms the empty state doesn't ALSO leave some other element
    // showing a stale/fabricated id.
    await expect(page.getByTestId("display-confidence-element")).toHaveCount(0);
    await expect(page.getByTestId("display-identify-panel")).toHaveCount(0);
    await expect(page.getByTestId("requested-printing-badge")).toHaveCount(0);
  });

  test("the printing id appears exactly once in the rail (D14 only) for a slot WITH a resolved image - 'More details' carries the rest of the metadata but not the Canonical Card row", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const d14 = page.getByTestId("display-confidence-element");
    await expect(d14).toBeVisible();
    const idText = (await d14.locator(".idtext").textContent())?.trim();
    expect(idText).toBeTruthy();

    await page.getByTestId("display-rail-more-details-toggle").click();
    const detailsBody = page.getByTestId("display-rail-more-details-body");
    await expect(detailsBody).toBeVisible();
    // RD7 (rev #2) - CardMetaTable's own "Canonical Card" row is dropped in this context
    // (`showCanonicalCard={false}`) - the only "Canonical Card" text anywhere in the rail is
    // gone, and the D14 id text itself is not textually repeated inside the metadata table.
    await expect(detailsBody).not.toContainText("Canonical Card");
    if (idText != null) {
      await expect(detailsBody).not.toContainText(idText);
    }
  });

  // RD4/O3 - the desktop/tablet float panel node isn't even RENDERED at phone width (the mockup's
  // own verified claim, "display:none-el" - here, absent from the DOM entirely, not just hidden).
  test("at phone width (390px) the Filters panel expands IN PLACE inline - the desktop/tablet float node and its backdrop are never mounted", async ({
    page,
    network,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const filtersToggle = page.getByTestId("funnel-filters-toggle");
    await expect(filtersToggle).toBeVisible();
    await filtersToggle.click();

    await expect(page.getByTestId("filters-panel-inline")).toBeVisible();
    await expect(page.getByTestId("filters-panel-float")).toHaveCount(0);
    await expect(page.getByTestId("filters-panel-scrim")).toHaveCount(0);
  });
});

// New coverage - editor-polish round (SPEC-editor-polish.md), items 6/8/9/cue + amendment 1.
// Comment-linked to the exact §D row each assertion's literal value comes from, same discipline
// as the describe block above.
test.describe("Editor-polish round: rail-head Front/Back + compare reveal, D14 pill restyle, sheet cue/flip gating, amendment 1 placement (SPEC-editor-polish.md)", () => {
  test.describe.configure({ timeout: 60_000 });

  const railFidelityHandlers = [
    cardDocumentsSelectVersionMixedResults,
    sourceDocumentsOneResult,
    searchResultsSelectVersionMixedResults,
    tagConsensusTwoUnresolvedTags,
    submitTagVoteResolvesToApply,
    castImplicitVoteSuccess,
    retractImplicitVoteSuccess,
    ...defaultHandlers,
  ];

  // EPcue (§D.8 `.slot-cue`, REV) + EP6/E24 (§D.8 `.slot-flip`, N) - both gated to slots that
  // hold a card; a page always has more grid capacity than this fixture's 3 cards, so the
  // trailing slots are genuinely empty and must show NEITHER button.
  test("the sheet's ⋯ cue and ⟲ flip button are both 26×26 and both gated to card-holding slots only", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const filledCue = page.getByTestId("page-preview-slot-menu-cue").first();
    await expect(filledCue).toHaveCSS("width", "26px");
    await expect(filledCue).toHaveCSS("height", "26px");
    const filledFlip = page.getByTestId("page-preview-slot-flip").first();
    await expect(filledFlip).toHaveCSS("width", "26px");
    await expect(filledFlip).toHaveCSS("height", "26px");

    const slots = page.getByTestId("page-preview-slot");
    const slotCount = await slots.count();
    const cueCount = await page
      .getByTestId("page-preview-slot-menu-cue")
      .count();
    const flipCount = await page.getByTestId("page-preview-slot-flip").count();
    // This fixture's own "1x my search query" import lands exactly ONE filled slot (issue #167's
    // shared setup, `openSelectVersionSection`) - every other grid position on the page is
    // genuinely empty, so both counts must be exactly 1, strictly less than the total slot count.
    expect(cueCount).toBe(1);
    expect(flipCount).toBe(1);
    expect(slotCount).toBeGreaterThan(1);
  });

  // EP6 (§D.1 `.fbtoggle`, N) - the rail-head Front/Back toggle exists once a card is selected,
  // and toggling it updates the subject box's own `data-face` attribute (the preview-only swap -
  // see RailHeader's own module comment for why D14/identify/More-details stay pinned to the
  // real editing face throughout).
  test("the rail-head Front/Back toggle previews the subject box's data-face without touching D14", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const subject = page.getByTestId("display-rail-subject");
    await expect(subject).toHaveAttribute("data-face", "front");
    const idTextBefore = await page
      .getByTestId("display-confidence-element")
      .locator(".idtext")
      .textContent();

    // WCAG/APCA audit fold-in (2026-07-24, PR #432's report; owner-ruled amendment to
    // SPEC-editor-polish.md §D.1's `.fbtoggle` row) - `min-height:24px` closes the WCAG 2.2
    // SC 2.5.8 target-size gap (measured 51-55x23px stock). Per issue #434's own lesson, this
    // asserts the REAL rendered `boundingBox()` of the visible `<label class="btn">` (what a
    // user actually taps), not the authored CSS `min-height` value and not the hidden
    // `role=radio` input the click below targets - a scaled ancestor could make those diverge.
    const frontToggleLabel = page
      .locator(".fbtoggle")
      .getByText("Front", { exact: true });
    const frontBox = await frontToggleLabel.boundingBox();
    expect(frontBox?.height ?? 0).toBeGreaterThanOrEqual(24);

    // `.click()` on the role=radio locator targets the (visually-hidden, `.btn-check`) input
    // itself, which Bootstrap's own toggle-button CSS covers with its sibling `<label>` by
    // design - `force: true` bypasses Playwright's actionability wait for that expected overlap
    // (the same pattern any `ToggleButtonGroup`/`ToggleButton` test in this codebase needs).
    await page.getByRole("radio", { name: "Back" }).click({ force: true });
    // Either a real back-face thumbnail (`.subject[data-face=back]`, same testid, reused - a
    // real distinct back ProjectMember resolved) or the `.backart` placeholder (nothing
    // resolved for back) renders - never the FRONT-faced subject any more either way.
    const backSubject = page
      .getByTestId("display-rail-subject-backart")
      .or(page.getByTestId("display-rail-subject"));
    await expect(backSubject.first()).toBeVisible();
    await expect(backSubject.first()).toHaveAttribute("data-face", "back");

    // D14 - identity of the ACTUAL selected/resolved printing - never moves with the preview
    // toggle.
    await expect(
      page.getByTestId("display-confidence-element").locator(".idtext")
    ).toHaveText(idTextBefore ?? "");
  });

  // EP9 (§D.1 `.compare`, §D.2 `.statepill.cmp`, N) - the compare trigger lives on the D14
  // pill now (not the set icon), and reveals a panel beside the subject image on hover/focus
  // (the fine-pointer/mouse path - `ConfidenceElement.tsx`'s `useCoarsePointer` gate keeps the
  // touch-only click-toggle handler UNWIRED here, so hover/mouseleave is the only mechanism a
  // real mouse user gets - see that hook's own comment for why the two can't safely coexist on
  // one element).
  test("hovering the D14 pill reveals the Scryfall compare panel beside the subject image (fine pointer), and the set icon is no longer itself an interactive trigger", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const setIcon = page.getByTestId("display-confidence-set-symbol");
    await expect(setIcon).not.toHaveAttribute("role", "button");

    await expect(page.getByTestId("display-rail-compare")).toHaveCount(0);
    const pill = page.getByTestId("display-confidence-compare-trigger");
    await expect(pill).toHaveAttribute("role", "button");
    await pill.hover();
    const compare = page.getByTestId("display-rail-compare");
    await expect(compare).toBeVisible();
    await expect(compare).toHaveCSS("position", "absolute");
    await expect(compare).toHaveCSS("left", "126px");

    // Moving away hides it again (mouseleave).
    await page.mouse.move(0, 0);
    await expect(compare).toHaveCount(0);
  });

  // EP9/§G - the coarse-pointer (touch) path: a real hover-capable-false context, where the
  // pill's tap IS the toggle (no hover wired at all - see ConfidenceElement.tsx's own
  // `useCoarsePointer` comment for why the mechanisms are mutually exclusive per pointer type).
  test.describe("coarse pointer (touch) - tap-toggle", () => {
    test.use({ hasTouch: true, isMobile: true });

    test("tapping the D14 pill toggles the compare panel open, then closed again", async ({
      page,
      network,
    }) => {
      network.use(...railFidelityHandlers);
      await openSelectVersionSection(page);

      const pill = page.getByTestId("display-confidence-compare-trigger");
      await expect(page.getByTestId("display-rail-compare")).toHaveCount(0);
      await pill.tap();
      await expect(page.getByTestId("display-rail-compare")).toBeVisible();
      await pill.tap();
      await expect(page.getByTestId("display-rail-compare")).toHaveCount(0);
    });
  });

  // EP8 (§D.2 `.notthis`, REV of the post-#413 look) - restyled to the pre-#413 tinted pill
  // idiom: rounded 10px, tinted danger background, never the flat outline-danger bar.
  test("the wrong-printing ✗ affordance is a tinted, rounded pill (EP8), not a flat outline-danger bar", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const notThis = page.getByTestId("display-confidence-not-this-printing");
    // Pill radius is $theme-radius-pill (10px, unchanged by the Semi-radius pass - see this
    // file's own header note).
    await expect(notThis).toHaveCSS("border-radius", "10px");
    // Tokyo-11: $theme-danger #d9534f -> #f7768e, rgba(217, 83, 79, .12) -> rgba(247, 118, 142, .12).
    await expect(notThis).toHaveCSS(
      "background-color",
      "rgba(247, 118, 142, 0.12)"
    );
  });

  // Amendment 1 (owner, 2026-07-24, BINDING) - "More details" renders directly under the D14
  // band now, ahead of the identify panel - not inside the rail head at all any more.
  test("amendment 1 - 'More details' sits directly under the D14 band, ahead of the identify panel, and is no longer a descendant of the rail head", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    await expect(
      page
        .getByTestId("display-rail-header")
        .getByTestId("display-rail-more-details-toggle")
    ).toHaveCount(0);

    const order = await page.evaluate(() => {
      const ids = [
        "display-confidence-element",
        "display-rail-more-details-toggle",
        "display-identify-panel",
      ];
      const positions = ids.map((id) => {
        const el = document.querySelector(`[data-testid="${id}"]`);
        if (el == null) {
          return -1;
        }
        // DOCUMENT_POSITION_FOLLOWING (4) means `el` comes AFTER document.body's first child scan
        // point - simplest robust ordering check is comparing each element's own index among all
        // matched nodes via compareDocumentPosition against the FIRST id found.
        return Array.from(document.querySelectorAll("[data-testid]")).indexOf(
          el
        );
      });
      return positions;
    });
    const [d14Pos, moreDetailsPos, identifyPos] = order;
    expect(d14Pos).toBeGreaterThan(-1);
    expect(moreDetailsPos).toBeGreaterThan(d14Pos);
    expect(identifyPos).toBeGreaterThan(moreDetailsPos);
  });
});

// Tokyo-11 AAA contrast policy (owner-ruled 2026-07-24 - see docs/features/theming.md's "AAA
// contrast policy" section): a permanent guard against a future token edit silently regressing
// the two pairings the theme-options study specifically verified - body text on the panel
// surface (strict-AAA-normal, 7:1) and the button ink on the primary action colour (also
// strict-AAA here, 8.40:1 - though the *policy* floor for button/pill text is only AAA-large,
// 4.5:1, see $theme-danger's own token-file note for the one variant that only clears that lower
// bar). Reads the ACTUAL rendered `--bs-*`/`--theme-*` custom properties (not hardcoded hex), so
// this keeps passing under any future re-theme that preserves the AAA ruling, and would fail
// loudly if one didn't.
test.describe("Tokyo-11 AAA contrast policy - permanent guard", () => {
  // Same fixture set the main describe block above uses (openSelectVersionSection/
  // openDisplayChangeQueryModal need a resolvable slot) - redeclared locally since this is a
  // separate `describe`, not nested inside the other one's own scope.
  const railFidelityHandlers = [
    cardDocumentsSelectVersionMixedResults,
    sourceDocumentsOneResult,
    searchResultsSelectVersionMixedResults,
    tagConsensusTwoUnresolvedTags,
    submitTagVoteResolvesToApply,
    castImplicitVoteSuccess,
    retractImplicitVoteSuccess,
    ...defaultHandlers,
  ];

  test("body text on the panel surface, and button ink on the primary action colour, both clear strict-AAA-normal (7:1)", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    const ratios = await page.evaluate(() => {
      function srgbToLin(c: number) {
        const cs = c / 255;
        return cs <= 0.04045 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
      }
      // CSS custom properties are unparsed token streams, not resolved colour values - unlike a
      // real element's own resolved `color`/`background-color` (always normalized to `rgb()` by
      // `getComputedStyle`), reading `--bs-*`/`--theme-*` directly off `:root` returns whatever
      // literal text the token file emitted (hex here) - this parses either form.
      function luminance(colour: string) {
        let r: number, g: number, b: number;
        if (colour.startsWith("#")) {
          const hex = colour.slice(1);
          r = parseInt(hex.slice(0, 2), 16);
          g = parseInt(hex.slice(2, 4), 16);
          b = parseInt(hex.slice(4, 6), 16);
        } else {
          const match = colour.match(/\d+(\.\d+)?/g);
          if (match == null || match.length < 3) {
            throw new Error(`unparseable colour: ${colour}`);
          }
          [r, g, b] = match.map(Number);
        }
        return (
          0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b)
        );
      }
      function contrast(a: string, b: string) {
        const l1 = luminance(a);
        const l2 = luminance(b);
        const lighter = Math.max(l1, l2);
        const darker = Math.min(l1, l2);
        return (lighter + 0.05) / (darker + 0.05);
      }
      const root = getComputedStyle(document.documentElement);
      const panel = root.getPropertyValue("--bs-secondary").trim();
      const text = root.getPropertyValue("--bs-body-color").trim();
      const primary = root.getPropertyValue("--bs-primary").trim();
      const btnInk = root.getPropertyValue("--theme-btn-ink").trim();
      const focusRing = root.getPropertyValue("--bs-focus-ring-color").trim();
      return {
        textOnPanel: contrast(text, panel),
        inkOnPrimary: contrast(btnInk, primary),
        // Non-text UI-component contrast (WCAG 2.2 SC 1.4.11/2.4.11) against panel - the
        // TOUGHEST of this theme's three surfaces (body/raised/panel), so this is the binding
        // worst case.
        focusRingOnPanel: contrast(focusRing, panel),
      };
    });

    // Study-verified: 7.54:1 (text-on-panel) and 8.40:1 (ink-on-primary) - asserting >= 7 (the
    // strict-AAA-normal floor) rather than the exact ratio keeps this guard from being brittle
    // against a future WITHIN-POLICY token nudge, while still catching any regression below the
    // bar itself.
    expect(ratios.textOnPanel).toBeGreaterThanOrEqual(7);
    expect(ratios.inkOnPrimary).toBeGreaterThanOrEqual(7);
    // WCAG/APCA audit fold-in (2026-07-24, PR #432's report) - the focus ring's own non-text
    // contrast floor is 3:1 (not the 7:1 text bar above); Tokyo-11's opaque accent ring measures
    // 5.26:1 against panel (verified 2026-07-24), comfortably clear.
    expect(ratios.focusRingOnPanel).toBeGreaterThanOrEqual(3);
  });

  // WCAG/APCA audit fold-in (2026-07-24, PR #432's report) - `.btn-close` (modal/offcanvas/toast
  // dismiss x) target size, WCAG 2.2 SC 2.5.8 (>=24x24 CSS px). Reads the REAL rendered
  // `boundingBox()` (issue #434's own lesson: authored CSS isn't proof of the rendered size),
  // on `ChangeQueryModal` - one of the ~15 sitewide mounts, chosen only because this spec file
  // already has a reachable, real Modal fixture; the fix itself is theme-layer
  // ($btn-close-width in styles.scss), so it applies identically to every other mount too.
  test("the modal dismiss (×) button clears the WCAG 2.2 24x24 target-size floor", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);

    const modal = await openDisplayChangeQueryModal(page, 1);
    await expect(modal).toBeVisible();
    const closeButton = modal.locator(".btn-close");
    const box = await closeButton.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(24);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);
  });
});
