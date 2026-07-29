/**
 * Proposal F chart 2 - human confirmations bucketed by week, split by `vote_surface`. Human-only
 * BY CONSTRUCTION on the backend (two independent filters - `vote_surface` non-null/non-blank
 * AND `source in HUMAN_SOURCES`, see MPCAutofill/cardpicker/catalog_stats.py's
 * `compute_contributions_over_time` docstring) - this panel therefore needs no machine overlay of
 * its own, and drawing one would violate the house rule against ever sharing an axis between a
 * human and a machine series at this catalog's real ratio (0.05% human, see this task's own
 * directive).
 */
import React from "react";

import { ContributionsOverTime } from "@/common/schema_types";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";

function formatWeekLabel(weekStart: string): string {
  const date = new Date(`${weekStart}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return weekStart;
  }
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function weeklyRows(contributionsOverTime: ContributionsOverTime): BarRow[] {
  return contributionsOverTime.series.map((week) => ({
    label: formatWeekLabel(week.weekStart),
    segments: Object.entries(week.bySurface).map(([surface, count]) => ({
      key: surface,
      label: surface,
      value: count,
    })),
  }));
}

export function ContributionsOverTimePanel({
  contributionsOverTime,
}: {
  contributionsOverTime: ContributionsOverTime;
}) {
  const rows = weeklyRows(contributionsOverTime);
  const legendKeys = Array.from(
    new Set(
      contributionsOverTime.series.flatMap((week) =>
        Object.keys(week.bySurface)
      )
    )
  );
  const weeks = Math.round(
    contributionsOverTime.series.length > 0
      ? contributionsOverTime.series.length
      : 0
  );

  return (
    <section data-testid="contributions-over-time-panel" className="mb-5">
      <h2>Human confirmations over time</h2>
      <p className="text-muted">
        Weekly, by the surface the confirmation was made from{" "}
        {weeks > 0 &&
          `(last ${weeks} week${weeks === 1 ? "" : "s"} with activity)`}
        .
      </p>
      <HorizontalBarChart
        title="Human confirmations by week, by surface"
        bars={rows}
        legendKeys={legendKeys}
        emptyMessage="No human confirmations recorded in the lookback window yet."
      />
    </section>
  );
}
