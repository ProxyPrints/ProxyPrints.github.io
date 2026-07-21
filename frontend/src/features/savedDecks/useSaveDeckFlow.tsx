/**
 * Extracted from SavedDeckPanel.tsx's own `handleSaveClick`/`pendingModal` orchestration
 * (proposal-h-display-layout-spec.md ADDENDUM D9, issue #275) so a SECOND call site - the
 * Finish footer's own "Save Deck" button (FinishFooter.tsx) and PrePrintSaveGate.tsx's "Save"
 * choice - can trigger the exact same passphrase-setup/unlock/save modal chain without forking
 * it, mirroring useLoadSavedDeck.ts's own precedent (extracted from MyDecksPage.tsx for the same
 * reason). SavedDeckPanel.tsx itself is refactored to use this hook too, so there is exactly ONE
 * place this three-modal sequencing lives - not the original plus a near-duplicate.
 *
 * Behaviour preserved verbatim from SavedDeckPanel.tsx: `no-profile` -> PassphraseSetupModal ->
 * `unlocked` (session flips) -> SaveDeckModal shown next; `locked` -> UnlockModal -> same;
 * `unlocked` already -> SaveDeckModal directly. `triggerSave` accepts an optional `onSaved`
 * callback so a caller that needs to do something AFTER a successful save (PrePrintSaveGate's
 * "navigate to the Print page only once persistence resolves", D9(3)c) can hook it, while
 * SavedDeckPanel's own plain "just close the modal" caller can omit it.
 */
import React, { useCallback, useState } from "react";

import { useAppSelector } from "@/common/types";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import { PassphraseSetupModal } from "@/features/savedDecks/PassphraseSetupModal";
import { SaveDeckModal } from "@/features/savedDecks/SaveDeckModal";
import { UnlockModal } from "@/features/savedDecks/UnlockModal";
import { useGetWhoamiQuery } from "@/store/api";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

type PendingModal = "passphrase-setup" | "unlock" | "save" | null;

export interface UseSaveDeckFlowResult {
  /** Render this once, near wherever `triggerSave` is called from - the whole modal surface
   * (PassphraseSetupModal/UnlockModal/SaveDeckModal) this hook needs, and renders nothing until
   * it's actually needed. */
  element: React.ReactElement;
  /** Starts (or continues) the save flow: passphrase-setup/unlock first if the crypto session
   * isn't ready, then SaveDeckModal. `onSaved` (optional) fires once the deck has actually been
   * persisted - omit it for a plain "just save" caller. */
  triggerSave: (onSaved?: () => void) => void;
  /** True once a real, non-authenticated session is confirmed - callers that need to branch on
   * this themselves (the Finish footer's anonymous "Save Deck" state, D9's own "anonymous users'
   * nudge routes through sign-in first") read it directly rather than re-querying whoami. */
  isAuthenticated: boolean;
  /** Whether the current project has anything worth saving - SavedDeckPanel's own existing
   * `disabled={isProjectEmpty}` gate on its Save button, exposed here so a second caller
   * (the Finish footer) can apply the identical gate without re-deriving it. */
  isProjectEmpty: boolean;
}

export function useSaveDeckFlow(): UseSaveDeckFlowResult {
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const session = useCryptoSession();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);

  const [pendingModal, setPendingModal] = useState<PendingModal>(null);
  const [onSavedCallback, setOnSavedCallback] = useState<
    (() => void) | undefined
  >(undefined);

  const triggerSave = useCallback(
    (onSaved?: () => void) => {
      setOnSavedCallback(() => onSaved);
      if (session.status === "no-profile") {
        setPendingModal("passphrase-setup");
      } else if (session.status === "locked") {
        setPendingModal("unlock");
      } else if (session.status === "unlocked") {
        setPendingModal("save");
      }
    },
    [session.status]
  );

  const handleSaved = useCallback(() => {
    setPendingModal(null);
    onSavedCallback?.();
    setOnSavedCallback(undefined);
  }, [onSavedCallback]);

  const element = (
    <>
      <PassphraseSetupModal
        show={pendingModal === "passphrase-setup"}
        onCancel={() => setPendingModal(null)}
        onComplete={() => setPendingModal("save")}
      />
      <UnlockModal
        show={pendingModal === "unlock"}
        onCancel={() => setPendingModal(null)}
        onUnlocked={() => setPendingModal("save")}
      />
      <SaveDeckModal
        show={pendingModal === "save"}
        onCancel={() => setPendingModal(null)}
        onSaved={handleSaved}
      />
    </>
  );

  return { element, triggerSave, isAuthenticated, isProjectEmpty };
}
