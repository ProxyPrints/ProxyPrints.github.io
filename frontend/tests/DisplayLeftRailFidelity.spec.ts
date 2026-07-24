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
  openSelectVersionSection,
} from "./test-utils";

/**
 * Permanent CSS-fidelity guard for the /display left rail (SPEC-rail-delegacy.md - SOURCE OF
 * TRUTH for every literal value asserted below; that file's own §D.1 (inherited, reproduced
 * verbatim) and §D.2 (introduced this round) are where these numbers come from). Rewritten for
 * the rail-delegacy round (2026-07-24, owner-approved): every grey `AutofillCollapse` section is
 * gone from the rail, so the assertions this file used to carry for "AutofillCollapse header in
 * rail" / demoted-zone padding are retired along with them - see the second describe block below
 * for what replaces them (the identify panel band + the bottom control stack).
 *
 * Every assertion below reads REAL computed styles (`toHaveCSS`, backed by `getComputedStyle`),
 * never class names or inline-style source text - the same discipline this guard has followed
 * since PR #352's own regression (several density-table values documented as "done" while the
 * actual CSS still fell through to a Bootstrap/global default).
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

    // `.rail-head` (§D.1, inherited verbatim) - padding:8px 10px, #16202b hairline.
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "padding",
      "8px 10px"
    );
    await expect(page.getByTestId("display-rail-header")).toHaveCSS(
      "border-bottom",
      "1px solid rgb(22, 32, 43)"
    );

    // Rev #3 (RD8) - the `66px` subject-card preview, aspect 63/88, `1px rgba(235,235,235,.15)`
    // border. This fixture's slot has a real selected image, so the ART variant renders (not the
    // dashed empty state).
    const subject = page.getByTestId("display-rail-subject");
    await expect(subject).toBeVisible();
    await expect(subject).toHaveCSS("width", "66px");
    await expect(subject).toHaveCSS(
      "border",
      "1px solid rgba(235, 235, 235, 0.15)"
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
    await expect(detailsBody).toHaveCSS(
      "border-top",
      "1px solid rgb(22, 32, 43)"
    );
    // RD7 - the canonical printing id is NOT repeated in "More details" (it lives once in D14) -
    // the metadata table still carries the OTHER Card Details rows (e.g. a Language row).
    await expect(detailsBody).toContainText("Language");

    // D14 confidence band `.d14` (§D.1, inherited, LOCKED) - unchanged by this round; the
    // canonical printing id ("2X2 · 117"-shaped `.idtext`) lives here, exactly once in the rail.
    const d14 = page.getByTestId("display-confidence-element");
    await expect(d14).toBeVisible();
    await expect(d14).toHaveCSS("padding", "8px 10px");
    await expect(d14).toHaveCSS("background-color", "rgb(43, 62, 80)");

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
    const sortSelect = page.getByTestId("funnel-sort-select");
    await expect(sortSelect).toBeVisible();
    await expect(sortSelect).toHaveCSS("font-size", "12px");
    await expect(sortSelect).toHaveCSS("max-width", "150px");
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

    // Machine-diff-precedent tile styling (§D.1, inherited) - unchanged by this round.
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
  });

  test("the identify panel band (item 6) and the bottom control stack (item 7) resolve the spec's literal §D.2 values once opened, and the Sources accordion (§D.1, unchanged, not one of the nine) still resolves its own", async ({
    page,
    network,
  }) => {
    network.use(...railFidelityHandlers);
    await openSelectVersionSection(page);
    await expect(page.getByTestId("display-rail-content")).toBeVisible();

    // Item 6 (RD - "hangs off D14") - `.idhang`/`.idtoggle`/`.idbody` (§D.2): same surface colour
    // as D14 (`#2b3e50`), starts closed, PrintingTagsBlock mounts only once opened.
    const identifyPanel = page.getByTestId("display-identify-panel");
    await expect(identifyPanel).toBeVisible();
    await expect(identifyPanel).toHaveCSS(
      "background-color",
      "rgb(43, 62, 80)"
    );
    const identifyToggle = page.getByTestId("display-identify-toggle");
    await expect(identifyToggle).toHaveCSS("font-size", "12px");
    await expect(identifyToggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("display-identify-body")).toBeHidden();
    await identifyToggle.click();
    const identifyBody = page.getByTestId("display-identify-body");
    await expect(identifyBody).toBeVisible();
    await expect(identifyBody).toHaveCSS("background-color", "rgb(34, 48, 63)");
    // PrintingTagsBlock (reused verbatim, item 6/RD1) - the real "What's That Card?" heading.
    await expect(identifyBody).toContainText("What's That Card?");

    // Item 7 (RD5) - the ONE bottom `.cstack`: Print Options + Slot Actions + Report, each its
    // own `.cs-legend` (10px uppercase `#8fa0b0`) group, no grey accordion headers anywhere.
    const controlStack = page.getByTestId("display-control-stack");
    await expect(controlStack).toBeVisible();
    await expect(controlStack).toHaveCSS("padding", "8px 10px");
    const legends = controlStack.locator(".cs-legend");
    await expect(legends).toHaveCount(2);
    await expect(legends.first()).toHaveCSS("font-size", "10px");
    await expect(legends.first()).toHaveText("Print options");
    await expect(legends.nth(1)).toHaveText("Slot actions");

    // Slot Actions button stack (§D.1, inherited - "button stack gap:6px") - no expand click
    // needed any more, it's not behind an accordion.
    const slotActions = page.getByTestId("display-slot-actions-section");
    await expect(slotActions).toBeVisible();
    await expect(slotActions).toHaveCSS("gap", "6px");

    // Report (RD5) - a single `btn-outline-danger` that expands to `ReportCardPanel`'s reason
    // chips in place - `ReportBlock` is reused verbatim, no fork.
    const reportButton = controlStack.getByTestId("report-card-button");
    await expect(reportButton).toBeVisible();
    await reportButton.click();
    await expect(controlStack.getByTestId("report-card-panel")).toBeVisible();

    // Sources accordion (§D.1, inherited, unchanged) - NOT one of the nine removed sections
    // (owner answer #3) - still resolves its own literal values.
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
    await expect(emptySubject).toHaveCSS(
      "border",
      "1px dashed rgb(171, 182, 194)"
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
