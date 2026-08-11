import {
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";

import {
  ALL_ATTRIBUTE_CHIPS,
  filterCandidatesByChipStates,
  findExclusionGroup,
  getAutoTagChips,
  getOpenExclusionGroups,
  isChipContradicted,
  nextChipState,
} from "./attributeChips";

describe("nextChipState", () => {
  it("cycles untouched -> positive -> negative -> untouched", () => {
    expect(nextChipState("untouched")).toBe("positive");
    expect(nextChipState("positive")).toBe("negative");
    expect(nextChipState("negative")).toBe("untouched");
  });
});

describe("findExclusionGroup", () => {
  it("finds the group a border-color chip belongs to", () => {
    expect(findExclusionGroup("Black Border")?.id).toBe("borderColor");
  });

  // Owner ruling (frame-treatment axis rework, 2026-08): Borderless is Scryfall's own
  // border_color value, not a separate frame treatment - it moved into Border Color, mutually
  // exclusive with Black/White/Silver.
  it("finds Borderless in the border-color group, not a standalone chip", () => {
    expect(findExclusionGroup("Borderless")?.id).toBe("borderColor");
  });

  it("finds the group a frame-style chip belongs to", () => {
    expect(findExclusionGroup("Old Border")?.id).toBe("frameStyle");
  });

  it("finds the frame-treatment group a Showcase/Extended Art chip belongs to", () => {
    expect(findExclusionGroup("Showcase")?.id).toBe("frameTreatment");
    expect(findExclusionGroup("Extended")?.id).toBe("frameTreatment");
  });

  it("returns undefined for a standalone chip", () => {
    expect(findExclusionGroup("Etched")).toBeUndefined();
    // Full Art co-occurs with every border colour and with Showcase (measured against
    // CanonicalPrintingMetadata) - it's independent, not a member of any exclusion group.
    expect(findExclusionGroup("Full Art")).toBeUndefined();
  });
});

describe("ALL_ATTRIBUTE_CHIPS", () => {
  it("has no duplicate tagNames", () => {
    const names = ALL_ATTRIBUTE_CHIPS.map((chip) => chip.tagName);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("filterCandidatesByChipStates", () => {
  // printingCandidate1: fullArt=false, isBorderless=false, isShowcase=false, borderColor="black"
  // printingCandidate2: fullArt=true, isBorderless=true, isShowcase=true, borderColor="borderless"
  const candidates = [printingCandidate1, printingCandidate2];

  it("returns every candidate when no chip is explicit", () => {
    expect(filterCandidatesByChipStates(candidates, {})).toEqual(candidates);
  });

  it("a positive standalone chip keeps only matching candidates", () => {
    const result = filterCandidatesByChipStates(candidates, {
      "Full Art": "positive",
    });
    expect(result).toEqual([printingCandidate2]);
  });

  it("a negative standalone chip drops matching candidates", () => {
    const result = filterCandidatesByChipStates(candidates, {
      "Full Art": "negative",
    });
    expect(result).toEqual([printingCandidate1]);
  });

  it("a positive exclusion-group chip naturally excludes sibling values with no extra logic", () => {
    // printingCandidate1 is black-bordered, printingCandidate2 is borderless (a different
    // sibling of the same Border Color group)
    const result = filterCandidatesByChipStates(candidates, {
      "Black Border": "positive",
    });
    expect(result).toEqual([printingCandidate1]);
  });

  it("combines multiple active chips with AND semantics", () => {
    const result = filterCandidatesByChipStates(candidates, {
      "Full Art": "positive",
      Borderless: "positive",
    });
    expect(result).toEqual([printingCandidate2]);
    const noMatch = filterCandidatesByChipStates(candidates, {
      "Full Art": "positive",
      Borderless: "negative", // contradictory - candidate2 is both fullArt and borderless
    });
    expect(noMatch).toEqual([]);
  });

  // Measured against CanonicalPrintingMetadata: 4,902 printings are both borderless and full
  // art (82% of all borderless printings) - e.g. Ghalta, Primal Hunger. Full Art is standalone,
  // so this combination must stay representable.
  it("a card can be borderless and full art at the same time", () => {
    const result = filterCandidatesByChipStates(candidates, {
      Borderless: "positive",
      "Full Art": "positive",
    });
    expect(result).toEqual([printingCandidate2]);
  });
});

describe("getAutoTagChips", () => {
  // printingCandidate1: fullArt=false, isBorderless=false, isShowcase=false,
  // isExtendedArt=false, isEtched=false, borderColor="black", frame="2015"
  it("derives every standalone-false candidate as no chips, plus the matching exclusion-group values", () => {
    const tagNames = getAutoTagChips(printingCandidate1).map(
      (chip) => chip.tagName
    );
    expect(tagNames).toEqual(["Black Border", "Modern Border"]);
  });

  // printingCandidate2: fullArt=true, isBorderless=true, isShowcase=true, borderColor=
  // "borderless" (its own Border Color chip, not outside the taxonomy), frame="2003" - a real
  // three-way combination (full art AND borderless AND showcase), same shape as Cathars'
  // Crusade (INR 483), which is also full art, showcase, and borderless all at once.
  it("derives every true standalone plus the matching border-color and frame chips", () => {
    const tagNames = getAutoTagChips(printingCandidate2).map(
      (chip) => chip.tagName
    );
    expect(tagNames).toEqual(
      expect.arrayContaining([
        "Full Art",
        "Borderless",
        "Showcase",
        "Modern Border",
      ])
    );
    expect(tagNames).not.toEqual(
      expect.arrayContaining(["Black Border", "White Border", "Silver Border"])
    );
  });
});

describe("getOpenExclusionGroups", () => {
  it("is empty for a candidate whose border color and frame both match a taxonomy chip", () => {
    expect(getOpenExclusionGroups(printingCandidate1)).toEqual([]);
  });

  // printingCandidate2 is borderless - its own Borderless chip in the Border Color group
  // matches it directly now (border_color "borderless" is one of the group's four values), so
  // nothing is left open for this candidate.
  it("is empty for a borderless candidate - its own Border Color chip resolves it", () => {
    expect(getOpenExclusionGroups(printingCandidate2)).toEqual([]);
  });

  it("flags Border Color as open for a candidate whose border color falls outside the taxonomy", () => {
    const openGroups = getOpenExclusionGroups({
      ...printingCandidate1,
      borderColor: "gold",
      isShowcase: true,
    });
    expect(openGroups.map((group) => group.id)).toEqual(["borderColor"]);
  });

  it("never flags Frame Treatment as open - an ordinary card's two false booleans are a complete answer", () => {
    const openGroups = getOpenExclusionGroups({
      ...printingCandidate1,
      borderColor: "gold",
    });
    expect(openGroups.map((group) => group.id)).not.toContain("frameTreatment");
  });
});

describe("isChipContradicted", () => {
  it("is true for an untouched exclusion-group sibling of an explicit positive", () => {
    expect(
      isChipContradicted("White Border", { "Black Border": "positive" })
    ).toBe(true);
    expect(
      isChipContradicted("Silver Border", { "Black Border": "positive" })
    ).toBe(true);
  });

  // Borderless is now a Border Color sibling of Black/White/Silver (Scryfall's own
  // border_color enum), so it's contradicted by them exactly like any other sibling - no
  // separate cross-group gate is needed for this anymore.
  it("is true for Borderless once a different Border Color sibling is explicitly positive", () => {
    expect(
      isChipContradicted("Borderless", { "Black Border": "positive" })
    ).toBe(true);
  });

  it("is false for the chip that owns the positive vote itself", () => {
    expect(
      isChipContradicted("Black Border", { "Black Border": "positive" })
    ).toBe(false);
  });

  it("is false for an explicitly-voted sibling, even when a group-mate is positive", () => {
    // an explicit negative is itself an active filter, not a disqualified option
    expect(
      isChipContradicted("White Border", {
        "Black Border": "positive",
        "White Border": "negative",
      })
    ).toBe(false);
  });

  it("is false for a negative vote alone - it does not rule out any sibling value", () => {
    expect(
      isChipContradicted("White Border", { "Black Border": "negative" })
    ).toBe(false);
  });

  it("is false for standalone chips, which have no exclusion group", () => {
    expect(isChipContradicted("Etched", { Etched: "positive" })).toBe(false);
    expect(isChipContradicted("Etched", {})).toBe(false);
  });

  // Measured against CanonicalPrintingMetadata: Full Art is independent - it co-occurs with
  // every border colour and with Showcase, so it's never contradicted by a Border Color or
  // Frame Treatment vote.
  it("is false for Full Art regardless of Border Color or Frame Treatment votes", () => {
    expect(isChipContradicted("Full Art", { Borderless: "positive" })).toBe(
      false
    );
    expect(isChipContradicted("Full Art", { Showcase: "positive" })).toBe(
      false
    );
  });

  // Showcase and Extended Art co-occur in exactly 0 of 113,224 measured printings - the one
  // genuinely exclusive pair in the frame-treatment axis.
  it("is true for Showcase once Extended Art is explicitly positive, and vice versa", () => {
    expect(isChipContradicted("Showcase", { Extended: "positive" })).toBe(true);
    expect(isChipContradicted("Extended", { Showcase: "positive" })).toBe(true);
  });
});
