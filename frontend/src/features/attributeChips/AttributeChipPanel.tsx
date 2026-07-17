/**
 * Tri-state attribute chips surrounding the subject card in the unified question feed (see
 * QuestionFeed.tsx and docs/features/printing-tags.md's questionFeed section). Each chip
 * cycles untouched -> positive -> negative -> untouched on tap, casting a real CardTagVote
 * each time (including the retraction on cycling back to untouched - see
 * cardpicker.views.RETRACT_POLARITY). Fill color/intensity renders the tag's current
 * weighted net polarity (confidence), independent of - though usually correlated with - this
 * voter's own explicit state; exclusion-group siblings of an explicitly-positive chip render
 * a separate "implied-negative" dimmed style without casting a vote of their own.
 */

import styled from "@emotion/styled";
import React, { useState } from "react";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch } from "@/common/types";
import {
  ALL_ATTRIBUTE_CHIPS,
  CHIP_POLARITY,
  ChipVoteState,
  EXCLUSION_GROUPS,
  findExclusionGroup,
  nextChipState,
  STANDALONE_CHIPS,
} from "@/features/attributeChips/attributeChips";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

const POSITIVE_RGB = "40, 167, 69"; // bootstrap "success" green
const NEGATIVE_RGB = "220, 53, 69"; // bootstrap "danger" red

// alpha floor keeps a chip with a real but weak vote (netPolarity near 0) visibly distinct
// from a genuinely untouched, zero-signal chip - both would otherwise render identically at
// alpha 0, losing the "some signal exists, it's just weak" information entirely.
function confidenceFill(netPolarity: number): string {
  if (netPolarity === 0) return "transparent";
  const rgb = netPolarity > 0 ? POSITIVE_RGB : NEGATIVE_RGB;
  const alpha = 0.15 + Math.min(Math.abs(netPolarity), 1) * 0.55;
  return `rgba(${rgb}, ${alpha})`;
}

const Chip = styled.button<{ fill: string; impliedNegative: boolean }>`
  border: 2px solid rgba(0, 0, 0, 0.25);
  border-radius: 0.5rem;
  background-color: ${(props) => props.fill};
  opacity: ${(props) => (props.impliedNegative ? 0.45 : 1)};
  color: inherit;
  padding: 0.35rem 0.6rem;
  font-size: 0.85rem;
  white-space: nowrap;

  &:disabled {
    opacity: 0.5;
  }
`;

const ChipRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  justify-content: center;
`;

const ChipColumn = styled.div`
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  align-items: stretch;
`;

// A 3x3 grid with the card slot dead center and chips forming a ring around it - "top" holds
// the standalone toggles, "left"/"right" hold the two exclusion groups (arbitrarily assigned;
// nothing about a group is inherently left- or right-handed). Empty grid-template-columns
// cells (corners, bottom) collapse via `auto` sizing rather than reserving dead space.
const ChipRing = styled.div`
  display: grid;
  grid-template-areas:
    ".    top   ."
    "left card  right"
    ".    .     .";
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-rows: auto auto auto;
  gap: 0.6rem;
  align-items: center;
  justify-items: center;
`;

const TopArea = styled(ChipRow)`
  grid-area: top;
`;

const LeftArea = styled(ChipColumn)`
  grid-area: left;
`;

const RightArea = styled(ChipColumn)`
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
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );
  const [confidence, setConfidence] =
    useState<Record<string, number>>(tagConfidence);

  React.useEffect(() => {
    setConfidence(tagConfidence);
  }, [tagConfidence]);

  const tap = (tagName: string) => {
    const previousState = chipStates[tagName] ?? "untouched";
    const previousConfidence = confidence[tagName] ?? 0;
    const nextState = nextChipState(previousState);
    const polarity = CHIP_POLARITY[nextState];

    // optimistic: nudge the fill toward the tapped direction immediately, and update the
    // explicit state right away - both get reconciled with the server response below
    onChipStatesChange({ ...chipStates, [tagName]: nextState });
    setConfidence((previous) => ({
      ...previous,
      [tagName]: polarity === 0 ? 0 : polarity,
    }));
    setSubmittingTagName(tagName);

    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      polarity,
      "same-origin",
      "question-feed"
    )
      .then((response) => {
        setConfidence((previous) => ({
          ...previous,
          [tagName]: response.netPolarity,
        }));
      })
      .catch((error) => {
        // revert both the explicit state and the optimistic fill on failure - the vote
        // genuinely wasn't recorded regardless of which branch below fires
        onChipStatesChange({ ...chipStates, [tagName]: previousState });
        setConfidence((previous) => ({
          ...previous,
          [tagName]: previousConfidence,
        }));
        if (isRateLimited(error) && onRateLimited) {
          onRateLimited();
          return;
        }
        dispatch(
          setNotification([
            Math.random().toString(),
            errorToNotification(error, {
              name: "Vote failed",
              message:
                "Something went wrong submitting your tag - please try again.",
            }),
          ])
        );
      })
      .finally(() => setSubmittingTagName(null));
  };

  const renderChip = (tagName: string, label: string) => {
    const explicitState = chipStates[tagName] ?? "untouched";
    const group = findExclusionGroup(tagName);
    const impliedNegative =
      explicitState === "untouched" &&
      group != null &&
      group.chips.some(
        (sibling) =>
          sibling.tagName !== tagName &&
          (chipStates[sibling.tagName] ?? "untouched") === "positive"
      );
    return (
      <Chip
        key={tagName}
        type="button"
        fill={confidenceFill(confidence[tagName] ?? 0)}
        impliedNegative={impliedNegative}
        disabled={submittingTagName != null}
        onClick={() => tap(tagName)}
        data-testid={`attribute-chip-${tagName}`}
        data-chip-state={explicitState}
        title={
          explicitState === "positive"
            ? "Yes"
            : explicitState === "negative"
            ? "No"
            : "Tap to describe what you see"
        }
      >
        {getTagDisplayName(label)}
      </Chip>
    );
  };

  // EXCLUSION_GROUPS[0] (Border Color) renders left, [1] (Frame Style) renders right - an
  // arbitrary but fixed assignment, not a semantic left/right meaning for either group.
  const [leftGroup, rightGroup] = EXCLUSION_GROUPS;

  return (
    <ChipRing data-testid="attribute-chip-panel">
      <TopArea>
        {STANDALONE_CHIPS.map((chip) => renderChip(chip.tagName, chip.label))}
      </TopArea>
      {leftGroup != null && (
        <LeftArea>
          {leftGroup.chips.map((chip) => renderChip(chip.tagName, chip.label))}
        </LeftArea>
      )}
      <CardArea>{cardSlot}</CardArea>
      {rightGroup != null && (
        <RightArea>
          {rightGroup.chips.map((chip) => renderChip(chip.tagName, chip.label))}
        </RightArea>
      )}
    </ChipRing>
  );
}

export function initialChipStates(): Record<string, ChipVoteState> {
  return Object.fromEntries(
    ALL_ATTRIBUTE_CHIPS.map((chip) => [chip.tagName, "untouched"])
  );
}
