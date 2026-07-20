/**
 * Issue #204 - React-side wiring for the contextual consent toast. `requestConsent` is the whole
 * reusable API surface any future permission point calls (e.g. #203's client-side phash
 * contribution, not built here - this hook has no dependency on it and shouldn't gain one):
 * pass a permission `key` plus a `message` describing THAT SPECIFIC action, get back a Promise
 * that resolves to the user's decision. Nothing here is hardcoded to any one feature.
 *
 * Mirrors usePostExportContributionPrompt.ts's split (pure session logic lives in
 * consentToast.ts, this hook composes it into stateful show/decide wiring), generalised from a
 * single "shown once" flag to a per-key ACCEPT/DECLINE decision - see consentToast.ts's own
 * top comment for why that's scoped per key rather than global.
 *
 * Design decision (stated here, not left to fall out of the code by accident): dismissing the
 * toast without clicking either button - the header close button, or Escape - is treated as a
 * DECLINE, and that decision IS persisted for the rest of the session, the same as an explicit
 * "No thanks" click. Rationale: requirement 2 of #204 is a binary accept/decline outcome (the
 * caller's Promise<boolean> contract has no third "ask me again" state to resolve to), and
 * fail-closed-on-dismiss is the same posture cookie-consent banners and
 * PostExportContributionPrompt.tsx's own "shown = done, whether interacted with or not" precedent
 * both already take. A caller that genuinely wants "ask again next time" behaviour for a
 * dismiss (as opposed to an explicit decline) is a different feature, not this one - open a new
 * issue if a future permission point actually needs it.
 */
import React, { useCallback, useMemo, useRef, useState } from "react";

import { ConsentToast } from "@/features/consent/ConsentToast";
import {
  ConsentDecision,
  getStoredConsentDecision,
  shouldPromptForConsent,
  storeConsentDecision,
} from "@/features/consent/consentToast";

export interface ConsentRequest {
  /** Uniquely identifies WHAT this consent is for - decisions are scoped per key, never
   * global (issue #204 requirement 4). e.g. "phash-contribution". */
  key: string;
  /** Short label, e.g. "Help identify this printing?". Falls back to ConsentToast's own
   * default if omitted. */
  title?: string;
  /** Describes the SPECIFIC action/data-collection this request is for - always required,
   * never a generic "we use cookies" message (issue #204 requirement 1). */
  message: string;
  acceptLabel?: string;
  declineLabel?: string;
}

export interface UseConsentToastResult {
  /** Render this once (e.g. near the root of whatever feature calls requestConsent) - it's the
   * whole reusable presentational surface, and renders nothing until requestConsent is called
   * with a key that hasn't already been decided this session. */
  element: React.ReactElement;
  /**
   * Ask the user for consent for the given permission key. Resolves immediately, without
   * showing any UI, if that key already has a decision recorded this session (issue #204
   * requirement 4 - "don't re-ask on every action within the same session if already decided").
   * Otherwise shows the toast and resolves once the user accepts, declines, or dismisses it
   * (dismiss counts as decline - see this file's own top comment for why).
   */
  requestConsent: (request: ConsentRequest) => Promise<boolean>;
}

export function useConsentToast(): UseConsentToastResult {
  const [pendingRequest, setPendingRequest] = useState<ConsentRequest | null>(
    null
  );
  // A ref, not state, because it's only ever read inside callbacks that already have the
  // freshest value available synchronously (set immediately before it's needed) - it never
  // drives a render itself.
  const resolveRef = useRef<((accepted: boolean) => void) | null>(null);

  const requestConsent = useCallback(
    (request: ConsentRequest): Promise<boolean> => {
      const stored = getStoredConsentDecision(request.key);
      if (!shouldPromptForConsent(stored)) {
        return Promise.resolve(stored === "accepted");
      }
      return new Promise<boolean>((resolve) => {
        resolveRef.current = resolve;
        setPendingRequest(request);
      });
    },
    []
  );

  const decide = useCallback((decision: ConsentDecision) => {
    setPendingRequest((current) => {
      if (current == null) {
        return current;
      }
      storeConsentDecision(current.key, decision);
      resolveRef.current?.(decision === "accepted");
      resolveRef.current = null;
      return null;
    });
  }, []);

  const handleAccept = useCallback(() => decide("accepted"), [decide]);
  const handleDecline = useCallback(() => decide("declined"), [decide]);

  const element = useMemo(
    () => (
      <ConsentToast
        show={pendingRequest != null}
        title={pendingRequest?.title}
        message={pendingRequest?.message ?? ""}
        acceptLabel={pendingRequest?.acceptLabel}
        declineLabel={pendingRequest?.declineLabel}
        onAccept={handleAccept}
        onDecline={handleDecline}
      />
    ),
    [pendingRequest, handleAccept, handleDecline]
  );

  return { element, requestConsent };
}
