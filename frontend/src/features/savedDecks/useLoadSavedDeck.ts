/**
 * Extracted from `MyDecksPage`'s own `performLoad`/`openInEditor`/`LoadSafetyModal`/`UnlockModal`
 * orchestration (proposal-h-display-layout-spec.md §5/§6 row S1, issue #268) so the exact same
 * "open a saved deck" path can be reused from a second call site - the /display empty-project
 * landing (SavedDecksLandingPanel.tsx) - without forking any of it. Behaviour is unchanged for
 * MyDecksPage, which is the only caller that passes `navigateTo: "/editor"`; a caller that omits
 * it (the landing) loads the deck into the current project in place, exactly the same
 * `loadProject`/`loadFinishSettings`/`setCurrentSavedDeck` dispatch sequence, without navigating
 * anywhere - DisplayPage's own `isProjectEmpty` selector then flips false and the page re-renders
 * into the sheet+rail layout on its own (the same mechanism issue #238's inline importers use).
 *
 * Loss-proof by construction (frontend spec §4, preserved verbatim from MyDecksPage): an empty or
 * clean project loads immediately, but a dirty one always gets a safety copy saved first via
 * LoadSafetyModal - never silently discarded, never skippable. On the /display landing this
 * branch is a practical no-op (the landing only ever renders while `selectIsProjectEmpty` is
 * true), but the hook stays generic rather than special-casing that fact, since it's also used by
 * MyDecksPage where the project can genuinely be dirty.
 */
import { useRouter } from "next/router";
import React, { useCallback, useEffect, useState } from "react";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  deckContentForComparison,
  DecryptedSavedDeck,
  projectFromDeckPayload,
  serializeDeckPayload,
} from "@/features/savedDecks/deckPayload";
import { LoadSafetyModal } from "@/features/savedDecks/LoadSafetyModal";
import { selectIsCurrentProjectDirty } from "@/features/savedDecks/selectors";
import { UnlockModal } from "@/features/savedDecks/UnlockModal";
import { loadFinishSettings } from "@/store/slices/finishSettingsSlice";
import { loadProject, selectIsProjectEmpty } from "@/store/slices/projectSlice";
import { setCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";

export interface UseLoadSavedDeckOptions {
  /** Route to client-side-navigate to once a deck has loaded, e.g. `"/editor"`. Omit to load the
   * deck into the current project in place, without navigating anywhere - the /display landing's
   * own use. */
  navigateTo?: string;
}

export interface UseLoadSavedDeckResult {
  /** Render this once, near wherever `openDeck` is called from - it's the whole modal surface
   * (UnlockModal + LoadSafetyModal) this hook needs, and renders nothing until it's actually
   * needed. */
  element: React.ReactElement;
  /** Pass as a `DeckRow`'s `onOpen` prop (or call directly). Loads immediately for an empty/clean
   * project; prompts a safety save first for a dirty one. */
  openDeck: (deck: DecryptedSavedDeck) => void;
  /** True once `UnlockModal` has been dismissed without unlocking, while the crypto session is
   * still locked - lets a caller offer its own "Unlock my saved decks" affordance rather than the
   * auto-shown modal (MyDecksPage's own use; see its `session.status === "locked" && !showUnlock`
   * branch). */
  showUnlock: boolean;
  /** Re-opens the unlock modal on demand (e.g. from the affordance above). */
  openUnlock: () => void;
}

export function useLoadSavedDeck({
  navigateTo,
}: UseLoadSavedDeckOptions = {}): UseLoadSavedDeckResult {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const session = useCryptoSession();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const isProjectDirty = useAppSelector(selectIsCurrentProjectDirty);

  const [showUnlock, setShowUnlock] = useState(false);
  const [pendingLoadDeck, setPendingLoadDeck] =
    useState<DecryptedSavedDeck | null>(null);

  // Preserved verbatim from MyDecksPage: auto-prompt the passphrase unlock the moment this
  // hook mounts against a locked crypto session, so a caller never has to wire that up itself.
  useEffect(() => {
    if (session.status === "locked") {
      setShowUnlock(true);
    }
  }, [session.status]);

  const openUnlock = useCallback(() => setShowUnlock(true), []);

  const performLoad = useCallback(
    (deck: DecryptedSavedDeck) => {
      const { project, finishSettings, name } = projectFromDeckPayload(
        deck.payload
      );
      dispatch(loadProject(project));
      dispatch(loadFinishSettings(finishSettings));
      dispatch(
        setCurrentSavedDeck({
          key: deck.key,
          name,
          // Content-only (deckPayload.ts's `deckContentForComparison`) - matches the shape
          // `buildDeckPayload` produces, since the dirty-check compares the two directly. The
          // full payload's `revision`/`modifiedAt` (PR-6) live separately, in `lastSavedRevision`.
          serialized: serializeDeckPayload(
            deckContentForComparison(deck.payload)
          ),
          revision: deck.payload.revision,
        })
      );
      if (navigateTo != null) {
        router.push(navigateTo);
      }
    },
    [dispatch, navigateTo, router]
  );

  const openDeck = useCallback(
    (deck: DecryptedSavedDeck) => {
      if (isProjectEmpty || !isProjectDirty) {
        performLoad(deck);
      } else {
        setPendingLoadDeck(deck);
      }
    },
    [isProjectEmpty, isProjectDirty, performLoad]
  );

  const element = React.createElement(
    React.Fragment,
    null,
    React.createElement(UnlockModal, {
      show: showUnlock,
      onCancel: () => setShowUnlock(false),
      onUnlocked: () => setShowUnlock(false),
    }),
    React.createElement(LoadSafetyModal, {
      show: pendingLoadDeck != null,
      onCancel: () => setPendingLoadDeck(null),
      onSafetyCompleted: () => {
        const deck = pendingLoadDeck;
        setPendingLoadDeck(null);
        if (deck != null) {
          performLoad(deck);
        }
      },
    })
  );

  return { element, openDeck, showUnlock, openUnlock };
}
