/**
 * Tracks which saved deck (if any) the current editor content represents - the reverse
 * breadcrumb ("Editing: {name}" / "Unsaved project") and the dirty-check baseline (frontend
 * spec §4's load-into-editor section). Deliberately session-only: not wired into
 * listenerMiddleware.ts's localStorage persistence, since it's meaningless without the crypto
 * session's unlocked master key, which is itself never persisted (see cryptoSession.tsx).
 */

import { PayloadAction } from "@reduxjs/toolkit";

import { createAppSlice } from "@/common/types";
import { RootState } from "@/store/store";

export interface SavedDeckSessionState {
  currentDeckKey: string | null;
  currentDeckName: string | null;
  /** The serialized deck CONTENT (deckPayload.ts's `DeckPayloadContent` - no version/revision/
   * modifiedAt) at the moment of the last load/save - the dirty-check baseline. */
  lastSavedSerialized: string | null;
  /** The last-known `revision` (deckPayload.ts's PR-6 "Revision tracking") for `currentDeckKey` -
   * null when there's no saved row yet, or it predates revision tracking (a legacy v1 payload,
   * upgraded to revision 0 on load - see parseDeckPayload). The next save of this SAME row
   * increments from here; a brand-new row (Save As New / import) always starts fresh at 1 and
   * never reads this value. */
  lastSavedRevision: number | null;
}

const initialState: SavedDeckSessionState = {
  currentDeckKey: null,
  currentDeckName: null,
  lastSavedSerialized: null,
  lastSavedRevision: null,
};

export const savedDeckSessionSlice = createAppSlice({
  name: "savedDeckSession",
  initialState,
  reducers: {
    setCurrentSavedDeck: (
      state,
      action: PayloadAction<{
        key: string;
        name: string;
        serialized: string;
        revision: number | null;
      }>
    ) => {
      state.currentDeckKey = action.payload.key;
      state.currentDeckName = action.payload.name;
      state.lastSavedSerialized = action.payload.serialized;
      state.lastSavedRevision = action.payload.revision;
    },
    clearCurrentSavedDeck: (state) => {
      state.currentDeckKey = null;
      state.currentDeckName = null;
      state.lastSavedSerialized = null;
      state.lastSavedRevision = null;
    },
  },
});

export const { setCurrentSavedDeck, clearCurrentSavedDeck } =
  savedDeckSessionSlice.actions;
export default savedDeckSessionSlice.reducer;

//# region selectors

export const selectCurrentSavedDeck = (
  state: RootState
): SavedDeckSessionState => state.savedDeckSession;

//# endregion
