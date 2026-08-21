/**
 * The right rail's Page Setup section shows a "Bleed edge (mm)" input, but the number typed
 * there is only ever a REQUEST - `computeLayout` (`features/pdf/layout.ts`) grants each axis up
 * to that much bleed given the current page size, margin profile, and spacing, never more (see
 * `LayoutSlot.bleedMM`'s own comment). Nothing on screen used to say what was actually granted,
 * so a user could print for months against a bleed number the geometry never delivered. This
 * component is that missing readout: purely presentational, read-only derived state - it renders
 * exactly the per-edge numbers `computeLayout` already returned for the caller's own slot, never
 * recomputing the fit itself (that would risk a second, driftable copy of the same math).
 *
 * Left/right and top/bottom are always equal within a single `LayoutEdgeBleed` (one value per
 * AXIS, not per slot - see that type's own comment), so only two numbers ever need showing.
 */
import React from "react";

import { LayoutEdgeBleed } from "@/features/pdf/layout";

export interface BleedGrantedReadoutProps {
  requestedBleedMM: number;
  grantedBleedMM: LayoutEdgeBleed;
}

// Floating-point slack, not a real design tolerance - guards the "cropped" callout against
// flagging a granted value that's actually equal to the request but landed a few ULPs short of
// it after the water-filling division in fitAxisWithBleed.
const EPSILON_MM = 1e-6;

export function BleedGrantedReadout({
  requestedBleedMM,
  grantedBleedMM,
}: BleedGrantedReadoutProps) {
  const horizontalMM = grantedBleedMM.left;
  const verticalMM = grantedBleedMM.top;
  const horizontalCropped = horizontalMM < requestedBleedMM - EPSILON_MM;
  const verticalCropped = verticalMM < requestedBleedMM - EPSILON_MM;

  return (
    <div
      className="text-muted small mt-1"
      data-testid="display-bleed-granted-readout"
    >
      Granted: <strong>{horizontalMM.toFixed(3)}mm</strong> left/right edges
      {horizontalCropped && " (cropped)"} ·{" "}
      <strong>{verticalMM.toFixed(3)}mm</strong> top/bottom
      {verticalCropped && " (cropped)"}
    </div>
  );
}
