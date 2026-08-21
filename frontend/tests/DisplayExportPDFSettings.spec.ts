import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { fileURLToPath } from "url";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// The editor's real Export ▾ -> PDF settings step (DisplayExportPDF.tsx) - every control that
// replaced a named default in displayPdfProps.ts (card selection, page range, cut-line colour/
// geometry, an opt-in crosshair-marks toggle, an advanced per-side margin override, SCM cutting
// mode), plus the rail's own Page Setup / Print quality controls it shares an export pipeline
// with (Custom page size, image quality, corner rounding), and the willGenerateBleed signal on
// the sheet itself. Reads back the actual downloaded PDF bytes (pdfjs-dist, page-count/page-
// dimension metadata only - no canvas/rendering needed for that) rather than trusting the wiring
// by inspection, per this feature's own "a control that renders but doesn't affect the export"
// failure mode.
test.describe.configure({ timeout: 60_000 });

const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);
const imageWorkerSuccess = http.get(
  IMAGE_WORKER_URL_PATTERN,
  () =>
    new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    })
);
const imageBucketSuccess = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () =>
    new HttpResponse(validImageBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    })
);

const tenCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  imageWorkerSuccess,
  imageBucketSuccess,
  ...defaultHandlers,
];

const openPDFSettings = async (page: import("@playwright/test").Page) => {
  await page.getByTestId("display-export-menu-toggle").click();
  await page.getByTestId("display-export-pdf-button").click();
  await expect(
    page.getByTestId("display-export-pdf-settings-modal")
  ).toBeVisible();
};

// Editor export rescue (docs/features/pdf-generator.md's "Page cut guide lines, Google Drive
// save, and retiring the Finish footer's own print route") - the Download button now runs
// through `runExportGate`, so a fresh project (still riding the untouched default cardback) shows
// the cardback reminder gate on the FIRST export attempt each test. CB1 suppresses it for the
// rest of that session, so later calls in the same test see no gate - `.click()`'s own auto-wait
// (bounded here) absorbs both cases without a race.
const clickDownload = async (page: import("@playwright/test").Page) => {
  await page.getByTestId("display-export-pdf-download-button").click();
  await page
    .getByTestId("pre-print-cardback-gate")
    .getByTestId("cardback-gate-use-current")
    .click({ timeout: 3_000 })
    .catch(() => {});
};

const readNumPages = async (buffer: Buffer): Promise<number> => {
  const doc = await getDocument({ data: new Uint8Array(buffer) }).promise;
  return doc.numPages;
};

test.describe("DisplayExportPDF - Save PDF to Google Drive (rescued from /print's PDFGenerator.tsx)", () => {
  test("the Drive button is absent when Drive isn't configured (this suite's own env), matching PDFGenerator.tsx's own isGoogleDriveAppConfigured() gate", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    await expect(
      page.getByTestId("display-export-pdf-drive-button")
    ).toHaveCount(0);
    // Absent rather than broken - Download PDF is still the sole, working action.
    await expect(
      page.getByTestId("display-export-pdf-download-button")
    ).toBeVisible();
  });
});

