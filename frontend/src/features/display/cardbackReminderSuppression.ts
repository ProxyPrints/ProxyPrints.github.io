/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.1, `CB1`) - the no-cardback reminder gate's
 * own "at most once per session, per project" suppression, mirroring
 * `postExportContributionPrompt.ts`'s identical sessionStorage-not-localStorage precedent (must
 * NOT survive a "clear site data"/incognito test the way a real persisted setting would, but does
 * need to survive this tab's own reloads within one print attempt). Per-PROJECT (not one flag for
 * the whole session) - keyed by `savedDeckSession`'s `currentDeckKey`, falling back to a fixed
 * bucket for an unsaved/anonymous project (see `useCardbackReminderGate.ts`'s own comment on why
 * that bucket is an acceptable approximation, not a real per-project key, until every project has
 * a stable identity regardless of save state).
 */

const SESSION_FLAG_PREFIX = "cardbackReminderGateSuppressed:";

/** Fixed bucket for a project with no saved-deck key yet (anonymous, or authenticated but never
 * saved this project) - see this module's own header comment. */
export const UNSAVED_PROJECT_SUPPRESSION_KEY = "__unsaved__";

function storageKey(projectKey: string): string {
  return `${SESSION_FLAG_PREFIX}${projectKey}`;
}

export function hasSuppressedCardbackReminderThisSession(
  projectKey: string
): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.sessionStorage.getItem(storageKey(projectKey)) === "true";
}

export function suppressCardbackReminderThisSession(projectKey: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(storageKey(projectKey), "true");
}

/** Test-only reset - a fresh session/tab in real use always starts unset. */
export function resetCardbackReminderSuppressionForTests(
  projectKey: string
): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(storageKey(projectKey));
}
