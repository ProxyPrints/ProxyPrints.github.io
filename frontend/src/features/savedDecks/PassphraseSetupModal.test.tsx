import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { base64ToBytes } from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import { CryptoSessionProvider } from "@/features/savedDecks/cryptoSession";
import {
  noProfileHandler,
  saveCryptoProfileHandler,
} from "@/features/savedDecks/cryptoTestHandlers";
import { PassphraseSetupModal } from "@/features/savedDecks/PassphraseSetupModal";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

function renderModal(onComplete: () => void, onCancel: () => void) {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <PassphraseSetupModal
          show
          onCancel={onCancel}
          onComplete={onComplete}
        />
      </CryptoSessionProvider>
    </Provider>
  );
}

beforeEach(() => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
});

test("mismatched passphrases show an error and never call createProfile", async () => {
  const onComplete = jest.fn();
  renderModal(onComplete, jest.fn());

  fireEvent.change(screen.getByLabelText("new-passphrase"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.change(screen.getByLabelText("confirm-new-passphrase"), {
    target: { value: "does not match" },
  });
  fireEvent.click(screen.getByText("Create passphrase"));

  await waitFor(() =>
    expect(screen.getByText("Passphrases don't match.")).toBeInTheDocument()
  );
  expect(screen.queryByTestId("recovery-key-text")).not.toBeInTheDocument();
  expect(onComplete).not.toHaveBeenCalled();
});

test("a too-short passphrase is rejected before calling createProfile", async () => {
  renderModal(jest.fn(), jest.fn());

  fireEvent.change(screen.getByLabelText("new-passphrase"), {
    target: { value: "short" },
  });
  fireEvent.change(screen.getByLabelText("confirm-new-passphrase"), {
    target: { value: "short" },
  });
  fireEvent.click(screen.getByText("Create passphrase"));

  await waitFor(() =>
    expect(screen.getByText(/at least 12 characters/)).toBeInTheDocument()
  );
});

test("matching passphrases create a profile, show the recovery key, and only complete once acknowledged", async () => {
  let savedBody: any = null;
  server.use(saveCryptoProfileHandler((body) => (savedBody = body)));
  const onComplete = jest.fn();
  renderModal(onComplete, jest.fn());

  fireEvent.change(screen.getByLabelText("new-passphrase"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.change(screen.getByLabelText("confirm-new-passphrase"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.click(screen.getByText("Create passphrase"));

  const recoveryKeyText = await screen.findByTestId("recovery-key-text");
  expect(base64ToBytes(recoveryKeyText.textContent ?? "")).toHaveLength(32);
  expect(savedBody.salt).toBeTruthy();

  // Continue is disabled until the acknowledgement checkbox is checked
  const continueButton = screen.getByTestId("recovery-key-continue");
  expect(continueButton).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText("I've saved this recovery key somewhere safe")
  );
  expect(continueButton).toBeEnabled();

  fireEvent.click(continueButton);
  expect(onComplete).toHaveBeenCalledTimes(1);
});
