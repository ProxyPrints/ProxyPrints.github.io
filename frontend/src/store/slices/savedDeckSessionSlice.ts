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
  /** The serialized deck payload (see deckPayload.ts) at the moment of the last load/save. */
  lastSavedSerialized: string | null;
}

const initialState: SavedDeckSessionState = {
  currentDeckKey: null,
  currentDeckName: null,
  lastSavedSerialized: null,
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
      }>
    ) => {
      state.currentDeckKey = action.payload.key;
      state.currentDeckName = action.payload.name;
      state.lastSavedSerialized = action.payload.serialized;
    },
    clearCurrentSavedDeck: (state) => {
      state.currentDeckKey = null;
      state.currentDeckName = null;
      state.lastSavedSerialized = null;
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
