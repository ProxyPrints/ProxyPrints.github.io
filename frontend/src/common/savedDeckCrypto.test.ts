import {
  base64ToBytes,
  bytesToBase64,
  changePassphrase,
  createCryptoProfile,
  createDeckKey,
  decryptDeckPayload,
  encryptDeckPayload,
  generateRecoveryKey,
  rewrapMasterKeyWithNewRecoveryKey,
  unlockDeckKey,
  unlockWithPassphrase,
  unlockWithRecoveryKey,
} from "@/common/savedDeckCrypto";

// low iteration count for test speed - the real floor (600,000+) is enforced server-side
// (SAVED_DECK_MIN_KDF_ITERATIONS) and doesn't need to be exercised here to prove correctness
const TEST_ITERATIONS = 100;

describe("base64 round-trip", () => {
  test("arbitrary bytes survive a base64 round-trip", () => {
    const original = crypto.getRandomValues(new Uint8Array(64));
    const roundTripped = base64ToBytes(bytesToBase64(original));
    expect(roundTripped).toEqual(original);
  });
});

describe("deck payload encrypt/decrypt", () => {
  test("round-trip returns the original plaintext", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const { dek } = await createDeckKey(profile.masterKey);
    const plaintext = JSON.stringify({ name: "My Deck", members: [] });

    const { ciphertext, nonce } = await encryptDeckPayload(plaintext, dek);
    const decrypted = await decryptDeckPayload(ciphertext, nonce, dek);

    expect(decrypted).toEqual(plaintext);
  });

  test("ciphertext tamper causes an AES-GCM authentication failure, not a silent garbage decrypt", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const { dek } = await createDeckKey(profile.masterKey);
    const { ciphertext, nonce } = await encryptDeckPayload(
      JSON.stringify({ name: "My Deck" }),
      dek
    );

    const tampered = new Uint8Array(ciphertext);
    tampered[0] ^= 0xff; // flip a bit

    await expect(decryptDeckPayload(tampered, nonce, dek)).rejects.toThrow();
  });

  test("decrypting with the wrong DEK fails", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const { dek: dek1 } = await createDeckKey(profile.masterKey);
    const { dek: dek2 } = await createDeckKey(profile.masterKey);
    const { ciphertext, nonce } = await encryptDeckPayload(
      JSON.stringify({ name: "Deck 1" }),
      dek1
    );

    await expect(decryptDeckPayload(ciphertext, nonce, dek2)).rejects.toThrow();
  });
});

describe("passphrase unlock", () => {
  test("the correct passphrase unwraps the master key", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const unlockedMasterKey = await unlockWithPassphrase(
      "correct horse battery staple",
      profile.salt,
      profile.iterations,
      profile.passphraseWrapped
    );

    // prove it's really the same master key: wrap/unwrap a DEK with each and confirm they agree
    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const unwrappedWithUnlockedKey = await unlockDeckKey(
      wrappedDek,
      unlockedMasterKey
    );
    const { ciphertext, nonce } = await encryptDeckPayload("hello", dek);
    const decrypted = await decryptDeckPayload(
      ciphertext,
      nonce,
      unwrappedWithUnlockedKey
    );
    expect(decrypted).toEqual("hello");
  });

  test("the wrong passphrase fails to unwrap", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    await expect(
      unlockWithPassphrase(
        "wrong passphrase entirely",
        profile.salt,
        profile.iterations,
        profile.passphraseWrapped
      )
    ).rejects.toThrow();
  });
});

