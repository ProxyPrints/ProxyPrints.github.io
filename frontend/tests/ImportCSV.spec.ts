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
  expectDisplaySheetSlotStates,
  importCSVOnEmptyLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page.
// DisplayPage's empty-project landing mounts the same plain ImportCSV component verbatim, inline
// inside a collapsed "Import a File or URL" accordion rather than behind the classic dropdown-
// triggered modal - see importCSVOnEmptyLanding (test-utils.ts) for the DOM difference. All 6
// tests here import into an empty project, so that's the only surface this file needs; see
// ImportXML.spec.ts's own "into a non-empty project" test for the populated-toolbar counterpart.
// Per-slot assertions are ported via expectDisplaySheetSlotStates - see that helper's own comment
// for why dropping the selectedImage/totalImages numeric checks is still a faithful port of every
// test below (each fixture card here has its own distinct name, so the name check alone already
// proves which specific candidate got selected).

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

    await importCSVOnEmptyLanding(
      page,
      `Quantity,Front
    ,my search query`
    );

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );
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

    await importCSVOnEmptyLanding(
      page,
      `Quantity,Front
    2,my search query`
    );

    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
      ]
    );
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

    await importCSVOnEmptyLanding(
      page,
      `Quantity,Front,Front ID
    ,my search query,${cardDocument3.identifier}`
    );

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument3.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );
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

    await importCSVOnEmptyLanding(
      page,
      `Quantity,Front
    ,query 1\n,t:query 6\n,b:query 5`
    );

    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument6.name },
        { slot: 3, name: cardDocument5.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
        { slot: 3, name: cardDocument2.name },
      ]
    );
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

    await importCSVOnEmptyLanding(
      page,
      `Quantity,Front,Front ID,Back,Back ID
    2,my search query,${cardDocument3.identifier},my search query,${cardDocument4.identifier}
    ,my search query`
    );

    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument3.name },
        { slot: 2, name: cardDocument3.name },
        { slot: 3, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument4.name },
        { slot: 2, name: cardDocument4.name },
        { slot: 3, name: cardDocument2.name },
      ]
    );
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

    await importCSVOnEmptyLanding(
      page,
      `Quantity, Front , Front ID
    ,my search query,${cardDocument3.identifier}`
    );

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument3.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );
  });
});
