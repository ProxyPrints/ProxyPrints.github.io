import { expect } from "@playwright/test";

import {
  cardDocumentsOneResult,
  contributionsOneSource,
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
  formatFailureTable,
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

test.describe("Contrast audit - /contributions (owner defect 1+2: accordion header + body)", () => {
  test("Contribution Guidelines accordion - collapsed and expanded", async ({
    page,
    network,
  }) => {
    network.use(contributionsOneSource, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "contributions");

    const header = page.getByRole("button", {
      name: "Contribution Guidelines",
    });
    await expect(header).toBeVisible();

    const collapsed = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-contributions-collapsed-390.png",
    });

    await header.click();
    await expect(page.getByText("File Format")).toBeVisible();
    const expanded = await auditContrast(page);
    await page.screenshot({
      path: "test-results/contrast-audit-contributions-expanded-390.png",
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

    assertNoNewFailures(collapsed.contrastFailures, "contributions collapsed");
    assertNoNewFailures(expanded.contrastFailures, "contributions expanded");
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
  test("Showing: Fronts / Cardback / Export controls in the offcanvas", async ({
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
    await expect(rail.getByText(/Showing: (Fronts|Backs)/)).toBeVisible();

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