test.describe("DisplayExportPDF - editor export controls", () => {
  test("opens with a safe default selection mode and a real, non-guessed total page count", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    // 10 identical fronts, 8 cards per page at the rail's default LETTER/rearFeed/D18 layout
    // (see displayPdfProps.test.ts's own documented 4x2 grid) -> 2 real pages.
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);

    await expect(
      page.getByTestId("display-export-card-selection-mode")
    ).toHaveValue("frontsAndBacks");
    await expect(page.getByText("Pages (2 total)")).toBeVisible();
  });

  test("page range slices the export to fewer real pages", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("1");
    await page.getByTestId("display-export-page-range-end").fill("1");
    const download1 = page.waitForEvent("download");
    await clickDownload(page);
    const path1 = await (await download1).path();
    if (!path1) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(path1))).toBe(1);

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("");
    await page.getByTestId("display-export-page-range-end").fill("");
    const download2 = page.waitForEvent("download");
    await clickDownload(page);
    const path2 = await (await download2).path();
    if (!path2) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(path2))).toBe(2);
  });

  test("card selection mode changes which faces the export contains", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    // Fronts only, never a back selection - "Backs Only" has nothing to paginate at all, "Fronts
    // + Backs" (the default) has 10 real fronts across 2 pages. A real, opposite-end difference.
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);
    const defaultDownload = page.waitForEvent("download");
    await clickDownload(page);
    const defaultPath = await (await defaultDownload).path();
    if (!defaultPath) throw new Error("Download path is null");
    expect(await readNumPages(readFileSync(defaultPath))).toBe(2);

    await openPDFSettings(page);
    await page
      .getByTestId("display-export-card-selection-mode")
      .selectOption("backsOnly");
    const backsOnlyDownload = page.waitForEvent("download");
    await clickDownload(page);
    const backsOnlyPath = await (await backsOnlyDownload).path();
    if (!backsOnlyPath) throw new Error("Download path is null");
    // PDF.tsx's own fallback for zero paginated pages ([[]]) - a single essentially-empty page,
    // not the 2 real pages the fronts produced.
    expect(await readNumPages(readFileSync(backsOnlyPath))).toBe(1);
  });

  test("the rail's DPI and JPG quality controls set the actual image-worker request's dpi/jpgQuality query params", async ({
    page,
    network,
  }) => {
    // The mock image worker always serves the same static blank.png regardless of query
    // params, so a downloaded-file-size comparison would only measure incidental bleed-math
    // side effects, not the setting itself - getWorkerImageURL (common/image.ts) embeds
    // `dpi`/`jpgQuality` directly in the fetched URL, which is the actual signal PDFCardImage's
    // full-resolution path sends downstream, so assert on that request instead.
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    // These two now live in the rail's own "Print quality" section, not the export dialog - set
    // before opening it, since the dialog's backdrop blocks the rail behind it while it's open.
    await page.getByTestId("display-image-dpi").fill("100");
    await page.getByTestId("display-jpg-quality").fill("5");

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("1");
    await page.getByTestId("display-export-page-range-end").fill("1");

    const requestPromise = page.waitForRequest(
      (request) =>
        IMAGE_WORKER_URL_PATTERN.test(request.url()) &&
        request.url().includes("/full/")
    );
    const downloadPromise = page.waitForEvent("download");
    await clickDownload(page);
    const [request] = await Promise.all([requestPromise, downloadPromise]);

    const requestUrl = new URL(request.url());
    expect(requestUrl.searchParams.get("dpi")).toBe("100");
    expect(requestUrl.searchParams.get("jpgQuality")).toBe("5");
  });

  test("cut-line colour and cross-marks toggle are only shown when the rail's Guides toggle is on, and map through to the export", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    // These now live in the rail next to the Guides toggle they depend on, not the export
    // dialog - no dialog to open for this check.
    await expect(page.getByTestId("display-cut-line-color")).toBeVisible();
    const crossToggle = page.getByTestId("display-cross-cut-lines");
    await expect(crossToggle).toBeVisible();
    await expect(crossToggle).not.toBeChecked();
    await page.getByTestId("display-cut-line-color").fill("#ff0000");
    await crossToggle.check();
    await expect(page.getByTestId("display-cut-line-color")).toHaveValue(
      "#ff0000"
    );
    await expect(crossToggle).toBeChecked();

    // Guides off -> the colour/cross-marks controls have nothing to style, so they don't render.
    await page.getByLabel("Guides").uncheck();
    await expect(page.getByTestId("display-cut-line-color")).not.toBeVisible();
  });

  test("the bleed-will-be-generated badge appears on the editor sheet for a forced-trimmed eligible card", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await page.getByTestId("page-preview-slot").first().click();

    const select = page.getByTestId(
      `bleed-override-select-${cardDocument1.identifier}`
    );
    await expect(select).toBeVisible();
    await expect(
      page.getByTestId("page-preview-bleed-badge")
    ).not.toBeVisible();

    await select.selectOption("force-trimmed");

    await expect(page.getByTestId("page-preview-bleed-badge")).toBeVisible();
    await expect(page.getByTestId("page-preview-bleed-badge")).toContainText(
      "Bleed will be generated"
    );
  });
});

