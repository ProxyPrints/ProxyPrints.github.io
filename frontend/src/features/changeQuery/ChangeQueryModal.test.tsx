/**
 * Owner ruling (item 1, companion to PR #820): retyping a slot's query through this modal is
 * refining which printing of an already-bound card is wanted, not discovering a new card - so it
 * joins the "already-imported card searches precisely" rule regardless of the live Fuzzy/Precise
 * search preference. The actual candidate-image search already inherits this automatically
 * (doSearch always routes project-slot queries through editorSearch/retrieve_card_identifiers,
 * which PR #820 forced precise unconditionally) - the one behaviour this modal's own code
 * controls is the DFC-back-pair suggestion, which used to consult the live global fuzzy setting.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { Front } from "@/common/constants";
import {
  cardDocument4,
  localBackend,
  projectSelectedImage1,
} from "@/common/test-constants";
import { ChangeQueryModal } from "@/features/changeQuery/ChangeQueryModal";
import { dfcPairsMatchingCards1And4, sampleCards } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { getDefaultSearchSettings } from "@/store/slices/searchSettingsSlice";
import { setupStore } from "@/store/store";

function renderModal() {
  const store = setupStore({
    backend: localBackend,
    project: projectSelectedImage1,
    // Global Fuzzy search preference is ON - this is the setting the DFC-back suggestion used to
    // read directly, and must no longer widen matching for an already-bound slot.
    searchSettings: getDefaultSearchSettings({}, true),
  });
  render(
    <Provider store={store}>
      <ChangeQueryModal
        slots={[[Front, 0]]}
        query="my search query"
        show
        handleClose={jest.fn()}
      />
    </Provider>
  );
}

test("retyping a slot's query to a fuzzy-only prefix match does not surface the DFC-back suggestion, even with the global fuzzy preference on", async () => {
  server.use(dfcPairsMatchingCards1And4, sampleCards);
  renderModal();
  const user = userEvent.setup();

  const input = await screen.findByLabelText(
    "change-selected-image-queries-text"
  );
  // "my search quer" is a proper prefix of the single dfc pair front key "my search query" - with
  // the global fuzzy preference this used to surface the suggestion via a prefix match. Retyping
  // a slot's query is now always precise, so only an exact key match should suggest.
  await user.clear(input);
  await user.type(input, "my search quer");
  await waitFor(() => expect(input).toHaveValue("my search quer"));

  expect(
    screen.queryByText(/matches a double-faced card pair/i)
  ).not.toBeInTheDocument();
});

test("retyping a slot's query to an exact dfc pair match still surfaces the DFC-back suggestion", async () => {
  server.use(dfcPairsMatchingCards1And4, sampleCards);
  renderModal();
  const user = userEvent.setup();

  const input = await screen.findByLabelText(
    "change-selected-image-queries-text"
  );
  await user.clear(input);
  await user.type(input, "my search query");

  await waitFor(() =>
    expect(
      screen.getByText(/matches a double-faced card pair/i)
    ).toBeInTheDocument()
  );
  // getDFCPairs' transformResponse normalises names via processQuery(), so the suggested back
  // renders lower-cased regardless of cardDocument4.name's own casing.
  expect(
    screen.getByText(cardDocument4.name.toLowerCase())
  ).toBeInTheDocument();
});
