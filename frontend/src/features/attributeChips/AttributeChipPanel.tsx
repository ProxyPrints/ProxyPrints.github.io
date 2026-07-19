/**
 * Tri-state attribute chips surrounding the subject card in the unified question feed (see
 * QuestionFeed.tsx and docs/features/printing-tags.md's questionFeed section). Each chip
 * cycles untouched -> positive -> negative -> untouched on tap, casting a real CardTagVote
 * each time (including the retraction on cycling back to untouched - see
 * cardpicker.views.RETRACT_POLARITY). Fill color/intensity renders the tag's current
 * weighted net polarity (confidence), independent of - though usually correlated with - this
 * voter's own explicit state; exclusion-group siblings of an explicitly-positive chip render
 * a separate "implied-negative" dimmed style without casting a vote of their own.
 *
 * The chip button itself (styling, fill/tooltip/data-chip-state logic) and the tap/vote-
 * submission machinery both live in shared modules now (attributeChipRender.tsx, useTagVoting.ts
 * - Proposal H pane migration, left-panel unification) so the display page's rail Attributes
 * section (features/display/AttributesSection.tsx) renders the exact same chip through the exact
 * same vote call, in its own plain vertical stack instead of this component's ring-around-a-card
 * layout. This file now owns only the ring arrangement itself.
 */

import styled from "@emotion/styled";
import React from "react";

import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  ChipRow,
  hasAttributeLean,
  renderAttributeChip,
} from "@/features/attributeChips/attributeChipRender";
import {
  ALL_ATTRIBUTE_CHIPS,
  ChipVoteState,
  EXCLUSION_GROUPS,
  STANDALONE_CHIPS,
} from "@/features/attributeChips/attributeChips";
import { useTagVoting } from "@/features/attributeChips/useTagVoting";

// A 3x3 grid with the card slot dead center and chips forming a ring around it - "top" holds
// the standalone toggles, "left"/"right" hold the two exclusion groups (arbitrarily assigned;
// nothing about a group is inherently left- or right-handed). Empty grid-template-columns
// cells (corners, bottom) collapse via `auto` sizing rather than reserving dead space.
//
// MOBILE OVERRIDE (layout reconciliation pass): this grid has no responsive behavior below
// `sm` - the ring's flanking left/right columns are `auto`-sized to their own chip content
// (never allowed to shrink) while the card's own "card" column is the only flexible one
// (`minmax(0, 1fr)`), so at narrow widths the card gets squeezed to whatever width is left
// over after both chip columns claim theirs, rather than the chips reflowing around a
// full-width card. Below `sm` this collapses to a single vertical stack (top chips, then the
// card at its own full natural width, then left/right chips below it as ordinary flowing
// rows) - the ring visual only survives at widths wide enough to contain it without
// squeezing the card, per this pass's decision rule.
const ChipRing = styled.div`
  display: grid;
  grid-template-areas:
    "top"
    "card"
    "left"
    "right";
  grid-template-columns: minmax(0, 1fr);
  gap: 0.6rem;
  align-items: center;
  justify-items: center;

  @media (min-width: 576px) {
    grid-template-areas:
      ".    top   ."
      "left card  right"
      ".    .     .";
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-rows: auto auto auto;
  }
`;

const TopArea = styled(ChipRow)`
  grid-area: top;
`;

// Row+wrap below `sm` (matching TopArea, since the ring hasn't formed yet and there's no
// flanking column to stack vertically inside) - becomes a genuine vertical column only once
// the ring itself forms at `sm` and up.
const LeftArea = styled(ChipRow)`
  grid-area: left;

  @media (min-width: 576px) {
    flex-direction: column;
    align-items: stretch;
  }
`;

const RightArea = styled(ChipRow)`
  grid-area: right;

  @media (min-width: 576px) {
    flex-direction: column;
    align-items: stretch;
  }
`;

// position: relative so an absolutely-positioned burst rendered as part of `cardSlot` (see
// QuestionFeed.tsx) sizes and centers itself against the card's own box specifically, not
// this whole ring (which includes the flanking chip columns and would make the burst far
// larger, and off-center, than intended - see docs/features/printing-tags.md's Stage 7).
const CardArea = styled.div`
  grid-area: card;
  width: 100%;
  position: relative;
`;

interface AttributeChipPanelProps {
  backendURL: string;
  cardIdentifier: string;
  /** tagName -> weighted net polarity in [-1, 1], from the questionFeed payload. */
  tagConfidence: Record<string, number>;
  /** Controlled explicit vote state per tagName - lifted to the parent since candidate
   * filtering (QuestionFeed.tsx) needs to read the same state. */
  chipStates: Record<string, ChipVoteState>;
  onChipStatesChange: (next: Record<string, ChipVoteState>) => void;
  /** The card image/reveal-overlay/caption, rendered dead center with chips forming a ring
   * around it - passed in rather than owned here so QuestionFeed.tsx keeps sole ownership of
   * the reveal-animation state machine (revealed/onAnimationEnd) that slot's contents depend on. */
  cardSlot: React.ReactNode;
  /** Called instead of the usual error toast when a submission is rejected with 429 - this
   * component has only one caller (QuestionFeed.tsx), so this is effectively always provided,
   * but stays optional to match the same safe-default convention as the other funnel
   * components (see ArtistVotePicker.tsx's identical prop for the full rationale). */
  onRateLimited?: () => void;
}

export function AttributeChipPanel({
  backendURL,
  cardIdentifier,
  tagConfidence,
  chipStates,
  onChipStatesChange,
  cardSlot,
  onRateLimited,
}: AttributeChipPanelProps) {
  const getTagDisplayName = useTagDisplayName();
  const { confidence, submittingTagName, tap } = useTagVoting({
    backendURL,
    cardIdentifier,
    tagConfidence,
    chipStates,
    onChipStatesChange,
    onRateLimited,
  });

  const chipArgs = {
    confidence,
    chipStates,
    submittingTagName,
    tap,
    getTagDisplayName,
  };

  // EXCLUSION_GROUPS[0] (Border Color) renders left, [1] (Frame Style) renders right - an
  // arbitrary but fixed assignment, not a semantic left/right meaning for either group.
  const [leftGroup, rightGroup] = EXCLUSION_GROUPS;

  return (
    <>
      {hasAttributeLean(confidence) && (
        <p
          className="text-muted small text-center mb-2"
          data-testid="attribute-chip-legend"
        >
          Chip color shows how community + machine votes lean - not a confirmed
          fact.
        </p>
      )}
      <ChipRing data-testid="attribute-chip-panel">
        <TopArea>
          {STANDALONE_CHIPS.map((chip) =>
            renderAttributeChip(chipArgs, chip.tagName, chip.label)
          )}
        </TopArea>
        {leftGroup != null && (
          <LeftArea>
            {leftGroup.chips.map((chip) =>
              renderAttributeChip(chipArgs, chip.tagName, chip.label)
            )}
          </LeftArea>
        )}
        <CardArea data-testid="attribute-chip-card-area">{cardSlot}</CardArea>
        {rightGroup != null && (
          <RightArea>
            {rightGroup.chips.map((chip) =>
              renderAttributeChip(chipArgs, chip.tagName, chip.label)
            )}
          </RightArea>
        )}
      </ChipRing>
    </>
  );
}

export function initialChipStates(): Record<string, ChipVoteState> {
  return Object.fromEntries(
    ALL_ATTRIBUTE_CHIPS.map((chip) => [chip.tagName, "untouched"])
  );
}
