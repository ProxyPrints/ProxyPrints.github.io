import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { PostExportContributionPrompt } from "@/features/export/PostExportContributionPrompt";
import { resetPostExportContributionPromptSessionFlag } from "@/features/export/postExportContributionPrompt";
import { usePostExportContributionPrompt } from "@/features/export/usePostExportContributionPrompt";

// Harness pattern mirrors useConsentToast.test.tsx's own precedent for testing a hook's
// stateful behaviour through the real component tree, since the auto-dismiss timer and the
// "never repeats this session" flag both live in the hook, not the presentational component.
function Harness() {
  const prompt = usePostExportContributionPrompt();
  return (
    <div>
      <button
        data-testid="export-succeeded"
        onClick={prompt.notifyExportSucceeded}
      >
        Export
      </button>
      <PostExportContributionPrompt
        show={prompt.visible}
        onDismiss={prompt.dismiss}
      />
    </div>
  );
}

describe("usePostExportContributionPrompt", () => {
  beforeEach(() => {
    resetPostExportContributionPromptSessionFlag();
  });

  afterEach(() => {
    resetPostExportContributionPromptSessionFlag();
  });

  test("shows the prompt after a PDF export succeeds, then auto-dismisses after its delay", () => {
    jest.useFakeTimers();
    render(<Harness />);

    expect(
      screen.queryByTestId("post-export-contribution-prompt")
    ).not.toBeInTheDocument();

    act(() => {
      fireEvent.click(screen.getByTestId("export-succeeded"));
    });

    expect(
      screen.getByTestId("post-export-contribution-prompt")
    ).toBeInTheDocument();

    // Still present well before the auto-dismiss delay elapses.
    act(() => {
      jest.advanceTimersByTime(10000);
    });
    expect(
      screen.getByTestId("post-export-contribution-prompt")
    ).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(15000);
    });
    expect(
      screen.queryByTestId("post-export-contribution-prompt")
    ).not.toBeInTheDocument();

    jest.useRealTimers();
  });

  test("a manual dismiss removes the prompt immediately", () => {
    render(<Harness />);

    fireEvent.click(screen.getByTestId("export-succeeded"));
    screen.getByTestId("post-export-contribution-prompt");

    fireEvent.click(screen.getByRole("button", { name: "Close alert" }));

    expect(
      screen.queryByTestId("post-export-contribution-prompt")
    ).not.toBeInTheDocument();
  });
});
