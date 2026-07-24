/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2, OWNER AMENDMENT 2/OQ-B) - component-level
 * coverage for the shared apply-all/set-default prompt: the two entries' distinct copy/chrome
 * (toolbar's "Not now" skip link vs. rail's never-pre-checked trap-guard line), the done-state
 * flip on each button, and the OWNER AMENDMENT 2 thumbnail grid.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { CardbackApplyPrompt } from "@/features/card/CardbackApplyPrompt";

describe("CardbackApplyPrompt", () => {
  test("toolbar entry: project-wide copy, a 'Not now' skip link, no trap-guard note", () => {
    const onDismiss = jest.fn();
    render(
      <CardbackApplyPrompt
        entry="toolbar"
        affectedCount={3}
        customBackThumbnails={[]}
        onApplyAll={jest.fn()}
        onSetDefault={jest.fn()}
        onDismiss={onDismiss}
      />
    );

    expect(
      screen.getByText(/Set as this project’s cardback/)
    ).toBeInTheDocument();
    expect(screen.getByTestId("cardback-apply-all-button")).toHaveTextContent(
      "Apply to all (3)"
    );
    expect(screen.queryByTestId("cardback-apply-prompt-trapnote")).toBeNull();
    expect(
      screen.getByTestId("cardback-apply-prompt-not-now")
    ).toBeInTheDocument();
  });

  test("rail entry: per-slot copy, the never-pre-checked trap-guard note, no skip link", () => {
    render(
      <CardbackApplyPrompt
        entry="rail"
        affectedCount={6}
        customBackThumbnails={[]}
        onApplyAll={jest.fn()}
        onSetDefault={jest.fn()}
      />
    );

    expect(
      screen.getByText(/Applied to this slot’s back only/)
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("cardback-apply-prompt-trapnote")
    ).toHaveTextContent(/never pre-checked/);
    expect(screen.queryByTestId("cardback-apply-prompt-not-now")).toBeNull();
  });

  test("apply-all button is never pre-checked/done, and flips to a done state only after a real click", async () => {
    const user = userEvent.setup();
    const onApplyAll = jest.fn();
    render(
      <CardbackApplyPrompt
        entry="rail"
        affectedCount={6}
        customBackThumbnails={[]}
        onApplyAll={onApplyAll}
        onSetDefault={jest.fn()}
      />
    );

    const applyButton = screen.getByTestId("cardback-apply-all-button");
    expect(applyButton).toHaveTextContent("Apply to all (6)");
    expect(onApplyAll).not.toHaveBeenCalled();

    await user.click(applyButton);

    expect(onApplyAll).toHaveBeenCalledTimes(1);
    expect(applyButton).toHaveTextContent("Applied to all ✓");
  });

  test("set-default button flips to a done state independently of apply-all (two distinct, individually-skippable actions)", async () => {
    const user = userEvent.setup();
    const onSetDefault = jest.fn();
    render(
      <CardbackApplyPrompt
        entry="toolbar"
        affectedCount={1}
        customBackThumbnails={[]}
        onApplyAll={jest.fn()}
        onSetDefault={onSetDefault}
        onDismiss={jest.fn()}
      />
    );

    const defaultButton = screen.getByTestId("cardback-set-default-button");
    await user.click(defaultButton);

    expect(onSetDefault).toHaveBeenCalledTimes(1);
    expect(defaultButton).toHaveTextContent("Default set ✓");
    // The apply-all button is untouched - the two choices are independent.
    expect(screen.getByTestId("cardback-apply-all-button")).toHaveTextContent(
      "Apply to all (1)"
    );
  });

  test("OWNER AMENDMENT 2 - renders a thumbnail (front + current custom back) for every affected slot, above the count line", () => {
    render(
      <CardbackApplyPrompt
        entry="toolbar"
        affectedCount={2}
        customBackThumbnails={[
          {
            slotLabel: "Slot 2",
            frontThumbnailUrl: "https://example.com/front-2.png",
            frontName: "Front 2",
            backThumbnailUrl: "https://example.com/back-2.png",
            backName: "Back 2",
          },
          {
            slotLabel: "Slot 5",
            frontThumbnailUrl: undefined,
            frontName: undefined,
            backThumbnailUrl: "https://example.com/back-5.png",
            backName: "Back 5",
          },
        ]}
        onApplyAll={jest.fn()}
        onSetDefault={jest.fn()}
        onDismiss={jest.fn()}
      />
    );

    const thumbnails = screen.getByTestId("cardback-apply-prompt-thumbnails");
    expect(thumbnails).toHaveTextContent("Slot 2");
    expect(thumbnails).toHaveTextContent("Slot 5");
    // also overrides copy names the count.
    expect(screen.getByText(/also overrides 2 cards/)).toBeInTheDocument();
  });

  test("renders no thumbnail grid when nothing is currently custom", () => {
    render(
      <CardbackApplyPrompt
        entry="toolbar"
        affectedCount={0}
        customBackThumbnails={[]}
        onApplyAll={jest.fn()}
        onSetDefault={jest.fn()}
        onDismiss={jest.fn()}
      />
    );

    expect(screen.queryByTestId("cardback-apply-prompt-thumbnails")).toBeNull();
  });
});
