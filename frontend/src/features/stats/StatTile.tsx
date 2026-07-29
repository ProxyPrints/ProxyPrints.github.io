/**
 * A single raw-count stat tile - plain number + label, no chart. Per the dataviz skill's own
 * form heuristic, "a single number is a stat tile, not a chart" - used throughout the
 * participation (call-to-action) panel, which is deliberately all raw counts (no percentage, see
 * ParticipationPanel.tsx's own comment).
 */
import React from "react";

interface StatTileProps {
  label: string;
  value: string;
  emphasize?: boolean;
  testId?: string;
}

export function StatTile({
  label,
  value,
  emphasize = false,
  testId,
}: StatTileProps) {
  return (
    <div className="d-flex flex-column" data-testid={testId}>
      <span
        style={{
          fontSize: emphasize ? "2.25rem" : "1.5rem",
          fontWeight: 700,
          color: emphasize ? "var(--bs-primary)" : "var(--theme-text)",
          lineHeight: 1.1,
        }}
      >
        {value}
      </span>
      <span className="text-muted" style={{ fontSize: "0.85rem" }}>
        {label}
      </span>
    </div>
  );
}
