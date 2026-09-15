import { expect } from "@playwright/test";
import { inflateSync } from "zlib";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expandRailSection,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

const singleCardHandlers = [
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

// ─── PNG decoder (reused from PagePreviewImageScale.spec.ts) ────────────────
// Minimal, dependency-free PNG decoder: 8-bit, non-interlaced, colour type 2
// (RGB) or 6 (RGBA) - exactly what Chromium's own screenshot encoder produces.
function decodePNG(buffer: Buffer): {
  width: number;
  height: number;
  data: Buffer;
  channels: number;
} {
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idatChunks: Buffer[] = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const dataStart = offset + 8;
    if (type === "IHDR") {
      width = buffer.readUInt32BE(dataStart);
      height = buffer.readUInt32BE(dataStart + 4);
      bitDepth = buffer.readUInt8(dataStart + 8);
      colorType = buffer.readUInt8(dataStart + 9);
    } else if (type === "IDAT") {
      idatChunks.push(buffer.subarray(dataStart, dataStart + length));
    } else if (type === "IEND") {
      break;
    }
    offset = dataStart + length + 4;
  }
  if (bitDepth !== 8) {
    throw new Error(`unsupported PNG bit depth ${bitDepth}`);
  }
  const channels =
    colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : null;
  if (channels == null) {
    throw new Error(`unsupported PNG color type ${colorType}`);
  }
  const raw = inflateSync(Buffer.concat(idatChunks));
  const stride = width * channels;
  const data = Buffer.alloc(height * stride);
  const prevLine = Buffer.alloc(stride);
  let rawOffset = 0;
  for (let y = 0; y < height; y++) {
    const filterType = raw[rawOffset];
    rawOffset += 1;
    const line = raw.subarray(rawOffset, rawOffset + stride);
    rawOffset += stride;
    const outLine = data.subarray(y * stride, y * stride + stride);
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? outLine[x - channels] : 0;
      const b = prevLine[x];
      const c = x >= channels ? prevLine[x - channels] : 0;
      let value = line[x];
      switch (filterType) {
        case 0:
          break;
        case 1:
          value = (value + a) & 0xff;
          break;
        case 2:
          value = (value + b) & 0xff;
          break;
        case 3:
          value = (value + Math.floor((a + b) / 2)) & 0xff;
          break;
        case 4: {
          const p = a + b - c;
          const pa = Math.abs(p - a);
          const pb = Math.abs(p - b);
          const pc = Math.abs(p - c);
          const predictor = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
          value = (value + predictor) & 0xff;
          break;
        }
        default:
          throw new Error(`unsupported PNG filter type ${filterType}`);
      }
      outLine[x] = value;
    }
    outLine.copy(prevLine);
  }
  return { width, height, data, channels };
}

// ─── Guide color detection ──────────────────────────────────────────────────
// Default cutLineColor is #8ae234 (a bright yellow-green). After rasterisation
// the rendered colour may shift slightly due to anti-aliasing and gamma, so we
// match a broad green-dominant band rather than the exact hex.
function isGuideGreen(r: number, g: number, b: number): boolean {
  return g > 150 && g > r * 1.3 && g > b * 1.3;
}

function countGuidePixels(image: {
  width: number;
  height: number;
  data: Buffer;
  channels: number;
}): number {
  let count = 0;
  const { width, height, data, channels } = image;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * channels;
      if (isGuideGreen(data[i], data[i + 1], data[i + 2])) {
        count++;
      }
    }
  }
  return count;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

type MarginProfile = "bordered" | "rearFeed";

/**
 * Load the Display page, import a single card, configure the margin profile,
 * cut-line shape, and guides toggle.  All UI interaction happens at the default
 * Playwright viewport (800×600 from the config) where the rail is visible.
 * The caller resizes to the target viewport *after* this returns, then waits
 * for the layout to settle before screenshotting.
 */
async function setupCardOnPage(
  page: import("@playwright/test").Page,
  marginProfile: MarginProfile,
  cutLineShape: "perimeter" | "cornerMarks" | "both" = "perimeter"
) {
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "1x my search query");

  const profileSelect = page.getByTestId("display-margin-profile-select");
  await profileSelect.waitFor({ state: "visible" });
  await profileSelect.selectOption(marginProfile);

  await expandRailSection(page, "cut-lines-guides");
  await page.getByTestId("display-cut-line-shape").selectOption(cutLineShape);
}

/**
 * Wait for the sheet region to finish re-layout after a viewport resize, then
 * return the page-preview-slot locator (assumes the first card slot).
 */
