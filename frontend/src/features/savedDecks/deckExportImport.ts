/**
 * Deck portability (docs/proposals/proposal-g-user-accounts-saved-decks.md, "PR-6, post-v1:
 * deck portability"): export/import of the complete encrypted bundle a saved-decks account
 * holds. Every field in the bundle is exactly the same opaque, already-encrypted bytes the
 * server itself stores - `buildExportBundle` never sees deck contents in plaintext, and export
 * requires no unlock (see MyDecksPage's "Export my decks" wiring). Import DOES need a
 * passphrase or recovery key, but it's the BUNDLE's own (via `unlockBundleMasterKeyWith*`
 * below) - not necessarily the live session's - since a bundle may be re-imported on a
 * different account or a different (compatible) instance entirely.
 *
 * `EXPORT_FORMAT_VERSION` is this bundle's own PUBLIC wire-format version (starts at 1) -
 * distinct from deckPayload.ts's PRIVATE, per-deck `version` field, which lives inside each
 * deck's encrypted ciphertext and is never visible here. This format is documented publicly
 * (this file, plus docs/features/saved-decks.md) specifically so a fork, or a completely
 * independent reimplementation, could read an exported bundle without this codebase at all -
 * see the standalone decrypt tool at `tools/decrypt-saved-deck-export/`, the trust anchor for
 * that claim.
 */

import {
  base64ToBytes,
  unlockWithPassphrase,
  unlockWithRecoveryKey,
  WrappedKey,
} from "@/common/savedDeckCrypto";
import { CryptoProfileResponse, SavedDeckSummary } from "@/common/schema_types";
import {
  DecryptedSavedDeck,
  decryptSavedDeckSummary,
} from "@/features/savedDecks/deckPayload";

export const EXPORT_FORMAT_VERSION = 1;

export interface ExportBundleCryptoProfile {
  salt: string;
  kdfIterations: number;
  passphraseWrappedMasterKey: string;
  passphraseWrappedMasterKeyNonce: string;
  recoveryWrappedMasterKey: string;
  recoveryWrappedMasterKeyNonce: string;
}

/** Identical wire shape to `SavedDeckSummary` - literally the same opaque bytes the server
 * already holds for this row, just also written into the exported file. */
export type ExportBundleDeck = SavedDeckSummary;

export interface ExportBundleV1 {
  formatVersion: 1;
  exportedAt: string;
  cryptoProfile: ExportBundleCryptoProfile;
  decks: Array<ExportBundleDeck>;
}

/**
 * Builds the export bundle. Requires NO unlock (docs/proposals/.../PR-6's own explicit
 * requirement) - a user who's forgotten their passphrase can still export, since this is just
 * the same opaque bytes the server already stores, reshaped into one file.
 */
export function buildExportBundle(
  cryptoProfile: CryptoProfileResponse,
  decks: Array<SavedDeckSummary>
): ExportBundleV1 {
  if (
    !cryptoProfile.exists ||
    cryptoProfile.salt == null ||
    cryptoProfile.kdfIterations == null ||
    cryptoProfile.passphraseWrappedMasterKey == null ||
    cryptoProfile.passphraseWrappedMasterKeyNonce == null ||
    cryptoProfile.recoveryWrappedMasterKey == null ||
    cryptoProfile.recoveryWrappedMasterKeyNonce == null
  ) {
    throw new Error(
      "No saved-deck crypto profile to export yet - save a deck first."
    );
  }
  return {
    formatVersion: EXPORT_FORMAT_VERSION,
    exportedAt: new Date().toISOString(),
    cryptoProfile: {
      salt: cryptoProfile.salt,
      kdfIterations: cryptoProfile.kdfIterations,
      passphraseWrappedMasterKey: cryptoProfile.passphraseWrappedMasterKey,
      passphraseWrappedMasterKeyNonce:
        cryptoProfile.passphraseWrappedMasterKeyNonce,
      recoveryWrappedMasterKey: cryptoProfile.recoveryWrappedMasterKey,
      recoveryWrappedMasterKeyNonce:
        cryptoProfile.recoveryWrappedMasterKeyNonce,
    },
    decks: decks.map((deck) => ({
      key: deck.key,
      kind: deck.kind,
      ciphertext: deck.ciphertext,
      ciphertextNonce: deck.ciphertextNonce,
      wrappedDek: deck.wrappedDek,
      wrappedDekNonce: deck.wrappedDekNonce,
      createdAt: deck.createdAt,
      updatedAt: deck.updatedAt,
    })),
  };
}

export function serializeExportBundle(bundle: ExportBundleV1): string {
  return JSON.stringify(bundle, null, 2);
}

export function parseExportBundle(serialized: string): ExportBundleV1 {
  const parsed = JSON.parse(serialized);
  if (parsed?.formatVersion !== EXPORT_FORMAT_VERSION) {
    throw new Error(
      `Unsupported saved-deck export format version: ${parsed?.formatVersion}`
    );
  }
  if (!Array.isArray(parsed.decks) || parsed.cryptoProfile == null) {
    throw new Error("Malformed saved-deck export file.");
  }
  return parsed as ExportBundleV1;
}

/** Browser-only: triggers a download of the bundle as a timestamped `.json` file. */
export function downloadExportBundle(bundle: ExportBundleV1): void {
  const blob = new Blob([serializeExportBundle(bundle)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `proxyprints-saved-decks-${bundle.exportedAt.slice(
      0,
      10
    )}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Unwraps the BUNDLE's own master key using its own passphrase - deliberately independent of
 * whatever crypto profile the live session (if any) already has, since a bundle can be
 * re-imported on a different account or instance entirely. Throws on a wrong passphrase (AES-GCM
 * authentication failure), same as the live unlock path. */
export async function unlockBundleMasterKeyWithPassphrase(
  bundle: ExportBundleV1,
  passphrase: string
): Promise<CryptoKey> {
  const wrapped: WrappedKey = {
    wrapped: base64ToBytes(bundle.cryptoProfile.passphraseWrappedMasterKey),
    nonce: base64ToBytes(bundle.cryptoProfile.passphraseWrappedMasterKeyNonce),
  };
  return unlockWithPassphrase(
    passphrase,
    base64ToBytes(bundle.cryptoProfile.salt),
    bundle.cryptoProfile.kdfIterations,
    wrapped
  );
}

/** As above, via the bundle's own recovery key instead of its passphrase. */
export async function unlockBundleMasterKeyWithRecoveryKey(
  bundle: ExportBundleV1,
  recoveryKeyBase64: string
): Promise<CryptoKey> {
  const wrapped: WrappedKey = {
    wrapped: base64ToBytes(bundle.cryptoProfile.recoveryWrappedMasterKey),
    nonce: base64ToBytes(bundle.cryptoProfile.recoveryWrappedMasterKeyNonce),
  };
  return unlockWithRecoveryKey(base64ToBytes(recoveryKeyBase64), wrapped);
}

/** Decrypts every deck in a bundle using the bundle's own (already-unwrapped) master key. A
 * failure on any single entry aborts the whole import rather than silently skipping a row -
 * partial imports would be a confusing, hard-to-notice way to lose data. */
export async function decryptBundleDecks(
  bundle: ExportBundleV1,
  bundleMasterKey: CryptoKey
): Promise<Array<DecryptedSavedDeck>> {
  return Promise.all(
    bundle.decks.map((deck) => decryptSavedDeckSummary(deck, bundleMasterKey))
  );
}
