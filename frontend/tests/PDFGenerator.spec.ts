import { expect, Page } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import { ManualOverridesKey } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  tagConsensusAppropriateBleedTrimmed,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

// Matches the domains configured via NEXT_PUBLIC_IMAGE_WORKER_URL /
// NEXT_PUBLIC_IMAGE_BUCKET_URL in playwright.config.ts's webServer env.
const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

// A small real PNG so @react-pdf/renderer can actually decode it into a page,
// not just a byte blob that happens to satisfy `response.ok`.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);

const imageWorkerFailure = http.get(
  IMAGE_WORKER_URL_PATTERN,
  () => new HttpResponse(null, { status: 500 })
);
const imageBucketFailure = http.get(
  IMAGE_BUCKET_URL_PATTERN,
  () => new HttpResponse(null, { status: 404 })
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

const addCardAndOpenPDFTab = async (page: Page) => {
  await loadPageWithDefaultBackend(page);
  await importText(page, "my search query");
  await page.getByRole("tab", { name: "Print!" }).click();
  await page.getByRole("tab", { name: "PDF" }).click();
};

test.describe("PDFGenerator - card image fetch failures", () => {
  test("warns in the live preview when a card image fails to fetch", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);

    const warning = page.getByTestId("pdf-preview-image-failures");
    await expect(warning).toBeVisible({ timeout: 15_000 });
    await expect(warning).toContainText(cardDocument1.name);
  });

  test("blocks the download behind a confirm naming the failed card, and honours cancelling it", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(page.getByTestId("pdf-preview-image-failures")).toBeVisible({
      timeout: 15_000,
    });

    let dialogMessage = "";
    page.once("dialog", async (dialog) => {
      dialogMessage = dialog.message();
      await dialog.dismiss();
    });

    const downloadPromise = page
      .waitForEvent("download", { timeout: 3_000 })
      .catch(() => undefined);
    await page.getByRole("button", { name: "Generate PDF" }).click();

    await expect(page.getByText("Download Cancelled")).toBeVisible();
    expect(dialogMessage).toContain(cardDocument1.name);
    expect(dialogMessage.toLowerCase()).toContain("blank");
    // Cancelling the confirm must actually prevent the file from downloading.
    await expect(downloadPromise).resolves.toBeUndefined();
  });

  test("downloads anyway once the user confirms despite the failed image", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketFailure,
      imageWorkerFailure,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(page.getByTestId("pdf-preview-image-failures")).toBeVisible({
      timeout: 15_000,
    });

    page.once("dialog", (dialog) => dialog.accept());

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Generate PDF" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
  });

  test("downloads without any warning or confirm when card images load successfully", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      imageWorkerSuccess,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(
      page.getByTestId("pdf-preview-image-failures")
    ).not.toBeVisible();

    let dialogFired = false;
    page.once("dialog", (dialog) => {
      dialogFired = true;
      void dialog.dismiss();
    });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Generate PDF" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("cards.pdf");
    expect(dialogFired).toBe(false);
  });
});

test.describe("PDFGenerator - manual bleed override (Proposal B PR-2)", () => {
  test("setting an override persists to localStorage and survives reload", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      imageWorkerSuccess,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);

    await page.getByText("Bleed Overrides").click();
    const select = page.getByTestId(
      `bleed-override-select-${cardDocument1.identifier}`
    );
    await expect(select).toBeVisible();
    await expect(select).toHaveValue("auto");

    await select.selectOption("force-bleed");
    await expect(select).toHaveValue("force-bleed");

    // The override is keyed by card identifier in a standalone localStorage entry, independent
    // of the in-memory project (which doesn't itself persist across reload today) - decision 4
    // only requires the override itself to survive, not the whole open project.
    await expect
      .poll(() =>
        page.evaluate((key) => localStorage.getItem(key), ManualOverridesKey)
      )
      .toBe(JSON.stringify({ [cardDocument1.identifier]: "force-bleed" }));

    // A fresh navigation rather than page.reload() - reload() alone was observed to hang past
    // the test timeout in this app; waiting for "domcontentloaded" rather than the default
    // "load" avoids a second hang, both unrelated to anything this PR touches (this app's
    // webworkers appear not to settle a second "load" event cleanly within one Playwright page).
    await page.goto("/editor?server=http://127.0.0.1:8000", {
      waitUntil: "domcontentloaded",
    });
    await page.getByText("Choose Art").click();
    await importText(page, "my search query");
    await page.getByRole("tab", { name: "Print!" }).click();
    await page.getByRole("tab", { name: "PDF" }).click();
    await page.getByText("Bleed Overrides").click();

    await expect(
      page.getByTestId(`bleed-override-select-${cardDocument1.identifier}`)
    ).toHaveValue("force-bleed");
  });
});

test.describe("PDFGenerator - bleed preview badge (Proposal B PR-3)", () => {
  test("shows the hedged badge once the appropriate-bleed prior resolves to 'trimmed'", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      imageWorkerSuccess,
      tagConsensusAppropriateBleedTrimmed,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);

    // The badge only renders once the prior fetch resolves (no provisional guess beforehand -
    // see PDFGenerator.tsx's fastPreviewSlots comment), so this is a genuine wait on the real
    // async round trip, not an instant assertion.
    const badge = page.getByTestId("page-preview-bleed-badge");
    await expect(badge).toBeVisible({ timeout: 15_000 });
    await expect(badge).toHaveText("Bleed will be generated");
  });

  test("forcing 'Force bleed' hides the badge regardless of the resolved prior", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      imageBucketSuccess,
      imageWorkerSuccess,
      tagConsensusAppropriateBleedTrimmed,
      ...defaultHandlers
    );

    await addCardAndOpenPDFTab(page);
    await expect(page.getByTestId("page-preview-bleed-badge")).toBeVisible({
      timeout: 15_000,
    });

    await page.getByText("Bleed Overrides").click();
    await page
      .getByTestId(`bleed-override-select-${cardDocument1.identifier}`)
      .selectOption("force-bleed");

    await expect(
      page.getByTestId("page-preview-bleed-badge")
    ).not.toBeVisible();
  });
});
