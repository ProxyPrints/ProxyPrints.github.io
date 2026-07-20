/**
 * Zero-dependency test for decrypt.mjs, using Node's own built-in test runner (`node --test`) -
 * no npm install needed to verify this tool, matching its own "dependency-minimal" promise.
 * Builds a bundle independently (via raw WebCrypto calls mirroring
 * frontend/src/common/savedDeckCrypto.ts's own wrap/encrypt logic) rather than importing
 * anything from the frontend, so this test also serves as a live cross-check that decrypt.mjs's
 * understanding of the wire format hasn't drifted from the browser's.
 *
 * Run with: node --test decrypt-saved-deck-export/tests/decrypt.test.mjs
 */

import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";

import { decryptBundle } from "../decrypt.mjs";

const { subtle } = webcrypto;
const getRandomValues = webcrypto.getRandomValues.bind(webcrypto);

function bytesToBase64(bytes) {
  return Buffer.from(bytes).toString("base64");
}

async function buildTestBundle(passphrase, deckPayloads) {
  const salt = getRandomValues(new Uint8Array(16));
  const iterations = 100;
  const baseKey = await subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  const passphraseKey = await subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey"]
  );

  const masterKey = await subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["wrapKey", "unwrapKey"]
  );
  const passphraseWrapNonce = getRandomValues(new Uint8Array(12));
  const passphraseWrappedMasterKey = await subtle.wrapKey(
    "raw",
    masterKey,
    passphraseKey,
    { name: "AES-GCM", iv: passphraseWrapNonce }
  );

  // Recovery slot isn't exercised by these tests but the format requires it to be present.
  const recoveryKeyBytes = getRandomValues(new Uint8Array(32));
  const recoveryKey = await subtle.importKey(
    "raw",
    recoveryKeyBytes,
    "AES-GCM",
    false,
    ["wrapKey"]
  );
  const recoveryWrapNonce = getRandomValues(new Uint8Array(12));
  const recoveryWrappedMasterKey = await subtle.wrapKey(
    "raw",
    masterKey,
    recoveryKey,
    { name: "AES-GCM", iv: recoveryWrapNonce }
  );

  const decks = [];
  for (const [index, payload] of deckPayloads.entries()) {
    const dek = await subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      true,
      ["encrypt", "decrypt", "wrapKey", "unwrapKey"]
    );
    const dekWrapNonce = getRandomValues(new Uint8Array(12));
    const wrappedDek = await subtle.wrapKey("raw", dek, masterKey, {
      name: "AES-GCM",
      iv: dekWrapNonce,
    });
    const ciphertextNonce = getRandomValues(new Uint8Array(12));
    const ciphertext = await subtle.encrypt(
      { name: "AES-GCM", iv: ciphertextNonce },
      dek,
      new TextEncoder().encode(JSON.stringify(payload))
    );
    decks.push({
      key: `deck-${index}`,
      kind: "deck",
      ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
      ciphertextNonce: bytesToBase64(ciphertextNonce),
      wrappedDek: bytesToBase64(new Uint8Array(wrappedDek)),
      wrappedDekNonce: bytesToBase64(dekWrapNonce),
      createdAt: "2026-01-01",
      updatedAt: "2026-01-02",
    });
  }

  return {
    formatVersion: 1,
    exportedAt: "2026-01-02T00:00:00.000Z",
    cryptoProfile: {
      salt: bytesToBase64(salt),
      kdfIterations: iterations,
      passphraseWrappedMasterKey: bytesToBase64(
        new Uint8Array(passphraseWrappedMasterKey)
      ),
      passphraseWrappedMasterKeyNonce: bytesToBase64(passphraseWrapNonce),
      recoveryWrappedMasterKey: bytesToBase64(
        new Uint8Array(recoveryWrappedMasterKey)
      ),
      recoveryWrappedMasterKeyNonce: bytesToBase64(recoveryWrapNonce),
    },
    decks,
  };
}

async function unlockWithPassphrase(bundle, passphrase) {
  const baseKey = await subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  const passphraseKey = await subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: Buffer.from(bundle.cryptoProfile.salt, "base64"),
      iterations: bundle.cryptoProfile.kdfIterations,
      hash: "SHA-256",
    },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["unwrapKey"]
  );
  return subtle.unwrapKey(
    "raw",
    Buffer.from(bundle.cryptoProfile.passphraseWrappedMasterKey, "base64"),
    passphraseKey,
    {
      name: "AES-GCM",
      iv: Buffer.from(
        bundle.cryptoProfile.passphraseWrappedMasterKeyNonce,
        "base64"
      ),
    },
    { name: "AES-GCM", length: 256 },
    true,
    ["unwrapKey", "decrypt"]
  );
}

test("decryptBundle recovers every deck's plaintext payload given the bundle's own master key", async () => {
  const bundle = await buildTestBundle("the real passphrase", [
    { version: 2, name: "Aggro", revision: 3, modifiedAt: "2026-01-01" },
    { version: 1, name: "Legacy Deck" },
  ]);
  const masterKey = await unlockWithPassphrase(bundle, "the real passphrase");

  const decrypted = await decryptBundle(bundle, masterKey);
  assert.equal(decrypted.length, 2);
  assert.equal(decrypted[0].payload.name, "Aggro");
  assert.equal(decrypted[0].payload.revision, 3);
  assert.equal(decrypted[1].payload.name, "Legacy Deck");
  assert.equal(decrypted[1].payload.version, 1);
});

test("a wrong master key fails to decrypt (AES-GCM authentication failure), never returns silently-wrong plaintext", async () => {
  const bundle = await buildTestBundle("the real passphrase", [
    { version: 2, name: "Aggro", revision: 1, modifiedAt: "2026-01-01" },
  ]);
  const wrongMasterKey = await subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["wrapKey", "unwrapKey"]
  );
  await assert.rejects(() => decryptBundle(bundle, wrongMasterKey));
});
