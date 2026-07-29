import { render, screen } from "@testing-library/react";
import React from "react";

import { PilotRunHistoryEntry } from "@/common/schema_types";

import { RunHistoryPanel } from "./RunHistoryPanel";

const baseRun: PilotRunHistoryEntry = {
  runId: "run-1",
  command: "local_identify_printing_tags",
  status: "completed",
  startedAt: "2026-07-28T01:00:00Z",
  finishedAt: "2026-07-28T01:42:00Z",
  durationSeconds: 2520,
  votesWritten: 1840,
};

describe("RunHistoryPanel", () => {
  it("renders a null votesWritten as '—', never '0' - null is not zero (stage_e_streaming_dispatch rows)", () => {
    const streamingDispatchRun: PilotRunHistoryEntry = {
      ...baseRun,
      runId: "run-2",
      command: "stage_e_streaming_dispatch",
      votesWritten: null,
    };
    render(<RunHistoryPanel recent={[streamingDispatchRun]} />);

    const votesWrittenText = screen.getByTestId("run-history-votes-written");
    expect(votesWrittenText).toHaveTextContent("votes written: —");
    expect(votesWrittenText).not.toHaveTextContent("votes written: 0");
  });

  it("renders a real zero votesWritten as '0', distinct from null", () => {
    const zeroVotesRun: PilotRunHistoryEntry = {
      ...baseRun,
      runId: "run-3",
      votesWritten: 0,
    };
    render(<RunHistoryPanel recent={[zeroVotesRun]} />);

    expect(screen.getByTestId("run-history-votes-written")).toHaveTextContent(
      "votes written: 0"
    );
  });

  it("renders a null durationSeconds as '—' for a still-running row", () => {
    const runningRun: PilotRunHistoryEntry = {
      ...baseRun,
      runId: "run-4",
      status: "running",
      finishedAt: null,
      durationSeconds: null,
      votesWritten: null,
    };
    render(<RunHistoryPanel recent={[runningRun]} />);

    expect(screen.getByText(/duration: —/)).toBeInTheDocument();
  });

  it("renders the empty state when no runs are recorded yet", () => {
    render(<RunHistoryPanel recent={[]} />);
    expect(screen.getByText("No pilot runs recorded yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("run-history-list")).not.toBeInTheDocument();
  });
});
