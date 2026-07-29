/**
 * Proposal F chart 6 - recent pilot runs. A plain chronological list with a status dot (the
 * mock's own "✓ completed ✓ completed ✗ failed" treatment), not a chart - `runHistory` is
 * inherently a log, not a magnitude/identity comparison.
 *
 * `votesWritten` IS `null` FOR `command="stage_e_streaming_dispatch"` ROWS - a real, documented
 * observability gap (see MPCAutofill/cardpicker/catalog_stats.py's `compute_run_history`
 * docstring), not missing data to backfill as zero. `formatNullableCount` below renders it as
 * "—", never "0" - a reader must be able to tell "we don't know" apart from "zero votes written".
 * Same treatment for `durationSeconds`, null while a run is still going (or crashed before
 * `finished_at` was ever set).
 */
import React from "react";

import { PilotRunHistoryEntry } from "@/common/schema_types";
import { colorForRunStatus } from "@/features/stats/colors";
import { formatDuration } from "@/features/stats/format";

function formatNullableCount(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

function formatNullableDuration(value: number | null): string {
  return value === null ? "—" : formatDuration(value);
}

function StatusDot({ status }: { status: string }) {
  return (
    <span
      aria-hidden="true"
      data-testid="run-status-dot"
      title={status}
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        backgroundColor: colorForRunStatus(status),
        marginRight: 8,
      }}
    />
  );
}

function RunRow({ run }: { run: PilotRunHistoryEntry }) {
  const startedAt = new Date(run.startedAt);
  return (
    <li
      className="d-flex align-items-center gap-3 py-2 border-bottom"
      style={{ borderColor: "var(--theme-divider)" }}
      data-testid="run-history-row"
    >
      <StatusDot status={run.status} />
      <span className="flex-grow-1">
        <b>{run.command}</b> <span className="text-muted">({run.status})</span>
        <br />
        <span className="text-muted" style={{ fontSize: "0.85rem" }}>
          {Number.isNaN(startedAt.getTime())
            ? run.startedAt
            : startedAt.toLocaleString()}
        </span>
      </span>
      <span className="text-muted" style={{ fontSize: "0.85rem" }}>
        duration: {formatNullableDuration(run.durationSeconds)}
      </span>
      <span
        className="text-muted"
        style={{ fontSize: "0.85rem" }}
        data-testid="run-history-votes-written"
      >
        votes written: {formatNullableCount(run.votesWritten)}
      </span>
    </li>
  );
}

export function RunHistoryPanel({
  recent,
}: {
  recent: PilotRunHistoryEntry[];
}) {
  return (
    <section data-testid="run-history-panel" className="mb-5">
      <h2>Recent pilot runs</h2>
      {recent.length === 0 ? (
        <p className="text-muted">No pilot runs recorded yet.</p>
      ) : (
        <ul className="list-unstyled" data-testid="run-history-list">
          {recent.map((run) => (
            <RunRow key={run.runId} run={run} />
          ))}
        </ul>
      )}
    </section>
  );
}
