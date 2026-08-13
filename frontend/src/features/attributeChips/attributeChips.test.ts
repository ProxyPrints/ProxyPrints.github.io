import {
  printingCandidate1,
  printingCandidate2,
  printingCandidate3,
} from "@/common/test-constants";

import {
  ALL_ATTRIBUTE_CHIPS,
  candidateHasAttributeTag,
  candidateSatisfiesAttributeTag,
  ChipMembershipCandidate,
  filterCandidatesByChipStates,
  findExclusionGroup,
  getAutoTagChips,
  getOpenExclusionGroups,
  isAttributeAxisUnknownForCandidate,
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

  // Issue #790, defect 2: a border outside the Black/White/Silver/Borderless taxonomy is a
  // genuine unknown, not a contradiction - it must not be treated as "definitely not black".
  it("a positive border chip does not filter out a candidate whose border falls outside the taxonomy", () => {
    const result = filterCandidatesByChipStates(
      [printingCandidate1, printingCandidate3],
      { "Black Border": "positive" }
    );
    expect(result).toContainEqual(printingCandidate3);
    expect(result).toEqual([printingCandidate1, printingCandidate3]);
  });

  // Issue #790, defect 1: an illustration usually spans several printings with different
  // borders - a chip must narrow WITHIN that illustration, never eliminate it outright.
  describe("illustration-grouped candidates", () => {
    const illustrationId = "11111111-1111-1111-1111-111111111111";
    const whiteBordered = {
      ...printingCandidate1,
      identifier: "printing-white",
      borderColor: "white",
      illustrationId,
    };
    const silverBordered = {
      ...printingCandidate1,
      identifier: "printing-silver",
      borderColor: "silver",
      illustrationId,
    };
    const blackBordered = {
      ...printingCandidate1,
      identifier: "printing-black",
      borderColor: "black",
      illustrationId,
    };

    it("keeps every printing of an illustration that has none matching the active border chip", () => {
      const result = filterCandidatesByChipStates(
        [whiteBordered, silverBordered],
        { "Black Border": "positive" }
      );
      expect(result).toEqual([whiteBordered, silverBordered]);
    });

    it("still narrows within an illustration that does have a matching printing", () => {
      const result = filterCandidatesByChipStates(
        [whiteBordered, blackBordered],
        { "Black Border": "positive" }
      );
      expect(result).toEqual([blackBordered]);
    });

    it("a candidate with no illustrationId at all is unaffected - still excluded on a genuine mismatch", () => {
      const result = filterCandidatesByChipStates(
        [printingCandidate1, printingCandidate2],
        { "White Border": "positive" }
      );
      expect(result).toEqual([]);
    });
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

describe("isAttributeAxisUnknownForCandidate", () => {
  const untagged: ChipMembershipCandidate = { tags: [] };

  it("is true for a border-color chip when the candidate carries no border signal at all", () => {
    expect(
      isAttributeAxisUnknownForCandidate(untagged, "Black Border", true)
    ).toBe(true);
  });

  // The population the fix exists for: a border value (e.g. gold) outside the Black/White/
  // Silver/Borderless taxonomy has no chip that could ever resolve it, so it stays unknown no
  // matter how complete the vote ledger becomes - not just on today's empty one.
  it("stays true regardless of votesOn - there is no tag this candidate could ever carry", () => {
    expect(
      isAttributeAxisUnknownForCandidate(untagged, "Black Border", false)
    ).toBe(true);
  });

  it("is false once a sibling in the same group resolves to a different value", () => {
    const resolvedWhite: ChipMembershipCandidate = { tags: ["White Border"] };
    expect(
      isAttributeAxisUnknownForCandidate(resolvedWhite, "Black Border", true)
    ).toBe(false);
  });

  it("is false once a sibling in the same group is only suggested, with votes on", () => {
    const suggestedWhite: ChipMembershipCandidate = {
      tags: [],
      suggestedFilterTagNames: ["White Border"],
    };
    expect(
      isAttributeAxisUnknownForCandidate(suggestedWhite, "Black Border", true)
    ).toBe(false);
  });

  it("is true for a frame-style chip when the candidate carries no frame signal at all", () => {
    expect(
      isAttributeAxisUnknownForCandidate(untagged, "Old Border", true)
    ).toBe(true);
  });

  // Scoped exactly like getOpenExclusionGroups: a standalone chip has no sibling and no
  // taxonomy-gap case, so "no tag" stays a definite non-match, not an unknown.
  it("is false for a standalone chip - it has no exclusion group to be unknown within", () => {
    expect(isAttributeAxisUnknownForCandidate(untagged, "Etched", true)).toBe(
      false
    );
    expect(isAttributeAxisUnknownForCandidate(untagged, "Full Art", true)).toBe(
      false
    );
  });

  // Scoped exactly like getOpenExclusionGroups' own FRAME_TREATMENT_GROUP carve-out: Showcase/
  // Extended Art are plain booleans, so neither being present is itself a complete answer.
  it("is false for Frame Treatment chips - two false booleans are a complete answer, not a gap", () => {
    expect(isAttributeAxisUnknownForCandidate(untagged, "Showcase", true)).toBe(
      false
    );
    expect(isAttributeAxisUnknownForCandidate(untagged, "Extended", true)).toBe(
      false
    );
  });
});

describe("candidateHasAttributeTag", () => {
  it("is true for a resolved tag", () => {
    expect(candidateHasAttributeTag({ tags: ["Etched"] }, "Etched", true)).toBe(
      true
    );
  });

  it("is true for a suggested tag only when votes are on", () => {
    const suggested: ChipMembershipCandidate = {
      tags: [],
      suggestedFilterTagNames: ["Etched"],
    };
    expect(candidateHasAttributeTag(suggested, "Etched", true)).toBe(true);
    expect(candidateHasAttributeTag(suggested, "Etched", false)).toBe(false);
  });

  // The definite-signal half candidateSatisfiesAttributeTag is built from - never true for a
  // candidate the tag was simply never evaluated on.
  it("is false for a candidate with no signal at all - never true merely from absence", () => {
    expect(candidateHasAttributeTag({ tags: [] }, "Black Border", true)).toBe(
      false
    );
  });
});

describe("candidateSatisfiesAttributeTag", () => {
  it("is true when the candidate resolves the tag", () => {
    expect(
      candidateSatisfiesAttributeTag(
        { tags: ["Black Border"] },
        "Black Border",
        true
      )
    ).toBe(true);
  });

  it("is true when the candidate only suggests the tag and votes are on", () => {
    const suggested: ChipMembershipCandidate = {
      tags: [],
      suggestedFilterTagNames: ["Black Border"],
    };
    expect(
      candidateSatisfiesAttributeTag(suggested, "Black Border", true)
    ).toBe(true);
  });

  // votesOn only gates the suggested signal, not the unknown-axis carve-out below - a
  // suggested-only candidate still survives with votes off, just via "unknown", not "matches".
  it("does not count a suggested-only tag as a match once votes are off", () => {
    const suggested: ChipMembershipCandidate = {
      tags: [],
      suggestedFilterTagNames: ["Black Border"],
    };
    expect(candidateHasAttributeTag(suggested, "Black Border", false)).toBe(
      false
    );
  });

  it("stays false for a resolved mismatch regardless of votesOn", () => {
    const whiteBordered: ChipMembershipCandidate = { tags: ["White Border"] };
    expect(
      candidateSatisfiesAttributeTag(whiteBordered, "Black Border", false)
    ).toBe(false);
  });

  // The defect this closes: an untagged candidate used to fail every AND-ed chip check and
  // disappear from the grid. It must now survive an active chip on an axis it carries no
  // signal for, since absence of signal is not evidence of mismatch.
  it("survives an active border chip when the candidate has no tags at all", () => {
    expect(
      candidateSatisfiesAttributeTag({ tags: [] }, "Black Border", true)
    ).toBe(true);
  });

  it("survives with votes off too - correct on an empty ledger, not only a full one", () => {
    expect(
      candidateSatisfiesAttributeTag({ tags: [] }, "Black Border", false)
    ).toBe(true);
  });

  // The gold-border population: a border color entirely outside the Black/White/Silver/
  // Borderless taxonomy has no tag that could ever resolve it, so every border chip must
  // survive it regardless of which one is active.
  it("survives every border chip for a candidate whose border falls entirely outside the taxonomy", () => {
    const goldBordered: ChipMembershipCandidate = { tags: [] };
    expect(
      candidateSatisfiesAttributeTag(goldBordered, "Black Border", true)
    ).toBe(true);
    expect(
      candidateSatisfiesAttributeTag(goldBordered, "White Border", true)
    ).toBe(true);
    expect(
      candidateSatisfiesAttributeTag(goldBordered, "Silver Border", true)
    ).toBe(true);
  });

  // A resolved sibling in the same exclusion group is real, known information - this must still
  // disqualify the other members, or the border filter would do nothing at all.
  it("is false when a sibling in the same exclusion group resolves to a different value", () => {
    const whiteBordered: ChipMembershipCandidate = { tags: ["White Border"] };
    expect(
      candidateSatisfiesAttributeTag(whiteBordered, "Black Border", true)
    ).toBe(false);
  });

  // Standalone chips and Frame Treatment are unaffected by this fix - see
  // isAttributeAxisUnknownForCandidate's own tests for why "no tag" stays a definite non-match
  // for those.
  it("stays false for an untagged candidate on a standalone or Frame Treatment chip", () => {
    expect(candidateSatisfiesAttributeTag({ tags: [] }, "Etched", true)).toBe(
      false
    );
    expect(candidateSatisfiesAttributeTag({ tags: [] }, "Showcase", true)).toBe(
      false
    );
  });
});
