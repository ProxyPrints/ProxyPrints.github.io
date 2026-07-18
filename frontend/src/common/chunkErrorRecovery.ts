/**
 * Recovery for a stale cached HTML shell referencing webpack chunk files a newer GitHub Pages
 * deploy has since overwritten (the static export has no server, so old chunk hashes are gone
 * the moment a new deploy lands - GitHub Pages doesn't version them). A browser that opened the
 * app before a deploy, or is navigating client-side via `next/link` (editor/new/explore/
 * contributions/whatsthat all use it - see Navbar.tsx) with a stale bundle already loaded, gets a
 * 404 on the next chunk fetch. Next.js's webpack runtime throws this as a `ChunkLoadError` (or a
 * "Loading chunk N failed" message on older bundlers) - previously entirely unhandled here, so
 * the failed transition just left whatever partial/stale state was already on screen (reported
 * symptom: a stuck "No Server Configured" page until a manual hard refresh).
 */

const CHUNK_RELOAD_GUARD_KEY = "chunkReloadAttemptedAt";
// A real deploy-caused chunk failure is fixed by exactly one reload (the browser fetches the
// fresh HTML/chunk manifest). This window exists only to stop a reload LOOP if reloading somehow
// doesn't fix it (e.g. a mid-deploy race, or a genuinely broken deploy) - not a retry budget.
const CHUNK_RELOAD_GUARD_WINDOW_MS = 10_000;

/** True for both Next.js's own `ChunkLoadError` (`.name`) and the underlying webpack message
 * format, so this catches the error however it surfaces (thrown, rejected, or passed to a
 * Next.js router event). */
export function isChunkLoadError(error: unknown): boolean {
  if (error == null) {
    return false;
  }
  const name = (error as { name?: unknown })?.name;
  if (name === "ChunkLoadError") {
    return true;
  }
  const message = String((error as { message?: unknown })?.message ?? error);
  return /Loading( CSS)? chunk [\w.-]+ failed/i.test(message);
}

/** Pure guard logic, exported separately so it's testable without touching sessionStorage/
 * window.location directly - true means "go ahead and reload," false means "already tried
 * recently, don't loop." */
export function shouldAttemptReload(
  lastAttemptAt: number | null,
  now: number
): boolean {
  return (
    lastAttemptAt == null || now - lastAttemptAt >= CHUNK_RELOAD_GUARD_WINDOW_MS
  );
}

/** Reloads the page in response to a detected chunk-load failure, guarded against a loop via a
 * sessionStorage timestamp (survives the reload itself, unlike an in-memory flag, and is scoped
 * to this tab only - a fresh tab always gets a clean attempt). */
export function reloadOnceForChunkError(): void {
  const now = Date.now();
  const lastAttemptRaw = window.sessionStorage.getItem(CHUNK_RELOAD_GUARD_KEY);
  const lastAttemptAt = lastAttemptRaw != null ? Number(lastAttemptRaw) : null;
  if (!shouldAttemptReload(lastAttemptAt, now)) {
    return;
  }
  window.sessionStorage.setItem(CHUNK_RELOAD_GUARD_KEY, String(now));
  window.location.reload();
}
