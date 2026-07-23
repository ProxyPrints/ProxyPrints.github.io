/**
 * Regression coverage for the `autoPromptOnLock` trigger-timing fix: the unlock modal must
 * never pop unprompted when this hook mounts as part of an ambient page (the /display landing's
 * SavedDecksLandingPanel.tsx, which omits the option and gets the false default), and must still
 * pop immediately for a caller that deliberately opts in (MyDecksPage.tsx's own use, exercised
 * end-to-end by MyDecksPage.test.tsx's "opens automatically" case - this file only needs to
 * cover the hook's own opt-in/opt-out contract).
 */
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import {
  CryptoSessionProvider,
  useCryptoSession,
} from "@/features/savedDecks/cryptoSession";
import {
  existingProfileHandler,
  MockCryptoProfileMaterial,
} from "@/features/savedDecks/cryptoTestHandlers";
import { useLoadSavedDeck } from "@/features/savedDecks/useLoadSavedDeck";
import { whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;

jest.mock("next/router", () => ({
  useRouter: () => ({ push: jest.fn(), route: "/display" }),
}));

function TestHarness({ autoPromptOnLock }: { autoPromptOnLock?: boolean }) {
  const session = useCryptoSession();
  const { element } = useLoadSavedDeck({ autoPromptOnLock });
  return (
    <>
      <div data-testid="crypto-session-status">{session.status}</div>
      {element}
    </>
  );
}

function renderHarness(autoPromptOnLock?: boolean) {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <TestHarness autoPromptOnLock={autoPromptOnLock} />
      </CryptoSessionProvider>
    </Provider>
  );
}

async function mockLockedProfile(): Promise<MockCryptoProfileMaterial> {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  server.use(whoamiSignedInNotModerator, existingProfileHandler(profile));
  return profile;
}

test("omitting autoPromptOnLock (the /display landing's own default) never auto-opens the unlock modal against a locked session", async () => {
  await mockLockedProfile();
  renderHarness();

  // Wait for the crypto session to actually settle to "locked" (not "loading") - a session that
  // never gets there wouldn't be a meaningful negative assertion for the auto-open effect below.
  await waitFor(() =>
    expect(screen.getByTestId("crypto-session-status")).toHaveTextContent(
      "locked"
    )
  );
  expect(screen.queryByTestId("unlock-modal")).not.toBeInTheDocument();
});

test("autoPromptOnLock: true (MyDecksPage's own opt-in) still auto-opens the unlock modal against a locked session", async () => {
  await mockLockedProfile();
  renderHarness(true);

  await screen.findByTestId("unlock-modal");
});
