/**
 * Proposal F /stats page + homepage participation graph - shared formatting helpers. Deliberately
 * tiny: every one of these is a pure display-string function, no aggregation/computation of its
 * own (see this feature's own module comments for why - `participation` in particular ships raw
 * counts specifically so the frontend never derives a ratio the backend chose not to compute,
 * see MPCAutofill/cardpicker/catalog_stats.py's `compute_participation` docstring).
 */

export function formatCount(value: number): string {
  return value.toLocaleString();
}

/**
 * `generatedAt` is `null` on a cache miss (cold cache, or the "shared" cache backend isn't
 * configured) - callers MUST check for that themselves and render the "not computed yet" state
 * (see CatalogStatsPage.tsx) rather than calling this on a null value.
 */
export function formatGeneratedAt(generatedAt: string): string {
  const date = new Date(generatedAt);
  if (Number.isNaN(date.getTime())) {
    return generatedAt;
  }
  return `${date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })} ${date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

/**
 * `durationSeconds` is `null` for a still-running (or crashed-before-`finished_at`) row - callers
 * must not coerce that to "0s" (see RunHistoryPanel.tsx).
 */
export function formatDuration(durationSeconds: number): string {
  if (durationSeconds < 60) {
    return `${Math.round(durationSeconds)}s`;
  }
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = Math.round(durationSeconds % 60);
  if (minutes < 60) {
    return `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}
