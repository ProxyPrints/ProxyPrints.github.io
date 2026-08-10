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
  isBorderColorGroupDisqualified,
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

  it("finds the group a frame-style chip belongs to", () => {
    expect(findExclusionGroup("Old Border")?.id).toBe("frameStyle");
  });

  it("returns undefined for a standalone chip", () => {
    expect(findExclusionGroup("Etched")).toBeUndefined();
  });

  it("finds the frame-treatment group a frame-treatment chip belongs to", () => {
    expect(findExclusionGroup("Full Art")?.id).toBe("frameTreatment");
    expect(findExclusionGroup("Borderless")?.id).toBe("frameTreatment");
    expect(findExclusionGroup("Showcase")?.id).toBe("frameTreatment");
    expect(findExclusionGroup("Extended")?.id).toBe("frameTreatment");
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
    // printingCandidate1 is black-bordered, printingCandidate2 is borderless (not in this group)
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
  // "borderless" (outside the Border Color taxonomy), frame="2003"
  it("derives every true standalone plus the matching frame chip, but no border-color chip", () => {
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

  // printingCandidate2 is fullArt=true/isBorderless=true with borderColor="borderless" (outside
  // the Black/White/Silver taxonomy) - Border Color would read "open" by field value alone, but
  // it's disqualified outright here: a Borderless/Full Art card has no border colour to be
  // unknown about, so nothing is left open for this candidate at all.
  it("is empty for a candidate whose border color falls outside the taxonomy but is disqualified by a frame treatment", () => {
    expect(getOpenExclusionGroups(printingCandidate2)).toEqual([]);
  });

  it("flags Border Color as open for a candidate with no disqualifying frame treatment", () => {
    const openGroups = getOpenExclusionGroups({
      ...printingCandidate1,
      borderColor: "gold",
      isShowcase: true,
    });
    expect(openGroups.map((group) => group.id)).toEqual(["borderColor"]);
  });

  it("never flags Frame Treatment as open - an ordinary card's four false booleans are a complete answer", () => {
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
});

describe("isBorderColorGroupDisqualified", () => {
  it("is true once Borderless is explicitly positive", () => {
    expect(isBorderColorGroupDisqualified({ Borderless: "positive" })).toBe(
      true
    );
  });

  it("is true once Full Art is explicitly positive", () => {
    expect(isBorderColorGroupDisqualified({ "Full Art": "positive" })).toBe(
      true
    );
  });

  it("is false for Extended Art or Showcase - both still have a border colour", () => {
    expect(isBorderColorGroupDisqualified({ Extended: "positive" })).toBe(
      false
    );
    expect(isBorderColorGroupDisqualified({ Showcase: "positive" })).toBe(
      false
    );
  });

  it("is false with nothing voted", () => {
    expect(isBorderColorGroupDisqualified({})).toBe(false);
  });
});

describe("isChipContradicted - Border Color gated by Frame Treatment", () => {
  it("hides an untouched Border Color chip once Borderless is explicitly positive", () => {
    expect(isChipContradicted("Black Border", { Borderless: "positive" })).toBe(
      true
    );
  });

  it("hides an untouched Border Color chip once Full Art is explicitly positive", () => {
    expect(isChipContradicted("Black Border", { "Full Art": "positive" })).toBe(
      true
    );
  });

  it("leaves Border Color visible when Extended Art is explicitly positive", () => {
    expect(isChipContradicted("Black Border", { Extended: "positive" })).toBe(
      false
    );
  });

  it("leaves Border Color visible when Showcase is explicitly positive", () => {
    expect(isChipContradicted("Black Border", { Showcase: "positive" })).toBe(
      false
    );
  });

  it("still hides Full Art's own untouched Frame Treatment siblings, unaffected by the cross-group gate", () => {
    expect(isChipContradicted("Borderless", { "Full Art": "positive" })).toBe(
      true
    );
  });
});
