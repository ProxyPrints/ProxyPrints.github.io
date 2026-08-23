import { CardType, SlotProjectMembers } from "@/common/types";
import { countSiblingSlotsForImage } from "@/features/card/applySiblingImage";

function member(
  id: string,
  frontQuery: string | undefined,
  frontImage: string | undefined
): SlotProjectMembers {
  return {
    id,
    front: {
      query: { query: frontQuery ?? null, cardType: "CARD" as CardType },
      selectedImage: frontImage,
      selected: false,
    },
    back: null,
  };
}

describe("countSiblingSlotsForImage", () => {
  test("returns all zeros when the source slot has no selected image", () => {
    const members = [
      member("t-0", "Lightning Bolt", undefined),
      member("t-1", "Lightning Bolt", undefined),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 0,
      skippedDifferent: 0,
    });
  });

  test("counts other slots sharing the same query with no image yet as toUpdate", () => {
    const members = [
      member("t-0", "Lightning Bolt", "bolt-art-a"),
      member("t-1", "Lightning Bolt", undefined),
      member("t-2", "Lightning Bolt", undefined),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 2,
      skippedDifferent: 0,
    });
  });

  test("slots holding a different card (different query) are not counted at all", () => {
    const members = [
      member("t-0", "Lightning Bolt", "bolt-art-a"),
      member("t-1", "Counterspell", undefined),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 0,
      skippedDifferent: 0,
    });
  });

  test("a sibling that already has a DIFFERENT image deliberately chosen is counted as skipped, not toUpdate", () => {
    const members = [
      member("t-0", "Lightning Bolt", "bolt-art-a"),
      member("t-1", "Lightning Bolt", "bolt-art-b"),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 0,
      skippedDifferent: 1,
    });
  });

  test("a sibling that already matches the source image counts toward neither bucket", () => {
    const members = [
      member("t-0", "Lightning Bolt", "bolt-art-a"),
      member("t-1", "Lightning Bolt", "bolt-art-a"),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 0,
      skippedDifferent: 0,
    });
  });

  test("mixes toUpdate and skippedDifferent siblings correctly", () => {
    const members = [
      member("t-0", "Lightning Bolt", "bolt-art-a"),
      member("t-1", "Lightning Bolt", undefined),
      member("t-2", "Lightning Bolt", "bolt-art-b"),
      member("t-3", "Counterspell", undefined),
    ];
    expect(countSiblingSlotsForImage(members, "front", 0)).toStrictEqual({
      toUpdate: 1,
      skippedDifferent: 1,
    });
  });
});
