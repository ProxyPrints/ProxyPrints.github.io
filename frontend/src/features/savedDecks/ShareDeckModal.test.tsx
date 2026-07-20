import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import {
  bytesToBase64,
  createCryptoProfile,
  createDeckKey,
} from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import { existingProfileHandler } from "@/features/savedDecks/cryptoTestHandlers";
import { ShareDeckModal } from "@/features/savedDecks/ShareDeckModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
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

async function renderModal(onClose = jest.fn()) {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const { wrappedDek } = await createDeckKey(profile.masterKey);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestUnlockButton />
        <ShareDeckModal
          show
          onClose={onClose}
          deckKey="deck-1"
          deckName="My Deck"
          wrappedDek={bytesToBase64(wrappedDek.wrapped)}
          wrappedDekNonce={bytesToBase64(wrappedDek.nonce)}
        />
      </CryptoSessionProvider>
    </Provider>
  );
  await unlockSession();
}

test("creating a share posts the deckKey and a fresh wrapped-DEK-by-shareKey, then shows a copyable link", async () => {
  let createdRequest: any = null;
  server.use(
    http.post(
      "http://127.0.0.1:8000/2/createDeckShare/",
      async ({ request }) => {
        createdRequest = await request.json();
        return HttpResponse.json(
          { shareId: "share-abc", createdAt: "1st January, 2026" },
          { status: 200 }
        );
      }
    ),
    http.get("http://127.0.0.1:8000/2/deckShares/", () =>
      HttpResponse.json({ shares: [] }, { status: 200 })
    )
  );
  await renderModal();

  fireEvent.click(screen.getByText("Create share link"));

  await waitFor(() => expect(createdRequest).not.toBeNull());
  expect(createdRequest.deckKey).toEqual("deck-1");
  expect(createdRequest.wrappedDek).toBeTruthy();
  expect(createdRequest.expiresInDays).toBeNull();

  const linkText = await screen.findByTestId("share-link-text");
  expect(linkText.textContent).toContain("/shared?shareId=share-abc#");
});

test("lists existing shares for this deck only, and revoking calls the endpoint with its shareId", async () => {
  let revokedRequest: any = null;
  server.use(
    http.get("http://127.0.0.1:8000/2/deckShares/", () =>
      HttpResponse.json(
        {
          shares: [
            {
              shareId: "share-1",
              deckKey: "deck-1",
              createdAt: "1st January, 2026",
              expiresAt: null,
            },
            {
              shareId: "share-2",
              deckKey: "some-other-deck",
              createdAt: "2nd January, 2026",
              expiresAt: null,
            },
          ],
        },
        { status: 200 }
      )
    ),
    http.post(
      "http://127.0.0.1:8000/2/revokeDeckShare/",
      async ({ request }) => {
        revokedRequest = await request.json();
        return HttpResponse.json({ deleted: true }, { status: 200 });
      }
    )
  );
  const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
  await renderModal();

  const sharesList = await screen.findByTestId("active-shares-list");
  // only this deck's share shows up, not the other deck's
  expect(sharesList).toHaveTextContent("Created 1st January, 2026");
  expect(sharesList).not.toHaveTextContent("2nd January, 2026");

  fireEvent.click(screen.getByText("Revoke"));
  await waitFor(() => expect(revokedRequest).toEqual({ shareId: "share-1" }));
  confirmSpy.mockRestore();
});
