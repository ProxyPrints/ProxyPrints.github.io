/**
 * In-memory-only zero-knowledge crypto session (docs/proposals/proposal-g-user-accounts-saved-decks.md
 * §8's UX section: "unwrapped keys held in memory only - never localStorage, never any
 * persisted store"). A plain React Context, not Redux - `CryptoKey`/raw key-material values
 * aren't serializable, and Redux state is expected to be. Mirrors clientSearchContext.tsx's
 * precedent for holding session-scoped, non-serializable state outside the store.
 *
 * The master key clears itself on every page reload (component remount) automatically, simply
 * by never being persisted anywhere - the explicit `lock()` action just does it sooner.
 */

import React, {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import { SavedDeckKdfIterations } from "@/common/constants";
import {
  base64ToBytes,
  bytesToBase64,
  changePassphrase,
  createCryptoProfile,
  rewrapMasterKeyWithNewRecoveryKey,
  unlockWithPassphrase as unwrapMasterKeyWithPassphrase,
  unlockWithRecoveryKey as unwrapMasterKeyWithRecoveryKey,
  WrappedKey,
} from "@/common/savedDeckCrypto";
import {
  useGetCryptoProfileQuery,
  useGetWhoamiQuery,
  useSaveCryptoProfileMutation,
} from "@/store/api";

export type CryptoSessionStatus =
  | "anonymous" // not signed in - the concept doesn't apply yet
  | "loading" // signed in, crypto profile still being fetched
  | "no-profile" // signed in, no crypto profile exists yet - first-save flow needed
  | "locked" // a crypto profile exists but the master key hasn't been unwrapped this session
  | "unlocked"; // master key is in memory and usable

export interface CryptoSessionContextValue {
  status: CryptoSessionStatus;
  masterKey: CryptoKey | null;
  /** First-save flow. Returns the recovery key (base64) to show the user exactly once. */
  createProfile: (passphrase: string) => Promise<string>;
  /** Normal unlock. Throws on a wrong passphrase. */
  unlockWithPassphrase: (passphrase: string) => Promise<void>;
  /**
   * "Forgot passphrase" flow: unwraps via the recovery key, sets a new passphrase, and
   * reissues a fresh recovery key (the old one is superseded once actually used - see
   * savedDeckCrypto.ts's rewrapMasterKeyWithNewRecoveryKey). Returns the new recovery key
   * (base64) to show the user exactly once. Throws on a wrong recovery key.
   */
  recoverAndSetNewPassphrase: (
    recoveryKeyBase64: string,
    newPassphrase: string
  ) => Promise<string>;
  lock: () => void;
}

const cryptoSessionContext = createContext<
  CryptoSessionContextValue | undefined
>(undefined);

export function useCryptoSession(): CryptoSessionContextValue {
  const context = useContext(cryptoSessionContext);
  if (context == null) {
    throw new Error(
      "Attempted to use cryptoSessionContext outside of CryptoSessionProvider"
    );
  }
  return context;
}

export function CryptoSessionProvider({ children }: PropsWithChildren) {
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const cryptoProfileQuery = useGetCryptoProfileQuery({
    skip: !isAuthenticated,
  });
  const [saveCryptoProfile] = useSaveCryptoProfileMutation();
  const [masterKey, setMasterKey] = useState<CryptoKey | null>(null);

  const status: CryptoSessionStatus = !isAuthenticated
    ? "anonymous"
    : masterKey != null
    ? "unlocked"
    : cryptoProfileQuery.data == null
    ? "loading"
    : cryptoProfileQuery.data.exists
    ? "locked"
    : "no-profile";

  const createProfile = useCallback(
    async (passphrase: string): Promise<string> => {
      const material = await createCryptoProfile(
        passphrase,
        SavedDeckKdfIterations
      );
      await saveCryptoProfile({
        salt: bytesToBase64(material.salt),
        kdfIterations: material.iterations,
        passphraseWrappedMasterKey: bytesToBase64(
          material.passphraseWrapped.wrapped
        ),
        passphraseWrappedMasterKeyNonce: bytesToBase64(
          material.passphraseWrapped.nonce
        ),
        recoveryWrappedMasterKey: bytesToBase64(
          material.recoveryWrapped.wrapped
        ),
        recoveryWrappedMasterKeyNonce: bytesToBase64(
          material.recoveryWrapped.nonce
        ),
      }).unwrap();
      setMasterKey(material.masterKey);
      return bytesToBase64(material.recoveryKeyBytes);
    },
    [saveCryptoProfile]
  );

  const unlockWithPassphrase = useCallback(
    async (passphrase: string): Promise<void> => {
      const profile = cryptoProfileQuery.data;
      if (profile == null || !profile.exists) {
        throw new Error("No crypto profile exists yet.");
      }
      const wrapped: WrappedKey = {
        wrapped: base64ToBytes(profile.passphraseWrappedMasterKey!),
        nonce: base64ToBytes(profile.passphraseWrappedMasterKeyNonce!),
      };
      const key = await unwrapMasterKeyWithPassphrase(
        passphrase,
        base64ToBytes(profile.salt!),
        profile.kdfIterations!,
        wrapped
      );
      setMasterKey(key);
    },
    [cryptoProfileQuery.data]
  );

  const recoverAndSetNewPassphrase = useCallback(
    async (
      recoveryKeyBase64: string,
      newPassphrase: string
    ): Promise<string> => {
      const profile = cryptoProfileQuery.data;
      if (profile == null || !profile.exists) {
        throw new Error("No crypto profile exists yet.");
      }
      const recoveryWrapped: WrappedKey = {
        wrapped: base64ToBytes(profile.recoveryWrappedMasterKey!),
        nonce: base64ToBytes(profile.recoveryWrappedMasterKeyNonce!),
      };
      const recoveredMasterKey = await unwrapMasterKeyWithRecoveryKey(
        base64ToBytes(recoveryKeyBase64),
        recoveryWrapped
      );
      const { salt, passphraseWrapped } = await changePassphrase(
        recoveredMasterKey,
        newPassphrase,
        SavedDeckKdfIterations
      );
      const {
        recoveryKeyBytes: newRecoveryKeyBytes,
        recoveryWrapped: newRecoveryWrapped,
      } = await rewrapMasterKeyWithNewRecoveryKey(recoveredMasterKey);
      await saveCryptoProfile({
        salt: bytesToBase64(salt),
        kdfIterations: SavedDeckKdfIterations,
        passphraseWrappedMasterKey: bytesToBase64(passphraseWrapped.wrapped),
        passphraseWrappedMasterKeyNonce: bytesToBase64(passphraseWrapped.nonce),
        recoveryWrappedMasterKey: bytesToBase64(newRecoveryWrapped.wrapped),
        recoveryWrappedMasterKeyNonce: bytesToBase64(newRecoveryWrapped.nonce),
      }).unwrap();
      setMasterKey(recoveredMasterKey);
      return bytesToBase64(newRecoveryKeyBytes);
    },
    [cryptoProfileQuery.data, saveCryptoProfile]
  );

  const lock = useCallback(() => setMasterKey(null), []);

  const value = useMemo(
    (): CryptoSessionContextValue => ({
      status,
      masterKey,
      createProfile,
      unlockWithPassphrase,
      recoverAndSetNewPassphrase,
      lock,
    }),
    [
      status,
      masterKey,
      createProfile,
      unlockWithPassphrase,
      recoverAndSetNewPassphrase,
      lock,
    ]
  );

  return (
    <cryptoSessionContext.Provider value={value}>
      {children}
    </cryptoSessionContext.Provider>
  );
}
