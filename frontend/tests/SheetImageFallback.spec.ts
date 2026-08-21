import { expect } from "@playwright/test";
import { readFileSync } from "fs";
import { http, HttpResponse } from "msw";
import path from "path";
import { fileURLToPath } from "url";

import { cardDocument1, localBackendURL } from "@/common/test-constants";
import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";

// Regression coverage for the /editor centre-sheet image fallback fix (P0, follow-up to PR
// #814): `getSheetImageURL` used to resolve ONE URL (bucket -> worker -> thumbnail) and hand it
// straight to a static <img>, with no recovery when the resolved bucket object didn't actually
// exist. PagePreview's own slot now steps through the same bucket -> worker -> thumbnail chain
// Card.tsx's `onError` handler already walks for the left rail. Matches the domains configured
// via NEXT_PUBLIC_IMAGE_WORKER_URL / NEXT_PUBLIC_IMAGE_BUCKET_URL in playwright.config.ts's
// webServer env.
const IMAGE_WORKER_URL_PATTERN = /^https:\/\/cdn\.proxyprints\.ca\//;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;
const FALLBACK_THUMBNAIL_URL =
  "https://fallback-thumbnail.example.test/thumb.png";

const buildRoute = (route: string) => `${localBackendURL}/${route}`;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const validImageBytes = readFileSync(
  path.join(__dirname, "..", "public", "blank.png")
);
const okImage = () =>
  new HttpResponse(validImageBytes, {
    status: 200,
    headers: { "Content-Type": "image/png" },
  });
const notFound = () => new HttpResponse(null, { status: 404 });

// cardDocument1's own mediumThumbnailUrl is "" (see test-constants.ts) - overridden here to a
// distinct, interceptable domain so the final fallback tier is independently observable from
// the bucket/worker CDN tiers.
const cardDocumentsWithFallbackThumbnail = http.post(
  buildRoute("2/cards/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument1.identifier]: {
            ...cardDocument1,
            mediumThumbnailUrl: FALLBACK_THUMBNAIL_URL,
          },
        },
      },
      { status: 200 }
    )
);

const oneCardHandlers = [
  cardDocumentsWithFallbackThumbnail,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

async function importOnDisplayLanding(page: any, text: string) {
  await page.goto(`/display?server=${localBackendURL}`);
  await page.getByRole("textbox", { name: "import-text" }).fill(text);
  await page.getByRole("button", { name: "import-text-submit" }).click();
  await expect(page.getByTestId("display-page")).toBeVisible();
}

test.describe("Centre sheet image fallback (PagePreview)", () => {
  test("bucket 404s, worker healthy - the sheet slot falls through to the worker CDN", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(IMAGE_BUCKET_URL_PATTERN, notFound),
      http.get(IMAGE_WORKER_URL_PATTERN, okImage),
      ...oneCardHandlers
    );
    await importOnDisplayLanding(page, "my search query");

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);
    const totalImgCount = await img.count();
    const naturalWidth = await img.evaluate(
      (el: HTMLImageElement) => el.naturalWidth
    );
    const src = await img.getAttribute("src");
    console.log(
      `[AFTER bucket-404/worker-ok] imgCount=${totalImgCount} naturalWidth=${naturalWidth} src-host=${
        new URL(src ?? "").host
      }`
    );
    expect(src).toMatch(IMAGE_WORKER_URL_PATTERN);
  });

  test("bucket AND worker 404, thumbnail healthy - the sheet slot falls through to the thumbnail URL", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(IMAGE_BUCKET_URL_PATTERN, notFound),
      http.get(IMAGE_WORKER_URL_PATTERN, notFound),
      http.get(FALLBACK_THUMBNAIL_URL, okImage),
      ...oneCardHandlers
    );
    await importOnDisplayLanding(page, "my search query");

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);
    const naturalWidth = await img.evaluate(
      (el: HTMLImageElement) => el.naturalWidth
    );
    const src = await img.getAttribute("src");
    console.log(
      `[AFTER bucket-404/worker-404] naturalWidth=${naturalWidth} src=${src}`
    );
    expect(src).toBe(FALLBACK_THUMBNAIL_URL);
  });

  test("bucket healthy - the sheet slot loads from the CDN bucket directly, never falling back", async ({
    page,
    network,
  }) => {
    network.use(
      http.get(IMAGE_BUCKET_URL_PATTERN, okImage),
      http.get(IMAGE_WORKER_URL_PATTERN, notFound),
      ...oneCardHandlers
    );
    await importOnDisplayLanding(page, "my search query");

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);
    const naturalWidth = await img.evaluate(
      (el: HTMLImageElement) => el.naturalWidth
    );
    const src = await img.getAttribute("src");
    console.log(`[healthy bucket] naturalWidth=${naturalWidth} src=${src}`);
    expect(src).toMatch(IMAGE_BUCKET_URL_PATTERN);
  });
});
