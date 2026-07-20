import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { LoadDeckResponseKind, SourceType } from "@/common/schema_types";
import { localBackend, projectSelectedImage1 } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import { existingProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { decryptSavedDeckSummary } from "@/features/savedDecks/deckPayload";
import { SaveDeckModal } from "@/features/savedDecks/SaveDeckModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { setupStore } from "@/store/store";

/** Decrypts a captured saveDeck request body the same way the server-stored ciphertext would be
 * decrypted on load, to assert on the PR-6 "Revision tracking" fields living inside it. */
async function decryptSavedRequest(savedRequest: any, masterKey: CryptoKey) {
  return decryptSavedDeckSummary(
    {
      key: savedRequest.key ?? "unused-in-test",
      kind: savedRequest.kind ?? LoadDeckResponseKind.Deck,
      ciphertext: savedRequest.ciphertext,
      ciphertextNonce: savedRequest.ciphertextNonce,
      wrappedDek: savedRequest.wrappedDek,
      wrappedDekNonce: savedRequest.wrappedDekNonce,
      createdAt: "2026-01-01",
      updatedAt: "2026-01-01",
    },
    masterKey
  );
}

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
    lastSavedRevision: 1,
  });
  // PR-6 "Revision tracking" - a brand-new row always starts at revision 1.
  const decrypted = await decryptSavedRequest(savedRequest, profile.masterKey);
  expect(decrypted.payload.revision).toEqual(1);
  expect(decrypted.payload.modifiedAt).toBeTruthy();
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
      lastSavedRevision: 3,
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
  // PR-6 "Revision tracking" - continuing the SAME row's chain increments from its last known
  // revision (3, from the preloaded savedDeckSession state above), never restarting at 1.
  const decrypted = await decryptSavedRequest(savedRequest, profile.masterKey);
  expect(decrypted.payload.revision).toEqual(4);
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
