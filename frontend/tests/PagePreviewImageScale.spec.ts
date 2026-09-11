import { expect, Locator, Page } from "@playwright/test";
import { http, HttpResponse } from "msw";
import { inflateSync } from "zlib";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import { cardDocument1, localBackendURL } from "@/common/test-constants";
import {
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";

// Preview/export parity fix - the shipped image transform assumed `object-fit: fill`'s math
// ("scale the natural size up to the slot, then scale back down") while the CSS actually used
// `object-fit: contain`, which fits the image UNIFORMLY (letterboxing the axis that doesn't
// bind) rather than filling the slot on both axes independently. The subsequent non-uniform
// correction transform then only cancelled out on the axis `contain` already bound to, leaving
// the letterboxed axis under/over-scaled - so the card's own trim edge landed off the cut guide
// whenever a card's measuredBleedMm differed from the page's granted bleed (the exact case this
// feature exists to handle).
//
// jsdom can't catch this: it doesn't lay out `object-fit` at all, and the old test only asserted
// the transform *string*, which was never the bug - the bug was which `object-fit` value that
// string got combined with. `getBoundingClientRect`/`boundingBox()` can't catch it either:
// `object-fit` never changes an element's own layout box (the img element is always exactly
// `slotWidthMM x slotHeightMM`, scaled by the same CSS transform regardless of `object-fit`) -
// it only changes how the image's pixels are PAINTED inside that box. So this suite renders a
// real two-tone fixture image (a blue "trim" rectangle inset by measuredBleedMm within a red
// "bleed" field, matching how a real bleed-extended card image is actually laid out) and reads
// back the ACTUAL PAINTED pixels via a real screenshot, decoded by hand (Node's built-in zlib,
// no new dependency) - the only way to observe what `object-fit` really did.
const buildRoute = (route: string) => `${localBackendURL}/${route}`;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

// Matches the assumption PagePreviewSlotEl's own scale math makes: the image's natural size is
// (CardWidthMM + 2*measuredBleedMm) x (CardHeightMM + 2*measuredBleedMm), with the trim
// rectangle (the actual CardWidthMM x CardHeightMM card face) centred inside it. The red field
// stands in for the bleed margin; the blue rectangle stands in for the card's own trim edge -
// exactly the boundary the cut guide is supposed to land on.
const FIXTURE_PX_PER_MM = 10;
function trimFixtureSvg(measuredBleedMm: number): string {
  const widthPx = (CardWidthMM + 2 * measuredBleedMm) * FIXTURE_PX_PER_MM;
  const heightPx = (CardHeightMM + 2 * measuredBleedMm) * FIXTURE_PX_PER_MM;
  const trimXPx = measuredBleedMm * FIXTURE_PX_PER_MM;
  const trimYPx = measuredBleedMm * FIXTURE_PX_PER_MM;
  const trimWidthPx = CardWidthMM * FIXTURE_PX_PER_MM;
  const trimHeightPx = CardHeightMM * FIXTURE_PX_PER_MM;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${widthPx}" height="${heightPx}">` +
    `<rect width="${widthPx}" height="${heightPx}" fill="#ff0000"/>` +
    `<rect x="${trimXPx}" y="${trimYPx}" width="${trimWidthPx}" height="${trimHeightPx}" fill="#0000ff"/>` +
    `</svg>`
  );
}

function cardDocumentsWithMeasuredBleed(measuredBleedMm: number) {
  return http.post(buildRoute("2/cards/"), () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument1.identifier]: { ...cardDocument1, measuredBleedMm },
        },
      },
      { status: 200 }
    )
  );
}

function trimFixtureImageHandler(measuredBleedMm: number) {
  return http.get(
    IMAGE_BUCKET_URL_PATTERN,
    () =>
      new HttpResponse(trimFixtureSvg(measuredBleedMm), {
        status: 200,
        headers: { "Content-Type": "image/svg+xml" },
      })
  );
}

async function importOnDisplayLanding(page: Page, text: string) {
  await page.goto(`/display?server=${localBackendURL}`);
  await page.getByRole("textbox", { name: "import-text" }).fill(text);
  await page.getByRole("button", { name: "import-text-submit" }).click();
  await expect(page.getByTestId("display-page")).toBeVisible();
}

