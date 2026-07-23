import { expect } from "@playwright/test";

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
  importText,
  importXML,
  loadPageWithDefaultBackend,
} from "./test-utils";

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

    await importText(
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

  // Foreign-order resilience Phase 1 follow-up (issue #324, owner-observed 2026-07-23): a BRAND
  // NEW project (no cardback selected yet - here because the mocked catalog has zero indexed
  // cardbacks at all, same as OrphanRendering.spec.ts's own repro) previously left the "Common
  // Cardback" panel (CommonCardback.tsx, the classic editor's right panel) showing "Card not
  // found" forever after an XML import, right next to a perfectly-rendered orphan back-face slot
  // tile - even though the import's own <cardback> (an orphan Drive file ID here, but this fix
  // applies identically to a real catalog cardback) was sitting right there unused. See
  // ImportXML.tsx's own parseXMLFile comment for the fix (state.project.cardback is now
  // initialised from the import when nothing was selected before it) and its own gate against
  // regressing the "should not have changed" tests above (an EXISTING project cardback is never
  // touched by a later import).
  test("importing an XML into a brand new project with no cardback yet initialises the Common Cardback panel from the file's own <cardback> - even an orphan", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers);
    await loadPageWithDefaultBackend(page);

    const orphanFrontId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
    const orphanBackId = "1LrVX0pUcye9n_0RtaDNVl2xPrQgn7CYf";

    await importXML(
      page,
      `<order>
        <details>
          <quantity>1</quantity>
          <stock>${S30}</stock>
          <foil>false</foil>
        </details>
        <fronts>
          <card>
            <id>${orphanFrontId}</id>
            <sourceType>google_drive</sourceType>
            <slots>0</slots>
            <name>Kharn.png</name>
            <query>kharn</query>
          </card>
        </fronts>
        <cardback>${orphanBackId}</cardback>
      </order>`
    );

    const commonCardback = page.getByTestId("common-cardback");
    await expect(commonCardback.getByTestId("orphan-badge")).toBeVisible();
    await expect(commonCardback).not.toContainText("Card Not Found");
  });
});
