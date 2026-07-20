/**
 * Post-export contribution prompt (issue #166, Proposal H milestone) - a small, dismissible
 * nudge shown after a REAL export success (PDF download or Save to Google Drive both count),
 * pointing the user at the existing "What's That Card?" vote-queue funnel
 * (docs/features/printing-tags.md) rather than inventing a parallel entry point. Mounted from
 * both real export surfaces per docs/features/print-export-page.md and
 * docs/features/pdf-generator.md: DisplayPage.tsx's own inline export (Proposal H, item 2) and
 * PDFGenerator.tsx itself (so the classic "Print!" tab / PDFGeneratorModal / ProjectEditor mounts
 * all get it too, since they all render the same PDFGenerator component) - one implementation,
 * not two.
 *
 * "Never repeats within a session" (the design doc's own §4.4′ footnote references this exact
 * feature by that name, task #31) - a session-scoped sessionStorage flag, matching
 * chunkErrorRecovery.ts's existing precedent for this fork (sessionStorage, not localStorage: it
 * must NOT survive a "clear site data"/incognito test the way a real persisted setting would,
 * but it does need to survive this tab's own reloads, which an in-memory-only flag would not).
 * The flag is set the moment the prompt is shown (not only on explicit dismiss) - showing it once
 * per session is the whole point, whether the user dismisses it, ignores it, or navigates away.
 */
import { FileDownload } from "@/common/types";
import store from "@/store/store";

const SESSION_FLAG_KEY = "postExportContributionPromptShown";

/** Pure - exported separately so it's testable without a real sessionStorage-backed browser
 * (mirrors chunkErrorRecovery.ts's own shouldAttemptReload split of pure-logic-from-storage). */
export function shouldShowPostExportContributionPrompt(
  alreadyShownThisSession: boolean
): boolean {
  return !alreadyShownThisSession;
}

export function hasShownPostExportContributionPromptThisSession(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.sessionStorage.getItem(SESSION_FLAG_KEY) === "true";
}

export function markPostExportContributionPromptShown(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(SESSION_FLAG_KEY, "true");
}

/** Only exported for tests (a fresh session/tab in real use always starts unset - this exists so
 * a single jest/Playwright process can exercise "already shown" without polluting other tests'
 * own sessionStorage). */
export function resetPostExportContributionPromptSessionFlag(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(SESSION_FLAG_KEY);
}

/** Pure - given the current `fileDownloads` redux slice, was the most recently COMPLETED
 * "cards.pdf" download (by `completedTimestamp`) a genuine success? Exported separately from
 * `wasLatestCardsPdfDownloadSuccessful` below so it's unit-testable without touching the real
 * store. Every "Generate PDF" click enqueues a brand-new entry (a fresh `Math.random()` id -
 * see `useDoFileDownload`, `download.ts`), so the freshest completed entry by timestamp always
 * belongs to the click that was just awaited - there's no risk of this picking up a stale
 * success from an earlier export earlier in the same session. */
export function wasMostRecentCardsPdfDownloadSuccessful(
  downloads: Array<FileDownload>
): boolean {
  const completedCardsPdfDownloads = downloads.filter(
    (download) => download.name === "cards.pdf" && download.status != null
  );
  if (completedCardsPdfDownloads.length === 0) {
    return false;
  }
  const mostRecent = completedCardsPdfDownloads.reduce((latest, current) =>
    new Date(current.completedTimestamp ?? 0).getTime() >
    new Date(latest.completedTimestamp ?? 0).getTime()
      ? current
      : latest
  );
  return mostRecent.status === "success";
}

/** `useDownloadPDF`'s returned function ultimately resolves `void` (its own `useDoFileDownload`
 * wrapper swallows the inner success boolean to drive the download-manager UI instead - see
 * `download.ts`), so callers that need to know whether THIS click's download actually succeeded
 * read it back out of the same `fileDownloads` redux slice the download manager itself already
 * populates, rather than threading a new return value through a hook five unrelated download
 * flows (XML/image/decklist/desktop-tool exports) also share. `store.getState()` outside a hook
 * is an established pattern in this codebase for exactly this kind of one-shot read after an
 * awaited action completes (see e.g. `CardSlot.tsx`, `Layout.tsx`, `downloadXML.ts`). */
export function wasLatestCardsPdfDownloadSuccessful(): boolean {
  return wasMostRecentCardsPdfDownloadSuccessful(
    Object.values(store.getState().fileDownloads)
  );
}
