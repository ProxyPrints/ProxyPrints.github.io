import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import {
  bytesToBase64,
  createCryptoProfile,
  createDeckKey,
  encryptDeckPayload,
} from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import { prepareDeckShare } from "@/features/savedDecks/deckShare";
import { SharedDeckPage } from "@/features/savedDecks/SharedDeckPage";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

let mockQuery: Record<string, string> = {};
jest.mock("next/router", () => ({
  useRouter: () => ({ isReady: true, query: mockQuery }),
}));

function renderPage() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <SharedDeckPage />
    </Provider>
  );
}

beforeEach(() => {
  mockQuery = {};
  window.history.replaceState(null, "", "/shared");
});

test("missing shareId or fragment key shows an error, without fetching anything", async () => {
  mockQuery = {};
  window.history.replaceState(null, "", "/shared");
  renderPage();
  await screen.findByText("This share link is missing its shareId or key.");
});

test("a valid share fetches, decrypts, and renders the deck's name", async () => {
  const profile = await createCryptoProfile("owner passphrase", 100);
  const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
  const { ciphertext, nonce } = await encryptDeckPayload(
    JSON.stringify({
      version: 1,
      name: "A Shared Deck",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: {},
    }),
    dek
  );
  const prepared = await prepareDeckShare(wrappedDek, profile.masterKey);

  server.use(
    http.post("http://127.0.0.1:8000/2/getSharedDeck/", async ({ request }) => {
      const body = (await request.json()) as any;
      expect(body.shareId).toEqual("share-xyz");
      return HttpResponse.json(
        {
          ciphertext: bytesToBase64(ciphertext),
          ciphertextNonce: bytesToBase64(nonce),
          wrappedDek: prepared.wrappedDek,
          wrappedDekNonce: prepared.wrappedDekNonce,
          createdAt: "1st January, 2026",
        },
        { status: 200 }
      );
    })
  );

  mockQuery = { shareId: "share-xyz" };
  window.history.replaceState(null, "", `/shared#${prepared.shareKeyFragment}`);
  renderPage();

  await screen.findByText("A Shared Deck");
  await screen.findByText("Shared on 1st January, 2026");
});

test("a wrong/tampered fragment key shows an error instead of garbage content", async () => {
  const profile = await createCryptoProfile("owner passphrase", 100);
  const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
  const { ciphertext, nonce } = await encryptDeckPayload(
    JSON.stringify({
      version: 1,
      name: "A Shared Deck",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: {},
    }),
    dek
  );
  const prepared = await prepareDeckShare(wrappedDek, profile.masterKey);

  server.use(
    http.post("http://127.0.0.1:8000/2/getSharedDeck/", () =>
      HttpResponse.json(
        {
          ciphertext: bytesToBase64(ciphertext),
          ciphertextNonce: bytesToBase64(nonce),
          wrappedDek: prepared.wrappedDek,
          wrappedDekNonce: prepared.wrappedDekNonce,
          createdAt: "1st January, 2026",
        },
        { status: 200 }
      )
    )
  );

  mockQuery = { shareId: "share-xyz" };
  // deliberately the WRONG fragment key
  window.history.replaceState(
    null,
    "",
    "/shared#wrongkeywrongkeywrongkeywrongkey"
  );
  renderPage();

  await screen.findByText(
    "This share link is invalid, expired, or has been revoked."
  );
});
