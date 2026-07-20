#!/usr/bin/env node
/**
 * Standalone decrypt tool for a ProxyPrints saved-decks export bundle
 * (docs/proposals/proposal-g-user-accounts-saved-decks.md, "PR-6, post-v1: deck portability" -
 * see this directory's readme.md for the full format writeup). This file is the trust anchor for
 * "if this site vanishes tomorrow, your decks are still yours": it runs without this site, this
 * codebase, or any server existing at all - only Node's own built-in `node:crypto` WebCrypto
 * implementation (no npm dependencies whatsoever).
 *
 * Usage:
 *   node decrypt.mjs <export.json> --passphrase "..."
 *   node decrypt.mjs <export.json> --recovery-key "base64..."
 *   node decrypt.mjs <export.json>                          # prompts for a passphrase
 *
 * Prints every decrypted deck's plaintext JSON to stdout (one bundle -> one JSON array), or use
 * --out <dir> to write one file per deck instead.
 *
 * License: MIT (mirrors federation-hash-tool/'s precedent for a standalone, dependency-free
 * tool meant to run independently of this GPL-3.0 repository's own codebase).
 */

import { webcrypto } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createInterface } from "node:readline";
import { join } from "node:path";

const { subtle } = webcrypto;

const AES_ALGO = "AES-GCM";
const AES_KEY_LENGTH = 256;
const PBKDF2_HASH = "SHA-256";

//# region base64 <-> bytes - identical wire format to the browser's own savedDeckCrypto.ts

function base64ToBytes(base64) {
  return new Uint8Array(Buffer.from(base64, "base64"));
}

//# endregion

//# region key derivation/unwrap - MUST match frontend/src/common/savedDeckCrypto.ts exactly

async function derivePassphraseKey(passphrase, salt, iterations) {
  const baseKey = await subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: PBKDF2_HASH },
    baseKey,
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    false,
    ["unwrapKey"]
  );
}

async function importRecoveryKey(recoveryKeyBytes) {
  return subtle.importKey("raw", recoveryKeyBytes, AES_ALGO, false, [
    "unwrapKey",
  ]);
}

async function unwrapKey(wrapped, nonce, wrappingKey, unwrappedKeyUsages) {
  return subtle.unwrapKey(
    "raw",
    wrapped,
    wrappingKey,
    { name: AES_ALGO, iv: nonce },
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    true,
    unwrappedKeyUsages
  );
}

async function decryptPayload(ciphertext, nonce, dek) {
  const plaintext = await subtle.decrypt(
    { name: AES_ALGO, iv: nonce },
    dek,
    ciphertext
  );
  return new TextDecoder().decode(plaintext);
}

//# endregion

/** Unwraps the bundle's own master key, via either its passphrase or its recovery key -
 * whichever the caller supplies. Throws (AES-GCM authentication failure) on a wrong one. */
async function unlockBundleMasterKey(
  bundle,
  { passphrase, recoveryKeyBase64 }
) {
  const profile = bundle.cryptoProfile;
  if (passphrase != null) {
    const wrappingKey = await derivePassphraseKey(
      passphrase,
      base64ToBytes(profile.salt),
      profile.kdfIterations
    );
    return unwrapKey(
      base64ToBytes(profile.passphraseWrappedMasterKey),
      base64ToBytes(profile.passphraseWrappedMasterKeyNonce),
      wrappingKey,
      ["unwrapKey"]
    );
  }
  const wrappingKey = await importRecoveryKey(base64ToBytes(recoveryKeyBase64));
  return unwrapKey(
    base64ToBytes(profile.recoveryWrappedMasterKey),
    base64ToBytes(profile.recoveryWrappedMasterKeyNonce),
    wrappingKey,
    ["unwrapKey"]
  );
}

/** Decrypts every deck in the bundle, given its already-unwrapped master key. Returns an array
 * of `{ key, kind, createdAt, updatedAt, payload }` - `payload` is the plaintext DeckPayload
 * object exactly as frontend/src/features/savedDecks/deckPayload.ts defines it (v1 or v2). */
export async function decryptBundle(bundle, masterKey) {
  const results = [];
  for (const deck of bundle.decks) {
    const dek = await unwrapKey(
      base64ToBytes(deck.wrappedDek),
      base64ToBytes(deck.wrappedDekNonce),
      masterKey,
      ["decrypt"]
    );
    const plaintext = await decryptPayload(
      base64ToBytes(deck.ciphertext),
      base64ToBytes(deck.ciphertextNonce),
      dek
    );
    results.push({
      key: deck.key,
      kind: deck.kind,
      createdAt: deck.createdAt,
      updatedAt: deck.updatedAt,
      payload: JSON.parse(plaintext),
    });
  }
  return results;
}

function promptHidden(question) {
  return new Promise((resolve) => {
    const rl = createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer);
    });
  });
}

async function main() {
  const args = process.argv.slice(2);
  const filePath = args.find((arg) => !arg.startsWith("--"));
  if (filePath == null) {
    console.error(
      'Usage: node decrypt.mjs <export.json> [--passphrase "..."] [--recovery-key "..."] [--out <dir>]'
    );
    process.exit(1);
  }

  const passphraseIndex = args.indexOf("--passphrase");
  const recoveryKeyIndex = args.indexOf("--recovery-key");
  const outIndex = args.indexOf("--out");
  let passphrase = passphraseIndex !== -1 ? args[passphraseIndex + 1] : null;
  const recoveryKeyBase64 =
    recoveryKeyIndex !== -1 ? args[recoveryKeyIndex + 1] : null;
  const outDir = outIndex !== -1 ? args[outIndex + 1] : null;

  const bundle = JSON.parse(readFileSync(filePath, "utf-8"));
  if (bundle.formatVersion !== 1) {
    console.error(
      `Unsupported saved-deck export format version: ${bundle.formatVersion} (this tool understands version 1)`
    );
    process.exit(1);
  }

  if (passphrase == null && recoveryKeyBase64 == null) {
    passphrase = await promptHidden("Passphrase: ");
  }

  let masterKey;
  try {
    masterKey = await unlockBundleMasterKey(bundle, {
      passphrase,
      recoveryKeyBase64,
    });
  } catch (e) {
    console.error(
      recoveryKeyBase64 != null
        ? "That recovery key doesn't match this file."
        : "That passphrase doesn't match this file."
    );
    process.exit(1);
  }

  const decrypted = await decryptBundle(bundle, masterKey);

  if (outDir != null) {
    mkdirSync(outDir, { recursive: true });
    for (const deck of decrypted) {
      const safeName = (deck.payload.name || deck.key).replace(
        /[^a-zA-Z0-9_-]+/g,
        "_"
      );
      writeFileSync(
        join(outDir, `${safeName}.json`),
        JSON.stringify(deck, null, 2)
      );
    }
    console.error(`Wrote ${decrypted.length} deck(s) to ${outDir}`);
  } else {
    console.log(JSON.stringify(decrypted, null, 2));
  }
}

// Only run as a CLI entrypoint - importing this module (e.g. from this directory's own tests)
// must not trigger stdin prompts or process.exit.
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
