/**
 * Zero-knowledge saved-deck encryption (docs/proposals/proposal-g-user-accounts-saved-decks.md
 * §8). Every operation here goes through the browser's native WebCrypto (`crypto.subtle`) -
 * no custom crypto primitives are implemented in this file. Nothing here ever transmits a
 * passphrase, a derived key, or an unwrapped master key anywhere - callers are responsible for
 * keeping every `CryptoKey`/raw-bytes return value in memory only (never `localStorage`), per
 * §8's UX section.
 *
 * Key model (see §8's "Key design" and "Recovery key" sections):
 * - The **master key** is a single random AES-256-GCM key, generated once at first save and
 *   never regenerated. Every deck's DEK is wrapped by it; both the passphrase-derived key and
 *   the user's recovery key only ever wrap this one master key, never anything else. A
 *   passphrase change re-wraps just the master key (see `changePassphrase`) - it never touches
 *   any deck's DEK or ciphertext, because the master key itself never changes.
 * - Each deck gets its own random **DEK**, wrapped by the master key, generated once when the
 *   deck is first created.
 */

const PBKDF2_HASH = "SHA-256";
const AES_ALGO = "AES-GCM";
const AES_KEY_LENGTH = 256;
// 96 bits - the size AES-GCM is designed around; using anything else forfeits guarantees the
// spec makes about nonce-misuse resistance.
const GCM_NONCE_LENGTH_BYTES = 12;
const SALT_LENGTH_BYTES = 16;
const RECOVERY_KEY_LENGTH_BYTES = 32; // 256 bits

//# region base64 <-> bytes (the wire format every API field uses)

export function bytesToBase64(bytes: Uint8Array<ArrayBuffer>): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

export function base64ToBytes(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

//# endregion

//# region random generation

export function generateSalt(): Uint8Array<ArrayBuffer> {
  return crypto.getRandomValues(new Uint8Array(SALT_LENGTH_BYTES));
}

function generateNonce(): Uint8Array<ArrayBuffer> {
  return crypto.getRandomValues(new Uint8Array(GCM_NONCE_LENGTH_BYTES));
}

/** A user-held recovery key (§8) - 256 bits of randomness, never derived from anything else. */
export function generateRecoveryKey(): Uint8Array<ArrayBuffer> {
  return crypto.getRandomValues(new Uint8Array(RECOVERY_KEY_LENGTH_BYTES));
}

//# endregion

//# region key derivation, generation, and import

/**
 * PBKDF2-SHA256 over the user's passphrase, producing an AES-GCM key used ONLY to wrap/unwrap
 * the master key - never to encrypt deck content directly (see this module's header).
 */
async function derivePassphraseKey(
  passphrase: string,
  salt: Uint8Array<ArrayBuffer>,
  iterations: number
): Promise<CryptoKey> {
  const baseKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: PBKDF2_HASH },
    baseKey,
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    false,
    ["wrapKey", "unwrapKey"]
  );
}

/**
 * The recovery key IS the key material (no KDF involved) - it's already 256 bits of true
 * randomness, not a user-remembered secret that needs stretching.
 */
async function importRecoveryKey(
  recoveryKeyBytes: Uint8Array<ArrayBuffer>
): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", recoveryKeyBytes, AES_ALGO, false, [
    "wrapKey",
    "unwrapKey",
  ]);
}

/** The master key (see this module's header) - extractable, since it must be wrappable by two
 * different keys (passphrase-derived, recovery). */
async function generateMasterKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    true,
    ["wrapKey", "unwrapKey"]
  );
}

/** A fresh per-deck DEK - one per deck, generated when that deck is first created. */
async function generateDEK(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    true,
    ["encrypt", "decrypt"]
  );
}

//# endregion

//# region key wrapping (master key <-> passphrase/recovery keys, DEK <-> master key)

export interface WrappedKey {
  wrapped: Uint8Array<ArrayBuffer>;
  nonce: Uint8Array<ArrayBuffer>;
}

/** Encrypts (wraps) `keyToWrap`'s raw key material under `wrappingKey`, with a fresh random
 * nonce every time this is called - never reuse a nonce across two different wrap operations. */
async function wrapKey(
  keyToWrap: CryptoKey,
  wrappingKey: CryptoKey
): Promise<WrappedKey> {
  const nonce = generateNonce();
  const wrapped = await crypto.subtle.wrapKey("raw", keyToWrap, wrappingKey, {
    name: AES_ALGO,
    iv: nonce,
  });
  return { wrapped: new Uint8Array(wrapped), nonce };
}

/**
 * Reverses wrapKey. Throws (AES-GCM authentication failure) if `wrappingKey` is wrong, or if
 * any byte of `wrapped`/`nonce` was tampered with - never silently returns garbage key material.
 */
async function unwrapKey(
  wrapped: Uint8Array<ArrayBuffer>,
  nonce: Uint8Array<ArrayBuffer>,
  wrappingKey: CryptoKey,
  unwrappedKeyUsages: ReadonlyArray<KeyUsage>
): Promise<CryptoKey> {
  return crypto.subtle.unwrapKey(
    "raw",
    wrapped,
    wrappingKey,
    { name: AES_ALGO, iv: nonce },
    { name: AES_ALGO, length: AES_KEY_LENGTH },
    true,
    unwrappedKeyUsages as KeyUsage[]
  );
}

//# endregion

//# region deck payload encryption

export interface EncryptedPayload {
  ciphertext: Uint8Array<ArrayBuffer>;
  nonce: Uint8Array<ArrayBuffer>;
}

