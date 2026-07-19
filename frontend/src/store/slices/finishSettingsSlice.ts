import { PayloadAction } from "@reduxjs/toolkit";

import { CardstockFoilCompatibility } from "@/common/constants";
import { Cardstock, createAppSlice, FinishSettingsState } from "@/common/types";
import { RootState } from "@/store/store";

//# region slice configuration

const initialState: FinishSettingsState = {
  cardstock: "(S30) Standard Smooth",
  foil: false,
};

export const finishSettingsSlice = createAppSlice({
  name: "finishSettings",
  initialState,
  reducers: {
    setCardstock: (state, action: PayloadAction<Cardstock>) => {
      state.cardstock = action.payload;
      if (!CardstockFoilCompatibility[action.payload]) {
        state.foil = false;
      }
    },
    setFoil: (state, action: PayloadAction<boolean>) => {
      state.foil = CardstockFoilCompatibility[state.cardstock]
        ? action.payload
        : false;
    },
    toggleFoil: (state) => {
      state.foil = CardstockFoilCompatibility[state.cardstock]
        ? !state.foil
        : false;
    },
    /** Used when loading a saved deck - see projectSlice's `loadProject`. */
    loadFinishSettings: (state, action: PayloadAction<FinishSettingsState>) => {
      state.cardstock = action.payload.cardstock;
      state.foil = action.payload.foil;
    },
  },
});

export const { setCardstock, setFoil, toggleFoil, loadFinishSettings } =
  finishSettingsSlice.actions;
export default finishSettingsSlice.reducer;

//# endregion

//# region selectors

export const selectFinishSettings = (state: RootState): FinishSettingsState =>
  state.finishSettings;

//# endregion
