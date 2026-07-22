/**
 * The /display left rail's promoted confidence element (editor-completion package, D14/E2#3,
 * L3). Per the task's own scope for this round, this is the PLACEHOLDER cut of D14 - the visual
 * slot (SetIcon + resolved/suggested read + a "not this printing" affordance) rather than the
 * full interactive version the design spec's own E2#3 describes (a live Scryfall-hover popover +
 * a real `useTagVoting` vote dispatch on "not this printing"). Deliberately narrower, not
 * silently different: the "not this printing" button renders disabled with an explanatory title,
 * and there's no image-hover popover - wiring either up to the real vote/Scryfall-image path is
 * left to a follow-up round, flagged in this task's own report.
 *
 * Renders nothing when there's no printing-identity signal to show at all (no cardDocument, or
 * neither a resolved canonicalCard nor a suggestedCanonicalCard) - same "never guess" precedent
 * ArtistSection.tsx and PrintOptionsSection.tsx already follow for a card that isn't resolved yet.
 */
import React from "react";

import { CardDocument } from "@/common/types";
import { SetIcon } from "@/components/SetIcon";

interface ConfidenceElementProps {
  cardDocument: CardDocument | undefined;
}

export function ConfidenceElement({ cardDocument }: ConfidenceElementProps) {
  if (cardDocument == null) {
    return null;
  }

  const resolvedPrinting = cardDocument.canonicalCard;
  const suggestedPrinting = cardDocument.suggestedCanonicalCard;
  const printing = resolvedPrinting ?? suggestedPrinting;
  if (printing == null) {
    return null;
  }

  const status: "confirmed" | "suggested" =
    resolvedPrinting != null ? "confirmed" : "suggested";

  return (
    <div className="confidence" data-testid="display-confidence-element">
      <span className="set-symbol" data-testid="display-confidence-set-symbol">
        <SetIcon expansionCode={printing.expansionCode} />
      </span>
      <span>
        {printing.expansionCode.toUpperCase()} · {printing.collectorNumber}
      </span>
      <span className={`conf-badge ${status}`}>
        {status === "confirmed" ? "Confirmed" : "Suggested"}
      </span>
      {status === "suggested" && (
        <button
          type="button"
          className="conf-x"
          disabled
          title="Casting a real vote from here is a follow-up round - see docs/features/printing-tags.md"
          data-testid="display-confidence-not-this-printing"
        >
          ✗ not this printing
        </button>
      )}
    </div>
  );
}
