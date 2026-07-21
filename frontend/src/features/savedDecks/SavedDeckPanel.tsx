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
 *
 * Issue #275 (proposal-h-display-layout-spec.md ADDENDUM D9) extracted the passphrase-setup/
 * unlock/save modal-chain orchestration below into useSaveDeckFlow.ts, so the new Finish footer's
 * own "Save Deck" button (FinishFooter.tsx) and PrePrintSaveGate.tsx's "Save" choice can trigger
 * the exact same flow without forking it - this component is its first, unchanged caller.
 */

import React, { useEffect, useRef } from "react";
import Button from "react-bootstrap/Button";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { useSaveDeckFlow } from "@/features/savedDecks/useSaveDeckFlow";
import { useGetWhoamiQuery } from "@/store/api";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { setNotification } from "@/store/slices/toastsSlice";

interface SavedDeckPanelProps {
  // Defaults to the original ProjectEditor placement's own spacing (a block stacked under the
  // panels above it in a vertical column) - DisplayPage.tsx passes "" instead, since there this
  // renders inline as one more item in the toolbar's own horizontal flex-wrap row, which already
  // supplies its own gap-2 between siblings.
  className?: string;
}

export function SavedDeckPanel({ className = "pt-2" }: SavedDeckPanelProps) {
  const dispatch = useAppDispatch();
  // Kept as its own query (RTK Query dedupes against useSaveDeckFlow's own identical call) rather
  // than reading `isAuthenticated` back out of the hook below - this effect needs the RAW
  // `whoami.data?.authenticated` (`undefined` while the query is still loading), not the hook's
  // already-coerced boolean, so an already-authenticated user's initial undefined->true
  // resolution can't be mistaken for a genuine live sign-in transition (see the `was === false`
  // check below - `undefined !== false`, so only a real anonymous->authenticated flip fires it).
  const whoami = useGetWhoamiQuery();
  const currentSavedDeck = useAppSelector(selectCurrentSavedDeck);
  const { element, triggerSave, isAuthenticated, isProjectEmpty } =
    useSaveDeckFlow();

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
          onClick={() => triggerSave()}
        >
          Save
        </Button>
      </div>
      {element}
    </>
  );
}
