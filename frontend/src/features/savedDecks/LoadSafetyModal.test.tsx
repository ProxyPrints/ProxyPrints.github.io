import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { localBackend, projectSelectedImage1 } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import { existingProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { decryptSavedDeckSummary } from "@/features/savedDecks/deckPayload";
import { LoadSafetyModal } from "@/features/savedDecks/LoadSafetyModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

/** Decrypts a captured saveDeck request body to assert on the PR-6 "Revision tracking" fields
 * living inside its ciphertext. */
async function decryptSavedRequest(savedRequest: any, masterKey: CryptoKey) {
  return decryptSavedDeckSummary(
    {
      key: savedRequest.key ?? "unused-in-test",
      kind: savedRequest.kind,
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

function renderModal(
  onSafetyCompleted: () => void,
  savedDeckSession: {
    currentDeckKey: string | null;
    currentDeckName: string | null;
    lastSavedSerialized: string | null;
    lastSavedRevision: number | null;
  }
) {
  const store = setupStore({
    backend: localBackend,
    project: projectSelectedImage1,
    savedDeckSession,
  });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestUnlockButton />
        <LoadSafetyModal
          show
          onCancel={jest.fn()}
          onSafetyCompleted={onSafetyCompleted}
        />
      </CryptoSessionProvider>
    </Provider>
  );
}

test("never-saved project: only a single 'save backup and continue' action, no 'skip' option", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  let savedRequest: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
      savedRequest = await request.json();
      return HttpResponse.json({ key: "snapshot-key" }, { status: 200 });
    })
  );
  const onSafetyCompleted = jest.fn();
  renderModal(onSafetyCompleted, {
    currentDeckKey: null,
    currentDeckName: null,
    lastSavedSerialized: null,
    lastSavedRevision: null,
  });
  await unlockSession();

  expect(screen.queryByText(/Update /)).not.toBeInTheDocument();
  expect(
    (screen.getByLabelText("snapshot-name") as HTMLInputElement).value
  ).toContain("Backup - ");

  fireEvent.click(screen.getByText("Save backup and continue"));

  await waitFor(() => expect(onSafetyCompleted).toHaveBeenCalledTimes(1));
  expect(savedRequest.key).toBeNull();
  expect(savedRequest.kind).toEqual("snapshot");
});

test("already-saved deck: offers Update-in-place vs Save-as-new-snapshot", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const requests: Array<any> = [];
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
      requests.push(await request.json());
      return HttpResponse.json({ key: "some-key" }, { status: 200 });
    })
  );
  const onSafetyCompleted = jest.fn();
  renderModal(onSafetyCompleted, {
    currentDeckKey: "existing-deck-key",
    currentDeckName: "My Existing Deck",
    lastSavedSerialized: "stale",
    lastSavedRevision: 2,
  });
  await unlockSession();

  expect(screen.getByText("Update My Existing Deck")).toBeInTheDocument();
  expect(screen.getByText("Save as new snapshot")).toBeInTheDocument();

  fireEvent.click(screen.getByText("Save as new snapshot"));

  await waitFor(() => expect(onSafetyCompleted).toHaveBeenCalledTimes(1));
  expect(requests).toHaveLength(1);
  expect(requests[0].key).toBeNull();
  expect(requests[0].kind).toEqual("snapshot");
  // PR-6 "Revision tracking" - a brand-new snapshot row starts at 1, never inheriting the
  // dirty editor's prior saved row's revision (2, from the preloaded state above).
  const decrypted = await decryptSavedRequest(requests[0], profile.masterKey);
  expect(decrypted.payload.revision).toEqual(1);
});

test("already-saved deck: choosing Update sends the existing deck's key, kind deck", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const requests: Array<any> = [];
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    http.post("http://127.0.0.1:8000/2/saveDeck/", async ({ request }) => {
      requests.push(await request.json());
      return HttpResponse.json({ key: "existing-deck-key" }, { status: 200 });
    })
  );
  const onSafetyCompleted = jest.fn();
  renderModal(onSafetyCompleted, {
    currentDeckKey: "existing-deck-key",
    currentDeckName: "My Existing Deck",
    lastSavedSerialized: "stale",
    lastSavedRevision: 2,
  });
  await unlockSession();

  fireEvent.click(screen.getByText("Update My Existing Deck"));

  await waitFor(() => expect(onSafetyCompleted).toHaveBeenCalledTimes(1));
  expect(requests[0].key).toEqual("existing-deck-key");
  expect(requests[0].kind).toEqual("deck");
  // PR-6 "Revision tracking" - updating the SAME row continues its chain (2 -> 3).
  const decrypted = await decryptSavedRequest(requests[0], profile.masterKey);
  expect(decrypted.payload.revision).toEqual(3);
});