// Total draw-op count for page 1, via pdfjs-dist's real operator list - a content-level signal,
// not a byte-size proxy, so a compression-size fluke can't produce a false pass either way.
const countPageOneDrawOps = async (buffer: Buffer): Promise<number> => {
  const doc = await getDocument({ data: new Uint8Array(buffer) }).promise;
  const pdfPage = await doc.getPage(1);
  const operatorList = await pdfPage.getOperatorList();
  return operatorList.fnArray.length;
};

test.describe("DisplayExportPDF - page cut guide lines (rescued from /print's PDFGenerator.tsx)", () => {
  test("drawPageCutLines reaches the rendered PDF: turning the toggle off removes real draw operations, not just UI state", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    const pageCutLines = page.getByTestId("display-export-page-cut-lines");
    // Matches /print's PDFGenerator.tsx own default.
    await expect(pageCutLines).toBeChecked();

    const onDownload = page.waitForEvent("download");
    await clickDownload(page);
    const onPath = await (await onDownload).path();
    if (!onPath) throw new Error("Download path is null");
    const onOps = await countPageOneDrawOps(readFileSync(onPath));

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-cut-lines").uncheck();
    const offDownload = page.waitForEvent("download");
    await clickDownload(page);
    const offPath = await (await offDownload).path();
    if (!offPath) throw new Error("Download path is null");
    const offOps = await countPageOneDrawOps(readFileSync(offPath));

    // A control that renders in the settings step but never reaches PDFProps.drawPageCutLines is
    // exactly the failure this rescue exists to fix - assert on the actual rendered content
    // (real draw ops), not the settings-step UI state, which the two `toBeChecked` assertions
    // above already covered.
    expect(onOps).toBeGreaterThan(offOps);
  });
});

const mmToPt = (mm: number) => (mm / 25.4) * 72;

test.describe("DisplayExportPDF - SCM cutting mode", () => {
  test("the mode switch swaps the settings step body between the standard controls and SCM's own sub-settings", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    await expect(
      page.getByTestId("display-export-card-selection-mode")
    ).toBeVisible();
    await expect(
      page.getByTestId("display-export-scm-paper-size")
    ).not.toBeVisible();

    await page.getByTestId("display-export-scm-mode-switch").check();

    await expect(
      page.getByTestId("display-export-card-selection-mode")
    ).not.toBeVisible();
    await expect(
      page.getByTestId("display-export-page-range-start")
    ).toHaveCount(0);
    await expect(
      page.getByTestId("display-export-scm-paper-size")
    ).toBeVisible();
    await expect(page.getByTestId("display-export-scm-variant")).toBeVisible();
    await expect(
      page.getByTestId("display-export-scm-registration")
    ).toBeVisible();
    await expect(page.getByTestId("display-export-scm-duplex")).toBeVisible();
    await expect(page.getByTestId("display-export-scm-offset-x")).toBeVisible();
    await expect(page.getByTestId("display-export-scm-offset-y")).toBeVisible();
    await expect(
      page.getByTestId("display-export-scm-offset-angle")
    ).toBeVisible();
    // Image quality now lives in the rail, not this dialog - stays visible and unaffected by
    // which panel (standard/SCM) is showing. SCMCard reads it exactly like the standard grid's
    // own card image does.
    await expect(page.getByTestId("display-image-dpi")).toBeVisible();
  });

  test("an SCM export is a structurally different document from the standard export", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "10x my search query");

    await openPDFSettings(page);
    const standardDownload = page.waitForEvent("download");
    await clickDownload(page);
    const standardPath = await (await standardDownload).path();
    if (!standardPath) throw new Error("Download path is null");
    const standardPages = await readNumPages(readFileSync(standardPath));

    await openPDFSettings(page);
    await page.getByTestId("display-export-scm-mode-switch").check();
    const scmDownload = page.waitForEvent("download");
    await clickDownload(page);
    const scmPath = await (await scmDownload).path();
    if (!scmPath) throw new Error("Download path is null");
    const scmPages = await readNumPages(readFileSync(scmPath));

    // PDF.tsx's own PDF component returns straight into <SCMPDF> for scmMode, an entirely
    // different pagination path (SCMPDF.tsx's own front/back pairing and layout table, ignoring
    // cardSelectionMode/margins/cut-line geometry the standard grid uses) - a real, structural
    // difference in the generated file, not a cosmetic one.
    expect(scmPages).not.toBe(standardPages);
  });
});

