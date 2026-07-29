/**
 * Proposal F chart 4 - `CardScanLog.skip_reason`, grouped by reason (single-series ranked
 * comparison, one flat colour - no legend needed, an axis of reasons already names each bar), and
 * by reason + engine (stacked by engine within each reason - a real legend here, since engine is
 * an identity dimension). Both come back from the backend already sorted by count descending
 * (ties broken alphabetically by reason) - see MPCAutofill/cardpicker/catalog_stats.py's
 * `compute_skip_breakdown` docstring - so this panel doesn't re-sort `byReason`.
 */
import React from "react";

import { SkipBreakdown, SkipReasonEngineCount } from "@/common/schema_types";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";

function byReasonRows(byReason: SkipBreakdown["byReason"]): BarRow[] {
  return byReason.map((row) => ({
    label: row.reason,
    segments: [{ key: row.reason, label: row.reason, value: row.count }],
  }));
}

/**
 * Pivots the flat (reason, engine, count) list into one row per reason, stacked-by-engine -
 * rows are re-sorted by each reason's own total descending (the flat list's own count-desc sort
 * interleaves reasons/engines, not grouped by reason), never by input order.
 */
function byReasonAndEngineRows(
  byReasonAndEngine: SkipReasonEngineCount[]
): BarRow[] {
  const segmentsByReason = new Map<
    string,
    { key: string; label: string; value: number }[]
  >();
  const totalByReason = new Map<string, number>();
  byReasonAndEngine.forEach(({ reason, engine, count }) => {
    totalByReason.set(reason, (totalByReason.get(reason) ?? 0) + count);
    const segments = segmentsByReason.get(reason) ?? [];
    segments.push({ key: engine, label: engine, value: count });
    segmentsByReason.set(reason, segments);
  });
  return Array.from(segmentsByReason.entries())
    .sort(
      ([reasonA], [reasonB]) =>
        (totalByReason.get(reasonB) ?? 0) - (totalByReason.get(reasonA) ?? 0)
    )
    .map(([reason, segments]) => ({ label: reason, segments }));
}

export function SkipBreakdownPanel({
  skipBreakdown,
}: {
  skipBreakdown: SkipBreakdown;
}) {
  const engineKeys = Array.from(
    new Set(skipBreakdown.byReasonAndEngine.map((row) => row.engine))
  );

  return (
    <section data-testid="skip-breakdown-panel" className="mb-5">
      <h2>Why the machine calculators abstained</h2>
      <p className="text-muted">
        Every card a calculator looked at and declined to vote on, grouped by
        reason.
      </p>
      <h3 className="h5">By reason</h3>
      <HorizontalBarChart
        title="Skips by reason"
        bars={byReasonRows(skipBreakdown.byReason)}
        emptyMessage="No skip-log rows recorded yet."
      />
      <h3 className="h5 mt-4">By reason and engine</h3>
      <HorizontalBarChart
        title="Skips by reason, by engine"
        bars={byReasonAndEngineRows(skipBreakdown.byReasonAndEngine)}
        legendKeys={engineKeys}
        emptyMessage="No skip-log rows recorded yet."
      />
    </section>
  );
}
