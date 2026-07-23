import { S30, SelectedImageSeparator } from "@/common/constants";
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
  expectCardSlotToExist,
  importTextOnEditorLanding,
  importXML,
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

test.describe("ImportXML", () => {
  test("importing one card by XML into an empty project", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>1</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>0</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <cardback>${cardDocument3.identifier}</cardback>
      </order>`
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
          name: cardDocument3.name,
          selectedImage: 2,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing multiple instances of one card by XML into an empty project", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>2</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <cardback>${cardDocument2.identifier}</cardback>
      </order>`
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

  test("importing one specific card version by XML into an empty project", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>1</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument3.identifier}</id>
            <slots>0</slots>
            <name>${cardDocument3.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <cardback>${cardDocument2.identifier}</cardback>
      </order>`
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>3</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>0</slots>
            <name>${cardDocument1.name}</name>
            <query>query 1</query>
          </card>
          <card>
            <id>${cardDocument6.identifier}</id>
            <slots>1</slots>
            <name>${cardDocument6.name}</name>
            <query>t:query 6</query>
          </card>
          <card>
            <id>${cardDocument5.identifier}</id>
            <slots>2</slots>
            <name>${cardDocument5.name}</name>
            <query>b:query 5</query>
          </card>
        </fronts>
        <cardback>${cardDocument3.identifier}</cardback>
      </order>`
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
          name: cardDocument3.name,
          selectedImage: 2,
          totalImages: 2,
        },
        {
          slot: 2,
          name: cardDocument3.name,
          selectedImage: 2,
          totalImages: 2,
        },
        {
          slot: 3,
          name: cardDocument3.name,
          selectedImage: 2,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing a more complex XML into an empty project", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>3</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument3.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument3.name}</name>
            <query>my search query</query>
          </card>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>2</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <backs>
          <card>
            <id>${cardDocument4.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument4.name}</name>
            <query>my search query</query>
          </card>
        </backs>
        <cardback>${cardDocument2.identifier}</cardback>
      </order>`
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

  test("importing an XML with gaps into an empty project", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>4</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument3.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument3.name}</name>
            <query>my search query</query>
          </card>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>3</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <backs>
          <card>
            <id>${cardDocument4.identifier}</id>
            <slots>0,3</slots>
            <name>${cardDocument4.name}</name>
            <query>my search query</query>
          </card>
        </backs>
        <cardback>${cardDocument2.identifier}</cardback>
      </order>`
    );

    await expectCardSlotToExist(page, 1);
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
          slot: 4,
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
          name: cardDocument2.name,
          selectedImage: 1,
          totalImages: 2,
        },
        {
          slot: 4,
          name: cardDocument4.name,
          selectedImage: 4,
          totalImages: 4,
        },
      ]
    );
    await expectCardSlotToExist(page, 3);
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("importing a more complex XML into a non-empty project", async ({
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

    await importTextOnEditorLanding(
      page,
      `1x my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 1,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 4,
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

    // import a few more cards
    await importXML(
      page,
      `<order>
        <details>
          <quantity>3</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument3.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument3.name}</name>
            <query>my search query</query>
          </card>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>2</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <backs>
          <card>
            <id>${cardDocument4.identifier}</id>
            <slots>0,1</slots>
            <name>${cardDocument4.name}</name>
            <query>my search query</query>
          </card>
        </backs>
        <cardback>${cardDocument3.identifier}</cardback>
      </order>`
    );

    await expectCardGridSlotStates(
      page,
      [
        {
          slot: 2,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 4,
        },
        {
          slot: 3,
          name: cardDocument3.name,
          selectedImage: 3,
          totalImages: 4,
        },
        {
          slot: 4,
          name: cardDocument1.name,
          selectedImage: 1,
          totalImages: 4,
        },
      ],
      [
        {
          slot: 2,
          name: cardDocument4.name,
          selectedImage: 4,
          totalImages: 4,
        },
        {
          slot: 3,
          name: cardDocument4.name,
          selectedImage: 4,
          totalImages: 4,
        },
        {
          slot: 4,
          name: cardDocument3.name,
          selectedImage: 2,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);
  });

  test("import an XML and use its cardback", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>1</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>0</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <cardback>${cardDocument3.identifier}</cardback>
      </order>`,
      true
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
          name: cardDocument3.name, // the cardback specified in XML
          selectedImage: 2,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2); // the project cardback should not have changed
  });

  test("import an XML and use the project cardback", async ({
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

    await expectCardbackSlotState(page, cardDocument2.name, 1, 2);

    await importXML(
      page,
      `<order>
        <details>
          <quantity>1</quantity>
          <bracket>18</bracket>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${cardDocument1.identifier}</id>
            <slots>0</slots>
            <name>${cardDocument1.name}</name>
            <query>my search query</query>
          </card>
        </fronts>
        <cardback>${cardDocument3.identifier}</cardback>
      </order>`,
      false
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
          name: cardDocument2.name, // the cardback configured for the project
          selectedImage: 1,
          totalImages: 2,
        },
      ]
    );
    await expectCardbackSlotState(page, cardDocument2.name, 1, 2); // cardback should not have changed
  });
});