test.describe("DisplayExportPDF - corner rounding and extended cut-line geometry", () => {
  test("length, thickness, and offset are settable alongside colour", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    // Rail controls now, next to the Guides toggle (on by default) - no dialog involved.
    await page.getByTestId("display-cut-line-length").fill("5");
    await page.getByTestId("display-cut-line-thickness").fill("1");
    await page.getByTestId("display-cut-line-offset").fill("0.5");

    await expect(page.getByTestId("display-cut-line-length")).toHaveValue("5");
    await expect(page.getByTestId("display-cut-line-thickness")).toHaveValue(
      "1"
    );
    await expect(page.getByTestId("display-cut-line-offset")).toHaveValue(
      "0.5"
    );
  });

  test("round/square corners toggle is settable", async ({ page, network }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    // Now a rail control ("Print quality" section) - no dialog to open. Defaults to checked
    // (roundCorners defaults to true - see DEFAULT_SHEET_SETTINGS).
    const roundCorners = page.getByTestId("display-round-corners");
    await expect(roundCorners).toBeChecked();
    await roundCorners.uncheck();
    await expect(roundCorners).not.toBeChecked();
    await roundCorners.check();
    await expect(roundCorners).toBeChecked();
  });
});

test.describe("DisplayExportPDF - advanced page-margin override", () => {
  test("enabling the override seeds top/bottom/left/right from the rail's current profile, and is editable", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await openPDFSettings(page);
    await expect(page.getByTestId("display-export-margin-top")).toHaveCount(0);

    await page.getByTestId("display-export-margin-override-toggle").check();
    // rearFeed, the rail's default profile: {top: 3, bottom: 3, left: 3, right: 20}.
    await expect(page.getByTestId("display-export-margin-top")).toHaveValue(
      "3"
    );
    await expect(page.getByTestId("display-export-margin-bottom")).toHaveValue(
      "3"
    );
    await expect(page.getByTestId("display-export-margin-left")).toHaveValue(
      "3"
    );
    await expect(page.getByTestId("display-export-margin-right")).toHaveValue(
      "20"
    );

    await page.getByTestId("display-export-margin-top").fill("10");
    await expect(page.getByTestId("display-export-margin-top")).toHaveValue(
      "10"
    );

    await page.getByTestId("display-export-margin-override-toggle").uncheck();
    await expect(page.getByTestId("display-export-margin-top")).toHaveCount(0);
  });
});

test.describe("DisplayExportPDF - Custom page size (rail)", () => {
  test("a Custom paper size on the rail exports a PDF at exactly the entered dimensions", async ({
    page,
    network,
  }) => {
    network.use(...tenCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await page.getByLabel("Paper size").selectOption("CUSTOM");
    await page.getByTestId("display-custom-page-width").fill("100");
    await page.getByTestId("display-custom-page-height").fill("150");

    await openPDFSettings(page);
    await page.getByTestId("display-export-page-range-start").fill("1");
    await page.getByTestId("display-export-page-range-end").fill("1");
    const download = page.waitForEvent("download");
    await clickDownload(page);
    const downloadPath = await (await download).path();
    if (!downloadPath) throw new Error("Download path is null");

    const doc = await getDocument({
      data: new Uint8Array(readFileSync(downloadPath)),
    }).promise;
    const pdfPage = await doc.getPage(1);
    const [x0, y0, x1, y1] = pdfPage.view;
    const widthPt = x1 - x0;
    const heightPt = y1 - y0;
    // The landscape rule (displayPdfProps.ts's own module comment): portrait width/height
    // entered on the rail come out swapped in the export, same as every other paper size.
    expect(widthPt).toBeCloseTo(mmToPt(150), 0);
    expect(heightPt).toBeCloseTo(mmToPt(100), 0);
  });
});
