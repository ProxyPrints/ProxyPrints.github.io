/**
 * The saved-deck action cluster (docs/proposals/proposal-g-user-accounts-saved-decks.md §4): the
 * reverse breadcrumb ("Editing: {name}" / "Unsaved project") and the Save button, rendered only
 * when authenticated - a logged-out user sees nothing new here at all. Clicking Save runs the
 * passphrase-setup or unlock prerequisite first if the crypto session isn't ready, then opens
 * SaveDeckModal. Also raises the one-time anonymous-to-login "adopt your project" toast on the
 * whoami transition to authenticated.
 *
 * Mounted in two places (issue #165, Proposal G save integration into Proposal H's unified
 * display page): ProjectEditor.tsx's right-panel action cluster (original placement, `pt-2` to
 * stack under the panels above it) and DisplayPage.tsx's top toolbar (docs/proposals/
 * proposal-h-unified-display-page.md §5's "deck name" toolbar slot - see that doc's own row for
 * this component). The component itself is entirely route-agnostic (reads/writes projectSlice +
 * savedDeckSessionSlice only), so the only thing that differs between callers is spacing - hence
 * the className prop rather than a second, forked component.
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

interface SavedDeckPanelProps {
  // Defaults to the original ProjectEditor placement's own spacing (a block stacked under the
  // panels above it in a vertical column) - DisplayPage.tsx passes "" instead, since there this
  // renders inline as one more item in the toolbar's own horizontal flex-wrap row, which already
  // supplies its own gap-2 between siblings.
  className?: string;
}

export function SavedDeckPanel({ className = "pt-2" }: SavedDeckPanelProps) {
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
      <div className={`d-flex align-items-center gap-2 ${className}`.trim()}>
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
