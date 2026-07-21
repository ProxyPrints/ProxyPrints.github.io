import { PayloadAction } from "@reduxjs/toolkit";

import { DefaultCardSpacing } from "@/common/constants";
import { CardSpacingState, createAppSlice } from "@/common/types";
import { RootState } from "@/store/store";

//# region slice configuration
//
// Proposal H D18/D19 (docs/proposals/proposal-h-display-layout-spec.md) - the /display sheet's
// inter-card gutter used to be a hardcoded `useMemo` constant on DisplayPage.tsx (`{ row: 0, col:
// 0 }`); D19's right-rail "Card Spacing (mm)" control makes it live, user-editable state instead,
// seeded from D18's asymmetric default (0mm horizontal / 14.5mm vertical). Persisted per saved
// deck via the same `finishSettingsSlice` -> `deckPayload.ts` precedent (see that file's
// `cardSpacing` field) - this slice mirrors `finishSettingsSlice.ts`'s own shape almost exactly
// (a `load*` reducer for the saved-deck load path, a plain selector) on purpose.

const initialState: CardSpacingState = DefaultCardSpacing;

export const cardSpacingSlice = createAppSlice({
  name: "cardSpacing",
  initialState,
  reducers: {
    /** Horizontal gutter (between columns) - `layout.ts`'s width axis. */
    setCardSpacingCol: (state, action: PayloadAction<number>) => {
      state.col = action.payload;
    },
    /** Vertical gutter (between rows) - `layout.ts`'s height axis. */
    setCardSpacingRow: (state, action: PayloadAction<number>) => {
      state.row = action.payload;
    },
    /** Used when loading a saved deck - see useLoadSavedDeck's performLoad, mirroring
     * finishSettingsSlice's loadFinishSettings verbatim. */
    loadCardSpacing: (state, action: PayloadAction<CardSpacingState>) => {
      state.row = action.payload.row;
      state.col = action.payload.col;
    },
  },
});

export const { setCardSpacingCol, setCardSpacingRow, loadCardSpacing } =
  cardSpacingSlice.actions;
export default cardSpacingSlice.reducer;

//# endregion

//# region selectors

export const selectCardSpacing = (state: RootState): CardSpacingState =>
  state.cardSpacing;

//# endregion
