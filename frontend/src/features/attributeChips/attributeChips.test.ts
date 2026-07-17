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

  it("flags Border Color as open for a candidate outside black/white/silver", () => {
    const openGroups = getOpenExclusionGroups(printingCandidate2);
    expect(openGroups.map((group) => group.id)).toEqual(["borderColor"]);
  });
});
