import { cardDocument1, cardDocument2 } from "@/common/test-constants";
import { CardType, SlotProjectMembers } from "@/common/types";
import {
  countBackFacesAffectedByApplyAll,
  resolveCustomBackSlotThumbnails,
} from "@/features/card/cardbackApply";

function member(
  id: string,
  frontImage: string | undefined,
  backImage: string | undefined
): SlotProjectMembers {
  return {
    id,
    front:
      frontImage != null
        ? {
            query: { query: null, cardType: "CARD" as CardType },
            selectedImage: frontImage,
            selected: false,
          }
        : null,
    back:
      backImage != null
        ? {
            query: { query: null, cardType: "CARDBACK" as CardType },
            selectedImage: backImage,
            selected: false,
          }
        : null,
  };
}

describe("resolveCustomBackSlotThumbnails (OWNER AMENDMENT 2/OQ-B)", () => {
  test("returns nothing when there is no project cardback to be 'different' from", () => {
    const members = [member("t-0", cardDocument1.identifier, "some-back")];
    expect(
      resolveCustomBackSlotThumbnails(members, undefined, {})
    ).toStrictEqual([]);
  });

  test("excludes slots whose back matches the project cardback", () => {
    const members = [member("t-0", cardDocument1.identifier, "the-default")];
    expect(
      resolveCustomBackSlotThumbnails(members, "the-default", {})
    ).toStrictEqual([]);
  });

  test("excludes slots with no back face at all", () => {
    const members = [member("t-0", cardDocument1.identifier, undefined)];
    expect(
      resolveCustomBackSlotThumbnails(members, "the-default", {})
    ).toStrictEqual([]);
  });

  test("includes a slot whose back differs, with resolved front/back thumbnail+name pairs", () => {
    const members = [
      member("t-0", cardDocument1.identifier, cardDocument2.identifier),
    ];
    const cardDocumentsByIdentifier = {
      [cardDocument1.identifier]: cardDocument1,
      [cardDocument2.identifier]: cardDocument2,
    };
    const result = resolveCustomBackSlotThumbnails(
      members,
      "the-default",
      cardDocumentsByIdentifier
    );
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      slotLabel: "Slot 1",
      frontName: cardDocument1.name,
      backName: cardDocument2.name,
    });
  });

  test("1-based slot labelling, and only the custom slots are returned out of several", () => {
    const members = [
      member("t-0", cardDocument1.identifier, "the-default"),
      member("t-1", cardDocument1.identifier, "a-custom-back"),
      member("t-2", cardDocument1.identifier, "the-default"),
    ];
    const result = resolveCustomBackSlotThumbnails(members, "the-default", {});
    expect(result.map((thumbnail) => thumbnail.slotLabel)).toStrictEqual([
      "Slot 2",
    ]);
  });
});

describe("countBackFacesAffectedByApplyAll", () => {
  test("counts every slot whose back is not already the new cardback - including custom ones", () => {
    const members = [
      member("t-0", undefined, "the-old-default"),
      member("t-1", undefined, "already-custom"),
      member("t-2", undefined, "the-new-cardback"),
      member("t-3", undefined, undefined),
    ];
    // "the-new-cardback" is what's being applied - already-matching slots don't count, everything
    // else does (2 non-matching backs + 1 slot with no back at all).
    expect(countBackFacesAffectedByApplyAll(members, "the-new-cardback")).toBe(
      3
    );
  });
});
