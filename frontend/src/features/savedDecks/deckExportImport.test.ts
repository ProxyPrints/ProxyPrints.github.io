/**
 * "PR-6, post-v1: deck portability" (docs/proposals/proposal-g-user-accounts-saved-decks.md) -
 * export/import bundle round-trip, both unlock paths (passphrase and recovery key), and the
 * format-version guard that keeps a future incompatible bundle from being silently misread.
 */

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { bytesToBase64 } from "@/common/savedDeckCrypto";
import { CryptoProfileResponse } from "@/common/schema_types";
import { buildMockSavedDeckSummary } from "@/features/savedDecks/cryptoTestHandlers";
import {
  buildExportBundle,
  decryptBundleDecks,
  EXPORT_FORMAT_VERSION,
  parseExportBundle,
  serializeExportBundle,
  unlockBundleMasterKeyWithPassphrase,
  unlockBundleMasterKeyWithRecoveryKey,
} from "@/features/savedDecks/deckExportImport";

const TEST_ITERATIONS = 100;
const PASSPHRASE = "the real one";

function cryptoProfileResponse(profile: {
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
}): CryptoProfileResponse {
  return {
    exists: true,
    salt: bytesToBase64(profile.salt),
    kdfIterations: profile.iterations,
    passphraseWrappedMasterKey: bytesToBase64(
      profile.passphraseWrapped.wrapped
    ),
    passphraseWrappedMasterKeyNonce: bytesToBase64(
      profile.passphraseWrapped.nonce
    ),
    recoveryWrappedMasterKey: bytesToBase64(profile.recoveryWrapped.wrapped),
    recoveryWrappedMasterKeyNonce: bytesToBase64(profile.recoveryWrapped.nonce),
  };
}

test("buildExportBundle refuses to export without a real crypto profile", () => {
  expect(() =>
    buildExportBundle(
      {
        exists: false,
        salt: null,
        kdfIterations: null,
        passphraseWrappedMasterKey: null,
        passphraseWrappedMasterKeyNonce: null,
        recoveryWrappedMasterKey: null,
        recoveryWrappedMasterKeyNonce: null,
      },
      []
    )
  ).toThrow(/No saved-deck crypto profile/);
});

test("parseExportBundle rejects an unsupported formatVersion and malformed bundles", () => {
  expect(() =>
    parseExportBundle(JSON.stringify({ formatVersion: 99, decks: [] }))
  ).toThrow(/Unsupported saved-deck export format version: 99/);
  expect(() =>
    parseExportBundle(JSON.stringify({ formatVersion: EXPORT_FORMAT_VERSION }))
  ).toThrow(/Malformed/);
});

test("export -> serialize -> parse -> unlock (passphrase) -> decrypt round-trips every deck, including its revision", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const deck = await buildMockSavedDeckSummary(
    "deck-1",
    "deck",
    {
      version: 2,
      name: "Commander Deck",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
      revision: 3,
      modifiedAt: "2026-01-01T00:00:00.000Z",
    },
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );

  const bundle = buildExportBundle(cryptoProfileResponse(profile), [deck]);
  expect(bundle.formatVersion).toEqual(EXPORT_FORMAT_VERSION);

  const reparsed = parseExportBundle(serializeExportBundle(bundle));
  expect(reparsed.decks).toHaveLength(1);

  const bundleMasterKey = await unlockBundleMasterKeyWithPassphrase(
    reparsed,
    PASSPHRASE
  );
  const decrypted = await decryptBundleDecks(reparsed, bundleMasterKey);
  expect(decrypted).toHaveLength(1);
  expect(decrypted[0].name).toEqual("Commander Deck");
  expect(decrypted[0].payload.revision).toEqual(3);
  expect(decrypted[0].payload.modifiedAt).toEqual("2026-01-01T00:00:00.000Z");
});

test("unlockBundleMasterKeyWithRecoveryKey also unwraps the bundle's master key", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const bundle = buildExportBundle(cryptoProfileResponse(profile), []);

  const bundleMasterKey = await unlockBundleMasterKeyWithRecoveryKey(
    bundle,
    bytesToBase64(profile.recoveryKeyBytes)
  );
  expect(bundleMasterKey).toBeDefined();
});

test("a wrong passphrase fails to unlock the bundle's master key", async () => {
  const profile = await createCryptoProfile(PASSPHRASE, TEST_ITERATIONS);
  const bundle = buildExportBundle(cryptoProfileResponse(profile), []);

  await expect(
    unlockBundleMasterKeyWithPassphrase(bundle, "wrong passphrase")
  ).rejects.toThrow();
});
