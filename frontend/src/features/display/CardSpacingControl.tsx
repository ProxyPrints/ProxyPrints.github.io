/**
 * Proposal H D19 (docs/proposals/proposal-h-display-layout-spec.md's ADDENDUM) - the right rail's
 * "Card Spacing (mm)" control group: independent Horizontal (X -> `spacing.col`, the gutter
 * between columns) / Vertical (Y -> `spacing.row`, the gutter between rows) numeric inputs, plus
 * a LINK/UNLINK toggle. Extracted as its own component (rather than inlined into DisplayPage.tsx's
 * already-large right rail) so the link/unlink behavior - the one genuinely new interaction here -
 * has a plain React Testing Library unit-test target instead of needing a full DisplayPage
 * render (see CardSpacingControl.test.tsx).
 *
 * Opens UNLINKED every mount (D19: "linking...is an opt-in convenience, not the initial state,"
 * chosen because the D18 defaults are asymmetric - 0 / 14.5 - so linking would silently discard
 * that asymmetry the moment the control renders if it opened linked). The linked/unlinked toggle
 * itself is therefore local, session-only UI state, not persisted; only the numeric row/col
 * VALUES persist per deck (DisplayPage.tsx wires those through the `cardSpacingSlice` redux slice
 * -> deckPayload.ts, mirroring finishSettingsSlice's own persistence precedent - see that slice's
 * own module comment).
 *
 * PROVENANCE (verbatim discipline, docs/upstreaming/license-provenance.md's absorption posture):
 * this control's link/unlink BEHAVIOR is emulated from an owner-provided screenshot description
 * of an AGPL-licensed proxy-PDF tool - patterns only, no source code was consulted or is
 * consultable (AGPL). No code was reused from that tool; this is a from-scratch implementation.
 */
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";

import { CardSpacingState } from "@/common/types";

export interface CardSpacingControlProps {
  spacing: CardSpacingState;
  onChangeCol: (value: number) => void;
  onChangeRow: (value: number) => void;
}

export function CardSpacingControl({
  spacing,
  onChangeCol,
  onChangeRow,
}: CardSpacingControlProps) {
  const [linked, setLinked] = useState(false);

  const handleColChange = (value: number) => {
    onChangeCol(value);
    if (linked) {
      onChangeRow(value);
    }
  };
  const handleRowChange = (value: number) => {
    onChangeRow(value);
    if (linked) {
      onChangeCol(value);
    }
  };
  const toggleLinked = () => {
    setLinked((previous) => {
      const next = !previous;
      // Mirrors the owner-described tool's own "collapse to a single value on link" behavior -
      // Horizontal (X) drives Vertical (Y) the instant linking turns on, rather than waiting for
      // the next edit to notice the two axes disagree (D19: "Linked ⇒ one value drives both").
      if (next) {
        onChangeRow(spacing.col);
      }
      return next;
    });
  };

  return (
    <div className="mt-3" data-testid="display-spacing-group">
      <div className="d-flex justify-content-between align-items-center mb-1">
        <span className="small">Card spacing (mm)</span>
        <Button
          size="sm"
          variant={linked ? "primary" : "outline-secondary"}
          onClick={toggleLinked}
          aria-pressed={linked}
          data-testid="display-spacing-link-toggle"
          title="Linked: one value drives both axes. Unlinked: X and Y independent (default 0 / 14.5)."
        >
          {linked ? "🔗 Linked" : "🔗 Link"}
        </Button>
      </div>
      <div className="d-flex gap-2 mb-1">
        <Form.Group className="flex-fill">
          <Form.Label className="small mb-1">Horizontal (X)</Form.Label>
          <Form.Control
            size="sm"
            type="number"
            min={0}
            step={0.5}
            value={spacing.col}
            onChange={(event) => {
              const value = parseFloat(event.target.value);
              if (!Number.isNaN(value)) {
                handleColChange(value);
              }
            }}
            aria-label="Horizontal card spacing (mm)"
            data-testid="display-spacing-x"
          />
        </Form.Group>
        <Form.Group className="flex-fill">
          <Form.Label className="small mb-1">Vertical (Y)</Form.Label>
          <Form.Control
            size="sm"
            type="number"
            min={0}
            step={0.5}
            value={spacing.row}
            onChange={(event) => {
              const value = parseFloat(event.target.value);
              if (!Number.isNaN(value)) {
                handleRowChange(value);
              }
            }}
            aria-label="Vertical card spacing (mm)"
            data-testid="display-spacing-y"
          />
        </Form.Group>
      </div>
      <div className="text-muted small">
        Separate axes ease cutting — 0 horizontal butts columns for strip
        cutting; a vertical gap suits die cutters.
      </div>
    </div>
  );
}
