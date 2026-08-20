import { CardDocument } from "@/common/types";

import { computePresentLanguages } from "./GridSelectorFilters";

function card(language: string): CardDocument {
  return { language } as CardDocument;
}

describe("computePresentLanguages", () => {
  test("returns an empty array when there are no card documents", () => {
    expect(computePresentLanguages({})).toEqual([]);
  });

  test("ignores identifiers whose card document hasn't loaded yet", () => {
    expect(
      computePresentLanguages({ id1: undefined, id2: card("EN") })
    ).toEqual(["EN"]);
  });

  test("returns every distinct language present across the card documents", () => {
    const result = computePresentLanguages({
      id1: card("EN"),
      id2: card("FR"),
      id3: card("JA"),
    });
    expect(result).toHaveLength(3);
    expect(result).toEqual(expect.arrayContaining(["EN", "FR", "JA"]));
  });

  test("deduplicates cards that share the same language", () => {
    const result = computePresentLanguages({
      id1: card("EN"),
      id2: card("EN"),
      id3: card("FR"),
    });
    expect(result).toHaveLength(2);
    expect(result).toEqual(expect.arrayContaining(["EN", "FR"]));
  });
});
