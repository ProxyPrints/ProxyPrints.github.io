/**
 * Small tap-target "card" chip, styled with the same blue (#4d8ddf) used for the "resolved
 * consensus" highlight and the "No match" placeholder over in PrintingTagQueue.tsx's
 * candidate grid (see CandidateButton/ArtPlaceholder there) - reused here so the post-vote
 * follow-up strips (NoMatchReasonStrip, PrintingConfirmStrip) read as the same visual
 * language as the picker a user just interacted with, rather than introducing a second
 * unrelated chip style. Deliberately lighter than CandidateButton: no starburst/hover-zoom,
 * since these chips are small and numerous rather than one large focal candidate.
 */

import styled from "@emotion/styled";
import React from "react";
import Button from "react-bootstrap/Button";

import { STARBURST_OUTER_COLOR } from "@/features/printingTags/starburstShape";

const StyledChipButton = styled(Button)`
  border: 2px solid ${STARBURST_OUTER_COLOR};
  border-radius: 0.5rem;
  background-color: transparent;
  color: inherit;
  width: 100%;
  padding: 0.5rem 0.25rem;
  text-align: center;

  &:hover,
  &:focus {
    background-color: rgba(77, 141, 223, 0.15);
    border-color: ${STARBURST_OUTER_COLOR};
    color: inherit;
  }

  &.highlighted {
    background-color: ${STARBURST_OUTER_COLOR};
    color: #000000;
  }

  &.highlighted:hover,
  &.highlighted:focus {
    background-color: ${STARBURST_OUTER_COLOR};
  }

  &:disabled {
    opacity: 0.6;
  }
`;

interface ChipCardProps {
  label: string;
  sublabel?: string;
  highlighted?: boolean;
  disabled?: boolean;
  onClick: () => void;
  "data-testid"?: string;
}

export function ChipCard({
  label,
  sublabel,
  highlighted = false,
  disabled = false,
  onClick,
  "data-testid": dataTestId,
}: ChipCardProps) {
  return (
    <StyledChipButton
      variant="outline-secondary"
      className={highlighted ? "highlighted" : ""}
      disabled={disabled}
      onClick={onClick}
      data-testid={dataTestId}
    >
      <div>{label}</div>
      {sublabel != null && <div className="small text-muted">{sublabel}</div>}
    </StyledChipButton>
  );
}
