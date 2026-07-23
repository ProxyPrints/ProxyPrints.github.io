import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
  cardDocument4,
  cardDocument5,
  cardDocument6,
} from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsSixResults,
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsFourResults,
  searchResultsOneResult,
  searchResultsSixResults,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectCardbackSlotState,
  expectCardGridSlotStates,
  importCSV,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`); the classic grid `ProjectEditor` this file's own setup
// depends on (via testids/interaction patterns like `front-slot`/`back-slot`/`common-cardback`/
// the "Add Cards" right-panel dropdown/the classic "Print!" tab, or a component with no rendered
// equivalent on the new page yet - see issue #272's own tracked parity gaps) is fully unrouted,
// not just delisted from the nav. Skipped here rather than deleted (component files themselves
// are untouched, per this swap's own scope) or silently left red - porting this coverage to
// DisplayPage's DOM is real, non-mechanical work tracked against #272, not done as part of the
// route swap itself (the owner's directive was to proceed with the swap regardless of the
// checklist's open items).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Proposal H switchover (2026-07-23): tests classic /editor-only UI, now unrouted - see issue #272"
  );
});

test.describe("ImportCSV", () => {
  test("importing one card by CSV into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity,Front
    ,my search query`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing multiple instances of one card by CSV into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity,Front
    2,my search query`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        },
        {
          slot: 2,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
        {
          slot: 2,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing one specific card version by CSV into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity,Front,Front ID
    ,my search query,${cardDocument3.identifier}`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 3,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing one card of each type into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksTwoOtherResults,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity,Front
    ,query 1\n,t:query 6\n,b:query 5`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 1,
        },
        {
          slot: 2,
          name: cardDocument6.name,
          selectedImage: 1,
          totalImages: 1,
        },
        {
          slot: 3,
          name: cardDocument5.name,
          selectedImage: 1,
          totalImages: 1,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
        {
          slot: 2,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
        {
          slot: 3,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing a more complex CSV into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsFourResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity,Front,Front ID,Back,Back ID
    2,my search query,${cardDocument3.identifier},my search query,${cardDocument4.identifier}
    ,my search query`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 4,
        },
        {
          slot: 2,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 4,
        },
        {
          slot: 3,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 4,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument4.name,
          selectedImage: 4,
          totalImages: 4,
        },
        {
          slot: 2,
          name: cardDocument4.name,
          selectedImage: 4,
          totalImages: 4,
        },
        {
          slot: 3,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("CSV header has spaces", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importCSV(
      page,
      `Quantity, Front , Front ID
    ,my search query,${cardDocument3.identifier}`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 3,
        },
      ],
      [
        {
          slot: 1,
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });
});
