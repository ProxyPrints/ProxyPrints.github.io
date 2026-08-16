import { expect } from "@playwright/test";

import {
  cardDocumentsOneResult,
  catalogStatsCurrentRatio,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  whoamiAnonymous,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";
import {
  auditContrast,
  ContrastFailure,
  contrastRatioHex,
  formatFailureTable,
  rgbStringToHex,
  splitKnownOpenItems,
} from "./tooling/contrastAudit";

// Site-wide contrast/residual-grey audit (2026-07-25, owner-reported live-mobile defects after
// the Tokyo-11 re-theme, #438). See tests/tooling/contrastAudit.ts for the extraction/ratio
// methodology and its documented approximations, and docs/features/theming.md's "2026-07-25
// contrast/residual-grey audit" section for how to run this outside CI plus the full writeup of
// every OPEN ITEM referenced below. Binding bar (owner ruling): AAA - 7:1 normal text, 4.5:1
// large/bold text; disabled controls only need to clear 3:1 and never go below it.
//
// Each `test` below asserts ZERO **new** contrast failures (`splitKnownOpenItems` - see that
// function's own comment in tooling/contrastAudit.ts for the exact matched signatures) for its
// route/state - a real regression gate, not just a one-off report generator, so a future
// component that reintroduces an unrouted Bootstrap default fails CI here rather than needing
// another live-screenshot report. The small set of already-known, owner-attention-needed OPEN
// ITEMS this same audit surfaced (documented in theming.md, not fixed by this pass) are logged,
// not asserted on - they're real numbers, just not new ones, and re-litigating an already-ratified
// token's own compromise or a deliberate pre-existing convention needs an owner decision this PR
// doesn't make. Off-palette-grey backgrounds are reported (console.log) but never asserted on:
// catching every legitimate use of a grey-ish literal (e.g. a card image's own pixels) is out of
// scope for a DOM-background sweep, so that half stays fully advisory.

const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

function assertNoNewFailures(
  contrastFailures: ContrastFailure[],
  label: string
) {
  const { newFailures, knownOpenItems } = splitKnownOpenItems(contrastFailures);
  if (knownOpenItems.length > 0) {
    console.log(
      `${label} known open items:\n` + formatFailureTable(knownOpenItems)
    );
  }
  expect(newFailures, formatFailureTable(newFailures)).toEqual([]);
}

// Route moved 2026-07-29 (Proposal F /stats transform, PR #558): /contributions is now a plain
// client-side redirect shell to /stats (pages/contributions.tsx) - the Contribution Guidelines
// accordion this describe block audits still exists verbatim
// (features/stats/ContributionGuidelines.tsx), it just renders on /stats now. Same surface, same
// assertions, new URL - see .github/coverage-acks.txt for the old-title acks this rename needed.
test.describe("Contrast audit - /stats (owner defect 1+2: accordion header + body)", () => {
  test("Contribution Guidelines accordion - collapsed and expanded", async ({
    page,
    network,
  }) => {
    // generatedAt must be non-null here - a cache-miss fixture would render /stats's "not
    // computed yet" state instead of the panels/accordion this test audits.
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "stats");

    const header = page.getByRole("button", {
      name: "Contribution Guidelines",
    });
    await expect(header).toBeVisible();

    const collapsed = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-stats-collapsed-390.png",
    });

    await header.click();
    await expect(page.getByText("File Format")).toBeVisible();
    const expanded = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-stats-expanded-390.png",
      fullPage: true,
    });

    // The accordion header text itself is the owner's defect 1 - hard-asserted directly
    // (never allowlisted, unlike the general sweep below) so a regression here fails with an
    // obvious message rather than getting lost in a big table or silently passing through the
    // known-open-items filter.
    const headerContrast = [
      ...collapsed.contrastFailures,
      ...expanded.contrastFailures,
    ].filter((f) => f.text.includes("Contribution Guidelines"));
    expect(headerContrast, formatFailureTable(headerContrast)).toEqual([]);

    console.log(
      "collapsed off-palette-grey:\n" +
        formatFailureTable(collapsed.paletteFailures)
    );
    console.log(
      "expanded off-palette-grey:\n" +
        formatFailureTable(expanded.paletteFailures)
    );

    assertNoNewFailures(collapsed.contrastFailures, "stats collapsed");
    assertNoNewFailures(expanded.contrastFailures, "stats expanded");
  });
});

