import { expect, Page } from "@playwright/test";
import { http, HttpResponse } from "msw";
import { inflateSync } from "zlib";

import { CardHeightMM, CardWidthMM, CornerRadiusMM } from "@/common/constants";
import { cardDocument1, localBackendURL } from "@/common/test-constants";
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

const buildRoute = (route: string) => `${localBackendURL}/${route}`;
const IMAGE_BUCKET_URL_PATTERN = /^https:\/\/img\.proxyprints\.ca\//;

const FIXTURE_PX_PER_MM = 10;
const FIXTURE_BLEED_EDGE_MM = 3.175;
const FIXTURE_BLEED_MM = {
  top: FIXTURE_BLEED_EDGE_MM,
  bottom: FIXTURE_BLEED_EDGE_MM,
  left: FIXTURE_BLEED_EDGE_MM,
  right: FIXTURE_BLEED_EDGE_MM,
};

function cardDocumentsWithBleed(measuredBleedMm: number) {
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

function fixtureImageHandler(measuredBleedMm: number) {
  const widthPx = (CardWidthMM + 2 * measuredBleedMm) * FIXTURE_PX_PER_MM;
  const heightPx = (CardHeightMM + 2 * measuredBleedMm) * FIXTURE_PX_PER_MM;
  const trimXPx = measuredBleedMm * FIXTURE_PX_PER_MM;
  const trimYPx = measuredBleedMm * FIXTURE_PX_PER_MM;
  const trimWidthPx = CardWidthMM * FIXTURE_PX_PER_MM;
  const trimHeightPx = CardHeightMM * FIXTURE_PX_PER_MM;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${widthPx}" height="${heightPx}">` +
    `<rect width="${widthPx}" height="${heightPx}" fill="#ff0000"/>` +
    `<rect x="${trimXPx}" y="${trimYPx}" width="${trimWidthPx}" height="${trimHeightPx}" fill="#0000ff"/>` +
    `</svg>`;
  return http.get(
    IMAGE_BUCKET_URL_PATTERN,
    () =>
      new HttpResponse(svg, {
        status: 200,
        headers: { "Content-Type": "image/svg+xml" },
      })
  );
}

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

function samplePixel(
  image: { width: number; height: number; data: Buffer; channels: number },
  x: number,
  y: number
): { r: number; g: number; b: number } | null {
  if (x < 0 || x >= image.width || y < 0 || y >= image.height) return null;
  const i = (y * image.width + x) * image.channels;
  return {
    r: image.data[i],
    g: image.data[i + 1],
    b: image.data[i + 2],
  };
}

const isBlue = (r: number, g: number, b: number) => b > 180 && r < 60 && g < 60;

function findBounds(
  image: { width: number; height: number; data: Buffer; channels: number },
  matches: (r: number, g: number, b: number) => boolean
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < image.width; x++) {
      const px = samplePixel(image, x, y);
      if (px && matches(px.r, px.g, px.b)) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  return maxX < minX ? null : { minX, minY, maxX, maxY };
}

async function ensureRoundCornersEnabled(page: Page) {
  await expandRailSection(page, "print-quality");
  const toggle = page.getByTestId("display-round-corners");
  if (!(await toggle.isChecked())) {
    await toggle.click();
  }
  await expect(toggle).toBeChecked();
}

async function ensureRoundCornersDisabled(page: Page) {
  await expandRailSection(page, "print-quality");
  const toggle = page.getByTestId("display-round-corners");
  if (await toggle.isChecked()) {
    await toggle.click();
  }
  await expect(toggle).not.toBeChecked();
}

test.describe("PagePreview - card corner radius matches exporter", () => {
  test("roundCorners on: the card's extreme corner pixel is background (not card)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithBleed(FIXTURE_BLEED_EDGE_MM),
      fixtureImageHandler(FIXTURE_BLEED_EDGE_MM),
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await ensureRoundCornersEnabled(page);

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);

    const screenshot = await slot.screenshot();
    const decoded = decodePNG(screenshot);

    const cardBounds = findBounds(decoded, isBlue);
    expect(cardBounds).not.toBeNull();

    // Corner radius = CornerRadiusMM + min(grantedH, grantedV).  The layout crowds
    // the horizontal axis so the granted horizontal bleed is ~0.54 mm/side, while the
    // vertical axis is uncrowded at the full 3.175 mm/side.  Measured radius is
    // 2.5 + 0.5375 = 3.0375 mm ≈ 11.5 px at 96/25.4.  The slot's extreme corner
    // pixel (0,0) is outside the card image when rounded — it should NOT be blue.
    const topLeftPixel = samplePixel(decoded, 0, 0);
    expect(topLeftPixel).not.toBeNull();
    expect(isBlue(topLeftPixel!.r, topLeftPixel!.g, topLeftPixel!.b)).toBe(
      false
    );

    // A pixel inset well past the rounding zone should be inside the blue card area.
    const insetPixel = samplePixel(decoded, 80, 80);
    expect(insetPixel).not.toBeNull();
    expect(isBlue(insetPixel!.r, insetPixel!.g, insetPixel!.b)).toBe(true);
  });

  test("roundCorners off: the card's extreme corner pixel is card (not background)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithBleed(FIXTURE_BLEED_EDGE_MM),
      fixtureImageHandler(FIXTURE_BLEED_EDGE_MM),
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await ensureRoundCornersDisabled(page);

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);

    const screenshot = await slot.screenshot();
    const decoded = decodePNG(screenshot);

    // The card image's blue trim area starts at bleed*pxPerMm (~32px) from each edge.
    // With square corners, a pixel just inside the blue trim area at the top-left
    // corner should be blue (no rounding clips it).
    const trimInsetPx = FIXTURE_BLEED_EDGE_MM * FIXTURE_PX_PER_MM;
    const cornerX = Math.ceil(trimInsetPx) + 2;
    const cornerY = Math.ceil(trimInsetPx) + 2;
    const topLeftPixel = samplePixel(decoded, cornerX, cornerY);
    expect(topLeftPixel).not.toBeNull();
    expect(isBlue(topLeftPixel!.r, topLeftPixel!.g, topLeftPixel!.b)).toBe(
      true
    );
  });

  test("slot element has borderRadius when roundCorners is on", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithBleed(FIXTURE_BLEED_EDGE_MM),
      fixtureImageHandler(FIXTURE_BLEED_EDGE_MM),
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await ensureRoundCornersEnabled(page);

    const slot = page.getByTestId("page-preview-slot").first();
    await expect(slot).toBeVisible();

    const borderRadius = await slot.evaluate((el: HTMLElement) => {
      const cs = getComputedStyle(el);
      return {
        topLeft: cs.borderTopLeftRadius,
        topRight: cs.borderTopRightRadius,
        bottomLeft: cs.borderBottomLeftRadius,
        bottomRight: cs.borderBottomRightRadius,
      };
    });

    expect(borderRadius.topLeft).not.toBe("0px");
    expect(borderRadius.topRight).not.toBe("0px");
    expect(borderRadius.bottomLeft).not.toBe("0px");
    expect(borderRadius.bottomRight).not.toBe("0px");

    // The invariant: after trimming the granted bleed, the finished card corner
    // radius is exactly CornerRadiusMM.  Derive the granted bleed from the slot's
    // own rendered box rather than assuming the full configured bleed is granted.
    const CSS_PX_PER_MM = 96 / 25.4;
    const slotBoxPx = await slot.evaluate((el: HTMLElement) => {
      const cs = getComputedStyle(el);
      return { widthPx: parseFloat(cs.width), heightPx: parseFloat(cs.height) };
    });
    const slotWidthMM = slotBoxPx.widthPx / CSS_PX_PER_MM;
    const slotHeightMM = slotBoxPx.heightPx / CSS_PX_PER_MM;
    const grantedHorizontalMM = (slotWidthMM - CardWidthMM) / 2;
    const grantedVerticalMM = (slotHeightMM - CardHeightMM) / 2;
    const minGrantedMM = Math.min(grantedHorizontalMM, grantedVerticalMM);

    for (const value of Object.values(borderRadius)) {
      const radiusPx = parseFloat(value);
      const radiusMM = radiusPx / CSS_PX_PER_MM;
      const finishedRadiusMM = radiusMM - minGrantedMM;
      expect(Math.abs(finishedRadiusMM - CornerRadiusMM)).toBeLessThan(0.05);
    }
  });

  test("slot element has no borderRadius when roundCorners is off", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithBleed(FIXTURE_BLEED_EDGE_MM),
      fixtureImageHandler(FIXTURE_BLEED_EDGE_MM),
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");

    await ensureRoundCornersDisabled(page);

    const slot = page.getByTestId("page-preview-slot").first();
    await expect(slot).toBeVisible();

    const borderRadius = await slot.evaluate((el: HTMLElement) => {
      const cs = getComputedStyle(el);
      return {
        topLeft: cs.borderTopLeftRadius,
        topRight: cs.borderTopRightRadius,
        bottomLeft: cs.borderBottomLeftRadius,
        bottomRight: cs.borderBottomRightRadius,
      };
    });

    // All corners should be zero
    expect(borderRadius.topLeft).toBe("0px");
    expect(borderRadius.topRight).toBe("0px");
    expect(borderRadius.bottomLeft).toBe("0px");
    expect(borderRadius.bottomRight).toBe("0px");
  });
});
