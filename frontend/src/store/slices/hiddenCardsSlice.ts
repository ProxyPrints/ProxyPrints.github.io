import { createSelector, PayloadAction } from "@reduxjs/toolkit";

import { createAppSlice } from "@/common/types";
import { RootState } from "@/store/store";

//# region slice configuration

/**
 * Identifiers of cards this visitor hid for themselves via a `hide=True` card report
 * (issue #714 - see docs/features/moderation.md's hidden-card section). Mirrors the
 * server-side `HiddenCard` rows for the current anonymous identity: hydrated once at app
 * start from localStorage and written through on every `hideCard` (listener middleware), so
 * the current session's views drop a hidden card immediately on dispatch without waiting for
 * a refetch (the server-side question-feed filter is the durable mechanism).
 */
export interface HiddenCardsState {
  hiddenIdentifiers: string[];
}

const initialState: HiddenCardsState = {
  hiddenIdentifiers: [],
};

export const hiddenCardsSlice = createAppSlice({
  name: "hiddenCards",
  initialState,
  reducers: {
    /**
     * Replace the full hidden set (e.g., when hydrating from localStorage at app start).
     * @param hiddenIdentifiers - The complete hidden identifiers to set
     */
    setAllHiddenCardIdentifiers: (state, action: PayloadAction<string[]>) => {
      state.hiddenIdentifiers = action.payload;
    },
    /**
     * Hide a card for the current anonymous identity.
     * @param identifier - The card identifier to hide
     */
    hideCard: (state, action: PayloadAction<string>) => {
      if (!state.hiddenIdentifiers.includes(action.payload)) {
        state.hiddenIdentifiers.push(action.payload);
      }
    },
  },
});

export const { setAllHiddenCardIdentifiers, hideCard } =
  hiddenCardsSlice.actions;
export default hiddenCardsSlice.reducer;

//# endregion

//# region selectors

export const selectHiddenCardIdentifiers = (state: RootState): string[] =>
  state.hiddenCards.hiddenIdentifiers;

/**
 * Returns a Set of hidden identifiers for fast O(1) lookup.
 */
export const selectHiddenCardIdentifiersSet = createSelector(
  (state: RootState) => state.hiddenCards.hiddenIdentifiers,
  (hiddenIdentifiers) => new Set(hiddenIdentifiers)
);

//# endregion