test.describe("Contrast audit - card-list/editor page (owner defect 3+4: Dismiss/Syntax Guide)", () => {
  test("empty-project landing with the restore-draft banner (Dismiss button)", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...oneCardHandlers);
    // The draft-backup note (`finish-footer-draft-note`) lives inside FinishFooter, which only
    // mounts inline at >=xl (1200px) - below that it's inside RightRailOffcanvas, a CLOSED
    // drawer by default, so waiting for it at 390px hangs. Do the import/debounce-wait/delete
    // sequence at the default desktop viewport (matching DisplayFinishFooter.spec.ts's own
    // working precedent for this exact flow), THEN resize to the owner's 390px phone width for
    // the actual audit/screenshot - the restore banner itself lives on the main empty-landing
    // page, not inside the rail, so it's unaffected by the resize.
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await expect(page.getByTestId("display-page")).toBeVisible();

    await page
      .getByTestId("display-finish-footer")
      .getByTestId("finish-footer-draft-note")
      .waitFor({ timeout: 5_000 });
    await page.getByTestId("page-preview-slot").first().click();
    await page.getByTestId("display-slot-action-delete").click();

    const banner = page.getByTestId("display-restore-draft-banner");
    await expect(banner).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    const result = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-restore-banner-390.png",
    });
    console.log(
      "restore-banner off-palette-grey:\n" +
        formatFailureTable(result.paletteFailures)
    );
    assertNoNewFailures(result.contrastFailures, "restore-banner");
  });

  test("import-text landing's Syntax Guide accordion, collapsed and expanded", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);

    const header = page.getByRole("button", { name: "Syntax Guide" });
    await expect(header).toBeVisible();
    const collapsed = await auditContrast(page);

    await header.click();
    await expect(page.getByText(/three types of images/)).toBeVisible();
    const expanded = await auditContrast(page);

    console.log(
      "syntax-guide collapsed off-palette-grey:\n" +
        formatFailureTable(collapsed.paletteFailures)
    );
    console.log(
      "syntax-guide expanded off-palette-grey:\n" +
        formatFailureTable(expanded.paletteFailures)
    );
    assertNoNewFailures(collapsed.contrastFailures, "syntax-guide collapsed");
    assertNoNewFailures(expanded.contrastFailures, "syntax-guide expanded");
  });
});

test.describe("Contrast audit - editor mobile Print & Settings sheet (owner defect 3)", () => {
  test("View segments / Cardback / Export controls in the offcanvas", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...oneCardHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await expect(page.getByTestId("display-page")).toBeVisible();

    await page.getByTestId("display-gear-button").click();
    const rail = page.getByTestId("display-print-settings-rail");
    await expect(rail).toBeVisible();
    await expect(rail.getByTestId("display-view-toggle-fronts")).toBeVisible();

    const result = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-print-settings-sheet-390.png",
    });
    console.log(
      "print-settings-sheet off-palette-grey:\n" +
        formatFailureTable(result.paletteFailures)
    );
    assertNoNewFailures(result.contrastFailures, "print-settings-sheet");
  });
});

// Broader sweep: static/informational routes that don't need a populated project. Not
// exhaustive (routes needing deep interactive state - moderation queue, question feed, saved
// decks crypto flows - are covered by the dedicated states above and their own fidelity specs,
// not repeated here) but catches any OTHER page carrying the same unrouted-Bootstrap-default
// class of defect this task's four reported spots turned out to share a root cause with.
for (const route of ["", "about", "explore", "myDecks", "whatsthat", "new"]) {
  test(`Contrast audit - static sweep: /${route || "(home)"}`, async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, route);
    await page.waitForTimeout(500);

    const result = await auditContrast(page);
    console.log(
      `/${route || "(home)"} off-palette-grey:\n` +
        formatFailureTable(result.paletteFailures)
    );
    assertNoNewFailures(result.contrastFailures, `/${route || "(home)"}`);
  });
}