/**
 * Encrypts a deck's full plaintext (the whole saved-deck JSON envelope, including its title -
 * see §8's "the entire deck payload, including the title") under its own DEK, with a fresh
 * random nonce every call.
 */
export async function encryptDeckPayload(
  plaintext: string,
  dek: CryptoKey
): Promise<EncryptedPayload> {
  const nonce = generateNonce();
  const ciphertext = await crypto.subtle.encrypt(
    { name: AES_ALGO, iv: nonce },
    dek,
    new TextEncoder().encode(plaintext)
  );
  return { ciphertext: new Uint8Array(ciphertext), nonce };
}

/**
 * Reverses encryptDeckPayload. Throws (AES-GCM authentication failure) on a wrong DEK or any
 * tampered byte in ciphertext/nonce - never returns silently-corrupted plaintext.
 */
export async function decryptDeckPayload(
  ciphertext: Uint8Array<ArrayBuffer>,
  nonce: Uint8Array<ArrayBuffer>,
  dek: CryptoKey
): Promise<string> {
  const plaintext = await crypto.subtle.decrypt(
    { name: AES_ALGO, iv: nonce },
    dek,
    ciphertext
  );
  return new TextDecoder().decode(plaintext);
}

//# endregion

//# region high-level orchestration - what PR4b's UI actually calls

export interface NewCryptoProfileMaterial {
  masterKey: CryptoKey;
  /** Show this to the user exactly once (download/print/copy) - it is never re-derivable or
   * re-showable once this function returns, and this module never stores it anywhere. */
  recoveryKeyBytes: Uint8Array<ArrayBuffer>;
  salt: Uint8Array<ArrayBuffer>;
  iterations: number;
  passphraseWrapped: WrappedKey;
  recoveryWrapped: WrappedKey;
}

/**
 * The first-save flow (§8): generates a master key and a random recovery key, then wraps the
 * master key under both the passphrase-derived key and the recovery key.
 */
export async function createCryptoProfile(
  passphrase: string,
  iterations: number
): Promise<NewCryptoProfileMaterial> {
  const salt = generateSalt();
  const recoveryKeyBytes = generateRecoveryKey();
  const [passphraseKey, recoveryKey] = await Promise.all([
    derivePassphraseKey(passphrase, salt, iterations),
    importRecoveryKey(recoveryKeyBytes),
  ]);
  const masterKey = await generateMasterKey();
  const [passphraseWrapped, recoveryWrapped] = await Promise.all([
    wrapKey(masterKey, passphraseKey),
    wrapKey(masterKey, recoveryKey),
  ]);
  return {
    masterKey,
    recoveryKeyBytes,
    salt,
    iterations,
    passphraseWrapped,
    recoveryWrapped,
  };
}

/** The normal unlock path: unwraps the master key using the user's passphrase. Throws on a
 * wrong passphrase (AES-GCM authentication failure inside unwrapKey). */
export async function unlockWithPassphrase(
  passphrase: string,
  salt: Uint8Array<ArrayBuffer>,
  iterations: number,
  passphraseWrapped: WrappedKey
): Promise<CryptoKey> {
  const passphraseKey = await derivePassphraseKey(passphrase, salt, iterations);
  return unwrapKey(
    passphraseWrapped.wrapped,
    passphraseWrapped.nonce,
    passphraseKey,
    ["wrapKey", "unwrapKey"]
  );
}

/** The "forgot passphrase" path: unwraps the master key using the user's recovery key. */
export async function unlockWithRecoveryKey(
  recoveryKeyBytes: Uint8Array<ArrayBuffer>,
  recoveryWrapped: WrappedKey
): Promise<CryptoKey> {
  const recoveryKey = await importRecoveryKey(recoveryKeyBytes);
  return unwrapKey(
    recoveryWrapped.wrapped,
    recoveryWrapped.nonce,
    recoveryKey,
    ["wrapKey", "unwrapKey"]
  );
}

/**
 * Re-wraps the SAME master key under a newly-derived passphrase key (a fresh salt too, so the
 * new passphrase gets its own derivation). The recovery-wrapped slot is untouched - it still
 * wraps the same master key - and no deck's DEK or ciphertext needs to change either, since
 * DEKs are wrapped by the master key, which never changes across a passphrase change.
 */
export async function changePassphrase(
  masterKey: CryptoKey,
  newPassphrase: string,
  iterations: number
): Promise<{ salt: Uint8Array<ArrayBuffer>; passphraseWrapped: WrappedKey }> {
  const salt = generateSalt();
  const passphraseKey = await derivePassphraseKey(
    newPassphrase,
    salt,
    iterations
  );
  const passphraseWrapped = await wrapKey(masterKey, passphraseKey);
  return { salt, passphraseWrapped };
}

/** Generates a fresh DEK for a brand-new deck, wrapped by the (already-unlocked) master key. */
export async function createDeckKey(
  masterKey: CryptoKey
): Promise<{ dek: CryptoKey; wrappedDek: WrappedKey }> {
  const dek = await generateDEK();
  const wrappedDek = await wrapKey(dek, masterKey);
  return { dek, wrappedDek };
}

/** Unwraps an existing deck's DEK using the (already-unlocked) master key. */
export async function unlockDeckKey(
  wrappedDek: WrappedKey,
  masterKey: CryptoKey
): Promise<CryptoKey> {
  return unwrapKey(wrappedDek.wrapped, wrappedDek.nonce, masterKey, [
    "encrypt",
    "decrypt",
  ]);
}

//# endregion
