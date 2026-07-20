import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { ConsentToast } from "@/features/consent/ConsentToast";

describe("ConsentToast", () => {
  test("renders nothing when show is false", () => {
    render(
      <ConsentToast
        show={false}
        message="We'd like to check your card image against known printings."
        onAccept={jest.fn()}
        onDecline={jest.fn()}
      />
    );
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
  });

  test("renders the caller-supplied message describing the specific action, not a generic notice", () => {
    render(
      <ConsentToast
        show
        title="Help identify this printing?"
        message="We'd like to check your card image against known printings."
        onAccept={jest.fn()}
        onDecline={jest.fn()}
      />
    );
    expect(screen.getByText("Help identify this printing?")).toBeVisible();
    expect(
      screen.getByText(
        "We'd like to check your card image against known printings."
      )
    ).toBeVisible();
  });

  test("exposes an alertdialog role (not a passive alert) since it requires a user decision", () => {
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={jest.fn()}
        onDecline={jest.fn()}
      />
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  test("focuses the accept button when it appears (keyboard/screen-reader affordance)", () => {
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={jest.fn()}
        onDecline={jest.fn()}
      />
    );
    expect(screen.getByTestId("consent-toast-accept")).toHaveFocus();
  });

  test("clicking Allow calls onAccept", () => {
    const onAccept = jest.fn();
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={onAccept}
        onDecline={jest.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("consent-toast-accept"));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  test("clicking No thanks calls onDecline", () => {
    const onDecline = jest.fn();
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={jest.fn()}
        onDecline={onDecline}
      />
    );
    fireEvent.click(screen.getByTestId("consent-toast-decline"));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  test("the header close button also calls onDecline (dismiss counts as decline)", () => {
    const onDecline = jest.fn();
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={jest.fn()}
        onDecline={onDecline}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  test("pressing Escape calls onDecline (keyboard dismissible)", () => {
    const onDecline = jest.fn();
    render(
      <ConsentToast
        show
        message="some specific action"
        onAccept={jest.fn()}
        onDecline={onDecline}
      />
    );
    fireEvent.keyDown(screen.getByTestId("consent-toast-wrapper"), {
      key: "Escape",
    });
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  test("supports custom accept/decline labels", () => {
    render(
      <ConsentToast
        show
        message="some specific action"
        acceptLabel="Yes, help out"
        declineLabel="Not now"
        onAccept={jest.fn()}
        onDecline={jest.fn()}
      />
    );
    expect(screen.getByText("Yes, help out")).toBeVisible();
    expect(screen.getByText("Not now")).toBeVisible();
  });
});
