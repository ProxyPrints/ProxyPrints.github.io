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
import { CardDocument } from "@/common/types";

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

/**
 * Every chip auto-derivable from a selected candidate - standalone attributes plus whichever
 * exclusion-group chip actually matches (Finding 2: PrintingCandidate carries borderColor/
 * frame directly, so a group value is just as derivable as the standalone booleans). Cast as
 * positive tag votes on selection - see QuestionFeed.tsx's selectCandidate.
 */
export function getAutoTagChips(
  candidate: PrintingCandidate
): AttributeChipDef[] {
  return ALL_ATTRIBUTE_CHIPS.filter((chip) => chip.matches(candidate));
}

/**
 * The /display art-picker FUNNEL's axis descriptor (funnel-spec.md F2, XF1) - a thin wrapper
 * over the exclusion groups/standalone chips above so the funnel can render one segmented
 * `ToggleButtonGroup` per axis (radio for an exclusive group, checkbox for Treatment) instead of
 * the flat 11-chip wall this taxonomy used to render everywhere. No new taxonomy - `chips` is
 * always a reference to the same `AttributeChipDef` arrays above.
 */
export interface FunnelAxis {
  id: string;
  label: string;
  /** true = mutually-exclusive radio segment (Border/Frame); false = independent checkboxes
   * (Treatment) - D23: filter chips are positive-or-off here, never the QuestionFeed's
   * untouched/positive/negative tri-state. */
  exclusive: boolean;
  chips: AttributeChipDef[];
}

export const FUNNEL_AXES: FunnelAxis[] = [
  {
    id: BORDER_COLOR_GROUP.id,
    label: "Border",
    exclusive: true,
    chips: BORDER_COLOR_GROUP.chips,
  },
  {
    id: FRAME_STYLE_GROUP.id,
    label: "Frame",
    exclusive: true,
    chips: FRAME_STYLE_GROUP.chips,
  },
  {
    // D23 honesty note (funnel-spec.md): no "finish" axis exists in the catalog taxonomy -
    // foil/finish is a print SETTING (finishSettingsSlice), not a per-card vote/filter
    // dimension; "Etched" is the only finish-adjacent chip and it lives here, in Treatment.
    id: "treatment",
    label: "Treatment",
    exclusive: false,
    chips: STANDALONE_CHIPS,
  },
];

/**
 * A chip's membership state over a set of surviving candidates (funnel-spec.md F3): "settled"
 * when at least one candidate resolves the tag (`card.tags`, a consensus-resolved fact), or
 * "suggested" when every candidate that carries the tag only does so via an unconfirmed,
 * machine-suggested vote (`tagVoteStatuses === "suggested"`). `undefined` means no surviving
 * candidate carries this attribute at all - the funnel doesn't render the chip (F3's
 * "aggregation over candidates" rule).
 *
 * `votesOn` gates the "suggested" read entirely (F5's votes-off seam): when false, a candidate
 * that only carries the tag via a suggested vote is treated as not carrying it at all, so the
 * chip either shows as settled (if some OTHER candidate resolves it) or doesn't render - never
 * "suggested" - matching F5's "every chip renders SETTLED/plain" base-funnel guarantee.
 *
 * DEVIATION (documented, not silent - see this task's own report): the spec's ground-truth
 * section describes chip membership as readable from raw Scryfall fields via
 * `chip.matches(candidate)` against a `PrintingCandidate`. The /display funnel's actual
 * candidate set is `CardDocument[]` (`cardDocumentsByIdentifier`, fed by the search index), which
 * has NO `borderColor`/`frame`/`fullArt`/etc fields at all - those exist only on the distinct
 * `PrintingCandidate` schema QuestionFeed.tsx's own feed items carry. Since every chip in this
 * taxonomy is already backed by a seeded Tag row (this file's own top-of-file comment), the only
 * signal actually available here is `tags`/`tagVoteStatuses` - exactly what this function reads.
 * The "metadata" membership state (F3.3) therefore stays honestly unreachable via this helper,
 * same as the spec's own carve-out for "a future metadata-only chip."
 */
export type ChipMembershipState = "settled" | "suggested" | "metadata";

export interface ChipMembershipCandidate {
  tags: CardDocument["tags"];
  tagVoteStatuses?: CardDocument["tagVoteStatuses"];
}

export function chipMembershipState(
  candidates: Array<ChipMembershipCandidate>,
  tagName: string,
  votesOn: boolean
): ChipMembershipState | undefined {
  let anyResolved = false;
  let anySuggested = false;
  for (const candidate of candidates) {
    if (candidate.tags.includes(tagName)) {
      anyResolved = true;
    } else if (
      votesOn &&
      candidate.tagVoteStatuses?.[tagName] === "suggested"
    ) {
      anySuggested = true;
    }
  }
  if (anyResolved) return "settled";
  if (anySuggested) return "suggested";
  return undefined;
}

/**
 * Whether a single candidate satisfies an active filter tag - resolved (`tags`) OR, only when
 * `votesOn`, suggested-but-unconfirmed (`tagVoteStatuses`). The funnel's own per-axis
 * survivor-narrowing filter (F1/F2) applies this per active chip, ANDed across chips (same
 * semantics `filterCandidatesByChipStates` already uses for the QuestionFeed's tri-state chips,
 * just sourced from Tag-consensus data rather than `chip.matches` - see `chipMembershipState`'s
 * own comment for why).
 */
export function candidateSatisfiesAttributeTag(
  candidate: ChipMembershipCandidate,
  tagName: string,
  votesOn: boolean
): boolean {
  return (
    candidate.tags.includes(tagName) ||
    (votesOn && candidate.tagVoteStatuses?.[tagName] === "suggested")
  );
}

/**
 * An exclusion group is "open" for a candidate when none of its chips match it - e.g.
 * borderColor "borderless" or "gold" fall outside the Black/White/Silver taxonomy (see
 * printingCandidate2's fixture, borderColor: "borderless"). Standalone chips are never open:
 * their underlying fields are plain booleans, so a definite "false" is itself a complete
 * derived answer, not an unknown one. Drives Level 3's conditional render in QuestionFeed.tsx
 * - most candidates leave nothing open and skip straight past it.
 */
export function getOpenExclusionGroups(
  candidate: PrintingCandidate
): ExclusionGroup[] {
  return EXCLUSION_GROUPS.filter(
    (group) => !group.chips.some((chip) => chip.matches(candidate))
  );
}
