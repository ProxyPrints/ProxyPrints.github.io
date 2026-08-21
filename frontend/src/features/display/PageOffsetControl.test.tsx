/**
 * Plain props in, plain callback out - mirrors CardSpacingControl.test.tsx's own precedent.
 * The key behavior under test is the ABSENCE of any clamping: this control has no `min`/`max`
 * on either input, unlike CardSpacingControl's `min={0}` (spacing can't be negative; a
 * registration offset legitimately can be, in either direction).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { PageOffsetControl } from "./PageOffsetControl";

function renderControl(offsetXMM = 0, offsetYMM = 0) {
  const onChangeX = jest.fn();
  const onChangeY = jest.fn();
  render(
    <PageOffsetControl
      offsetXMM={offsetXMM}
      offsetYMM={offsetYMM}
      onChangeX={onChangeX}
      onChangeY={onChangeY}
    />
  );
  return { onChangeX, onChangeY };
}

describe("PageOffsetControl", () => {
  it("defaults to 0/0 and renders both axis inputs", () => {
    renderControl();
    expect(screen.getByTestId("display-page-offset-x")).toHaveValue(0);
    expect(screen.getByTestId("display-page-offset-y")).toHaveValue(0);
  });

  it("calls onChangeX with a large, unclamped value - no max exists to cap it", () => {
    const { onChangeX } = renderControl();
    fireEvent.change(screen.getByTestId("display-page-offset-x"), {
      target: { value: "50" },
    });
    expect(onChangeX).toHaveBeenCalledWith(50);
  });

  it("calls onChangeY with a negative value - offset may go either direction", () => {
    const { onChangeY } = renderControl();
    fireEvent.change(screen.getByTestId("display-page-offset-y"), {
      target: { value: "-15" },
    });
    expect(onChangeY).toHaveBeenCalledWith(-15);
  });

  it("has no min/max attribute on either input", () => {
    renderControl();
    expect(screen.getByTestId("display-page-offset-x")).not.toHaveAttribute(
      "min"
    );
    expect(screen.getByTestId("display-page-offset-x")).not.toHaveAttribute(
      "max"
    );
    expect(screen.getByTestId("display-page-offset-y")).not.toHaveAttribute(
      "min"
    );
    expect(screen.getByTestId("display-page-offset-y")).not.toHaveAttribute(
      "max"
    );
  });
});