async function waitForLayoutSettle(
  page: import("@playwright/test").Page
): Promise<import("@playwright/test").Locator> {
  const slot = page.getByTestId("page-preview-slot").first();
  await expect(slot).toBeVisible();
  const guide = slot.getByTestId("page-preview-cut-line");
  await expect(guide.first()).toBeVisible();
  // Give the CSS transform scale time to recalculate after resize.
  await page.waitForTimeout(300);
  return slot;
}

// ─── Test suite ─────────────────────────────────────────────────────────────

/**
 * Cut-guide painted-output verification — browser-level verification that the
 * sub-pixel stroke floor actually produces painted guide pixels on every
 * margin-profile × viewport-width combination.
 *
 * The sub-pixel floor (minStrokeMM = 1 / (scale * CSS_PX_PER_MM)) ensures
 * each guide element is at least 1 device pixel wide after the page's CSS
 * transform. Without it, the default 0.25mm stroke goes sub-pixel at every
 * realistic scale and is silently dropped by the rasterizer.
 *
 * This suite exercises at least two margin profiles (bordered, rearFeed) and
 * at least two viewport widths so the outer `scale` differs materially
 * between them, asserting that guide colour pixels are actually painted in
 * every combination.
 */
test.describe("Cut guide rendering - painted output", () => {
  test.describe.configure({ timeout: 90_000 });

  const viewports: Array<{ name: string; width: number; height: number }> = [
    { name: "narrow (800px)", width: 800, height: 600 },
    { name: "wide (1280px)", width: 1280, height: 800 },
  ];

  const profiles: MarginProfile[] = ["bordered", "rearFeed"];

  for (const viewport of viewports) {
    for (const profile of profiles) {
      test(`perimeter guide paints green pixels [${profile}, ${viewport.name}]`, async ({
        page,
        network,
      }) => {
        network.use(...singleCardHandlers);
        await setupCardOnPage(page, profile, "perimeter");

        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        });
        const slot = await waitForLayoutSettle(page);

        const screenshot = await slot.screenshot();
        const decoded = decodePNG(screenshot);
        const guidePixels = countGuidePixels(decoded);

        expect(
          guidePixels,
          `Expected painted guide pixels in slot screenshot (${profile}, ${viewport.name}) — guide may have gone sub-pixel`
        ).toBeGreaterThan(20);
      });
    }
  }

  for (const viewport of viewports) {
    for (const profile of profiles) {
      test(`cornerMarks guide paints green pixels [${profile}, ${viewport.name}]`, async ({
        page,
        network,
      }) => {
        network.use(...singleCardHandlers);
        await setupCardOnPage(page, profile, "cornerMarks");

        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        });
        const slot = await waitForLayoutSettle(page);

        const screenshot = await slot.screenshot();
        const decoded = decodePNG(screenshot);
        const guidePixels = countGuidePixels(decoded);

        expect(
          guidePixels,
          `Expected painted corner-mark pixels (${profile}, ${viewport.name})`
        ).toBeGreaterThan(8);
      });
    }
  }

  for (const viewport of viewports) {
    for (const profile of profiles) {
      test(`both shape paints green pixels [${profile}, ${viewport.name}]`, async ({
        page,
        network,
      }) => {
        network.use(...singleCardHandlers);
        await setupCardOnPage(page, profile, "both");

        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        });
        const slot = await waitForLayoutSettle(page);

        const screenshot = await slot.screenshot();
        const decoded = decodePNG(screenshot);
        const guidePixels = countGuidePixels(decoded);

        expect(
          guidePixels,
          `Expected painted guide pixels for "both" shape (${profile}, ${viewport.name})`
        ).toBeGreaterThan(30);
      });
    }
  }

  // ─── Shape-switching still works (DOM-level sanity, kept from old suite) ───

  test("shape switcher replaces DOM segments correctly", async ({
    page,
    network,
  }) => {
    network.use(...singleCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await expandRailSection(page, "cut-lines-guides");
    const shapeSelect = page.getByTestId("display-cut-line-shape");

    await shapeSelect.selectOption("perimeter");
    const slot = page.getByTestId("page-preview-slot").first();
    const guides = slot.getByTestId("page-preview-cut-line");
    await expect(guides).toBeVisible();
    expect(await guides.count()).toBe(1);

    await shapeSelect.selectOption("cornerMarks");
    await expect(guides.first()).toBeVisible();
    expect(await guides.count()).toBe(8);

    await shapeSelect.selectOption("both");
    await expect(guides.first()).toBeVisible();
    expect(await guides.count()).toBe(9);

    await shapeSelect.selectOption("perimeter");
    await expect(guides).toBeVisible();
    expect(await guides.count()).toBe(1);
  });
});
