/**
 * Tests for per-deck share links ("PR-5, post-v1: per-deck share links" -
 * docs/proposals/proposal-g-user-accounts-saved-decks.md). These are the four scenarios the
 * spec names explicitly as "written now as the spec's requirement for PR-5, to implement when
 * that PR is built" - pure crypto-module tests, no network involved (the backend's own
 * ownership/expiry/404 behaviour is covered separately in
 * MPCAutofill/cardpicker/tests/test_saved_deck_share_views.py). See
 * cardpicker.models.SavedDeckShare's docstring and deckShare.ts's header for the frozen-snapshot
 * deviation this exercises in the "rotation" test below.
 */

import {
  createCryptoProfile,
  createDeckKey,
  decryptDeckPayload,
  encryptDeckPayload,
} from "@/common/savedDeckCrypto";
import {
  decryptSharedDeck,
  prepareDeckShare,
} from "@/features/savedDecks/deckShare";

const TEST_ITERATIONS = 100;

describe("share round-trip", () => {
  test("create a share, then fetch-and-decrypt via shareId + fragment key decrypts correctly", async () => {
    const profile = await createCryptoProfile(
      "owner passphrase",
      TEST_ITERATIONS
    );
    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const plaintext = JSON.stringify({
      version: 1,
      name: "My Deck",
      members: [],
      cardback: null,
      manualOverrides: {},
      finishSettings: {},
    });
    const { ciphertext, nonce } = await encryptDeckPayload(plaintext, dek);

    // owner-side: create the share (this is exactly what ShareDeckModal does before POSTing)
    const prepared = await prepareDeckShare(wrappedDek, profile.masterKey);

    // recipient-side: everything it has is what the server would actually return from
    // 2/getSharedDeck/ (a frozen ciphertext copy + this share's own wrapped DEK), plus the
    // shareKey fragment from the URL - nothing else
    const decrypted = await decryptSharedDeck(
      {
        ciphertext: Buffer.from(ciphertext).toString("base64"),
        ciphertextNonce: Buffer.from(nonce).toString("base64"),
        wrappedDek: prepared.wrappedDek,
        wrappedDekNonce: prepared.wrappedDekNonce,
        createdAt: "1st January, 2026",
      },
      prepared.shareKeyFragment
    );

    expect(decrypted.name).toEqual("My Deck");
    expect(decrypted.payload.members).toEqual([]);
  });
});

describe("rotation-on-revoke", () => {
  test("a previously-captured shareKey cannot decrypt the deck's rotated ciphertext, but still decrypts its own frozen share snapshot", async () => {
    const profile = await createCryptoProfile(
      "owner passphrase",
      TEST_ITERATIONS
    );
    const { dek: originalDek, wrappedDek: originalWrappedDek } =
      await createDeckKey(profile.masterKey);
    const { ciphertext: originalCiphertext, nonce: originalNonce } =
      await encryptDeckPayload(
        JSON.stringify({
          version: 1,
          name: "Shared Deck",
          members: [],
          cardback: null,
          manualOverrides: {},
          finishSettings: {},
        }),
        originalDek
      );

    // share creation captures the DEK as it stood at this moment
    const prepared = await prepareDeckShare(
      originalWrappedDek,
      profile.masterKey
    );
    const frozenShareResponse = {
      ciphertext: Buffer.from(originalCiphertext).toString("base64"),
      ciphertextNonce: Buffer.from(originalNonce).toString("base64"),
      wrappedDek: prepared.wrappedDek,
      wrappedDekNonce: prepared.wrappedDekNonce,
      createdAt: "1st January, 2026",
    };

    // owner later rotates the LIVE deck's DEK (an ordinary saveDeck-shaped re-encrypt, or the
    // explicit "paranoid" rotate-on-revoke action) - a brand new DEK, brand new ciphertext
    const { dek: rotatedDek } = await createDeckKey(profile.masterKey);
    const { ciphertext: rotatedCiphertext, nonce: rotatedNonce } =
      await encryptDeckPayload(
        JSON.stringify({
          version: 1,
          name: "Shared Deck (rotated)",
          members: [],
          cardback: null,
          manualOverrides: {},
          finishSettings: {},
        }),
        rotatedDek
      );

    // the previously-captured share material must NOT decrypt the rotated live content
    await expect(
      decryptDeckPayload(rotatedCiphertext, rotatedNonce, originalDek)
    ).rejects.toThrow();

    // DELIBERATE, DOCUMENTED DEVIATION (see SavedDeckShare's docstring): because this share is
    // a frozen, self-contained snapshot rather than a live reference, rotating the live deck
    // does NOT invalidate this (still-outstanding, not-yet-revoked) share's own frozen content -
    // it keeps decrypting exactly what it always did.
    const stillDecryptsItsOwnSnapshot = await decryptSharedDeck(
      frozenShareResponse,
      prepared.shareKeyFragment
    );
    expect(stillDecryptsItsOwnSnapshot.name).toEqual("Shared Deck");
  });
});

describe("cross-deck isolation", () => {
  test("a leaked shareKey for deck A cannot unwrap or decrypt anything belonging to deck B", async () => {
    const profile = await createCryptoProfile(
      "owner passphrase",
      TEST_ITERATIONS
    );

    const { wrappedDek: wrappedDekA } = await createDeckKey(profile.masterKey);
    const { dek: dekB, wrappedDek: wrappedDekB } = await createDeckKey(
      profile.masterKey
    );
    const { ciphertext: ciphertextB, nonce: nonceB } = await encryptDeckPayload(
      JSON.stringify({
        version: 1,
        name: "Deck B",
        members: [],
        cardback: null,
        manualOverrides: {},
        finishSettings: {},
      }),
      dekB
    );

    // share ONLY deck A
    const sharedA = await prepareDeckShare(wrappedDekA, profile.masterKey);

    // deck A's leaked shareKey must not unwrap deck B's wrapped DEK...
    await expect(
      decryptSharedDeck(
        {
          ciphertext: Buffer.from(ciphertextB).toString("base64"),
          ciphertextNonce: Buffer.from(nonceB).toString("base64"),
          wrappedDek: Buffer.from(wrappedDekB.wrapped).toString("base64"),
          wrappedDekNonce: Buffer.from(wrappedDekB.nonce).toString("base64"),
          createdAt: "1st January, 2026",
        },
        sharedA.shareKeyFragment
      )
    ).rejects.toThrow();

    // ...nor decrypt deck B's ciphertext even paired with deck A's own (correctly-unwrapped-by-
    // its-own-shareKey) wrapped DEK material
    await expect(
      decryptSharedDeck(
        {
          ciphertext: Buffer.from(ciphertextB).toString("base64"),
          ciphertextNonce: Buffer.from(nonceB).toString("base64"),
          wrappedDek: sharedA.wrappedDek,
          wrappedDekNonce: sharedA.wrappedDekNonce,
          createdAt: "1st January, 2026",
        },
        sharedA.shareKeyFragment
      )
    ).rejects.toThrow();
  });
});
