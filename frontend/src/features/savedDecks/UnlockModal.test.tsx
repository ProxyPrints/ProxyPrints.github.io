import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import {
  base64ToBytes,
  bytesToBase64,
  createCryptoProfile,
} from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import { CryptoSessionProvider } from "@/features/savedDecks/cryptoSession";
import {
  existingProfileHandler,
  saveCryptoProfileHandler,
} from "@/features/savedDecks/cryptoTestHandlers";
import { UnlockModal } from "@/features/savedDecks/UnlockModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;

function renderModal(onUnlocked: () => void, onCancel: () => void) {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <UnlockModal show onCancel={onCancel} onUnlocked={onUnlocked} />
      </CryptoSessionProvider>
    </Provider>
  );
}

// The crypto profile fetch is still in flight the instant the modal mounts (see
// UnlockModal.tsx's isProfileLoading guard) - every test below must wait for it to settle
// before submitting, or the submit button is simply disabled and the click no-ops.
async function waitForProfileToLoad() {
  await waitFor(() =>
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument()
  );
}

test("wrong passphrase shows an error and never unlocks", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  const onUnlocked = jest.fn();
  renderModal(onUnlocked, jest.fn());
  await waitForProfileToLoad();

  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the wrong one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await waitFor(() =>
    expect(
      screen.getByText("That passphrase doesn't match.")
    ).toBeInTheDocument()
  );
  expect(onUnlocked).not.toHaveBeenCalled();
});

test("correct passphrase unlocks", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  const onUnlocked = jest.fn();
  renderModal(onUnlocked, jest.fn());
  await waitForProfileToLoad();

  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await waitFor(() => expect(onUnlocked).toHaveBeenCalledTimes(1));
});

test("forgot passphrase: wrong recovery key errors without unlocking", async () => {
  const profile = await createCryptoProfile("forgotten", TEST_ITERATIONS);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  const onUnlocked = jest.fn();
  renderModal(onUnlocked, jest.fn());
  await waitForProfileToLoad();

  fireEvent.click(screen.getByText("Forgot your passphrase?"));
  fireEvent.change(screen.getByLabelText("recovery-key-input"), {
    target: { value: "not-the-real-recovery-key-at-all-nope" },
  });
  fireEvent.change(screen.getByLabelText("new-passphrase-after-recovery"), {
    target: { value: "brand new passphrase" },
  });
  fireEvent.click(screen.getByText("Recover"));

  await waitFor(() =>
    expect(
      screen.getByText("That recovery key doesn't match.")
    ).toBeInTheDocument()
  );
  expect(onUnlocked).not.toHaveBeenCalled();
});

test("forgot passphrase: correct recovery key shows a fresh recovery key, then unlocks once acknowledged", async () => {
  const profile = await createCryptoProfile("forgotten", TEST_ITERATIONS);
  let savedBody: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    saveCryptoProfileHandler((body) => (savedBody = body))
  );
  const onUnlocked = jest.fn();
  renderModal(onUnlocked, jest.fn());
  await waitForProfileToLoad();

  fireEvent.click(screen.getByText("Forgot your passphrase?"));
  fireEvent.change(screen.getByLabelText("recovery-key-input"), {
    target: { value: bytesToBase64(profile.recoveryKeyBytes) },
  });
  fireEvent.change(screen.getByLabelText("new-passphrase-after-recovery"), {
    target: { value: "brand new passphrase" },
  });
  fireEvent.click(screen.getByText("Recover"));

  const recoveryKeyText = await screen.findByTestId("recovery-key-text");
  expect(base64ToBytes(recoveryKeyText.textContent ?? "")).toHaveLength(32);
  expect(recoveryKeyText.textContent).not.toEqual(
    bytesToBase64(profile.recoveryKeyBytes)
  );
  expect(savedBody.recoveryWrappedMasterKey).not.toEqual(
    bytesToBase64(profile.recoveryWrapped.wrapped)
  );

  fireEvent.click(
    screen.getByLabelText("I've saved this recovery key somewhere safe")
  );
  fireEvent.click(screen.getByTestId("recovery-key-continue"));

  expect(onUnlocked).toHaveBeenCalledTimes(1);
});
