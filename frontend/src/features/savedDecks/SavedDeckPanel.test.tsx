import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { QueryTags } from "@/common/constants";
import { localBackend, projectSelectedImage1 } from "@/common/test-constants";
import { CryptoSessionProvider } from "@/features/savedDecks/cryptoSession";
import { noProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { SavedDeckPanel } from "@/features/savedDecks/SavedDeckPanel";
import { whoamiAnonymous, whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { api } from "@/store/api";
import { selectToastsNotifications } from "@/store/slices/toastsSlice";
import { setupStore } from "@/store/store";

function renderPanel(preloadedState: Parameters<typeof setupStore>[0]) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <SavedDeckPanel />
      </CryptoSessionProvider>
    </Provider>
  );
  return store;
}

test("unauthenticated: renders nothing", async () => {
  server.use(whoamiAnonymous);
  const store = renderPanel({ backend: localBackend });

  await waitFor(() => expect(store.getState().api.queries).not.toEqual({}));
  expect(screen.queryByTestId("saved-deck-breadcrumb")).not.toBeInTheDocument();
});

test("authenticated, no saved deck loaded: shows 'Unsaved project'", async () => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
  renderPanel({ backend: localBackend });

  await screen.findByTestId("saved-deck-breadcrumb");
  expect(screen.getByTestId("saved-deck-breadcrumb")).toHaveTextContent(
    "Unsaved project"
  );
});

test("authenticated, a saved deck is loaded: shows the reverse breadcrumb", async () => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
  renderPanel({
    backend: localBackend,
    savedDeckSession: {
      currentDeckKey: "some-key",
      currentDeckName: "My Deck",
      lastSavedSerialized: null,
    },
  });

  await screen.findByTestId("saved-deck-breadcrumb");
  expect(screen.getByTestId("saved-deck-breadcrumb")).toHaveTextContent(
    "Editing: My Deck"
  );
});

test("Save is disabled while the project is empty", async () => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
  renderPanel({ backend: localBackend });

  await screen.findByTestId("saved-deck-breadcrumb");
  expect(screen.getByText("Save")).toBeDisabled();
});

test("signing in while the project is non-empty raises the adopt-by-save toast", async () => {
  server.use(whoamiAnonymous);
  const store = renderPanel({
    backend: localBackend,
    project: projectSelectedImage1,
  });

  // the anonymous whoami result must actually land before switching handlers, or the
  // false -> true transition this toast depends on is never observed (see cryptoSession.tsx's
  // own "loading vs anonymous" regression fix for the same class of ordering bug)
  await waitFor(() =>
    expect(
      Object.values(store.getState().api.queries).some(
        (query: any) => query?.data?.authenticated === false
      )
    ).toBe(true)
  );

  server.use(whoamiSignedInNotModerator, noProfileHandler());
  store.dispatch(api.util.invalidateTags([QueryTags.BackendSpecific]));

  await waitFor(() => {
    const notifications = selectToastsNotifications(store.getState());
    expect(
      Object.values(notifications).some((n) => n.name === "Signed in")
    ).toBe(true);
  });
});

test("signing in with an empty project does not raise the adopt toast", async () => {
  server.use(whoamiAnonymous);
  const store = renderPanel({ backend: localBackend });

  server.use(whoamiSignedInNotModerator, noProfileHandler());
  store.dispatch(api.util.invalidateTags([QueryTags.BackendSpecific]));

  await screen.findByTestId("saved-deck-breadcrumb");
  const notifications = selectToastsNotifications(store.getState());
  expect(Object.values(notifications).some((n) => n.name === "Signed in")).toBe(
    false
  );
});
