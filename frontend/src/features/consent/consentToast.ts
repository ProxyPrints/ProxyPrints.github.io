/**
 * Issue #204 - the contextual consent toast's pure, storage-adjacent logic (mirrors
 * postExportContributionPrompt.ts's own split of pure-logic-from-storage, one level up: that
 * file tracks a single "shown once" flag, this one tracks a per-permission-key ACCEPT/DECLINE
 * DECISION, since #204 is a general mechanism any future permission point can call with its own
 * key - e.g. #203's client-side phash contribution will eventually call this with something like
 * key="phash-contribution", but nothing here is specific to that feature).
 *
 * sessionStorage, not localStorage, for the same reason as postExportContributionPrompt.ts: a
 * consent decision must NOT survive a "clear site data"/incognito test the way a real persisted
 * setting would, but should survive this tab's own reloads. Each permission key gets its own
 * storage entry (`consentToastDecision:${key}`) so declining one contextual ask (e.g. a future
 * analytics-adjacent prompt) never silently suppresses an unrelated one (e.g. #203's phash
 * prompt) - requirement 4 of #204 is explicit that this must be scoped per key, not global.
 */

export type ConsentDecision = "accepted" | "declined";

const STORAGE_KEY_PREFIX = "consentToastDecision:";

function storageKey(permissionKey: string): string {
  return `${STORAGE_KEY_PREFIX}${permissionKey}`;
}

/** Pure - exported separately so it's testable without a real sessionStorage-backed browser. */
export function shouldPromptForConsent(
  storedDecision: ConsentDecision | null
): boolean {
  return storedDecision == null;
}

export function getStoredConsentDecision(
  permissionKey: string
): ConsentDecision | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.sessionStorage.getItem(storageKey(permissionKey));
  return raw === "accepted" || raw === "declined" ? raw : null;
}

export function storeConsentDecision(
  permissionKey: string,
  decision: ConsentDecision
): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(storageKey(permissionKey), decision);
}

/** Only exported for tests (a fresh session/tab in real use always starts unset - this exists so
 * a single jest/Playwright process can exercise "already decided" without polluting other tests'
 * own sessionStorage), mirroring resetPostExportContributionPromptSessionFlag's own precedent. */
export function resetConsentDecisionSessionFlag(permissionKey: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(storageKey(permissionKey));
}
