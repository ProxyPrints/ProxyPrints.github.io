import { cardDocument1, cardDocument2 } from "@/common/test-constants";
import { CardType, SlotProjectMembers } from "@/common/types";
import {
  countCardbackApplyTargets,
  isBackSpecified,
  resolveCustomBackSlotThumbnails,
  resolveEligibleCardbackApplySlots,
} from "@/features/card/cardbackApply";

function member(
  id: string,
  frontImage: string | undefined,
  backImage: string | undefined,
  backQuery: string | null = null
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
      backImage != null || backQuery != null
        ? {
            query: { query: backQuery, cardType: "CARDBACK" as CardType },
            selectedImage: backImage,
            selected: false,
          }
        : null,
  };
}

describe("isBackSpecified", () => {
  test("a defaulted, untouched back is not specified", () => {
    const members = member("t-0", cardDocument1.identifier, "the-default");
    expect(isBackSpecified(members, "the-default", {})).toBe(false);
  });

  test("no back face at all is not specified - there's nothing to protect", () => {
    const members = member("t-0", cardDocument1.identifier, undefined);
    expect(isBackSpecified(members, "the-default", {})).toBe(false);
  });

  test("import-specified: a real search query on the back is specified even before it resolves", () => {
    const members = member(
      "t-0",
      cardDocument1.identifier,
      undefined,
      "Some Token"
    );
    expect(isBackSpecified(members, "the-default", {})).toBe(true);
  });

  test("intrinsic: the front card's own layout carries real back art", () => {
    const members = member("t-0", cardDocument1.identifier, "the-default");
    const cardDocumentsByIdentifier = {
      [cardDocument1.identifier]: { ...cardDocument1, layout: "transform" },
    };
    expect(
      isBackSpecified(members, "the-default", cardDocumentsByIdentifier)
    ).toBe(true);
  });

  test("a front layout outside the intrinsic set is not specified on that basis alone", () => {
    const members = member("t-0", cardDocument1.identifier, "the-default");
    const cardDocumentsByIdentifier = {
      [cardDocument1.identifier]: { ...cardDocument1, layout: "normal" },
    };
    expect(
      isBackSpecified(members, "the-default", cardDocumentsByIdentifier)
    ).toBe(false);
  });

  test("manually changed: resolved to something other than the project cardback", () => {
    const members = member(
      "t-0",
      cardDocument1.identifier,
      cardDocument2.identifier
    );
    expect(isBackSpecified(members, "the-default", {})).toBe(true);
  });

  test("nothing counts as manually changed when there's no project cardback to differ from", () => {
    const members = member(
      "t-0",
      cardDocument1.identifier,
      cardDocument2.identifier
    );
    expect(isBackSpecified(members, undefined, {})).toBe(false);
  });
});

describe("resolveCustomBackSlotThumbnails (OWNER AMENDMENT 2/OQ-B)", () => {
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

  test("includes a specified (manually-changed) slot, with resolved front/back thumbnail+name pairs", () => {
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

  test("1-based slot labelling, and only the specified slots are returned out of several", () => {
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

describe("resolveEligibleCardbackApplySlots", () => {
  test("returns the indices of every non-specified slot, skipping specified ones", () => {
    const members = [
      member("t-0", cardDocument1.identifier, "the-default"),
      member("t-1", cardDocument1.identifier, "a-custom-back"),
      member("t-2", cardDocument1.identifier, undefined),
    ];
    expect(
      resolveEligibleCardbackApplySlots(members, "the-default", {})
    ).toStrictEqual([0, 2]);
  });
});

describe("countCardbackApplyTargets", () => {
  test("splits eligible changes from specified/skipped slots - specified slots never count as updates", () => {
    const members = [
      member("t-0", undefined, "the-old-default"),
      member("t-1", undefined, "already-custom"),
      member("t-2", undefined, "the-new-cardback"),
      member("t-3", undefined, undefined),
    ];
    // "the-new-cardback" is what's being applied, against a project cardback of
    // "the-old-default": t-0 is eligible and changes; t-3 has no back yet and is eligible too.
    // t-1's custom back is specified (manually changed) and is skipped, never counted as an
    // update. t-2 is ALSO specified - "manually changed" compares against the CURRENT project
    // cardback ("the-old-default"), not the value being applied, so a slot that happens to
    // already hold the new image but got there by a deliberate per-slot pick is still
    // protected, not silently folded into "already up to date".
    expect(
      countCardbackApplyTargets(
        members,
        "the-new-cardback",
        "the-old-default",
        {}
      )
    ).toStrictEqual({ toUpdate: 2, skippedSpecified: 2 });
  });
});
