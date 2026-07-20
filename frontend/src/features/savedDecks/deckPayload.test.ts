/**
 * PR-6 "Revision tracking" (docs/proposals/proposal-g-user-accounts-saved-decks.md) coverage:
 * the v1 -> v2 upgrade path, the content/revision split that keeps the dirty-check baseline
 * stable, and the two encrypt entry points (`encryptDeckPayloadForSave` bumps revision,
 * `encryptFinalizedDeckPayload` preserves it verbatim - the one import needs).
 */

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { LoadDeckResponseKind } from "@/common/schema_types";
import { FinishSettingsState, Project } from "@/common/types";
import {
  buildDeckPayload,
  countDeviceLocalSlots,
  DECK_PAYLOAD_VERSION,
  deckContentForComparison,
  DeckPayloadV1,
  decryptSavedDeckSummary,
  encryptDeckPayloadForSave,
  encryptFinalizedDeckPayload,
  parseDeckPayload,
  serializeDeckPayload,
} from "@/features/savedDecks/deckPayload";

const TEST_ITERATIONS = 100;

const emptyFinishSettings: FinishSettingsState = {
  cardstock: "(S30) Standard Smooth",
  foil: false,
};

const emptyProject: Project = {
  members: [],
  nextMemberId: 0,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

function v1Payload(name: string): DeckPayloadV1 {
  return {
    version: 1,
    name,
    members: [],
    cardback: null,
    manualOverrides: {},
    finishSettings: emptyFinishSettings,
  };
}

test("buildDeckPayload's output never carries version/revision/modifiedAt - only content", () => {
  const content = buildDeckPayload(
    "My Deck",
    emptyProject,
    emptyFinishSettings,
    {}
  );
  expect(content).not.toHaveProperty("version");
  expect(content).not.toHaveProperty("revision");
  expect(content).not.toHaveProperty("modifiedAt");
  expect(countDeviceLocalSlots(content)).toEqual(0);
});

test("buildDeckPayload is deterministic across calls with identical inputs - the dirty-check's own invariant", () => {
  const first = serializeDeckPayload(
    buildDeckPayload("My Deck", emptyProject, emptyFinishSettings, {})
  );
  const second = serializeDeckPayload(
    buildDeckPayload("My Deck", emptyProject, emptyFinishSettings, {})
  );
  expect(first).toEqual(second);
});

test("parseDeckPayload upgrades a legacy v1 payload to v2, backfilling revision 0 and a fallback modifiedAt", () => {
  const serialized = JSON.stringify(v1Payload("Legacy Deck"));
  const upgraded = parseDeckPayload(serialized, "2026-01-02T00:00:00.000Z");
  expect(upgraded.version).toEqual(2);
  expect(upgraded.revision).toEqual(0);
  expect(upgraded.modifiedAt).toEqual("2026-01-02T00:00:00.000Z");
  expect(upgraded.name).toEqual("Legacy Deck");
});

test("parseDeckPayload reads a v2 payload as-is, and rejects an unrecognised version", () => {
  const v2 = {
    version: 2,
    name: "Modern Deck",
    members: [],
    cardback: null,
    manualOverrides: {},
    finishSettings: emptyFinishSettings,
    revision: 5,
    modifiedAt: "2026-01-01T00:00:00.000Z",
  };
  expect(parseDeckPayload(JSON.stringify(v2))).toEqual(v2);
  expect(() => parseDeckPayload(JSON.stringify({ version: 99 }))).toThrow(
    "Unsupported saved deck payload version: 99"
  );
});

test("deckContentForComparison strips version/revision/modifiedAt so a loaded deck's baseline matches a freshly-rebuilt draft", () => {
  const content = buildDeckPayload(
    "Round Trip",
    emptyProject,
    emptyFinishSettings,
    {}
  );
  const finalized = {
    ...content,
    version: DECK_PAYLOAD_VERSION as 2,
    revision: 7,
    modifiedAt: "2026-01-01T00:00:00.000Z",
  };
  expect(serializeDeckPayload(deckContentForComparison(finalized))).toEqual(
    serializeDeckPayload(content)
  );
});

test("encryptDeckPayloadForSave bumps revision from previousRevision, and stamps a fresh modifiedAt", async () => {
  const { masterKey } = await createCryptoProfile(
    "passphrase",
    TEST_ITERATIONS
  );
  const content = buildDeckPayload(
    "Bumped",
    emptyProject,
    emptyFinishSettings,
    {}
  );
  const freshRow = await encryptDeckPayloadForSave(content, masterKey, null);
  expect(freshRow.revision).toEqual(1);

  const continuedRow = await encryptDeckPayloadForSave(
    content,
    masterKey,
    freshRow.revision
  );
  expect(continuedRow.revision).toEqual(2);

  const decrypted = await decryptSavedDeckSummary(
    {
      key: "k",
      kind: LoadDeckResponseKind.Deck,
      ciphertext: continuedRow.ciphertext,
      ciphertextNonce: continuedRow.ciphertextNonce,
      wrappedDek: continuedRow.wrappedDek,
      wrappedDekNonce: continuedRow.wrappedDekNonce,
      createdAt: "2026-01-01",
      updatedAt: "2026-01-01",
    },
    masterKey
  );
  expect(decrypted.payload.revision).toEqual(2);
  expect(decrypted.payload.modifiedAt).toEqual(continuedRow.modifiedAt);
});

test("encryptFinalizedDeckPayload preserves an already-finalized payload's revision/modifiedAt verbatim - the import path's requirement", async () => {
  const { masterKey } = await createCryptoProfile(
    "passphrase",
    TEST_ITERATIONS
  );
  const finalized = {
    ...buildDeckPayload("Imported", emptyProject, emptyFinishSettings, {}),
    version: DECK_PAYLOAD_VERSION as 2,
    revision: 42,
    modifiedAt: "2020-01-01T00:00:00.000Z",
  };
  const encrypted = await encryptFinalizedDeckPayload(finalized, masterKey);
  const decrypted = await decryptSavedDeckSummary(
    {
      key: "k",
      kind: LoadDeckResponseKind.Deck,
      ...encrypted,
      createdAt: "2026-01-01",
      updatedAt: "2026-01-01",
    },
    masterKey
  );
  expect(decrypted.payload.revision).toEqual(42);
  expect(decrypted.payload.modifiedAt).toEqual("2020-01-01T00:00:00.000Z");
});
