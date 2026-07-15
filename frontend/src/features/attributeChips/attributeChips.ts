/**
 * The attribute-chip taxonomy for the "What's That Card?" question feed (see
 * docs/features/printing-tags.md's questionFeed section and
 * journal/2026-07-14-queue-question-feed-design.md for the full grounding/data-census this
 * set is derived from - don't add a chip here without checking that doc first, the taxonomy
 * is deliberately NOT "every value CanonicalPrintingMetadata happens to contain").
 *
 * Every `tagName` below must already exist as a seeded `Tag` row for a tap to actually work
 * (400s otherwise) - "Full Art"/"Borderless"/"Showcase"/"Extended" come from
 * cardpicker.default_tags (already seeded in production); the rest come from
 * cardpicker.attribute_tags.ATTRIBUTE_TAGS (seed_attribute_tags command, run once as part of
 * this feature's own deploy step, same pattern as seed_sensitive_tags).
 */

import { PrintingCandidate } from "@/common/schema_types";

export interface AttributeChipDef {
  /** The backend Tag.name this chip votes on - see cardpicker.attribute_tags. */
  tagName: string;
  label: string;
  /** Whether a given candidate visibly has this attribute - drives auto-tag-on-selection
   * (standalone chips only - see QuestionFeed.tsx) and live candidate filtering. */
  matches: (candidate: PrintingCandidate) => boolean;
}

export interface ExclusionGroup {
  id: string;
  label: string;
  chips: AttributeChipDef[];
}

// EXCLUSION GROUPS: a card has exactly one border_color / one frame value, so within a
// group a positive tap on one chip drives live filtering + renders implied-negative styling
// on its siblings - but casts NO vote on those siblings, only on the one actually tapped
// (spec requirement: "votes are only explicit taps"). Filtering itself needs no special
// group-awareness beyond this - see filterCandidatesByChipStates in QuestionFeed.tsx: an
// explicit positive on one member already excludes every candidate whose border_color/frame
// doesn't match, which naturally excludes the group's other values with no extra logic.
export const BORDER_COLOR_GROUP: ExclusionGroup = {
  id: "borderColor",
  label: "Border Color",
  chips: [
    {
      tagName: "Black Border",
      label: "Black Border",
      matches: (candidate) => candidate.borderColor === "black",
    },
    {
      tagName: "White Border",
      label: "White Border",
      matches: (candidate) => candidate.borderColor === "white",
    },
    {
      tagName: "Silver Border",
      label: "Silver Border",
      matches: (candidate) => candidate.borderColor === "silver",
    },
  ],
};

// Bucketed 1993+1997 -> "Old Border" and 2003+2015 -> "Modern Border" rather than exposing
// all four raw Scryfall frame years as separate chips - the finer distinctions are hard for
// a non-expert to reliably tell apart at a glance. See the design doc for the full rationale.
export const FRAME_STYLE_GROUP: ExclusionGroup = {
  id: "frameStyle",
  label: "Frame Style",
  chips: [
    {
      tagName: "Old Border",
      label: "Old Border",
      matches: (candidate) =>
        candidate.frame === "1993" || candidate.frame === "1997",
    },
    {
      tagName: "Modern Border",
      label: "Modern Border",
      matches: (candidate) =>
        candidate.frame === "2003" || candidate.frame === "2015",
    },
    {
      tagName: "Future Frame",
      label: "Future Frame",
      matches: (candidate) => candidate.frame === "future",
    },
  ],
};

export const EXCLUSION_GROUPS: ExclusionGroup[] = [
  BORDER_COLOR_GROUP,
  FRAME_STYLE_GROUP,
];

// Independent toggles - not mutually exclusive with each other or with the exclusion groups
// above (a card can be simultaneously Full Art, Showcase, and black-bordered).
export const STANDALONE_CHIPS: AttributeChipDef[] = [
  {
    tagName: "Full Art",
    label: "Full Art",
    matches: (candidate) => candidate.fullArt,
  },
  {
    tagName: "Borderless",
    label: "Borderless",
    matches: (candidate) => candidate.isBorderless,
  },
  {
    tagName: "Showcase",
    label: "Showcase",
    matches: (candidate) => candidate.isShowcase,
  },
  {
    tagName: "Extended",
    label: "Extended Art",
    matches: (candidate) => candidate.isExtendedArt,
  },
  {
    tagName: "Etched",
    label: "Etched",
    matches: (candidate) => candidate.isEtched,
  },
];

export const ALL_ATTRIBUTE_CHIPS: AttributeChipDef[] = [
  ...STANDALONE_CHIPS,
  ...EXCLUSION_GROUPS.flatMap((group) => group.chips),
];

export type ChipVoteState = "untouched" | "positive" | "negative";

export const CHIP_POLARITY: Record<ChipVoteState, number> = {
  untouched: 0, // retract sentinel - see cardpicker.views.RETRACT_POLARITY
  positive: 1,
  negative: -1,
};

/** untouched -> positive -> negative -> untouched, per spec's tri-state tap cycle. */
export function nextChipState(current: ChipVoteState): ChipVoteState {
  if (current === "untouched") return "positive";
  if (current === "positive") return "negative";
  return "untouched";
}

/** The group (if any) a given tagName belongs to - used to compute implied-negative styling. */
export function findExclusionGroup(
  tagName: string
): ExclusionGroup | undefined {
  return EXCLUSION_GROUPS.find((group) =>
    group.chips.some((chip) => chip.tagName === tagName)
  );
}

/**
 * Filters candidates against the current explicit chip vote states: a positive chip drops
 * any candidate that doesn't match it, a negative chip drops any candidate that does. Implied-
 * negative (exclusion-group sibling) styling never contributes an extra filter condition on
 * its own - see the exclusion-group comment above for why that's unnecessary.
 */
export function filterCandidatesByChipStates<T extends PrintingCandidate>(
  candidates: T[],
  chipStates: Record<string, ChipVoteState>
): T[] {
  const activeChips = ALL_ATTRIBUTE_CHIPS.filter(
    (chip) => (chipStates[chip.tagName] ?? "untouched") !== "untouched"
  );
  if (activeChips.length === 0) {
    return candidates;
  }
  return candidates.filter((candidate) =>
    activeChips.every((chip) => {
      const state = chipStates[chip.tagName] ?? "untouched";
      const isMatch = chip.matches(candidate);
      return state === "positive" ? isMatch : !isMatch;
    })
  );
}
