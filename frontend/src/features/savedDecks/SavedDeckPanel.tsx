/**
 * The editor's saved-deck action cluster (docs/proposals/proposal-g-user-accounts-saved-decks.md
 * §4): the reverse breadcrumb ("Editing: {name}" / "Unsaved project") and the Save button,
 * rendered only when authenticated - a logged-out user sees nothing new here at all. Clicking
 * Save runs the passphrase-setup or unlock prerequisite first if the crypto session isn't ready,
 * then opens SaveDeckModal. Also raises the one-time anonymous-to-login "adopt your project"
 * toast on the whoami transition to authenticated.
 */

import React, { useEffect, useRef, useState } from "react";
import Button from "react-bootstrap/Button";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import { PassphraseSetupModal } from "@/features/savedDecks/PassphraseSetupModal";
import { SaveDeckModal } from "@/features/savedDecks/SaveDeckModal";
import { UnlockModal } from "@/features/savedDecks/UnlockModal";
import { useGetWhoamiQuery } from "@/store/api";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { setNotification } from "@/store/slices/toastsSlice";

type PendingModal = "passphrase-setup" | "unlock" | "save" | null;

export function SavedDeckPanel() {
  const dispatch = useAppDispatch();
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const session = useCryptoSession();
  const currentSavedDeck = useAppSelector(selectCurrentSavedDeck);
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const [pendingModal, setPendingModal] = useState<PendingModal>(null);

  // Anonymous -> login adopt-by-save toast: surfaced once, right at the moment whoami flips to
  // authenticated, only if there's actually a non-empty in-memory project worth offering to
  // save. The toast system (Toasts.tsx) is plain informational text with no action button, so
  // this points at the Save button below rather than embedding a "save now" action in the toast
  // itself - extending shared toast infra for one caller wasn't worth it here.
  const previousAuthenticated = useRef(whoami.data?.authenticated);
  useEffect(() => {
    const was = previousAuthenticated.current;
    const now = whoami.data?.authenticated;
    if (was === false && now === true && !isProjectEmpty) {
      dispatch(
        setNotification([
          "saved-deck-anonymous-login-adopt",
          {
            name: "Signed in",
            message:
              "Your current project is still here - use Save below to add it to your saved decks.",
            level: "info",
          },
        ])
      );
    }
    previousAuthenticated.current = now;
  }, [whoami.data?.authenticated, isProjectEmpty, dispatch]);

  if (!isAuthenticated) {
    return null;
  }

  const handleSaveClick = () => {
    if (session.status === "no-profile") {
      setPendingModal("passphrase-setup");
    } else if (session.status === "locked") {
      setPendingModal("unlock");
    } else if (session.status === "unlocked") {
      setPendingModal("save");
    }
  };

  return (
    <>
      <div className="d-flex align-items-center gap-2 pt-2">
        <span className="text-muted small" data-testid="saved-deck-breadcrumb">
          {currentSavedDeck.currentDeckName
            ? `Editing: ${currentSavedDeck.currentDeckName}`
            : "Unsaved project"}
        </span>
        <Button
          size="sm"
          variant="outline-primary"
          disabled={isProjectEmpty}
          onClick={handleSaveClick}
        >
          Save
        </Button>
      </div>
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
        onSaved={() => setPendingModal(null)}
      />
    </>
  );
}
