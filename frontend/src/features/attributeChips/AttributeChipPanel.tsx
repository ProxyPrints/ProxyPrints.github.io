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

// Mobile funnel pass (thumb-native tap targets): measured at ~30px tall against the previous
// 0.35rem/0.6rem padding - short of the 44px minimum both Apple's HIG and WCAG 2.5.5 (Target
// Size, AA) call for, on the ring's own answer controls. min-height/min-width guarantee the real
// hit area regardless of label length; flex centering keeps the (unchanged, still compact) text
// centered in the now-taller box rather than pinned to its old top-padding baseline.
const Chip = styled.button<{ fill: string; impliedNegative: boolean }>`
  border: 2px solid rgba(0, 0, 0, 0.25);
  border-radius: 0.5rem;
  background-color: ${(props) => props.fill};
  opacity: ${(props) => (props.impliedNegative ? 0.45 : 1)};
  color: inherit;
  padding: 0.35rem 0.6rem;
  font-size: 0.85rem;
  white-space: nowrap;
  min-height: 44px;
  min-width: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;

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

  // The chip's fill color is a *lean*, not a verdict - it renders the tag's current weighted
  // net polarity across community + machine votes (see the header comment), which can be
  // wrong, and is never treated as confirmed anywhere else in this funnel (see the
  // "Suggested match" vs. a real confirmation distinction in QuestionFeed.tsx). An untouched
  // chip with a strong fill could otherwise read as "the system has already confirmed this" -
  // this tooltip and the legend below it exist to head that misreading off explicitly.
  const leanTooltip = (netPolarity: number): string | null => {
    if (netPolarity === 0) return null;
    const percent = Math.round(Math.abs(netPolarity) * 100);
    const direction = netPolarity > 0 ? "yes" : "no";
    return `Community + machine votes lean ${direction} (${percent}%) - not confirmed`;
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
    const lean = leanTooltip(confidence[tagName] ?? 0);
    const title =
      explicitState === "positive"
        ? "Yes"
        : explicitState === "negative"
        ? "No"
        : lean ?? "Tap to describe what you see";
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
        title={title}
      >
        {getTagDisplayName(label)}
      </Chip>
    );
  };

  // EXCLUSION_GROUPS[0] (Border Color) renders left, [1] (Frame Style) renders right - an
  // arbitrary but fixed assignment, not a semantic left/right meaning for either group.
  const [leftGroup, rightGroup] = EXCLUSION_GROUPS;

  // Only shown once a chip actually has a lean to explain - a panel with nothing but
  // untouched, zero-signal chips has nothing for the legend to clarify yet.
  const hasLean = Object.values(confidence).some((value) => value !== 0);

  return (
    <>
      {hasLean && (
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
          {STANDALONE_CHIPS.map((chip) => renderChip(chip.tagName, chip.label))}
        </TopArea>
        {leftGroup != null && (
          <LeftArea>
            {leftGroup.chips.map((chip) =>
              renderChip(chip.tagName, chip.label)
            )}
          </LeftArea>
        )}
        <CardArea data-testid="attribute-chip-card-area">{cardSlot}</CardArea>
        {rightGroup != null && (
          <RightArea>
            {rightGroup.chips.map((chip) =>
              renderChip(chip.tagName, chip.label)
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
