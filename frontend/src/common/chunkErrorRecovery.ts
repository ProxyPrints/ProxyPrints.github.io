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

// In-memory only (module-level, not sessionStorage) - this only needs to survive from the
// instant reloadOnceForChunkError() decides to reload to the synchronous `beforeunload` event
// that `window.location.reload()` fires, both within the same tick, before this module's whole
// JS context is torn down by the reload itself. See isRecoveryReloadInFlight()'s own comment for
// why ProjectEditor.tsx's unsaved-work guard needs this at all.
let recoveryReloadInFlight = false;

/** True for the brief window between reloadOnceForChunkError() deciding to reload and the
 * reload's own beforeunload event actually firing. ProjectEditor.tsx's unsaved-work guard reads
 * this to distinguish "the app itself is recovering from a stale/failed chunk fetch" (this
 * function's whole reason for existing) from a genuine user-initiated exit (tab close, address-
 * bar navigation, a manual refresh) - `beforeunload` itself carries zero information about *why*
 * or *where* the page is unloading (a deliberate browser privacy/security constraint), so there
 * is no way for the guard to tell these apart except a flag exactly like this one. Root-caused
 * from a priority bug report: clicking a next/link nav item (e.g. Editor -> /display) while that
 * target route's JS chunk fails to fetch (a stale deploy, or a plain transient network blip - see
 * this file's own module comment) sends the router down this exact recovery path; since the
 * failed transition never actually left the current page, ProjectEditor's beforeunload listener
 * was still mounted and - correctly, per its own narrow logic, but unhelpfully here - intercepted
 * this reload as if the user were abandoning their work, when it's really the app's own recovery
 * attempt for a problem unrelated to their project state. */
export function isRecoveryReloadInFlight(): boolean {
  return recoveryReloadInFlight;
}

// Exported (pure data, no behaviour change) so chunkErrorRecovery.spec.ts can defensively clear
// this key before dispatching its own synthetic error - see that file's own comment for why a
// real, unrelated chunk hiccup during dev-server on-demand compilation can otherwise pre-consume
// this one-shot guard before the test's synthetic dispatch ever runs.
export const CHUNK_RELOAD_GUARD_KEY = "chunkReloadAttemptedAt";
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
  recoveryReloadInFlight = true;
  window.location.reload();
}