describe("recovery key", () => {
  test("the correct recovery key unwraps the master key", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const unlockedMasterKey = await unlockWithRecoveryKey(
      profile.recoveryKeyBytes,
      profile.recoveryWrapped
    );

    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const unwrappedWithUnlockedKey = await unlockDeckKey(
      wrappedDek,
      unlockedMasterKey
    );
    const { ciphertext, nonce } = await encryptDeckPayload("hello", dek);
    const decrypted = await decryptDeckPayload(
      ciphertext,
      nonce,
      unwrappedWithUnlockedKey
    );
    expect(decrypted).toEqual("hello");
  });

  test("the wrong recovery key fails to unwrap", async () => {
    const profile = await createCryptoProfile(
      "correct horse battery staple",
      TEST_ITERATIONS
    );
    const wrongRecoveryKey = generateRecoveryKey();
    await expect(
      unlockWithRecoveryKey(wrongRecoveryKey, profile.recoveryWrapped)
    ).rejects.toThrow();
  });

  test("recovery flow: forget the passphrase, recover via the recovery key, set a new passphrase and a fresh recovery key", async () => {
    const profile = await createCryptoProfile(
      "original passphrase",
      TEST_ITERATIONS
    );

    // "forgot passphrase" - recover using the recovery key instead
    const recoveredMasterKey = await unlockWithRecoveryKey(
      profile.recoveryKeyBytes,
      profile.recoveryWrapped
    );

    // set a brand new passphrase AND reissue a fresh recovery key - the addendum's recovery
    // flow re-wraps BOTH slots, since the old recovery key has now actually been exercised
    // (unlike an ordinary passphrase change, which leaves the recovery slot untouched - see
    // the next describe block)
    const { salt: newSalt, passphraseWrapped: newPassphraseWrapped } =
      await changePassphrase(
        recoveredMasterKey,
        "brand new passphrase",
        TEST_ITERATIONS
      );
    const {
      recoveryKeyBytes: newRecoveryKeyBytes,
      recoveryWrapped: newRecoveryWrapped,
    } = await rewrapMasterKeyWithNewRecoveryKey(recoveredMasterKey);

    // the new passphrase now unlocks the SAME master key
    const unlockedAgain = await unlockWithPassphrase(
      "brand new passphrase",
      newSalt,
      TEST_ITERATIONS,
      newPassphraseWrapped
    );

    // prove it's the same master key by round-tripping a deck through it
    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const unwrapped = await unlockDeckKey(wrappedDek, unlockedAgain);
    const { ciphertext, nonce } = await encryptDeckPayload(
      "still readable",
      dek
    );
    expect(await decryptDeckPayload(ciphertext, nonce, unwrapped)).toEqual(
      "still readable"
    );

    // the OLD passphrase must no longer work
    await expect(
      unlockWithPassphrase(
        "original passphrase",
        newSalt,
        TEST_ITERATIONS,
        newPassphraseWrapped
      )
    ).rejects.toThrow();

    // the NEW recovery key unwraps the same master key too
    const unlockedViaNewRecoveryKey = await unlockWithRecoveryKey(
      newRecoveryKeyBytes,
      newRecoveryWrapped
    );
    const { ciphertext: c2, nonce: n2 } = await encryptDeckPayload(
      "readable via the new recovery key too",
      dek
    );
    expect(
      await decryptDeckPayload(
        c2,
        n2,
        await unlockDeckKey(wrappedDek, unlockedViaNewRecoveryKey)
      )
    ).toEqual("readable via the new recovery key too");

    // the OLD recovery key must no longer unwrap the new recovery slot
    await expect(
      unlockWithRecoveryKey(profile.recoveryKeyBytes, newRecoveryWrapped)
    ).rejects.toThrow();
  });

  test("a recovery key generated before a later passphrase change still unwraps the master key", async () => {
    const profile = await createCryptoProfile(
      "original passphrase",
      TEST_ITERATIONS
    );

    // change the passphrase (does not touch the recovery-wrapped slot)
    await changePassphrase(
      profile.masterKey,
      "changed passphrase",
      TEST_ITERATIONS
    );

    // the ORIGINAL recovery key, from before the passphrase change, must still work - it wraps
    // the master key directly, which never changed
    const stillWorks = await unlockWithRecoveryKey(
      profile.recoveryKeyBytes,
      profile.recoveryWrapped
    );
    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const unwrapped = await unlockDeckKey(wrappedDek, stillWorks);
    const { ciphertext, nonce } = await encryptDeckPayload(
      "unaffected by passphrase change",
      dek
    );
    expect(await decryptDeckPayload(ciphertext, nonce, unwrapped)).toEqual(
      "unaffected by passphrase change"
    );
  });
});

describe("passphrase change never touches deck DEKs or ciphertext", () => {
  test("a deck encrypted before a passphrase change is still readable after, via the master key alone", async () => {
    const profile = await createCryptoProfile(
      "original passphrase",
      TEST_ITERATIONS
    );
    const { dek, wrappedDek } = await createDeckKey(profile.masterKey);
    const { ciphertext, nonce } = await encryptDeckPayload(
      JSON.stringify({ name: "Pre-existing deck" }),
      dek
    );

    // change the passphrase - per §8, this only re-wraps the master key, nothing deck-related
    const { salt: newSalt, passphraseWrapped: newPassphraseWrapped } =
      await changePassphrase(
        profile.masterKey,
        "new passphrase",
        TEST_ITERATIONS
      );

    // unlock with the NEW passphrase, then the pre-existing deck's wrappedDek/ciphertext -
    // untouched by the change - must still decrypt correctly
    const unlockedMasterKey = await unlockWithPassphrase(
      "new passphrase",
      newSalt,
      TEST_ITERATIONS,
      newPassphraseWrapped
    );
    const unwrappedDek = await unlockDeckKey(wrappedDek, unlockedMasterKey);
    const decrypted = await decryptDeckPayload(ciphertext, nonce, unwrappedDek);

    expect(JSON.parse(decrypted)).toEqual({ name: "Pre-existing deck" });
  });
});
