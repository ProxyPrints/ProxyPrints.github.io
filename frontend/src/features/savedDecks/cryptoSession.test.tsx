import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React, { useState } from "react";
import { Provider } from "react-redux";

import {
  base64ToBytes,
  bytesToBase64,
  createCryptoProfile,
} from "@/common/savedDeckCrypto";
import { localBackend, localBackendURL } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import { whoamiAnonymous, whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

function noProfileHandler() {
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

function existingProfileHandler(profile: {
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
}) {
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

function saveCryptoProfileHandler(onSave: (body: any) => void) {
  return http.post(buildRoute("2/saveCryptoProfile/"), async ({ request }) => {
    onSave(await request.json());
    return HttpResponse.json({ saved: true }, { status: 200 });
  });
}

function Harness() {
  const session = useCryptoSession();
  const [passphrase, setPassphrase] = useState("");
  const [recoveryKey, setRecoveryKey] = useState("");
  const [shownRecoveryKey, setShownRecoveryKey] = useState("");
  const [error, setError] = useState("");

  return (
    <div>
      <span data-testid="status">{session.status}</span>
      <span data-testid="shown-recovery-key">{shownRecoveryKey}</span>
      <span data-testid="error">{error}</span>
      <input
        data-testid="passphrase-input"
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
      />
      <input
        data-testid="recovery-input"
        value={recoveryKey}
        onChange={(event) => setRecoveryKey(event.target.value)}
      />
      <button
        data-testid="create"
        onClick={() => {
          setError("");
          session
            .createProfile(passphrase)
            .then(setShownRecoveryKey)
            .catch((thrown) => setError(String(thrown)));
        }}
      >
        Create
      </button>
      <button
        data-testid="unlock"
        onClick={() => {
          setError("");
          session
            .unlockWithPassphrase(passphrase)
            .catch((thrown) => setError(String(thrown)));
        }}
      >
        Unlock
      </button>
      <button
        data-testid="recover"
        onClick={() => {
          setError("");
          session
            .recoverAndSetNewPassphrase(recoveryKey, passphrase)
            .then(setShownRecoveryKey)
            .catch((thrown) => setError(String(thrown)));
        }}
      >
        Recover
      </button>
      <button data-testid="lock" onClick={() => session.lock()}>
        Lock
      </button>
    </div>
  );
}

function renderHarness() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <Harness />
      </CryptoSessionProvider>
    </Provider>
  );
}

test("anonymous session never reaches past the anonymous status", async () => {
  server.use(whoamiAnonymous);
  renderHarness();

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous")
  );
});

test("authenticated with no crypto profile yet reports no-profile", async () => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
  renderHarness();

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("no-profile")
  );
});

test("createProfile unlocks the session and shows a usable recovery key", async () => {
  let savedBody: any = null;
  server.use(
    whoamiSignedInNotModerator,
    noProfileHandler(),
    saveCryptoProfileHandler((body) => (savedBody = body))
  );
  renderHarness();
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("no-profile")
  );

  fireEvent.change(screen.getByTestId("passphrase-input"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.click(screen.getByTestId("create"));

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("unlocked")
  );
  const shownKey = screen.getByTestId("shown-recovery-key").textContent ?? "";
  expect(base64ToBytes(shownKey)).toHaveLength(32);
  expect(savedBody.salt).toBeTruthy();
  expect(savedBody.passphraseWrappedMasterKey).toBeTruthy();
  expect(savedBody.recoveryWrappedMasterKey).toBeTruthy();
});

test("locked session: wrong passphrase errors and stays locked, correct passphrase unlocks", async () => {
  const profile = await createCryptoProfile(
    "the real passphrase",
    TEST_ITERATIONS
  );
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  renderHarness();

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("locked")
  );

  fireEvent.change(screen.getByTestId("passphrase-input"), {
    target: { value: "the wrong passphrase" },
  });
  fireEvent.click(screen.getByTestId("unlock"));
  await waitFor(() =>
    expect(screen.getByTestId("error").textContent).not.toEqual("")
  );
  expect(screen.getByTestId("status")).toHaveTextContent("locked");

  fireEvent.change(screen.getByTestId("passphrase-input"), {
    target: { value: "the real passphrase" },
  });
  fireEvent.click(screen.getByTestId("unlock"));
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("unlocked")
  );
});

test("recovery flow: unlocks via the recovery key, sets a new passphrase, and shows a fresh recovery key", async () => {
  const profile = await createCryptoProfile(
    "forgotten passphrase",
    TEST_ITERATIONS
  );
  let savedBody: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    saveCryptoProfileHandler((body) => (savedBody = body))
  );
  renderHarness();
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("locked")
  );

  fireEvent.change(screen.getByTestId("recovery-input"), {
    target: { value: bytesToBase64(profile.recoveryKeyBytes) },
  });
  fireEvent.change(screen.getByTestId("passphrase-input"), {
    target: { value: "brand new passphrase" },
  });
  fireEvent.click(screen.getByTestId("recover"));

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("unlocked")
  );
  const newRecoveryKey =
    screen.getByTestId("shown-recovery-key").textContent ?? "";
  expect(base64ToBytes(newRecoveryKey)).toHaveLength(32);
  expect(newRecoveryKey).not.toEqual(bytesToBase64(profile.recoveryKeyBytes));
  expect(savedBody.recoveryWrappedMasterKey).not.toEqual(
    bytesToBase64(profile.recoveryWrapped.wrapped)
  );
});

test("lock() clears the unlocked master key back to locked", async () => {
  const profile = await createCryptoProfile(
    "the real passphrase",
    TEST_ITERATIONS
  );
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  renderHarness();
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("locked")
  );

  fireEvent.change(screen.getByTestId("passphrase-input"), {
    target: { value: "the real passphrase" },
  });
  fireEvent.click(screen.getByTestId("unlock"));
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("unlocked")
  );

  fireEvent.click(screen.getByTestId("lock"));
  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("locked")
  );
});
