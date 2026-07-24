/**
 * Small tap-target "card" chip, styled with the same blue (#4d8ddf) used for the "resolved
 * consensus" highlight and the "No match" placeholder over in cardPanel.tsx's shared
 * candidate grid mechanics (see CandidateButton/ArtPlaceholder there) - reused here so the
 * post-vote follow-up strip (NoMatchReasonStrip) reads as the same visual language as the
 * picker a user just interacted with, rather than introducing a second unrelated chip style.
 * Deliberately lighter than CandidateButton: no starburst/hover-zoom, since these chips are
 * small and numerous rather than one large focal candidate.
 *
 * WTC rebuild (2026-07-24, SPEC-wtc-rebuild.md section 4/1c "reason chip") - the ONE caller
 * this component has today, NoMatchReasonStrip, sits inside the rebuilt /whatsthat's
 * quick-negative (shape c) surface, which the spec's binding per-element table frames in
 * `--danger` (a visibly different mode from a confirm/pick, per WD7) rather than this
 * component's own default accent/blue frame. `variant` is additive and optional (default
 * unchanged) specifically so this doesn't touch ReportCardPanel.tsx's own, unrelated use of
 * the same component - only NoMatchReasonStrip opts into "danger".
 */

import styled from "@emotion/styled";
import React from "react";
import Button from "react-bootstrap/Button";

import { STARBURST_OUTER_COLOR } from "@/features/printingTags/starburstShape";

const StyledChipButton = styled(Button)<{ $variant: "accent" | "danger" }>`
  border: 2px solid
    ${(props) =>
      props.$variant === "danger"
        ? "var(--bs-danger, #f7768e)"
        : STARBURST_OUTER_COLOR};
  border-radius: 0.5rem;
  background-color: transparent;
  color: inherit;
  width: 100%;
  padding: 0.5rem 0.25rem;
  text-align: center;

  &:hover,
  &:focus {
    background-color: ${(props) =>
      props.$variant === "danger"
        ? "color-mix(in srgb, var(--bs-danger, #f7768e) 15%, transparent)"
        : "rgba(77, 141, 223, 0.15)"};
    border-color: ${(props) =>
      props.$variant === "danger"
        ? "var(--bs-danger, #f7768e)"
        : STARBURST_OUTER_COLOR};
    color: inherit;
  }

  &.highlighted {
    background-color: ${(props) =>
      props.$variant === "danger"
        ? "var(--bs-danger, #f7768e)"
        : STARBURST_OUTER_COLOR};
    color: #000000;
  }

  &.highlighted:hover,
  &.highlighted:focus {
    background-color: ${(props) =>
      props.$variant === "danger"
        ? "var(--bs-danger, #f7768e)"
        : STARBURST_OUTER_COLOR};
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
  /** Additive, optional (own comment above) - "danger" is the WTC quick-negative frame;
   * omitted (every other caller) keeps this component's original accent/blue frame. */
  variant?: "accent" | "danger";
}

export function ChipCard({
  label,
  sublabel,
  highlighted = false,
  disabled = false,
  onClick,
  "data-testid": dataTestId,
  variant = "accent",
}: ChipCardProps) {
  return (
    <StyledChipButton
      variant="outline-secondary"
      $variant={variant}
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
