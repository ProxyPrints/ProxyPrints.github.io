/**
 * Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md) - the right rail's "Margin
 * profile" Page Setup control: a named-preset `Form.Select` (Borderless / Bordered / Rear-feed,
 * see `marginProfiles.ts`) plus a soft warning (never a hard clamp - the task's own instruction)
 * when the CURRENT bleed edge exceeds the selected profile's D6-table cap for a 4x2 sheet.
 * Extracted as its own component (mirrors `CardSpacingControl.tsx`'s own precedent) so the
 * cap-math/warning behaviour has a plain unit-test target without needing a full DisplayPage
 * render.
 *
 * #301 decision 3 (owner verbatim: "i want the bleed edge warning on the trailing edge rule to
 * allow trimming calculated bleed. include the disclaimer in the warning"): this warning used to
 * describe the pre-#301 rigid layout's actual behavior when the cap was exceeded - dropping the
 * sheet from 4 columns to 3. `layout.ts`'s fit math no longer does that (see `fitAxisWithBleed`'s
 * own comment) - it crops the bleed on the affected edge down to exactly `maxBleedMM` instead,
 * all 4 columns intact. The warning copy below reflects that: it now STATES the actual
 * consequence (bleed cropped to N mm, reduced cutting tolerance on that edge) as a disclaimer,
 * not a vague pointer to "see the warning above" - still never a hard clamp on the bleed input
 * itself (unchanged from before this round).
 */
import React from "react";
import Form from "react-bootstrap/Form";

import { MarginProfileKey } from "@/common/types";
import {
  MARGIN_PROFILES,
  maxBleedForFourColumns,
} from "@/features/display/marginProfiles";

export interface MarginProfileControlProps {
  profile: MarginProfileKey;
  onChange: (profile: MarginProfileKey) => void;
  bleedEdgeMM: number;
  pageWidthMM: number;
  cardWidthMM: number;
  spacingColMM: number;
}

export function MarginProfileControl({
  profile,
  onChange,
  bleedEdgeMM,
  pageWidthMM,
  cardWidthMM,
  spacingColMM,
}: MarginProfileControlProps) {
  const definition = MARGIN_PROFILES[profile];
  const maxBleedMM = maxBleedForFourColumns(
    pageWidthMM,
    definition.margins,
    cardWidthMM,
    spacingColMM
  );
  const exceedsCap = bleedEdgeMM > maxBleedMM;

  return (
    <Form.Group className="mb-2" data-testid="display-margin-profile-group">
      <Form.Label className="small mb-1">Margin profile</Form.Label>
      <Form.Select
        size="sm"
        value={profile}
        onChange={(event) => onChange(event.target.value as MarginProfileKey)}
        aria-label="Margin profile"
        data-testid="display-margin-profile-select"
      >
        {Object.values(MARGIN_PROFILES).map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </Form.Select>
      <div
        className={
          exceedsCap ? "text-warning small mt-1" : "text-muted small mt-1"
        }
        data-testid="display-margin-profile-note"
      >
        {exceedsCap ? (
          <>
            ⚠ Bleed edge ({bleedEdgeMM.toFixed(3)}mm) exceeds this
            profile&apos;s {maxBleedMM.toFixed(3)}mm cap for a 4-across sheet -
            all cards still render at full size; bleed on the affected edge will
            be cropped to {maxBleedMM.toFixed(3)}mm, with reduced cutting
            tolerance on that edge. {definition.description}
          </>
        ) : (
          <>
            Up to {maxBleedMM.toFixed(3)}mm bleed still fits a 4-across sheet.{" "}
            {definition.description}
          </>
        )}
      </div>
    </Form.Group>
  );
}
