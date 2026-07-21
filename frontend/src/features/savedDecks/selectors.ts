import { createSelector } from "@reduxjs/toolkit";

import {
  buildDeckPayload,
  serializeDeckPayload,
} from "@/features/savedDecks/deckPayload";
import { selectCardSpacing } from "@/store/slices/cardSpacingSlice";
import { selectFinishSettings } from "@/store/slices/finishSettingsSlice";
import {
  selectIsProjectEmpty,
  selectManualOverrides,
  selectProjectCardback,
  selectProjectMembers,
} from "@/store/slices/projectSlice";
import {
  SavedDeckSessionState,
  selectCurrentSavedDeck,
} from "@/store/slices/savedDeckSessionSlice";
import { RootState } from "@/store/store";

/**
 * "Dirty" per the frontend spec's load-into-editor section: the in-memory project differs
 * from whatever it was last loaded from/saved as, or is simply non-empty with no prior save
 * at all. Comparing serialized-payload strings (rather than deep object equality) is cheap and
 * exactly as precise, since both sides go through the same `serializeDeckPayload` function -
 * the `currentDeckName` is used on both sides too, so a rename alone (only possible via the
 * Save flow itself) never falsely marks the project dirty by name mismatch.
 */
export const selectIsCurrentProjectDirty = createSelector(
  (state: RootState) => selectIsProjectEmpty(state),
  (state: RootState) => selectCurrentSavedDeck(state),
  (state: RootState) => selectProjectMembers(state),
  (state: RootState) => selectProjectCardback(state),
  (state: RootState) => selectManualOverrides(state),
  (state: RootState) => selectFinishSettings(state),
  (state: RootState) => selectCardSpacing(state),
  (state: RootState) => state.cardDocuments.cardDocuments,
  (
    isProjectEmpty,
    savedDeckSession: SavedDeckSessionState,
    members,
    cardback,
    manualOverrides,
    finishSettings,
    cardSpacing,
    cardDocuments
  ): boolean => {
    if (isProjectEmpty) {
      return false;
    }
    if (savedDeckSession.lastSavedSerialized == null) {
      return true;
    }
    const currentSerialized = serializeDeckPayload(
      buildDeckPayload(
        savedDeckSession.currentDeckName ?? "",
        {
          members,
          nextMemberId: 0,
          cardback: cardback ?? null,
          mostRecentlySelectedSlot: null,
          manualOverrides,
        },
        finishSettings,
        cardDocuments,
        cardSpacing
      )
    );
    return currentSerialized !== savedDeckSession.lastSavedSerialized;
  }
);
