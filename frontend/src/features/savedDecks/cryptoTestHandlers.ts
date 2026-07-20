/**
 * Shared MSW handler builders for tests exercising CryptoSessionProvider and the saved-deck
 * endpoints (directly, or via a modal/page that consumes them) - kept in one place since
 * cryptoSession.test.tsx, PassphraseSetupModal.test.tsx, UnlockModal.test.tsx, and
 * MyDecksPage.test.tsx all need overlapping shapes.
 */

import { http, HttpResponse } from "msw";

import { bytesToBase64 } from "@/common/savedDeckCrypto";
import { LoadDeckResponseKind, SavedDeckSummary } from "@/common/schema_types";
import { localBackendURL } from "@/common/test-constants";
import {
  DeckPayload,
  encryptFinalizedDeckPayload,
} from "@/features/savedDecks/deckPayload";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

export function noProfileHandler() {
  return http.get(buildRoute("2/cryptoProfile/"), () =>
    HttpResponse.json(
      {
        exists: false,
        salt: null,
        kdfIterations: null,
        passphraseWrappedMasterKey: null,
        passphraseWrappedMasterKeyNonce: null,
        recoveryWrappedMasterKey: null,
        recoveryWrappedMasterKeyNonce: null,
      },
      { status: 200 }
    )
  );
}

export interface MockCryptoProfileMaterial {
  salt: Uint8Array<ArrayBuffer>;
  iterations: number;
  passphraseWrapped: {
    wrapped: Uint8Array<ArrayBuffer>;
    nonce: Uint8Array<ArrayBuffer>;
  };
  recoveryWrapped: {
    wrapped: Uint8Array<ArrayBuffer>;
    nonce: Uint8Array<ArrayBuffer>;
  };
}

export function existingProfileHandler(profile: MockCryptoProfileMaterial) {
  return http.get(buildRoute("2/cryptoProfile/"), () =>
    HttpResponse.json(
      {
        exists: true,
        salt: bytesToBase64(profile.salt),
        kdfIterations: profile.iterations,
        passphraseWrappedMasterKey: bytesToBase64(
          profile.passphraseWrapped.wrapped
        ),
        passphraseWrappedMasterKeyNonce: bytesToBase64(
          profile.passphraseWrapped.nonce
        ),
        recoveryWrappedMasterKey: bytesToBase64(
          profile.recoveryWrapped.wrapped
        ),
        recoveryWrappedMasterKeyNonce: bytesToBase64(
          profile.recoveryWrapped.nonce
        ),
      },
      { status: 200 }
    )
  );
}

export function saveCryptoProfileHandler(onSave: (body: any) => void) {
  return http.post(buildRoute("2/saveCryptoProfile/"), async ({ request }) => {
    onSave(await request.json());
    return HttpResponse.json({ saved: true }, { status: 200 });
  });
}

export function getSavedDecksHandler(decks: Array<SavedDeckSummary>) {
  return http.get(buildRoute("2/savedDecks/"), () =>
    HttpResponse.json({ decks }, { status: 200 })
  );
}

export function deleteDeckHandler(onDelete: (body: any) => void) {
  return http.post(buildRoute("2/deleteDeck/"), async ({ request }) => {
    onDelete(await request.json());
    return HttpResponse.json({ deleted: true }, { status: 200 });
  });
}

export function resetSavedDecksHandler(onReset: (body: any) => void) {
  return http.post(buildRoute("2/resetSavedDecks/"), async ({ request }) => {
    onReset(await request.json());
    return HttpResponse.json({ deletedDeckCount: 0 }, { status: 200 });
  });
}

export async function buildMockSavedDeckSummary(
  key: string,
  kind: "deck" | "snapshot",
  payload: DeckPayload,
  masterKey: CryptoKey,
  timestamps: { createdAt: string; updatedAt: string }
): Promise<SavedDeckSummary> {
  const encrypted = await encryptFinalizedDeckPayload(payload, masterKey);
  return {
    key,
    kind:
      kind === "deck"
        ? LoadDeckResponseKind.Deck
        : LoadDeckResponseKind.Snapshot,
    ...encrypted,
    ...timestamps,
  };
}
