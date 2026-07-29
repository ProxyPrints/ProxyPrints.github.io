/**
 * Proposal F /stats page - categorical + status colour assignment.
 *
 * No new dependency, no new palette study: every value here is one of the site's own existing,
 * already-AAA-audited Tokyo-11 tokens (`frontend/src/styles/_theme-tokens.scss`,
 * docs/features/theming.md) referenced via its `var(--bs-*)`/`var(--theme-*)` runtime custom
 * property, never a literal hex. Two disjoint roles, deliberately never mixed:
 *
 * - CATEGORICAL_ORDER - identity colour for a chart series (vote_surface, skip-log engine) -
 *   fixed order, assigned below by a stable, magnitude-independent rule so a filter/subset never
 *   repaints a survivor (house rule: "colour follows the entity, never its rank").
 * - Status colours (`STATUS_COLORS`) - reserved for genuine state (a pilot run's
 *   completed/failed/running status dot in RunHistoryPanel) and never reused as a categorical
 *   series colour here, even though `--bs-success`/`--bs-danger` would otherwise be free hues -
 *   see the dataviz skill's "status colours are reserved" rule.
 */

// Fixed order, never cycled. Orange/purple/cyan/amber - the four Tokyo-11 tokens not already
// carrying a status meaning elsewhere on the site (success/danger are reserved, see
// STATUS_COLORS below). A 5th+ distinct key folds into OTHER_KEY/OTHER_COLOR rather than
// generating or cycling a new hue - see assignCategoricalColors below.
export const CATEGORICAL_ORDER: readonly string[] = [
  "var(--bs-primary)", // orange
  "var(--theme-accent)", // purple
  "var(--bs-info)", // cyan
  "var(--bs-warning)", // amber
];

export const OTHER_KEY = "Other";
export const OTHER_COLOR = "var(--theme-muted)";

/**
 * Assigns each distinct key a fixed slot from CATEGORICAL_ORDER, in ALPHABETICAL order (not
 * first-seen, not by magnitude) - so the same key always gets the same colour regardless of what
 * else is in the dataset, what order the backend happened to emit rows in, or which subset of
 * rows a given panel renders. Keys beyond CATEGORICAL_ORDER's length all fold to OTHER_COLOR
 * (never a 5th generated/cycled hue) - callers building a legend should collapse every
 * OTHER_COLOR-mapped key into one "Other" entry rather than listing them individually.
 */
export function assignCategoricalColors(
  keys: readonly string[]
): Map<string, string> {
  const sortedUniqueKeys = Array.from(new Set(keys)).sort();
  const colorByKey = new Map<string, string>();
  sortedUniqueKeys.forEach((key, index) => {
    colorByKey.set(
      key,
      index < CATEGORICAL_ORDER.length ? CATEGORICAL_ORDER[index] : OTHER_COLOR
    );
  });
  return colorByKey;
}

// Reserved for RunHistoryPanel's status dots ONLY - never assigned to a chart series above.
export const STATUS_COLORS: { [status: string]: string } = {
  completed: "var(--bs-success)",
  failed: "var(--bs-danger)",
  running: "var(--bs-info)",
};
export const STATUS_COLOR_FALLBACK = "var(--theme-muted)";

export function colorForRunStatus(status: string): string {
  return STATUS_COLORS[status.toLowerCase()] ?? STATUS_COLOR_FALLBACK;
}
