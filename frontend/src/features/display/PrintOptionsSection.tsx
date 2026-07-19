/**
 * The display page rail's Print Options accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Per-card manual bleed
 * override (Auto / Force bleed / Force trimmed), reusing PDFGenerator.tsx's "Bleed Overrides"
 * panel machinery directly rather than a second implementation: the same projectSlice
 * selector/action (selectManualOverrides/setManualOverride) and the same eligibility rule
 * (PDF.tsx's isBleedNormalizationEligible - full-resolution Google Drive/local-file images only,
 * the two sources that carry a real, decodable full-res bitmap bleed normalization can measure).
 *
 * The design doc's own stub comment (§5, this section's row) originally flagged this as blocked
 * on "Proposal B PR-2 actually landing the control + projectSlice persistence" - both shipped
 * (see docs/features/pdf-generator.md's Proposal B status: "complete end to end"), so this
 * section is real, not another stub.
 */
import React from "react";
import Form from "react-bootstrap/Form";

import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { ManualOverride } from "@/features/pdf/bleedNormalize";
import { isBleedNormalizationEligible } from "@/features/pdf/PDF";
import {
  selectManualOverrides,
  setManualOverride,
} from "@/store/slices/projectSlice";

interface PrintOptionsSectionProps {
  cardDocument: CardDocument | undefined;
}

export function PrintOptionsSection({
  cardDocument,
}: PrintOptionsSectionProps) {
  const dispatch = useAppDispatch();
  const manualOverrides = useAppSelector(selectManualOverrides);

  if (cardDocument == null) {
    return (
      <p className="text-muted small mb-0">
        Select an image for this slot first.
      </p>
    );
  }

  // This page always exports at full-resolution (DisplayPage.tsx's own exportPdfProps) - matches
  // the same "full-resolution" literal BleedOverrideSettings' eligible-card list already assumes.
  if (!isBleedNormalizationEligible(cardDocument, "full-resolution")) {
    return (
      <p className="text-muted small mb-0">
        Bleed is measured automatically at export; this card doesn&apos;t
        support manual override (Google Drive / local-file sources only).
      </p>
    );
  }

  return (
    <div data-testid="display-print-options-section">
      <p className="text-muted small">
        Bleed is measured automatically per card at export. Override below if
        the automatic measurement gets it wrong.
      </p>
      <Form.Select
        size="sm"
        data-testid={`bleed-override-select-${cardDocument.identifier}`}
        value={manualOverrides[cardDocument.identifier] ?? "auto"}
        onChange={(event) =>
          dispatch(
            setManualOverride({
              identifier: cardDocument.identifier,
              override: event.target.value as ManualOverride,
            })
          )
        }
      >
        <option value="auto">Auto</option>
        <option value="force-bleed">Force bleed</option>
        <option value="force-trimmed">Force trimmed</option>
      </Form.Select>
    </div>
  );
}
