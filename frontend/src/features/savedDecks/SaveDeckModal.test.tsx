import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { SourceType } from "@/common/schema_types";
import { localBackend, projectSelectedImage1 } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import { existingProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { SaveDeckModal } from "@/features/savedDecks/SaveDeckModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

function TestUnlockButton() {
  const session = useCryptoSession();
  return (
    <>
      <span data-testid="test-session-status">{session.status}</span>
      <button
        data-testid="test-unlock"
        onClick={() => {
          session.unlockWithPassphrase(PASSPHRASE).catch(() => undefined);
        }}
      >
        test-unlock
      </button>
    </>
  );
}

function renderModal(
  onSaved: () => void,
  preloadedState: Parameters<typeof setupStore>[0] = {
    backend: localBackend,
    project: projectSelectedImage1,
  }
) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestUnlockButton />
        <SaveDeckModal show onCancel={jest.fn()} onSaved={onSaved} />
      </CryptoSessionProvider>
    </Provider>
  );
  return store;
}

async function unlockSession() {
  await waitFor(() =>
    expect(screen.getByTestId("test-session-status")).toHaveTextContent(
      "locked"
    )
  );
  fireEvent.click(screen.getByTestId("test-unlock"));
  await waitFor(() =>
    expect(screen.getByTestId("test-session-status")).toHaveTextContent(
      "unlocked"
    )
  );
}

test("saving a brand-new deck (no prior key) records the key the server returns", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  let savedRequest: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
      savedRequest = await request.json();
      return HttpResponse.json({ key: "new-deck-key" }, { status: 200 });
    })
  );
  const onSaved = jest.fn();
  const store = renderModal(onSaved);
  await unlockSession();

  fireEvent.change(screen.getByLabelText("save-deck-name"), {
    target: { value: "My New Deck" },
  });
  fireEvent.click(screen.getByText("Save"));

  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(savedRequest.key).toBeNull();
  expect(savedRequest.ciphertext).toBeTruthy();
  expect(selectCurrentSavedDeck(store.getState())).toMatchObject({
    currentDeckKey: "new-deck-key",
    currentDeckName: "My New Deck",
  });
});

test("saving over an already-loaded deck sends its existing key (an update, not a new deck)", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  let savedRequest: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
      savedRequest = await request.json();
      return HttpResponse.json({ key: "existing-key" }, { status: 200 });
    })
  );
  const store = setupStore({
    backend: localBackend,
    project: projectSelectedImage1,
    savedDeckSession: {
      currentDeckKey: "existing-key",
      currentDeckName: "Existing Deck",
      lastSavedSerialized: null,
    },
  });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestUnlockButton />
        <SaveDeckModal show onCancel={jest.fn()} onSaved={jest.fn()} />
      </CryptoSessionProvider>
    </Provider>
  );
  await unlockSession();

  // the name field is pre-filled with the existing deck's name
  expect(screen.getByLabelText("save-deck-name")).toHaveValue("Existing Deck");
  fireEvent.click(screen.getByText("Save"));

  await waitFor(() => expect(savedRequest).not.toBeNull());
  expect(savedRequest.key).toEqual("existing-key");
});

test("warns about local-file-sourced cards that won't restore on another device", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  const store = setupStore({
    backend: localBackend,
    project: projectSelectedImage1,
    cardDocuments: {
      status: "succeeded",
      error: null,
      cardDocuments: {
        [projectSelectedImage1.members[0].front!.selectedImage!]: {
          ...({} as any),
          sourceType: SourceType.LocalFile,
        },
      },
    },
  });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestUnlockButton />
        <SaveDeckModal show onCancel={jest.fn()} onSaved={jest.fn()} />
      </CryptoSessionProvider>
    </Provider>
  );
  await unlockSession();

  expect(
    screen.getByText(/won't be restorable on another device/)
  ).toBeInTheDocument();
});
