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
  downloadXML,
  expectCardbackSlotState,
  expectCardGridSlotState,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  normaliseString,
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
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
    await expectCardGridSlotState(page, 2, "front", cardDocument2.name, 1, 1);
    await expectCardbackSlotState(page, cardDocument5.name, 1, 1);

    const [content, filename] = await downloadXML(page);

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
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
    await expectCardGridSlotState(page, 2, "front", cardDocument2.name, 1, 1);
    await expectCardGridSlotState(page, 2, "back", cardDocument6.name, 1, 1);
    await expectCardbackSlotState(page, cardDocument5.name, 1, 1);

    const [content, filename] = await downloadXML(page);

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
    await expectCardGridSlotState(page, 1, "front", cardDocument1.name, 1, 1);
    await expectCardGridSlotState(page, 2, "front", cardDocument1.name, 1, 1);
    await expectCardGridSlotState(page, 3, "front", cardDocument2.name, 1, 1);
    await expectCardGridSlotState(page, 3, "back", cardDocument1.name, 1, 1);
    await expectCardbackSlotState(page, cardDocument5.name, 1, 1);

    const [content, filename] = await downloadXML(page);

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
