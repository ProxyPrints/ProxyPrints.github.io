/**
 * Unit coverage for the margin-profile Page Setup control: the profile select fires onChange
 * with the right key, and each profile's own description renders. Plain props in, plain callback
 * out (no redux store needed) - mirrors CardSpacingControl.test.tsx's own precedent.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { MarginProfileControl } from "./MarginProfileControl";
import { MARGIN_PROFILES } from "./marginProfiles";

function renderControl(
  profile: "borderless" | "bordered" | "rearFeed" = "rearFeed"
) {
  const onChange = jest.fn();
  render(<MarginProfileControl profile={profile} onChange={onChange} />);
  return { onChange };
}

describe("MarginProfileControl", () => {
  it("renders the given profile as selected", () => {
    renderControl("rearFeed");
    expect(screen.getByTestId("display-margin-profile-select")).toHaveValue(
      "rearFeed"
    );
  });

  it("selecting a different profile calls onChange with that profile's key", () => {
    const { onChange } = renderControl("rearFeed");
    fireEvent.change(screen.getByTestId("display-margin-profile-select"), {
      target: { value: "borderless" },
    });
    expect(onChange).toHaveBeenCalledWith("borderless");
  });

  it("lists every margin profile as a select option", () => {
    renderControl();
    Object.values(MARGIN_PROFILES).forEach((definition) => {
      expect(
        screen.getByRole("option", { name: definition.label })
      ).toBeInTheDocument();
    });
  });

  it("shows the selected profile's own trade-off description, not another profile's", () => {
    renderControl("bordered");
    const note = screen.getByTestId("display-margin-profile-note");
    expect(note).toHaveTextContent(MARGIN_PROFILES.bordered.description);
    expect(note).not.toHaveTextContent(MARGIN_PROFILES.borderless.description);
  });

  it("renders no boolean cap warning - the granted-vs-requested readout replaces it", () => {
    renderControl("rearFeed");
    expect(
      screen.getByTestId("display-margin-profile-note")
    ).not.toHaveTextContent("⚠");
  });
});
