import { expect } from "@playwright/test";

import { FaceSeparator, S30 } from "@/common/constants";
import { SourceType } from "@/common/schema_types";
import {
  cardDocument1,
  cardDocument2,
  cardDocument5,
  cardDocument6,
} from "@/common/test-constants";
import {
  cardbacksOneOtherResult,
  cardDocumentsSixResults,
  defaultHandlers,
  searchResultsSixResults,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  downloadXMLFromDisplayToolbar,
  expectDisplaySheetSlotStates,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  normaliseString,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// downloadXML itself is unchanged (ExportXML.tsx/downloadXML.test.ts already cover its own
// internals); only the trigger changed - see downloadXMLFromDisplayToolbar's own module comment
// (test-utils.ts). Per-slot setup assertions ported via expectDisplaySheetSlotStates - see that
// helper's own comment for why dropping the selectedImage/totalImages numeric checks doesn't
// weaken the name check every test here actually depends on. The classic grid's standalone
// "common cardback" preview tile (`expectCardbackSlotState`) has no equivalent on this page - not
// ported; the cardback IS part of the exported XML (unlike the decklist export), but that's
// already asserted against the downloaded file content itself below, independent of any preview
// widget.

test.describe("ExportXML", () => {
  test("the XML representation of a simple project with no custom backs", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksOneOtherResult,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(page, "query 1\nquery 2");
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument2.name },
      ],
      []
    );

    const [content, filename] = await downloadXMLFromDisplayToolbar(page);

    expect(normaliseString(content)).toBe(
      normaliseString(
        `<order version="2.0">
          <details>
            <quantity>2</quantity>
            <stock>${S30}</stock>
            <foil>false</foil>
          </details>
          <fronts>
            <card>
                <id>${cardDocument1.identifier}</id>
                <sourceType>${SourceType.GoogleDrive}</sourceType>
                <slots>0</slots>
                <name>${cardDocument1.name}.${cardDocument1.extension}</name>
                <query>card one</query>
            </card>
            <card>
                <id>${cardDocument2.identifier}</id>
                <sourceType>${SourceType.GoogleDrive}</sourceType>
                <slots>1</slots>
                <name>${cardDocument2.name}.${cardDocument2.extension}</name>
                <query>card 2</query>
              </card>
          </fronts>
          <cardback>${cardDocument5.identifier}</cardback>
        </order>`
      )
    );
    expect(filename).toBe("cards.xml");
  });

  test("the XML representation of a simple project with a custom back for one card", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksOneOtherResult,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `query 1\nquery 2${FaceSeparator}t:query 6`
    );
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument2.name },
      ],
      [{ slot: 2, name: cardDocument6.name }]
    );

    const [content, filename] = await downloadXMLFromDisplayToolbar(page);

    expect(normaliseString(content)).toBe(
      normaliseString(
        `<order version="2.0">
          <details>
            <quantity>2</quantity>
            <stock>${S30}</stock>
            <foil>false</foil>
          </details>
          <fronts>
            <card>
              <id>${cardDocument1.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>0</slots>
              <name>${cardDocument1.name}.${cardDocument1.extension}</name>
              <query>${cardDocument1.searchq}</query>
            </card>
            <card>
              <id>${cardDocument2.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>1</slots>
              <name>${cardDocument2.name}.${cardDocument2.extension}</name>
              <query>${cardDocument2.searchq}</query>
              </card>
          </fronts>
          <backs>
            <card>
              <id>${cardDocument6.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>1</slots>
              <name>${cardDocument6.name}.${cardDocument6.extension}</name>
              <query>t:${cardDocument6.searchq}</query>
            </card>
          </backs>
          <cardback>${cardDocument5.identifier}</cardback>
        </order>`
      )
    );
    expect(filename).toBe("cards.xml");
  });

  test("the XML representation of a simple project with multiple instances of a card", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksOneOtherResult,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `2x query 1\nquery 2${FaceSeparator}query 1`
    );
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument1.name },
        { slot: 3, name: cardDocument2.name },
      ],
      [{ slot: 3, name: cardDocument1.name }]
    );

    const [content, filename] = await downloadXMLFromDisplayToolbar(page);

    expect(normaliseString(content)).toBe(
      normaliseString(
        `<order version="2.0">
          <details>
            <quantity>3</quantity>
            <stock>${S30}</stock>
            <foil>false</foil>
          </details>
          <fronts>
            <card>
              <id>${cardDocument1.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>0,1</slots>
              <name>${cardDocument1.name}.${cardDocument1.extension}</name>
              <query>card one</query>
            </card>
            <card>
              <id>${cardDocument2.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>2</slots>
              <name>${cardDocument2.name}.${cardDocument2.extension}</name>
              <query>card 2</query>
              </card>
          </fronts>
          <backs>
            <card>
              <id>${cardDocument1.identifier}</id>
              <sourceType>${SourceType.GoogleDrive}</sourceType>
              <slots>2</slots>
              <name>${cardDocument1.name}.${cardDocument1.extension}</name>
              <query>card one</query>
            </card>
          </backs>
          <cardback>${cardDocument5.identifier}</cardback>
        </order>`
      )
    );
    expect(filename).toEqual("cards.xml");
  });
});
