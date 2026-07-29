/**
 * Proposal F /stats page - hand-rolled SVG horizontal (stacked-capable) bar chart. No charting
 * library (house rule: no new dependency, not even a small one - `package.json` carries none
 * today). One axis only (the value axis, x) - never a second/dual axis. Every row's total is
 * direct-labeled (selective direct-labeling, not a number on every segment); a legend renders
 * only when more than one distinct segment key is present anywhere in the data (a single series
 * needs no legend, its title already names it - house rule).
 *
 * Colour is assigned by `assignCategoricalColors` (features/stats/colors.ts) over the FULL set of
 * segment keys the caller passes in via `legendKeys` (or, if omitted, the set observed across
 * `bars` itself) - never by a segment's position within one particular row - so a key keeps its
 * colour regardless of which subset of rows/keys a given render happens to include.
 */
import React from "react";

import {
  assignCategoricalColors,
  OTHER_COLOR,
  OTHER_KEY,
} from "@/features/stats/colors";
import { formatCount } from "@/features/stats/format";

export interface BarSegment {
  key: string;
  label: string;
  value: number;
}

export interface BarRow {
  label: string;
  segments: BarSegment[];
}

interface HorizontalBarChartProps {
  title: string;
  bars: BarRow[];
  emptyMessage: string;
  /** Full set of segment keys to colour/legend against - defaults to the keys seen in `bars`. */
  legendKeys?: string[];
  valueFormatter?: (value: number) => string;
}

const ROW_HEIGHT = 28;
const ROW_GAP = 10;
const LABEL_WIDTH = 168;
const VALUE_LABEL_WIDTH = 60; // reserved space for the direct-labeled row total, right-aligned
const CHART_WIDTH = 420;
const SEGMENT_GAP = 2; // a 2px surface gap between adjacent stacked segments (mark spec)

export function HorizontalBarChart({
  title,
  bars,
  emptyMessage,
  legendKeys,
  valueFormatter = formatCount,
}: HorizontalBarChartProps) {
  if (bars.length === 0) {
    return (
      <p className="text-muted" data-testid="bar-chart-empty">
        {emptyMessage}
      </p>
    );
  }

  const allKeys =
    legendKeys ??
    Array.from(new Set(bars.flatMap((bar) => bar.segments.map((s) => s.key))));
  const colorByKey = assignCategoricalColors(allKeys);
  const hasMultipleSeries = allKeys.length > 1;
  const foldedIntoOther = allKeys.filter(
    (key) => colorByKey.get(key) === OTHER_COLOR
  );

  const maxValue = Math.max(
    1,
    ...bars.map((bar) => bar.segments.reduce((sum, s) => sum + s.value, 0))
  );
  const svgHeight = bars.length * (ROW_HEIGHT + ROW_GAP) - ROW_GAP;
  const barAreaWidth = CHART_WIDTH - LABEL_WIDTH - VALUE_LABEL_WIDTH;

  const keyLabel = (key: string) =>
    foldedIntoOther.includes(key)
      ? OTHER_KEY
      : bars.flatMap((bar) => bar.segments).find((s) => s.key === key)?.label ??
        key;

  return (
    <figure className="m-0" aria-label={title}>
      {hasMultipleSeries && (
        <ul
          className="list-unstyled d-flex flex-wrap gap-3 mb-2"
          data-testid="bar-chart-legend"
        >
          {Array.from(
            new Set(allKeys.map((key) => colorByKey.get(key) ?? OTHER_COLOR))
          ).map((color) => {
            const keysForColor = allKeys.filter(
              (key) => colorByKey.get(key) === color
            );
            const label =
              color === OTHER_COLOR ? OTHER_KEY : keyLabel(keysForColor[0]);
            return (
              <li
                key={color}
                className="d-flex align-items-center gap-2"
                style={{ fontSize: "0.85rem" }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: color,
                  }}
                />
                <span className="text-muted">{label}</span>
              </li>
            );
          })}
        </ul>
      )}
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${svgHeight}`}
        width="100%"
        role="img"
        aria-label={title}
        style={{ overflow: "visible" }}
      >
        {bars.map((bar, rowIndex) => {
          const y = rowIndex * (ROW_HEIGHT + ROW_GAP);
          const total = bar.segments.reduce((sum, s) => sum + s.value, 0);
          let cursorX = 0;
          return (
            <g key={bar.label} data-testid="bar-chart-row">
              <text
                x={0}
                y={y + ROW_HEIGHT / 2}
                dominantBaseline="middle"
                className="stats-chart-label"
                fill="var(--theme-muted)"
                fontSize={12}
              >
                {bar.label.length > 24
                  ? `${bar.label.slice(0, 23)}…`
                  : bar.label}
              </text>
              {/* recessive baseline axis for this row */}
              <line
                x1={LABEL_WIDTH}
                y1={y + ROW_HEIGHT}
                x2={LABEL_WIDTH + barAreaWidth}
                y2={y + ROW_HEIGHT}
                stroke="var(--theme-divider)"
                strokeWidth={1}
              />
              {bar.segments.map((segment) => {
                const segmentWidth =
                  maxValue === 0
                    ? 0
                    : (segment.value / maxValue) * barAreaWidth;
                const x = LABEL_WIDTH + cursorX;
                cursorX += segmentWidth + (segmentWidth > 0 ? SEGMENT_GAP : 0);
                if (segmentWidth <= 0) {
                  return null;
                }
                const color = colorByKey.get(segment.key) ?? OTHER_COLOR;
                return (
                  <rect
                    key={segment.key}
                    x={x}
                    y={y}
                    width={Math.max(segmentWidth - SEGMENT_GAP, 0)}
                    height={ROW_HEIGHT}
                    rx={4}
                    fill={color}
                  >
                    <title>
                      {segment.label}: {valueFormatter(segment.value)}
                    </title>
                  </rect>
                );
              })}
              <text
                x={CHART_WIDTH}
                y={y + ROW_HEIGHT / 2}
                dominantBaseline="middle"
                textAnchor="end"
                fill="var(--theme-text)"
                fontSize={12}
                fontWeight={600}
                data-testid="bar-chart-total"
              >
                {valueFormatter(total)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
