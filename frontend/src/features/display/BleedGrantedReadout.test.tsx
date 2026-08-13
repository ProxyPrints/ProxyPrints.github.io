/**
 * Verifies the readout against real `computeLayout` output (never hand-typed magic numbers) at
 * US Letter landscape, CardWidthMM=63/CardHeightMM=88, requested bleed 3.175mm, spacing
 * {row: 14.5, col: 0} - the exact combination each margin profile is calibrated against.
 */
import { render, screen } from "@testing-library/react";
import React from "react";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import { MARGIN_PROFILES } from "@/features/display/marginProfiles";
import { computeLayout, LayoutEdgeBleed } from "@/features/pdf/layout";

import { BleedGrantedReadout } from "./BleedGrantedReadout";

const PAGE_WIDTH_MM = 279.4;
const PAGE_HEIGHT_MM = 215.9;
const REQUESTED_BLEED_MM = 3.175;
const SPACING = { row: 14.5, col: 0 };

function grantedFor(profileKey: keyof typeof MARGIN_PROFILES): LayoutEdgeBleed {
  const layout = computeLayout(
    PAGE_WIDTH_MM,
    PAGE_HEIGHT_MM,
    CardWidthMM,
    CardHeightMM,
    REQUESTED_BLEED_MM,
    MARGIN_PROFILES[profileKey].margins,
    SPACING
  );
  return layout.slots[0].bleedMM;
}

function renderReadout(granted: LayoutEdgeBleed) {
  render(
    <BleedGrantedReadout
      requestedBleedMM={REQUESTED_BLEED_MM}
      grantedBleedMM={granted}
    />
  );
  return screen.getByTestId("display-bleed-granted-readout");
}

describe("BleedGrantedReadout - matches computeLayout at each margin profile", () => {
  it("borderless: full requested bleed on every edge (1.9mm slack covers it)", () => {
    const granted = grantedFor("borderless");
    expect(granted.left).toBeCloseTo(3.175, 3);
    expect(granted.top).toBeCloseTo(3.175, 3);
    const readout = renderReadout(granted);
    expect(readout).toHaveTextContent(`${granted.left.toFixed(3)}mm`);
    expect(readout).toHaveTextContent(`${granted.top.toFixed(3)}mm`);
    expect(readout).not.toHaveTextContent("cropped");
  });

  it("bordered: horizontal crops to 2.6625mm, vertical stays at the full 3.175mm request", () => {
    const granted = grantedFor("bordered");
    expect(granted.left).toBeCloseTo(2.6625, 4);
    expect(granted.top).toBeCloseTo(3.175, 3);
    const readout = renderReadout(granted);
    expect(readout).toHaveTextContent(`${granted.left.toFixed(3)}mm`);
    expect(readout).toHaveTextContent("left/right edges (cropped)");
    expect(readout).not.toHaveTextContent("top/bottom (cropped)");
  });

  it("rearFeed (the default profile): horizontal crops to 0.5375mm, vertical still hits the cap at 3.175mm", () => {
    const granted = grantedFor("rearFeed");
    expect(granted.left).toBeCloseTo(0.5375, 4);
    expect(granted.top).toBeCloseTo(3.175, 3);
    const readout = renderReadout(granted);
    expect(readout).toHaveTextContent(`${granted.left.toFixed(3)}mm`);
    expect(readout).toHaveTextContent("left/right edges (cropped)");
    expect(readout).not.toHaveTextContent("top/bottom (cropped)");
  });
});

describe("BleedGrantedReadout - presentation logic in isolation", () => {
  it("flags an axis as cropped only when it actually granted less than requested", () => {
    render(
      <BleedGrantedReadout
        requestedBleedMM={5}
        grantedBleedMM={{ top: 5, bottom: 5, left: 2, right: 2 }}
      />
    );
    const readout = screen.getByTestId("display-bleed-granted-readout");
    expect(readout).toHaveTextContent("2.000mm");
    expect(readout).toHaveTextContent("left/right edges (cropped)");
    expect(readout).toHaveTextContent("5.000mm");
    expect(readout).not.toHaveTextContent("top/bottom (cropped)");
  });

  it("shows no cropped flag on either axis when both meet the request exactly", () => {
    render(
      <BleedGrantedReadout
        requestedBleedMM={3}
        grantedBleedMM={{ top: 3, bottom: 3, left: 3, right: 3 }}
      />
    );
    expect(
      screen.getByTestId("display-bleed-granted-readout")
    ).not.toHaveTextContent("cropped");
  });
});
