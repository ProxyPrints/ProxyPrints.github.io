import { expect } from "@playwright/test";

import { FaceSeparator } from "@/common/constants";
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
  downloadDecklistFromDisplayToolbar,
  expectDisplaySheetSlotStates,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  normaliseString,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page -
// downloadDecklist itself is unchanged (ExportDecklist.tsx/ExportImages.test.tsx already cover
// its own internals); only the trigger changed - see downloadDecklistFromDisplayToolbar's own
// module comment (test-utils.ts). Per-slot setup assertions ported via
// expectDisplaySheetSlotStates - see that helper's own comment for why dropping the
// selectedImage/totalImages numeric checks doesn't weaken the name check every test here actually
// depends on. The classic grid's standalone "common cardback" preview tile
// (`expectCardbackSlotState`) has no equivalent on this page and isn't part of what a decklist
// export even reads (decklists never include the cardback - each test's own comment says so) - not
// ported.

test.describe("ExportDecklist", () => {
  test("the decklist representation of a simple project with no custom backs", async ({
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

    await importTextOnEditorLanding(page, "query 1\nquery 2\nt:query 5");
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument2.name },
      ],
      []
    );

    const [content, filename] = await downloadDecklistFromDisplayToolbar(page);

    // note: tokens are not included in decklists
    expect(normaliseString(content)).toBe(
      normaliseString(
        `1x ${cardDocument1.name}
            1x ${cardDocument2.name}`
      )
    );
    expect(filename).toBe("decklist.txt");
  });

  test("the decklist representation of a simple project with a custom back for one card", async ({
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

    const [content, filename] = await downloadDecklistFromDisplayToolbar(page);

    // note: the custom cardback is not included here because only cards are included in decklists
    expect(normaliseString(content)).toBe(
      normaliseString(
        `1x ${cardDocument1.name}
            1x ${cardDocument2.name}`
      )
    );
    expect(filename).toBe("decklist.txt");
  });

  test("the decklist representation of a simple project with multiple instances of a card", async ({
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

    const [content, filename] = await downloadDecklistFromDisplayToolbar(page);

    expect(normaliseString(content)).toBe(
      normaliseString(
        `2x ${cardDocument1.name}
            1x ${cardDocument2.name}${FaceSeparator}${cardDocument1.name}`
      )
    );
    expect(filename).toBe("decklist.txt");
  });
});
