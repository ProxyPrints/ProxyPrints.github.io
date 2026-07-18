import { Card } from "@/common/constants";
import { SlotProjectMembers } from "@/common/types";

import { paginateSlotsForDisplay } from "./displayPagination";

const makeMember = (id: string, selectedImage?: string): SlotProjectMembers => ({
  id,
  front: {
    query: { cardType: Card, query: id },
    selectedImage,
    selected: false,
  },
  back: null,
});

describe("paginateSlotsForDisplay", () => {
  it("chunks slots into pages of the given size, preserving original slot index", () => {
    const members = [
      makeMember("a"),
      makeMember("b"),
      makeMember("c"),
      makeMember("d"),
      makeMember("e"),
    ];
    const pages = paginateSlotsForDisplay(members, 2);
    expect(pages).toHaveLength(3);
    expect(pages[0].map((entry) => entry.slot)).toEqual([0, 1]);
    expect(pages[1].map((entry) => entry.slot)).toEqual([2, 3]);
    expect(pages[2].map((entry) => entry.slot)).toEqual([4]);
  });

  it("preserves each entry's member reference", () => {
    const member = makeMember("only", "image-1");
    const pages = paginateSlotsForDisplay([member], 8);
    expect(pages[0][0].member).toBe(member);
  });

  it("returns no pages for an empty project", () => {
    expect(paginateSlotsForDisplay([], 8)).toEqual([]);
  });

  it("returns no pages when cardsPerPage is zero or negative", () => {
    const members = [makeMember("a")];
    expect(paginateSlotsForDisplay(members, 0)).toEqual([]);
    expect(paginateSlotsForDisplay(members, -1)).toEqual([]);
  });
});