async function box(locator: Locator) {
  const rect = await locator.boundingBox();
  if (rect == null) {
    throw new Error("expected a visible bounding box");
  }
  return rect;
}

// Minimal, dependency-free PNG decoder: 8-bit, non-interlaced, colour type 2 (RGB) or 6 (RGBA) -
// exactly what Chromium's own screenshot encoder produces. Handles all 5 PNG filter types
// (None/Sub/Up/Average/Paeth) per the spec's own per-byte reconstruction algorithm.
function decodePNG(buffer: Buffer): {
  width: number;
  height: number;
  data: Buffer;
  channels: number;
} {
  let offset = 8; // skip the 8-byte PNG signature
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
    offset = dataStart + length + 4; // + 4 for the trailing CRC
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

function findColorBounds(
  image: { width: number; height: number; data: Buffer; channels: number },
  matches: (r: number, g: number, b: number) => boolean
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const { width, height, data, channels } = image;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * channels;
      if (matches(data[i], data[i + 1], data[i + 2])) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  return maxX < minX ? null : { minX, minY, maxX, maxY };
}

const isBlue = (r: number, g: number, b: number) =>
  b > 180 && r < 60 && g < 60;

test.describe("PagePreview - image scale matches object-fit (preview/export parity)", () => {
  // Real catalogue bleed measurements span roughly 0.05mm-3.95mm; DisplayPage's own default
  // `bleedEdgeMM` is STANDARD_BLEED_MARGIN_MM (3.175mm) - each case below deliberately sets
  // measuredBleedMm away from that default so the granted-vs-measured mismatch this feature
  // exists to handle is actually exercised, not accidentally collapsed to the identity case.
  const cases: Array<{ name: string; measuredBleedMm: number }> = [
    { name: "measured << granted", measuredBleedMm: 0.05 },
    {
      name: "measured at the standard convention (STANDARD_BLEED_MARGIN_MM)",
      measuredBleedMm: 3.175,
    },
    { name: "measured > granted (the clipped case)", measuredBleedMm: 3.952 },
  ];

  for (const { name, measuredBleedMm } of cases) {
    test(`${name}: the fixture's trim rectangle (blue) lands exactly on the cut guide`, async ({
      page,
      network,
    }) => {
      network.use(
        cardDocumentsWithMeasuredBleed(measuredBleedMm),
        trimFixtureImageHandler(measuredBleedMm),
        sourceDocumentsOneResult,
        searchResultsOneResult,
        ...defaultHandlers
      );
      await importOnDisplayLanding(page, "my search query");

      const slot = page.getByTestId("page-preview-slot").first();
      const img = slot.locator("img");
      await expect
        .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
          timeout: 15_000,
        })
        .toBeGreaterThan(0);

      const cutLine = slot.getByTestId("page-preview-cut-line");
      await expect(cutLine).toBeVisible();

      const slotBox = await box(slot);
      const guideBox = await box(cutLine);
      // Guide bounds, relative to the slot's own top-left corner - the same origin the
      // screenshot below uses (locator.screenshot() crops to exactly the target element's box).
      const guideRelLeft = guideBox.x - slotBox.x;
      const guideRelTop = guideBox.y - slotBox.y;
      const guideRelRight = guideRelLeft + guideBox.width;
      const guideRelBottom = guideRelTop + guideBox.height;

      const screenshot = await slot.screenshot();
      const decoded = decodePNG(screenshot);
      const blueBounds = findColorBounds(decoded, isBlue);
      expect(blueBounds).not.toBeNull();
      const trimLeft = blueBounds!.minX;
      const trimTop = blueBounds!.minY;
      const trimRight = blueBounds!.maxX + 1;
      const trimBottom = blueBounds!.maxY + 1;

      // A few px of tolerance for SVG rasterization anti-aliasing at rect edges - anything
      // beyond that is the actual defect, not rendering noise.
      const tolerancePx = 2;
      expect(Math.abs(trimLeft - guideRelLeft)).toBeLessThan(tolerancePx);
      expect(Math.abs(trimTop - guideRelTop)).toBeLessThan(tolerancePx);
      expect(Math.abs(trimRight - guideRelRight)).toBeLessThan(tolerancePx);
      expect(Math.abs(trimBottom - guideRelBottom)).toBeLessThan(tolerancePx);
    });
  }
});
