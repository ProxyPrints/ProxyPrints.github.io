/**
 * Per-deck share links (docs/proposals/proposal-g-user-accounts-saved-decks.md's "PR-5,
 * post-v1: per-deck share links"). Composes savedDeckCrypto.ts's share-key primitives with
 * deckPayload.ts's already-existing plaintext shape/parser - this file does not modify, and
 * does not need to modify, either of those.
 *
 * URL shape deviation from the spec's literal `/shared/<shareId>#<shareKey-base64url>` (a path
 * segment for shareId): this app is a Next.js static export served from GitHub Pages, which has
 * no server-side wildcard route fallback - a `[shareId]` dynamic path would need every possible
 * shareId enumerated at build time (`getStaticPaths`), which is impossible for ids created at
 * runtime. `shareId` therefore travels as a query param instead (`/shared?shareId=<uuid>`,
 * resolved client-side, exactly like any other static host would need). This changes nothing
 * about the property that's actually security-load-bearing: the `shareKey` itself still travels
 * ONLY in the URL fragment (`#...`), which no host - static or otherwise - ever receives.
 */

import {
  base64ToBytes,
  base64UrlToBytes,
  bytesToBase64,
  bytesToBase64Url,
  decryptDeckPayload,
  generateShareKey,
  unlockDeckKey,
  unwrapDeckKeyFromShare,
  wrapDeckKeyForShare,
  WrappedKey,
} from "@/common/savedDeckCrypto";
import { GetSharedDeckResponse } from "@/common/schema_types";
import {
  DeckPayloadV2,
  parseDeckPayload,
} from "@/features/savedDecks/deckPayload";

export interface PreparedDeckShare {
  wrappedDek: string;
  wrappedDekNonce: string;
  /** base64url - goes ONLY in the share URL's fragment, never in a request body. */
  shareKeyFragment: string;
}

/**
 * Owner-side share creation. `currentWrappedDek` is the deck's CURRENT wrapped-DEK fields
 * straight off its SavedDeckSummary/LoadDeckResponse (i.e. exactly what's already on the wire
 * for ordinary loads) - unwrapped here via the owner's already-unlocked master key, then
 * re-wrapped under a fresh, independent shareKey. Returns the fields to POST to
 * 2/createDeckShare/ plus the fragment to append to the share URL - callers must not persist
 * `shareKeyFragment` anywhere (not even in Redux/localStorage): once the modal that shows it
 * closes, it's gone for good, same as this deck's ordinary recovery key.
 */
export async function prepareDeckShare(
  currentWrappedDek: WrappedKey,
  masterKey: CryptoKey
): Promise<PreparedDeckShare> {
  const dek = await unlockDeckKey(currentWrappedDek, masterKey);
  const shareKeyBytes = generateShareKey();
  const wrapped = await wrapDeckKeyForShare(dek, shareKeyBytes);
  return {
    wrappedDek: bytesToBase64(wrapped.wrapped),
    wrappedDekNonce: bytesToBase64(wrapped.nonce),
    shareKeyFragment: bytesToBase64Url(shareKeyBytes),
  };
}

export function buildShareUrl(
  origin: string,
  shareId: string,
  shareKeyFragment: string
): string {
  return `${origin}/shared?shareId=${encodeURIComponent(
    shareId
  )}#${shareKeyFragment}`;
}

export interface DecryptedSharedDeck {
  name: string;
  // parseDeckPayload always upgrades to the latest shape (currently v2) - a recipient never
  // sees a raw, un-upgraded v1 payload.
  payload: DeckPayloadV2;
  sharedAt: string;
}

/**
 * Recipient-side decrypt - no account, master key, or passphrase involved. `shareKeyFragment`
 * comes straight from the share URL's fragment (`window.location.hash`, with the leading `#`
 * already stripped by the caller).
 */
export async function decryptSharedDeck(
  response: GetSharedDeckResponse,
  shareKeyFragment: string
): Promise<DecryptedSharedDeck> {
  const shareKeyBytes = base64UrlToBytes(shareKeyFragment);
  const wrappedDek: WrappedKey = {
    wrapped: base64ToBytes(response.wrappedDek),
    nonce: base64ToBytes(response.wrappedDekNonce),
  };
  const dek = await unwrapDeckKeyFromShare(wrappedDek, shareKeyBytes);
  const plaintext = await decryptDeckPayload(
    base64ToBytes(response.ciphertext),
    base64ToBytes(response.ciphertextNonce),
    dek
  );
  const payload = parseDeckPayload(plaintext);
  return { name: payload.name, payload, sharedAt: response.createdAt };
}
