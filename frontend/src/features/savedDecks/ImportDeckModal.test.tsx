/**
 * "PR-6, post-v1: deck portability" import flow: a bundle exported under one crypto profile
 * (its own passphrase) gets decrypted, then persisted under a DIFFERENT (the current session's)
 * master key - always as new rows, preserving each deck's own revision/modifiedAt verbatim.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { bytesToBase64, createCryptoProfile } from "@/common/savedDeckCrypto";
import { localBackend, localBackendURL } from "@/common/test-constants";
import { buildMockSavedDeckSummary } from "@/features/savedDecks/cryptoTestHandlers";
import {
  buildExportBundle,
  serializeExportBundle,
} from "@/features/savedDecks/deckExportImport";
import { decryptSavedDeckSummary } from "@/features/savedDecks/deckPayload";
import { ImportDeckModal } from "@/features/savedDecks/ImportDeckModal";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

function renderModal(props: React.ComponentProps<typeof ImportDeckModal>) {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <ImportDeckModal {...props} />
    </Provider>
  );
}

const TEST_ITERATIONS = 100;
const BUNDLE_PASSPHRASE = "the exported passphrase";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

test("importing a bundle decrypts it with ITS OWN passphrase, then persists every deck as new under the current session's master key, preserving revision/modifiedAt", async () => {
  const bundleProfile = await createCryptoProfile(
    BUNDLE_PASSPHRASE,
    TEST_ITERATIONS
  );
  const currentSessionProfile = await createCryptoProfile(
    "a completely different passphrase",
    TEST_ITERATIONS
  );

  const deckA = await buildMockSavedDeckSummary(
    "deck-a",
    "deck",
    {
      version: 2,
      name: "Aggro Deck",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
      revision: 5,
      modifiedAt: "2025-06-01T00:00:00.000Z",
    },
    bundleProfile.masterKey,
    { createdAt: "2025-01-01", updatedAt: "2025-06-01" }
  );
  const deckB = await buildMockSavedDeckSummary(
    "deck-b",
    "snapshot",
    {
      version: 2,
      name: "Backup",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
      revision: 1,
      modifiedAt: "2025-06-02T00:00:00.000Z",
    },
    bundleProfile.masterKey,
    { createdAt: "2025-06-02", updatedAt: "2025-06-02" }
  );

  const realBundle = buildExportBundle(
    {
      exists: true,
      salt: bytesToBase64(bundleProfile.salt),
      kdfIterations: bundleProfile.iterations,
      passphraseWrappedMasterKey: bytesToBase64(
        bundleProfile.passphraseWrapped.wrapped
      ),
      passphraseWrappedMasterKeyNonce: bytesToBase64(
        bundleProfile.passphraseWrapped.nonce
      ),
      recoveryWrappedMasterKey: bytesToBase64(
        bundleProfile.recoveryWrapped.wrapped
      ),
      recoveryWrappedMasterKeyNonce: bytesToBase64(
        bundleProfile.recoveryWrapped.nonce
      ),
    },
    [deckA, deckB]
  );

  const requests: Array<any> = [];
  server.use(
    http.post(buildRoute("2/saveDeck/"), async ({ request }) => {
      const body = await request.json();
      requests.push(body);
      return HttpResponse.json(
        { key: `imported-${requests.length}` },
        {
          status: 200,
        }
      );
    })
  );

  const onImported = jest.fn();
  renderModal({
    show: true,
    onCancel: jest.fn(),
    onImported,
    masterKey: currentSessionProfile.masterKey,
  });

  const file = new File([serializeExportBundle(realBundle)], "export.json", {
    type: "application/json",
  });
  fireEvent.change(screen.getByLabelText("import-file"), {
    target: { files: [file] },
  });

  await screen.findByText(/2 decks found/);
  fireEvent.change(screen.getByLabelText("import-passphrase"), {
    target: { value: BUNDLE_PASSPHRASE },
  });
  fireEvent.click(screen.getByText("Import"));

  await waitFor(() => expect(onImported).toHaveBeenCalledWith(2));
  expect(requests).toHaveLength(2);
  expect(requests.every((r) => r.key === null)).toBe(true);
  expect(requests.map((r) => r.kind).sort()).toEqual(["deck", "snapshot"]);

  // Every persisted row decrypts under the CURRENT session's master key (not the bundle's own),
  // and keeps its original revision/modifiedAt (deck-portability's whole point).
  const decryptedRequests = await Promise.all(
    requests.map((body) =>
      decryptSavedDeckSummary(
        {
          key: "unused",
          kind: body.kind,
          ciphertext: body.ciphertext,
          ciphertextNonce: body.ciphertextNonce,
          wrappedDek: body.wrappedDek,
          wrappedDekNonce: body.wrappedDekNonce,
          createdAt: "2026-01-01",
          updatedAt: "2026-01-01",
        },
        currentSessionProfile.masterKey
      )
    )
  );
  const names = decryptedRequests.map((d) => d.name).sort();
  expect(names).toEqual(["Aggro Deck", "Backup"]);
  const aggro = decryptedRequests.find((d) => d.name === "Aggro Deck")!;
  expect(aggro.payload.revision).toEqual(5);
  expect(aggro.payload.modifiedAt).toEqual("2025-06-01T00:00:00.000Z");
});

test("a wrong passphrase for the bundle shows an error, without persisting anything", async () => {
  const bundleProfile = await createCryptoProfile(
    BUNDLE_PASSPHRASE,
    TEST_ITERATIONS
  );
  const currentSessionProfile = await createCryptoProfile(
    "current session passphrase",
    TEST_ITERATIONS
  );
  const realBundle = buildExportBundle(
    {
      exists: true,
      salt: bytesToBase64(bundleProfile.salt),
      kdfIterations: bundleProfile.iterations,
      passphraseWrappedMasterKey: bytesToBase64(
        bundleProfile.passphraseWrapped.wrapped
      ),
      passphraseWrappedMasterKeyNonce: bytesToBase64(
        bundleProfile.passphraseWrapped.nonce
      ),
      recoveryWrappedMasterKey: bytesToBase64(
        bundleProfile.recoveryWrapped.wrapped
      ),
      recoveryWrappedMasterKeyNonce: bytesToBase64(
        bundleProfile.recoveryWrapped.nonce
      ),
    },
    []
  );

  let saveDeckCalled = false;
  server.use(
    http.post(buildRoute("2/saveDeck/"), async () => {
      saveDeckCalled = true;
      return HttpResponse.json({ key: "should-not-happen" }, { status: 200 });
    })
  );

  const onImported = jest.fn();
  renderModal({
    show: true,
    onCancel: jest.fn(),
    onImported,
    masterKey: currentSessionProfile.masterKey,
  });

  const file = new File([serializeExportBundle(realBundle)], "export.json", {
    type: "application/json",
  });
  fireEvent.change(screen.getByLabelText("import-file"), {
    target: { files: [file] },
  });

  await screen.findByText(/0 decks found/);
  fireEvent.change(screen.getByLabelText("import-passphrase"), {
    target: { value: "definitely wrong" },
  });
  fireEvent.click(screen.getByText("Import"));

  await screen.findByText("That passphrase doesn't match this file.");
  expect(onImported).not.toHaveBeenCalled();
  expect(saveDeckCalled).toBe(false);
});
