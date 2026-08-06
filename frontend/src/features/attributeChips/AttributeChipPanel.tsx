/**
 * Tri-state attribute chips surrounding the subject card in the unified question feed (see
 * QuestionFeed.tsx and docs/features/printing-tags.md's questionFeed section). Each chip is a
 * Yes/No button pair, either directly reachable in one tap, casting a real CardTagVote each
 * time (including the retraction when tapping the already-active button back to untouched -
 * see cardpicker.views.RETRACT_POLARITY). Fill color/intensity renders the tag's current
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

// Issue #743: BORDER_COLOR_GROUP and FRAME_STYLE_GROUP are independent axes (a card's border
// colour and its frame era don't imply each other), but nothing previously rendered their
// `ExclusionGroup.label` - the two groups' chip rows ran together as one unlabelled list, so a
// user reasonably read a correct half-collapse (one group's siblings dimming, the other
// untouched) as a bug. Renders the label that already existed as data.
const GroupHeading = styled.p`
  margin: 0 0 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(0, 0, 0, 0.55);
  text-align: center;
`;

// A divider between the two exclusion groups (flat-stack layout only, see the `cardSlot == null`
// branch below) - the ring layout already keeps them apart spatially (left/right of the card),
// so it doesn't need one.
const GroupDivider = styled.hr`
  width: 100%;
  margin: 0;
  border: none;
  border-top: 1px solid rgba(0, 0, 0, 0.12);
`;

// Row+wrap below `sm` (matching TopArea, since the ring hasn't formed yet and there's no
// flanking column to stack vertically inside) - becomes a genuine vertical column only once
// the ring itself forms at `sm` and up.
const ExclusionChipRow = styled(ChipRow)`
  @media (min-width: 576px) {
    flex-direction: column;
  }
`;

// Wraps a heading plus its `ExclusionChipRow` as one unit, so `ChipRing`'s grid can still
// position the whole group (heading + chips together) as a single "left"/"right" cell.
const LeftArea = styled.div`
  grid-area: left;
`;

const RightArea = styled.div`
  grid-area: right;
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

// A caller with no card to center (QuestionFeed.tsx's Level 2, since the reference card lives
// in its own pinned Subject column now - issue #707) gets a plain vertical stack of the same
// three ChipRow groups instead of the ring - there's no card slot for a ring to form around.
const FlatChipStack = styled.div`
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
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
   * the reveal-animation state machine (revealed/onAnimationEnd) that slot's contents depend
   * on. Omitted entirely by a caller with nothing to center (FlatChipStack above). */
  cardSlot?: React.ReactNode;
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

  const legend = hasAttributeLean(confidence) && (
    <p
      className="text-muted small text-center mb-2"
      data-testid="attribute-chip-legend"
    >
      Chip color shows how community + machine votes lean - not a confirmed
      fact.
    </p>
  );
  const topArea = (
    <TopArea>
      {STANDALONE_CHIPS.map((chip) =>
        renderAttributeChip(chipArgs, chip.tagName, chip.label)
      )}
    </TopArea>
  );
  const leftArea = leftGroup != null && (
    <LeftArea>
      <GroupHeading>{leftGroup.label}</GroupHeading>
      <ExclusionChipRow>
        {leftGroup.chips.map((chip) =>
          renderAttributeChip(chipArgs, chip.tagName, chip.label)
        )}
      </ExclusionChipRow>
    </LeftArea>
  );
  const rightArea = rightGroup != null && (
    <RightArea>
      <GroupHeading>{rightGroup.label}</GroupHeading>
      <ExclusionChipRow>
        {rightGroup.chips.map((chip) =>
          renderAttributeChip(chipArgs, chip.tagName, chip.label)
        )}
      </ExclusionChipRow>
    </RightArea>
  );

  if (cardSlot == null) {
    return (
      <>
        {legend}
        <FlatChipStack data-testid="attribute-chip-panel">
          {topArea}
          {leftArea}
          {leftArea != null && rightArea != null && <GroupDivider />}
          {rightArea}
        </FlatChipStack>
      </>
    );
  }

  return (
    <>
      {legend}
      <ChipRing data-testid="attribute-chip-panel">
        {topArea}
        {leftArea}
        <CardArea data-testid="attribute-chip-card-area">{cardSlot}</CardArea>
        {rightArea}
      </ChipRing>
    </>
  );
}

export function initialChipStates(): Record<string, ChipVoteState> {
  return Object.fromEntries(
    ALL_ATTRIBUTE_CHIPS.map((chip) => [chip.tagName, "untouched"])
  );
}
