/**
 * Proposal H D19 (docs/proposals/proposal-h-display-layout-spec.md's ADDENDUM) - unit coverage
 * for the one genuinely new interaction in the Card Spacing control: the link/unlink toggle.
 * Plain props in, plain callbacks out (no redux store needed) - DisplayPage.tsx wires the real
 * `cardSpacingSlice` dispatches, which is exactly why this logic was extracted into its own
 * component in the first place (see CardSpacingControl.tsx's own module comment).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { CardSpacingControl } from "./CardSpacingControl";

function renderControl(spacing = { row: 14.5, col: 0 }) {
  const onChangeCol = jest.fn();
  const onChangeRow = jest.fn();
  render(
    <CardSpacingControl
      spacing={spacing}
      onChangeCol={onChangeCol}
      onChangeRow={onChangeRow}
    />
  );
  return { onChangeCol, onChangeRow };
}

describe("CardSpacingControl", () => {
  it("renders the D18 default values and opens UNLINKED", () => {
    renderControl();
    expect(screen.getByTestId("display-spacing-x")).toHaveValue(0);
    expect(screen.getByTestId("display-spacing-y")).toHaveValue(14.5);
    expect(screen.getByTestId("display-spacing-link-toggle")).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });

  it("while unlinked, editing one axis never calls the other axis's callback", () => {
    const { onChangeCol, onChangeRow } = renderControl();

    fireEvent.change(screen.getByTestId("display-spacing-x"), {
      target: { value: "2" },
    });
    expect(onChangeCol).toHaveBeenCalledWith(2);
    expect(onChangeRow).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("display-spacing-y"), {
      target: { value: "10" },
    });
    expect(onChangeRow).toHaveBeenCalledWith(10);
    // Still not called as a SIDE EFFECT of the X edit above - only its own edit above.
    expect(onChangeCol).toHaveBeenCalledTimes(1);
  });

  it("turning Link ON immediately collapses Vertical (Y) to the current Horizontal (X) value", () => {
    const { onChangeRow } = renderControl({ row: 14.5, col: 3 });

    fireEvent.click(screen.getByTestId("display-spacing-link-toggle"));

    expect(onChangeRow).toHaveBeenCalledWith(3);
    expect(screen.getByTestId("display-spacing-link-toggle")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("once linked, editing either axis writes BOTH callbacks with the same value", () => {
    const { onChangeCol, onChangeRow } = renderControl();
    fireEvent.click(screen.getByTestId("display-spacing-link-toggle"));
    onChangeRow.mockClear();
    onChangeCol.mockClear();

    fireEvent.change(screen.getByTestId("display-spacing-x"), {
      target: { value: "5" },
    });
    expect(onChangeCol).toHaveBeenCalledWith(5);
    expect(onChangeRow).toHaveBeenCalledWith(5);

    fireEvent.change(screen.getByTestId("display-spacing-y"), {
      target: { value: "9" },
    });
    expect(onChangeRow).toHaveBeenCalledWith(9);
    expect(onChangeCol).toHaveBeenCalledWith(9);
  });

  it("toggling Link back OFF returns to independent axes with no further cross-writes", () => {
    const { onChangeCol, onChangeRow } = renderControl();
    const toggle = screen.getByTestId("display-spacing-link-toggle");
    fireEvent.click(toggle); // on
    fireEvent.click(toggle); // off again
    onChangeCol.mockClear();
    onChangeRow.mockClear();

    fireEvent.change(screen.getByTestId("display-spacing-x"), {
      target: { value: "7" },
    });
    expect(onChangeCol).toHaveBeenCalledWith(7);
    expect(onChangeRow).not.toHaveBeenCalled();
  });
});
