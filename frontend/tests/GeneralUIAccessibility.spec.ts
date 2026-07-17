import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

test.describe("Card slot controls - accessibility", () => {
  test("the more-options button has an accessible name", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const moreOptionsButton = page
      .getByTestId("front-slot0")
      .getByTestId("more-select-options");
    await expect(moreOptionsButton).toBeVisible();
    await expect(moreOptionsButton).toHaveAccessibleName("More options");
  });

  test("the select/remove buttons meet a comfortable touch-target size and have a visible focus style", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const selectButton = page
      .getByTestId("front-slot0")
      .locator(".card-select");
    const box = await selectButton.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(40);
    expect(box!.height).toBeGreaterThanOrEqual(40);

    // A prior mouse click (e.g. inside importText's flow) sets Chromium's input modality to
    // "mouse", under which a plain .focus() call does not match :focus-visible. Pressing Tab
    // first re-establishes keyboard modality, matching how a real keyboard user would land here.
    await page.keyboard.press("Tab");
    await selectButton.focus();
    const outlineStyle = await selectButton.evaluate(
      (el) => getComputedStyle(el).outlineStyle
    );
    expect(outlineStyle).not.toBe("none");
  });
});

test.describe("Editor - mobile layout", () => {
  test("at a mobile viewport, the settings panel stacks below the card grid instead of splitting the screen 50/50", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const leftPanel = page.getByTestId("left-panel");
    const rightPanel = page.getByTestId("right-panel");
    const leftBox = await leftPanel.boundingBox();
    const rightBox = await rightPanel.boundingBox();
    expect(leftBox).not.toBeNull();
    expect(rightBox).not.toBeNull();

    // Stacked (not side-by-side) means both panels span (close to) the full viewport width,
    // rather than splitting it in half.
    expect(leftBox!.width).toBeGreaterThan(350);
    expect(rightBox!.width).toBeGreaterThan(350);
  });

  test("at desktop width, the settings panel still sits beside the card grid (unaffected by the mobile change)", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    // default chromium project viewport (800x600) is above the md breakpoint
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");

    const leftPanel = page.getByTestId("left-panel");
    const rightPanel = page.getByTestId("right-panel");
    const leftBox = await leftPanel.boundingBox();
    const rightBox = await rightPanel.boundingBox();
    expect(leftBox).not.toBeNull();
    expect(rightBox).not.toBeNull();
    // Side-by-side means roughly the same vertical position and non-overlapping x-ranges.
    expect(Math.abs(leftBox!.y - rightBox!.y)).toBeLessThan(5);
    expect(leftBox!.x + leftBox!.width).toBeLessThanOrEqual(rightBox!.x + 1);
  });
});

test.describe("Console warning regressions", () => {
  test("the home page renders with none of the previously-observed console warnings", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "warning" || msg.type() === "error") {
        warnings.push(msg.text());
      }
    });

    await loadPageWithDefaultBackend(page, "");
    await page.waitForTimeout(1500);

    const flagged = [
      "heightDelta",
      "imageIsLoading",
      "showDetailedViewOnClick",
      "SSRProvider",
      "onLoadingComplete",
    ];
    for (const term of flagged) {
      expect(
        warnings.some((warning) => warning.includes(term)),
        `expected no console warning mentioning "${term}", saw: ${JSON.stringify(
          warnings.filter((w) => w.includes(term))
        )}`
      ).toBe(false);
    }
  });

  test("the editor page renders with none of the previously-observed console warnings", async ({
    page,
    network,
  }) => {
    network.use(...threeCardHandlers);
    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "warning" || msg.type() === "error") {
        warnings.push(msg.text());
      }
    });

    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.waitForTimeout(1500);

    const flagged = [
      "heightDelta",
      "imageIsLoading",
      "showDetailedViewOnClick",
      "SSRProvider",
      "onLoadingComplete",
    ];
    for (const term of flagged) {
      expect(
        warnings.some((warning) => warning.includes(term)),
        `expected no console warning mentioning "${term}", saw: ${JSON.stringify(
          warnings.filter((w) => w.includes(term))
        )}`
      ).toBe(false);
    }
  });
});

test.describe("About page", () => {
  test("the contributors image has meaningful alt text", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "about");

    await expect(page.getByAltText("Project contributors")).toBeVisible();
  });
});

test.describe("Home page logo - LCP hint", () => {
  test("the first animated logo card image is marked as a high fetch-priority image", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "");

    // the arrow decoration image renders before the animated card images in DOM order, so
    // it's excluded here rather than relying on .first() over every <img> in the container
    const firstLogoCardImage = page
      .getByTestId("dynamic-logo")
      .locator('img:not([alt="logo-arrow"])')
      .first();
    await expect(firstLogoCardImage).toBeVisible();
    await expect(firstLogoCardImage).toHaveAttribute("fetchpriority", "high");
  });
});
