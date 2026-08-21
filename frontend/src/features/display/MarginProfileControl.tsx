/**
 * Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md's ADDENDUM) - the right rail's
 * "Margin profile" Page Setup control: a named-preset `Form.Select` (Borderless / Bordered /
 * Rear-feed, see `marginProfiles.ts`) plus the profile's own plain-language trade-off note.
 * Extracted as its own component (mirrors `CardSpacingControl.tsx`'s own precedent) so profile
 * selection has a plain unit-test target without needing a full DisplayPage render.
 *
 * This control used to also compare the current bleed edge against the selected profile's D6-
 * table cap and render a soft warning when it was exceeded - a boolean that could only say
 * *whether* the requested bleed didn't fit, never *how much* actually rendered. That comparison
 * (and the `bleedEdgeMM`/`pageWidthMM`/`cardWidthMM`/`spacingColMM` props it needed) is gone: the
 * granted-vs-requested readout (`BleedGrantedReadout.tsx`, reading `computeLayout`'s own output
 * directly) states the real per-edge number instead, which makes a same-information boolean
 * redundant rather than merely stale.
 */
import React from "react";
import Form from "react-bootstrap/Form";

import { MarginProfileKey } from "@/common/types";
import { MARGIN_PROFILES } from "@/features/display/marginProfiles";

export interface MarginProfileControlProps {
  profile: MarginProfileKey;
  onChange: (profile: MarginProfileKey) => void;
}

export function MarginProfileControl({
  profile,
  onChange,
}: MarginProfileControlProps) {
  const definition = MARGIN_PROFILES[profile];

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
        className="text-muted small mt-1"
        data-testid="display-margin-profile-note"
      >
        {definition.description}
      </div>
    </Form.Group>
  );
}