// Link colour audit (2026-07-25 follow-up, owner-approved open item 2) - $link-color switched
// from $primary (measured 5.98:1 on panel, below AAA) to $theme-info (measured 7.09-9.96:1 on
// every surface a link can land on - see styles.scss's own comment for the full measurement,
// including why $theme-accent was tried and rejected: it's WORSE than $primary on every one of
// these five surfaces, not better). Covers resting, hover, AND the two pseudo-classes Bootstrap's
// own reboot.scss never gives a separate rule to (:visited/:active fall through to the resting
// $link-color unless :hover is also active - verified via source inspection, see styles.scss) -
// asserted here anyway rather than only trusted from source reading, since real getComputedStyle
// after a real DOM mutation is the actual regression gate, not the source-reading argument for it.
test.describe("Link colour audit (owner-approved open item 2 - $link-color -> $theme-info)", () => {
  // Synthetic isolated surfaces (deterministic backgrounds, not dependent on finding a real link
  // on all five - band-bg in particular has no real prose link anywhere in the app today) - real
  // getComputedStyle() of a real rendered <a>, not a recomputation of the SCSS literal.
  const SURFACES: Array<[label: string, hex: string]> = [
    ["body-bg", "#1a1b26"],
    ["raised-bg", "#24283b"],
    ["panel-bg", "#2f3549"],
    ["card-header-bg", "#2f3548"],
    ["band-bg", "#222234"],
  ];

  test("resting and hover colour clear strict-AAA-normal (7:1) on every surface a link can land on", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymous, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "about");

    const failures: string[] = [];
    for (const [label, bgHex] of SURFACES) {
      const linkId = `link-audit-${label}`;
      await page.evaluate(
        ({ bgHex, linkId }) => {
          // Remove any prior probe (they'd otherwise stack at the same fixed position - not
          // just visual clutter, the REAL mouse cursor left hovering the last one's pixel
          // position would make the new element start life already :hover'd, since :hover is
          // coordinate-based, not element-based).
          document
            .querySelectorAll('[data-link-audit-probe="1"]')
            .forEach((n) => n.remove());
          const div = document.createElement("div");
          div.setAttribute("data-link-audit-probe", "1");
          // Fixed + top z-index so this synthetic probe is never occluded by the real page's
          // own fixed/sticky chrome (the navbar intercepted pointer events here without this).
          div.style.position = "fixed";
          div.style.top = "0";
          div.style.left = "0";
          div.style.zIndex = "999999";
          div.style.backgroundColor = bgHex;
          div.style.padding = "8px";
          const a = document.createElement("a");
          a.href = "#";
          a.id = linkId;
          a.textContent = "Sample link text";
          div.appendChild(a);
          document.body.appendChild(div);
        },
        { bgHex, linkId }
      );
      // Move the real cursor well away before reading "resting" - :hover is coordinate-based, so
      // without this the cursor left over from the PREVIOUS iteration's `.hover()` call (same
      // fixed top:0/left:0 screen position every iteration) would make the freshly-created link
      // read as already-hovered.
      await page.mouse.move(600, 600);

      const link = page.locator(`#${linkId}`);
      const restingColor = await link.evaluate(
        (el) => getComputedStyle(el).color
      );
      const restingHex = rgbStringToHex(restingColor);
      const restingRatio = contrastRatioHex(restingHex, bgHex);
      if (restingRatio < 7) {
        failures.push(
          `${label} resting: ${restingHex} on ${bgHex} = ${restingRatio}:1 (< 7:1)`
        );
      }

      await link.hover();
      const hoverColor = await link.evaluate(
        (el) => getComputedStyle(el).color
      );
      const hoverHex = rgbStringToHex(hoverColor);
      const hoverRatio = contrastRatioHex(hoverHex, bgHex);
      if (hoverRatio < 7) {
        failures.push(
          `${label} hover: ${hoverHex} on ${bgHex} = ${hoverRatio}:1 (< 7:1)`
        );
      }

      console.log(
        `link colour - ${label}: resting ${restingHex} = ${restingRatio}:1, hover ${hoverHex} = ${hoverRatio}:1`
      );
    }

    expect(failures, failures.join("\n")).toEqual([]);
  });

  // Route moved 2026-07-29 (Proposal F /stats transform, PR #558) - see the "owner defect 1+2"
  // describe block above for the full note; same accordion, same link, now on /stats.
  test("a real production link (the /stats page's contribution guidelines' ISO-639-1 reference, inside the accordion body's panel-bg) clears strict-AAA-normal", async ({
    page,
    network,
  }) => {
    // generatedAt must be non-null here too - see the note on the first catalogStatsCurrentRatio
    // call site above.
    network.use(catalogStatsCurrentRatio, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "stats");

    const header = page.getByRole("button", {
      name: "Contribution Guidelines",
    });
    await header.click();
    const link = page.getByRole("link", { name: "ISO-639-1 nomenclature" });
    await expect(link).toBeVisible();

    const panelBgHex = "#2f3549";

    const restingColor = await link.evaluate(
      (el) => getComputedStyle(el).color
    );
    const restingHex = rgbStringToHex(restingColor);
    const restingRatio = contrastRatioHex(restingHex, panelBgHex);

    await link.hover();
    const hoverColor = await link.evaluate((el) => getComputedStyle(el).color);
    const hoverHex = rgbStringToHex(hoverColor);
    const hoverRatio = contrastRatioHex(hoverHex, panelBgHex);

    console.log(
      `real ISO-639-1 link: resting ${restingHex} = ${restingRatio}:1, hover ${hoverHex} = ${hoverRatio}:1`
    );
    expect(restingRatio).toBeGreaterThanOrEqual(7);
    expect(hoverRatio).toBeGreaterThanOrEqual(7);
  });
});
