import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { cardDocument8, localBackendURL } from "@/common/test-constants";
import {
  cardDocumentsWithCanonicalCards,
  cardDocumentsWithResolvedPrintingMatch,
  defaultHandlers,
  searchResultsResolvedPrintingMatch,
  searchResultsUnresolvedCanonicalImport,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

const REFERENCE_CANDIDATE = {
  identifier: "xyz-001-printing",
  canonicalId: "canonical-xyz-001",
  expansionCode: "xyz",
  expansionName: "XYZ Set",
  collectorNumber: "001",
  artist: "Some Artist",
  smallThumbnailUrl: "https://example.com/small-ref.png",
  mediumThumbnailUrl: "https://example.com/medium-ref.png",
  fullArt: false,
  isBorderless: false,
  frame: "2015",
  borderColor: "black",
  isShowcase: false,
  isExtendedArt: false,
  isEtched: false,
};

test.describe("Level 0 - deckbuilder in-context printing confirmation", () => {
  test("shows the affordance for a slot imported with a canonical printing ID that isn't yet confirmed", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");

    await expect(
      page.getByTestId(`deckbuilder-confirm-${cardDocument8.identifier}`)
    ).toBeVisible();
  });

  test("does not show the affordance for an already-resolved printing match", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithResolvedPrintingMatch,
      sourceDocumentsOneResult,
      searchResultsResolvedPrintingMatch,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 Lightning Bolt (2ED) 162");

    await expect(
      page.getByTestId("front-slot0").getByTestId("deckbuilder-confirm-badge")
    ).toHaveCount(0);
  });

  test("hover reveals the compare pin and enables Y/N; YES submits a positive vote with voteSurface=deckbuilder", async ({
    page,
    network,
  }) => {
    let submittedBody: Record<string, unknown> = {};
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        submittedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            resolvedPrinting: REFERENCE_CANDIDATE,
            isNoMatch: false,
            voteTally: [],
          },
          { status: 200 }
        );
      }),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");

    const slot = page.getByTestId("front-slot0");
    const yesButton = slot.getByTestId("deckbuilder-confirm-yes");
    await expect(yesButton).toBeDisabled();

    await slot.getByTestId("deckbuilder-confirm-badge").hover();
    await expect(slot.getByTestId("deckbuilder-compare-pin")).toBeVisible();
    await expect(yesButton).toBeEnabled();

    await yesButton.click();

    await expect
      .poll(() => submittedBody.printingIdentifier)
      .toBe(REFERENCE_CANDIDATE.identifier);
    expect(submittedBody.voteSurface).toBe("deckbuilder");
    await expect(
      slot.getByTestId(`deckbuilder-confirm-${cardDocument8.identifier}`)
    ).toHaveCount(0);
  });

  test("NO opens the existing grid selector for that slot without casting a printing vote", async ({
    page,
    network,
  }) => {
    let printingTagSubmitted = false;
    network.use(
      cardDocumentsWithCanonicalCards,
      sourceDocumentsOneResult,
      searchResultsUnresolvedCanonicalImport,
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), () => {
        printingTagSubmitted = true;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        );
      }),
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importText(page, "1 card 8 (xyz) 001");

    const slot = page.getByTestId("front-slot0");
    await slot.getByTestId("deckbuilder-confirm-badge").hover();
    const noButton = slot.getByTestId("deckbuilder-confirm-no");
    await expect(noButton).toBeEnabled();
    await noButton.click();

    await expect(page.getByTestId("front-slot0-grid-selector")).toBeVisible();
    expect(printingTagSubmitted).toBe(false);
  });
});
