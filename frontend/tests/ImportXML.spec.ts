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
  expectDisplaySheetSlotStates,
  expectDisplaySheetSlotToExist,
  importTextOnEditorLanding,
  importXMLFromToolbar,
  importXMLOnEmptyLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page.
// 8 of these 9 tests import into an EMPTY project - DisplayPage's empty-project landing mounts
// the same plain ImportXML component verbatim, inline inside a collapsed "Import a File or URL"
// accordion (importXMLOnEmptyLanding, test-utils.ts). The remaining test ("into a non-empty
// project") uses the populated toolbar's own "Add Cards" dropdown instead - the SAME classic
// Import.tsx dropdown, unforked, just mounted in a different container (importXMLFromToolbar).
// Per-slot assertions are ported via expectDisplaySheetSlotStates - see that helper's own comment
// for why dropping the selectedImage/totalImages numeric checks is still a faithful port here
// (every fixture card has its own distinct name).
//
// The classic grid's standalone "common cardback" preview tile (`expectCardbackSlotState`, this
// file's own pre-port version called it both before AND after every import) has no landing-page
// equivalent at all (there's no sheet, hence no cardback slot, until a project actually exists) -
// dropped rather than faked; its post-import state is already covered by the `backs` array of the
// relevant `expectDisplaySheetSlotStates` call in every test below that touches the project
// cardback.

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

    await importXMLOnEmptyLanding(
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

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument3.name }]
    );
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

    await importXMLOnEmptyLanding(
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

    await importXMLOnEmptyLanding(
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

    await importXMLOnEmptyLanding(
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

    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument6.name },
        { slot: 3, name: cardDocument5.name },
      ],
      [
        { slot: 1, name: cardDocument3.name },
        { slot: 2, name: cardDocument3.name },
        { slot: 3, name: cardDocument3.name },
      ]
    );
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

    await importXMLOnEmptyLanding(
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

    await importXMLOnEmptyLanding(
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

    await expectDisplaySheetSlotToExist(page, 1);
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument3.name },
        { slot: 2, name: cardDocument3.name },
        { slot: 4, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument4.name },
        { slot: 2, name: cardDocument2.name },
        { slot: 4, name: cardDocument4.name },
      ]
    );
    await expectDisplaySheetSlotToExist(page, 3);
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
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );

    // import a few more cards via the populated toolbar's "Add Cards" dropdown
    await importXMLFromToolbar(
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

    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 2, name: cardDocument3.name },
        { slot: 3, name: cardDocument3.name },
        { slot: 4, name: cardDocument1.name },
      ],
      [
        { slot: 2, name: cardDocument4.name },
        { slot: 3, name: cardDocument4.name },
        { slot: 4, name: cardDocument3.name },
      ]
    );
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

    await importXMLOnEmptyLanding(
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

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument3.name }] // the cardback specified in XML
    );
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

    await importXMLOnEmptyLanding(
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

    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }] // the cardback configured for the project
    );
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
