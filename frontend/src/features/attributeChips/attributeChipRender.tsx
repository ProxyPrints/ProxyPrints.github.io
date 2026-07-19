/**
 * The chip button styling + single chip-button render (fill color, implied-negative dimming,
 * lean tooltip, data-chip-state) shared by every attribute-chip layout. Extracted out of
 * AttributeChipPanel.tsx (Proposal H pane migration, left-panel unification) so the display
 * page's rail Attributes section (features/display/AttributesSection.tsx) renders byte-for-byte
 * the same chip a caller sees in the question feed's ring - only the surrounding arrangement
 * (ring around a card vs. a plain vertical stack) differs between the two, per the design doc's
 * §5 component-mapping table. AttributeChipPanel.tsx imports Chip/ChipRow/renderAttributeChip
 * from here (one-directional) rather than the other way around, so there's no import cycle
 * between this file and its own ring-layout caller.
 */
import styled from "@emotion/styled";
import React from "react";

import {
  ChipVoteState,
  findExclusionGroup,
} from "@/features/attributeChips/attributeChips";

// Mobile funnel pass (thumb-native tap targets): measured at ~30px tall against the previous
// 0.35rem/0.6rem padding - short of the 44px minimum both Apple's HIG and WCAG 2.5.5 (Target
// Size, AA) call for, on the ring's own answer controls. min-height/min-width guarantee the real
// hit area regardless of label length; flex centering keeps the (unchanged, still compact) text
// centered in the now-taller box rather than pinned to its old top-padding baseline.
export const Chip = styled.button<{ fill: string; impliedNegative: boolean }>`
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

export const ChipRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  justify-content: center;
`;

const POSITIVE_RGB = "40, 167, 69"; // bootstrap "success" green
const NEGATIVE_RGB = "220, 53, 69"; // bootstrap "danger" red

// alpha floor keeps a chip with a real but weak vote (netPolarity near 0) visibly distinct
// from a genuinely untouched, zero-signal chip - both would otherwise render identically at
// alpha 0, losing the "some signal exists, it's just weak" information entirely.
export function confidenceFill(netPolarity: number): string {
  if (netPolarity === 0) return "transparent";
  const rgb = netPolarity > 0 ? POSITIVE_RGB : NEGATIVE_RGB;
  const alpha = 0.15 + Math.min(Math.abs(netPolarity), 1) * 0.55;
  return `rgba(${rgb}, ${alpha})`;
}

// The chip's fill color is a *lean*, not a verdict - it renders the tag's current weighted net
// polarity across community + machine votes, which can be wrong, and is never treated as
// confirmed anywhere else in this funnel (see the "Suggested match" vs. a real confirmation
// distinction in QuestionFeed.tsx). An untouched chip with a strong fill could otherwise read as
// "the system has already confirmed this" - this tooltip exists to head that misreading off.
export function leanTooltip(netPolarity: number): string | null {
  if (netPolarity === 0) return null;
  const percent = Math.round(Math.abs(netPolarity) * 100);
  const direction = netPolarity > 0 ? "yes" : "no";
  return `Community + machine votes lean ${direction} (${percent}%) - not confirmed`;
}

export interface RenderAttributeChipArgs {
  confidence: Record<string, number>;
  chipStates: Record<string, ChipVoteState>;
  submittingTagName: string | null;
  tap: (tagName: string) => void;
  getTagDisplayName: (label: string) => string;
}

export function renderAttributeChip(
  {
    confidence,
    chipStates,
    submittingTagName,
    tap,
    getTagDisplayName,
  }: RenderAttributeChipArgs,
  tagName: string,
  label: string
): React.ReactElement {
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
}

/** Only shown once a chip actually has a lean to explain - nothing but untouched, zero-signal
 * chips has nothing for the legend to clarify yet. */
export function hasAttributeLean(confidence: Record<string, number>): boolean {
  return Object.values(confidence).some((value) => value !== 0);
}
