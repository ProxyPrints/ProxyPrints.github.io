import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsNoResults,
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsNoResults,
  searchResultsOneResult,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

/**
 * Editor-completion package (E18/E20, X18) - the /display sheet's dark empty/loading/failed
 * states, and the no-white invariant they all share. Every assertion here reads real computed
 * styles (`getComputedStyle`), not class names or inline-style source text - the same discipline
 * DisplayPage.spec.ts's own requested-printing-badge color test already follows, since a stray
 * cascade rule could otherwise silently paint white even where the source sets a dark value.
 */

function parseRGB(color: string): [number, number, number] {
  const parts = color.match(/\d+(\.\d+)?/g);
  if (parts == null || parts.length < 3) {
    throw new Error(`unparsable color: ${color}`);
  }
  return [Number(parts[0]), Number(parts[1]), Number(parts[2])];
}

function expectNotWhite(rgb: [number, number, number]) {
  const [r, g, b] = rgb;
  expect(r === 255 && g === 255 && b === 255).toBe(false);
}

test.describe("DisplayPage sheet slot states (editor-completion, E18/E20)", () => {
  test("a filled slot's own dark anti-flash background is never white, on both the slot and its <img>", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("my search query");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();

    const slot = page.getByTestId("page-preview-slot").first();
    const img = slot.locator("img");
    await expect(img).toHaveAttribute("alt", cardDocument1.name);

    const slotBg = await slot.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    const imgBg = await img.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    expectNotWhite(parseRGB(slotBg));
    expectNotWhite(parseRGB(imgBg));
  });

  test("a slot still awaiting search results renders the dark loading state, never white", async ({
    page,
    network,
  }) => {
    // A genuinely never-resolving request (same precedent as CardImageStates.spec.ts's own
    // "never resolves" test) keeps searchResultsSlice's status at "loading" indefinitely, so the
    // slot's own loadState="loading" branch is deterministically observable rather than racing a
    // real fetch that might settle before the assertion runs.
    network.use(
      http.post(
        /\/3\/editorSearch\/$/,
        () => new Promise<never>(() => undefined)
      ),
      cardDocumentsOneResult,
      sourceDocumentsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("my search query");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();

    const slot = page.getByTestId("page-preview-slot").first();
    await expect(slot.locator("img")).toHaveCount(0);
    const loadingBar = slot.getByTestId("page-preview-slot-loading");
    await expect(loadingBar).toBeVisible();

    const slotBg = await slot.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    expectNotWhite(parseRGB(slotBg));
    const trackBg = await loadingBar.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    expectNotWhite(parseRGB(trackBg));
  });

  test("a slot with genuinely no candidate images renders the dark failed state (muted ✗ + a deterministic 'Find this card' link), never white", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsNoResults,
      sourceDocumentsOneResult,
      searchResultsNoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("an unfindable card");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();

    const slot = page.getByTestId("page-preview-slot").first();
    await expect(slot.locator("img")).toHaveCount(0);
    await expect(slot.getByTestId("page-preview-slot-failed")).toBeVisible();
    await expect(slot.getByTestId("page-preview-slot-failed")).toContainText(
      "no art"
    );

    // E17 v1 - the deterministic, zero-backend Scryfall reference link (scryfallReference.ts):
    // a name-only query (no expansionCode/collectorNumber) falls back to a plain name search.
    const findLink = slot.getByTestId("page-preview-find-card-link");
    await expect(findLink).toBeVisible();
    await expect(findLink).toHaveAttribute(
      "href",
      "https://scryfall.com/search?q=an%20unfindable%20card"
    );

    const slotBg = await slot.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    expectNotWhite(parseRGB(slotBg));
  });

  test("the always-visible Select Version empty state also offers the directed-help Scryfall link (E17's other surface)", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsNoResults,
      sourceDocumentsOneResult,
      searchResultsNoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "display");
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("an unfindable card");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-page")).toBeVisible();
    await page.getByTestId("page-preview-slot").first().click();

    const link = page.getByTestId("display-select-version-find-card-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute(
      "href",
      "https://scryfall.com/search?q=an%20unfindable%20card"
    );
  });
});
