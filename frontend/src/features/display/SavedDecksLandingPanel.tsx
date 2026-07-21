/**
 * Design doc §5/§6 row S2 (docs/proposals/proposal-h-display-layout-spec.md, issue #268) - the
 * /display empty-project landing's saved-decks panel. Composes `useGetSavedDecksQuery` (the exact
 * endpoint MyDecksPage already fetches - no new backend calls) with `DeckRow` and
 * `useLoadSavedDeck`, both exported/extracted from MyDecksPage.tsx for this purpose (S1) -
 * repurposed, not forked, so unlocking, the safety-save-before-overwrite flow, and the actual
 * load/dispatch sequence are identical to MyDecksPage's own "Open in editor" path. Loading a deck
 * from here runs through the same `loadProject`/`loadFinishSettings`/`setCurrentSavedDeck`
 * dispatch, just without the `navigateTo` hop - DisplayPage's `isProjectEmpty` selector then flips
 * false and the page re-renders straight into the sheet+rail layout on its own (the same mechanism
 * issue #238's inline importers already rely on).
 *
 * Two-tier visibility (issue #268's own explicit constraint - "renders nothing for anonymous/zero-
 * deck sessions", no empty shell):
 *   1. `useHasSavedDecksForLanding` - a standalone, `useLoadSavedDeck`-FREE check (whoami +
 *      `useGetSavedDecksQuery`'s own raw encrypted deck count) - decides whether `DeckInputLanding`
 *      (DisplayPage.tsx) reserves the panel's grid column AT ALL. False for an anonymous session or
 *      one with zero saved rows (named decks or snapshots) ever created; true as soon as at least
 *      one encrypted row exists, whether or not this session has unlocked it yet - unlocking is not
 *      a precondition for "there is something to show here".
 *   2. `SavedDecksLandingPanel` itself only mounts once (1) is true, and handles the locked/
 *      unlocked split the exact same way MyDecksPage does: `useLoadSavedDeck`'s bundled UnlockModal
 *      auto-shows the moment this panel mounts against a locked session (same as visiting
 *      /myDecks) - deliberately NOT suppressed, since a user arriving at /display with saved decks
 *      should actually see them (the issue's own ask), not a silent no-op landing that never
 *      surfaces the passphrase prompt on a fresh session. A user who dismisses the modal without
 *      unlocking gets the same "Unlock my saved decks" button MyDecksPage shows in that state.
 *
 * Snapshots are intentionally excluded from the rendered list (mirrors the mockup, which only ever
 * shows plain saved decks) - MyDecksPage remains the one place snapshots are browsable/restorable.
 */
import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import ListGroup from "react-bootstrap/ListGroup";

import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  DecryptedSavedDeck,
  decryptSavedDeckSummary,
} from "@/features/savedDecks/deckPayload";
import { DeckRow } from "@/features/savedDecks/MyDecksPage";
import { useLoadSavedDeck } from "@/features/savedDecks/useLoadSavedDeck";
import { useGetSavedDecksQuery, useGetWhoamiQuery } from "@/store/api";

function sortByUpdatedAtDescending(decks: Array<DecryptedSavedDeck>) {
  return [...decks].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

/**
 * Standalone visibility gate - never mounts `useLoadSavedDeck`, so calling this alone never
 * triggers the auto-unlock prompt; it only decides whether `DeckInputLanding` renders the panel's
 * grid column at all. See this file's own module comment for the full two-tier rationale.
 */
export function useHasSavedDecksForLanding(): boolean {
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const session = useCryptoSession();
  const shouldFetchDecks =
    session.status === "locked" || session.status === "unlocked";
  const savedDecksQuery = useGetSavedDecksQuery({ skip: !shouldFetchDecks });
  return isAuthenticated && (savedDecksQuery.data?.decks.length ?? 0) > 0;
}

export function SavedDecksLandingPanel() {
  const session = useCryptoSession();
  const shouldFetchDecks =
    session.status === "locked" || session.status === "unlocked";
  const savedDecksQuery = useGetSavedDecksQuery({ skip: !shouldFetchDecks });

  const [decrypted, setDecrypted] = useState<Array<DecryptedSavedDeck>>([]);

  useEffect(() => {
    let cancelled = false;
    if (
      session.status === "unlocked" &&
      session.masterKey != null &&
      savedDecksQuery.data != null
    ) {
      Promise.all(
        savedDecksQuery.data.decks.map((summary) =>
          decryptSavedDeckSummary(summary, session.masterKey!)
        )
      )
        .then((results) => {
          if (!cancelled) {
            setDecrypted(results);
          }
        })
        // A decrypt failure here just leaves the list empty - MyDecksPage remains the place a
        // genuine decrypt-error message belongs; this compact landing panel stays silent.
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [session.status, session.masterKey, savedDecksQuery.data]);

  const namedDecks = useMemo(
    () => sortByUpdatedAtDescending(decrypted.filter((d) => d.kind === "deck")),
    [decrypted]
  );

  const {
    element: loadSavedDeckModals,
    openDeck,
    showUnlock,
    openUnlock,
  } = useLoadSavedDeck();

  return (
    <div data-testid="saved-decks-landing-panel">
      {loadSavedDeckModals}
      <h5>Your Saved Decks</h5>
      {session.status === "locked" && !showUnlock && (
        <p>
          <Button size="sm" onClick={openUnlock}>
            Unlock my saved decks
          </Button>
        </p>
      )}
      {session.status === "unlocked" && namedDecks.length === 0 && (
        <p>You haven&apos;t saved any decks yet.</p>
      )}
      {namedDecks.length > 0 && (
        <ListGroup className="mb-2" data-testid="landing-named-decks-list">
          {namedDecks.map((deck) => (
            <DeckRow
              key={deck.key}
              deck={deck}
              onOpen={openDeck}
              openLabel="Load"
            />
          ))}
        </ListGroup>
      )}
      <p className="small">
        <Link href="/myDecks">My decks →</Link>
      </p>
    </div>
  );
}
