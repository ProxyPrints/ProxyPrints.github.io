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

interface AttributeChipPanelProps {
  backendURL: string;
  cardIdentifier: string;
  /** tagName -> weighted net polarity in [-1, 1], from the questionFeed payload. */
  tagConfidence: Record<string, number>;
  /** Controlled explicit vote state per tagName - lifted to the parent since candidate
   * filtering (QuestionFeed.tsx) needs to read the same state. */
  chipStates: Record<string, ChipVoteState>;
  onChipStatesChange: (next: Record<string, ChipVoteState>) => void;
}

export function AttributeChipPanel({
  backendURL,
  cardIdentifier,
  tagConfidence,
  chipStates,
  onChipStatesChange,
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
      polarity
    )
      .then((response) => {
        setConfidence((previous) => ({
          ...previous,
          [tagName]: response.netPolarity,
        }));
      })
      .catch(() => {
        // revert both the explicit state and the optimistic fill on failure
        onChipStatesChange({ ...chipStates, [tagName]: previousState });
        setConfidence((previous) => ({
          ...previous,
          [tagName]: previousConfidence,
        }));
        dispatch(
          setNotification([
            Math.random().toString(),
            {
              name: "Vote failed",
              message:
                "Something went wrong submitting your tag - please try again.",
              level: "error",
            },
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

  return (
    <div data-testid="attribute-chip-panel">
      <ChipRow className="mb-2">
        {STANDALONE_CHIPS.map((chip) => renderChip(chip.tagName, chip.label))}
      </ChipRow>
      {EXCLUSION_GROUPS.map((group) => (
        <ChipRow key={group.id} className="mb-2">
          {group.chips.map((chip) => renderChip(chip.tagName, chip.label))}
        </ChipRow>
      ))}
    </div>
  );
}

export function initialChipStates(): Record<string, ChipVoteState> {
  return Object.fromEntries(
    ALL_ATTRIBUTE_CHIPS.map((chip) => [chip.tagName, "untouched"])
  );
}

export function hasAnyExplicitChip(
  chipStates: Record<string, ChipVoteState>
): boolean {
  return Object.values(chipStates).some((state) => state !== "untouched");
}
