import { processSearchQuery } from "@/common/processing";
import { CardType } from "@/common/schema_types";
import { cardDocument1, cardDocument12 } from "@/common/test-constants";
import { SlotProjectMembers } from "@/common/types";

import { generateDecklist } from "./downloadDecklist";

function buildSlot(id: string, frontIdentifier: string): SlotProjectMembers {
  return {
    id,
    front: {
      query: { query: null, cardType: CardType.Card },
      selectedImage: frontIdentifier,
      selected: false,
    },
    back: null,
  };
}

describe("generateDecklist", () => {
  it("emits a bare name for a card with no resolved canonicalCard", () => {
    const decklist = generateDecklist(
      [buildSlot("slot-1", cardDocument1.identifier)],
      { [cardDocument1.identifier]: cardDocument1 }
    );
    expect(decklist).toBe(`1x ${cardDocument1.name}`);
  });

  it("suffixes the name with (SET) NUM for a card with a resolved canonicalCard", () => {
    const decklist = generateDecklist(
      [buildSlot("slot-1", cardDocument12.identifier)],
      { [cardDocument12.identifier]: cardDocument12 }
    );
    expect(decklist).toBe(
      `1x ${cardDocument12.name} (${cardDocument12.canonicalCard?.expansionCode}) ${cardDocument12.canonicalCard?.collectorNumber}`
    );
  });

  it("round-trips through processSearchQuery back to the original set + collector number", () => {
    // this is the whole point of the suffix: the plaintext decklist importer's own parser
    // already recognises "(SET) NUM" syntax, so this isn't a new format - it's reusing one
    // that already exists on the import side.
    const decklist = generateDecklist(
      [buildSlot("slot-1", cardDocument12.identifier)],
      { [cardDocument12.identifier]: cardDocument12 }
    );
    const line = decklist.replace(/^1x /, "");
    const searchQuery = processSearchQuery(line);
    expect(searchQuery.expansionCode).toBe(
      cardDocument12.canonicalCard?.expansionCode
    );
    expect(searchQuery.collectorNumber).toBe(
      cardDocument12.canonicalCard?.collectorNumber
    );
  });
});
