import { expect } from "@playwright/test";

import { defaultHandlers, questionFeedConfirmSuggestion } from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Mobile funnel pass - PWA installability. Manifest/icons/theme-color are deliberately
// page-scoped to /whatsthat only (via that page's own next/head <Head>, not _document.tsx),
// so this also proves the scoping actually works under static export - a different page's
// generated HTML should carry none of this.
test.describe("/whatsthat PWA installability", () => {
  test("the manifest, theme-color, and apple-touch-icon tags are present on /whatsthat", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
      "href",
      "/whatsthat-manifest.json"
    );
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute(
      "content",
      "#ff4719"
    );
    await expect(
      page.locator('link[rel="apple-touch-icon"]')
    ).toHaveAttribute("href", "/whatsthat-icon-192.png");
  });

  test("the manifest is absent on a different page (scoping doesn't leak)", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page, "editor");

    await expect(page.locator('link[rel="manifest"]')).toHaveCount(0);
    await expect(
      page.locator('link[rel="apple-touch-icon"]')
    ).toHaveCount(0);
  });
});
