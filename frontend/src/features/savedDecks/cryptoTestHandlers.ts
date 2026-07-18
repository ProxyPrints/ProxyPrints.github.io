/**
 * Shared MSW handler builders for tests exercising CryptoSessionProvider (directly, or via a
 * modal/page that consumes it) - kept in one place since cryptoSession.test.tsx,
 * PassphraseSetupModal.test.tsx, and UnlockModal.test.tsx all need the same three shapes.
 */

import { http, HttpResponse } from "msw";

import { bytesToBase64 } from "@/common/savedDeckCrypto";
import { localBackendURL } from "@/common/test-constants";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

export function noProfileHandler() {
  return http.get(buildRoute("2/cryptoProfile/"), () =>
    HttpResponse.json(
      {
        exists: false,
        salt: null,
        kdfIterations: null,
        passphraseWrappedMasterKey: null,
        passphraseWrappedMasterKeyNonce: null,
        recoveryWrappedMasterKey: null,
        recoveryWrappedMasterKeyNonce: null,
      },
      { status: 200 }
    )
  );
}

export interface MockCryptoProfileMaterial {
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
}

export function existingProfileHandler(profile: MockCryptoProfileMaterial) {
  return http.get(buildRoute("2/cryptoProfile/"), () =>
    HttpResponse.json(
      {
        exists: true,
        salt: bytesToBase64(profile.salt),
        kdfIterations: profile.iterations,
        passphraseWrappedMasterKey: bytesToBase64(
          profile.passphraseWrapped.wrapped
        ),
        passphraseWrappedMasterKeyNonce: bytesToBase64(
          profile.passphraseWrapped.nonce
        ),
        recoveryWrappedMasterKey: bytesToBase64(
          profile.recoveryWrapped.wrapped
        ),
        recoveryWrappedMasterKeyNonce: bytesToBase64(
          profile.recoveryWrapped.nonce
        ),
      },
      { status: 200 }
    )
  );
}

export function saveCryptoProfileHandler(onSave: (body: any) => void) {
  return http.post(buildRoute("2/saveCryptoProfile/"), async ({ request }) => {
    onSave(await request.json());
    return HttpResponse.json({ saved: true }, { status: 200 });
  });
}
