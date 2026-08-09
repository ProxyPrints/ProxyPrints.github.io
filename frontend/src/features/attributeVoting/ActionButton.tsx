/**
 * DESIGN-REPASS Rule 1 (issue #711) - the ONE action-button primitive shared by every answer
 * row on the What's That Card surface. All primary decision and action buttons (Yes, No, Not
 * Sure, Skip, and the embedded custom action triggers - the tag question's Apply/Not
 * applicable, the no-match reason strip's Skip, the artist picker's candidate buttons) must
 * share identical sizing, padding, corner radii, and typography metrics, so no answer row
 * reads at a different scale than its siblings.
 *
 * This is the same geometry as QuestionFeed.tsx's own `Btn` (SPEC-wtc-rebuild.md section 1c's
 * `.btn` row: min-height 44px, font 15px/600, pad 6px 16px, `--r-btn` radius, 1px border) plus
 * Rule 2's `touch-action: manipulation` (kills the mobile double-tap-zoom gesture that
 * otherwise swallows a fast single tap). It exists as a separate primitive rather than an
 * import of `Btn` so the attribute-voting funnel components that render inside the question
 * feed (and in the card-detail modal, their other caller) share one uniform geometry without
 * the questionFeed -> attributeVoting import direction flipping.
 *
 * Variants mirror the surface's token palette; `w-100` stays available as a plain Bootstrap
 * utility class when a caller needs a full-cell button (the artist picker's grid cells).
 */

import styled from "@emotion/styled";

export const ActionButton = styled.button`
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  padding: 6px 16px;
  border-radius: var(--r-btn);
  border: 1px solid transparent;
  cursor: pointer;
  line-height: 1.2;
  text-align: center;
  /* DESIGN-REPASS Rule 2 (#715) - opt out of the mobile double-tap-zoom gesture. */
  touch-action: manipulation;

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &.primary {
    background: var(--primary);
    color: var(--btn-ink);
    border-color: var(--primary);
  }

  &.secondary {
    background: var(--raised);
    color: var(--text);
    border-color: var(--divider);
  }

  &.ghost {
    background: transparent;
    color: var(--muted);
    border-color: transparent;
  }

  /* The artist picker's consensus highlight (kept as its own variant so the "this is the
     current consensus" signal survives the geometry unification) - success-green fill. */
  &.success {
    background: var(--success);
    color: var(--btn-ink);
    border-color: var(--success);
  }
`;
