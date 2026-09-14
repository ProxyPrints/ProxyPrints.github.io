import { expect } from "@playwright/test";

import { localBackendURL } from "@/common/test-constants";
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

/**
 * Cut-guide shape rendering - browser-level verification that the three
 * CutLineShape values (perimeter, cornerMarks, both) produce the expected
 * number of painted guide segments on the real page preview. Style-string
 * assertions can't catch this: the guide's outline/background is invisible
 * to the accessibility tree and only observable via screenshot geometry.
 *
 * The sub-pixel stroke floor (Defect 1) ensures each guide element is at
 * least 1 device pixel wide after the page's CSS transform - without it,
 * zero-width strokes vanish at certain zoom levels.
 */
test.describe("Cut guide rendering - segment counts by shape", () => {
  test.describe.configure({ timeout: 60_000 });

  test("perimeter shape: exactly 1 guide segment visible", async ({
    page,
    network,
  }) => {
    network.use(...singleCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await expandRailSection(page, "cut-lines-guides");
    await page.getByTestId("display-cut-line-shape").selectOption("perimeter");

    const slot = page.getByTestId("page-preview-slot").first();
    const guides = slot.getByTestId("page-preview-cut-line");
    await expect(guides).toBeVisible();

    const count = await guides.count();
    expect(count).toBe(1);
  });

  test("cornerMarks shape: exactly 8 guide segments visible (2 per corner)", async ({
    page,
    network,
  }) => {
    network.use(...singleCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await expandRailSection(page, "cut-lines-guides");
    await page
      .getByTestId("display-cut-line-shape")
      .selectOption("cornerMarks");

    const slot = page.getByTestId("page-preview-slot").first();
    const guides = slot.getByTestId("page-preview-cut-line");
    await expect(guides.first()).toBeVisible();

    const count = await guides.count();
    expect(count).toBe(8);
  });

  test("both shape: exactly 9 guide segments visible (1 perimeter + 8 corner marks)", async ({
    page,
    network,
  }) => {
    network.use(...singleCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1x my search query");

    await expandRailSection(page, "cut-lines-guides");
    await page.getByTestId("display-cut-line-shape").selectOption("both");

    const slot = page.getByTestId("page-preview-slot").first();
    const guides = slot.getByTestId("page-preview-cut-line");
    await expect(guides.first()).toBeVisible();

    const count = await guides.count();
    expect(count).toBe(9);
  });

  test("shape switcher: changing from perimeter to cornerMarks replaces segments", async ({
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
