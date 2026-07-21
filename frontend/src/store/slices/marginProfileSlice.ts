import { PayloadAction } from "@reduxjs/toolkit";

import { DefaultMarginProfile } from "@/common/constants";
import {
  createAppSlice,
  MarginProfileKey,
  MarginProfileState,
} from "@/common/types";
import { RootState } from "@/store/store";

//# region slice configuration
//
// Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md) - the /display sheet's margin
// profile used to be a hardcoded `useMemo` constant on DisplayPage.tsx (`{ top: 5, bottom: 5,
// left: 5, right: 5 }`); this makes it live, user-editable state instead, seeded from D5's
// Borderless default. Persisted per saved deck via the same `finishSettingsSlice` ->
// `deckPayload.ts` precedent `cardSpacingSlice.ts` already rides (see that slice's own module
// comment) - this slice mirrors both of theirs almost exactly (a `load*` reducer for the
// saved-deck load path, a plain selector) on purpose.

const initialState: MarginProfileState = DefaultMarginProfile;

export const marginProfileSlice = createAppSlice({
  name: "marginProfile",
  initialState,
  reducers: {
    setMarginProfile: (state, action: PayloadAction<MarginProfileKey>) => {
      state.profile = action.payload;
    },
    /** Used when loading a saved deck - see useLoadSavedDeck's performLoad, mirroring
     * loadCardSpacing/loadFinishSettings verbatim. */
    loadMarginProfile: (state, action: PayloadAction<MarginProfileState>) => {
      state.profile = action.payload.profile;
    },
  },
});

export const { setMarginProfile, loadMarginProfile } =
  marginProfileSlice.actions;
export default marginProfileSlice.reducer;

//# endregion

//# region selectors

export const selectMarginProfile = (state: RootState): MarginProfileState =>
  state.marginProfile;

//# endregion
