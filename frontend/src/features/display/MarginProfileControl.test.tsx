/**
 * Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md's ADDENDUM) - unit coverage
 * for the margin-profile Page Setup control: the profile select fires onChange with the right
 * key, and the warning note appears ONLY when the current bleed edge exceeds the selected
 * profile's cap - never a hard clamp (the task's own instruction). Plain props in, plain
 * callback out (no redux store needed) - mirrors CardSpacingControl.test.tsx's own precedent.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { MarginProfileControl } from "./MarginProfileControl";

const PAGE_WIDTH_MM = 279.4; // US Letter landscape width
const CARD_WIDTH_MM = 63;

function renderControl(
  profile: "borderless" | "bordered" | "rearFeed" = "borderless",
  bleedEdgeMM = 3.175
) {
  const onChange = jest.fn();
  render(
    <MarginProfileControl
      profile={profile}
      onChange={onChange}
      bleedEdgeMM={bleedEdgeMM}
      pageWidthMM={PAGE_WIDTH_MM}
      cardWidthMM={CARD_WIDTH_MM}
      spacingColMM={0}
    />
  );
  return { onChange };
}

describe("MarginProfileControl", () => {
  it("renders the Borderless default with no warning at the D6 default bleed (3.175mm)", () => {
    renderControl("borderless", 3.175);
    expect(screen.getByTestId("display-margin-profile-select")).toHaveValue(
      "borderless"
    );
    expect(
      screen.getByTestId("display-margin-profile-note")
    ).not.toHaveTextContent("⚠");
  });

  it("selecting a different profile calls onChange with that profile's key", () => {
    const { onChange } = renderControl();
    fireEvent.change(screen.getByTestId("display-margin-profile-select"), {
      target: { value: "bordered" },
    });
    expect(onChange).toHaveBeenCalledWith("bordered");
  });

  it("warns (never clamps) when the current bleed exceeds the Bordered profile's cap at the D6 default bleed", () => {
    renderControl("bordered", 3.175);
    const note = screen.getByTestId("display-margin-profile-note");
    expect(note).toHaveTextContent("⚠");
    // No clamping behaviour exists to assert against - there is no bleed input in this
    // component at all; the caller's own bleed Form.Control has no `max` prop (DisplayPage.tsx),
    // which is the actual "never clamps" contract this control's warning exists to make visible.
  });

  it("warns even harder under the Rear-feed profile at the same bleed", () => {
    renderControl("rearFeed", 3.175);
    expect(screen.getByTestId("display-margin-profile-note")).toHaveTextContent(
      "⚠"
    );
  });

  it("shows no warning under Borderless even at a bleed below its own (higher) cap", () => {
    renderControl("borderless", 1);
    expect(
      screen.getByTestId("display-margin-profile-note")
    ).not.toHaveTextContent("⚠");
  });
});
