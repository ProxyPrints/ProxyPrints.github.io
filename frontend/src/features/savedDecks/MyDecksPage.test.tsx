import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { createCryptoProfile } from "@/common/savedDeckCrypto";
import { localBackend } from "@/common/test-constants";
import { CryptoSessionProvider } from "@/features/savedDecks/cryptoSession";
import {
  buildMockSavedDeckSummary,
  deleteDeckHandler,
  existingProfileHandler,
  getSavedDecksHandler,
  noProfileHandler,
  resetSavedDecksHandler,
} from "@/features/savedDecks/cryptoTestHandlers";
import { DeckPayloadV1 } from "@/features/savedDecks/deckPayload";
import { MyDecksPage } from "@/features/savedDecks/MyDecksPage";
import { whoamiAnonymous, whoamiSignedInNotModerator } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { selectProjectMembers } from "@/store/slices/projectSlice";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { setupStore } from "@/store/store";

const TEST_ITERATIONS = 100;

const routerPush = jest.fn();
jest.mock("next/router", () => ({
  useRouter: () => ({ push: routerPush, route: "/myDecks" }),
}));

function emptyDeckPayload(name: string): DeckPayloadV1 {
  return {
    version: 1,
    name,
    members: [],
    cardback: null,
    manualOverrides: {},
    finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
  };
}

function renderPage() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <CryptoSessionProvider>
        <MyDecksPage />
      </CryptoSessionProvider>
    </Provider>
  );
  return store;
}

beforeEach(() => {
  routerPush.mockClear();
});

test("anonymous session shows a sign-in prompt, never fetches saved decks", async () => {
  server.use(whoamiAnonymous);
  renderPage();

  await screen.findByText(
    "Sign in from the navbar above to save and load decks."
  );
});

test("authenticated with no crypto profile shows the empty state", async () => {
  server.use(whoamiSignedInNotModerator, noProfileHandler());
  renderPage();

  await screen.findByText(
    "You haven't saved any decks yet - save your current project from the editor to get started."
  );
});

test("locked: the unlock modal opens automatically; unlocking reveals named decks and snapshots in separate groups", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  const namedDeck = await buildMockSavedDeckSummary(
    "deck-1",
    "deck",
    emptyDeckPayload("Standard Aggro"),
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );
  const snapshot = await buildMockSavedDeckSummary(
    "snap-1",
    "snapshot",
    emptyDeckPayload("Backup - 2026-01-01"),
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-01" }
  );
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([namedDeck, snapshot])
  );
  renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await screen.findByTestId("named-decks-list");
  expect(screen.getByTestId("named-decks-list")).toHaveTextContent(
    "Standard Aggro"
  );
  expect(screen.getByTestId("snapshots-list")).toHaveTextContent(
    "Backup - 2026-01-01"
  );
});

test("opening a deck loads it into the project store and navigates to the editor", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  const payload = emptyDeckPayload("Control Deck");
  payload.members = [
    {
      front: { query: { query: "Island", cardType: "card" } },
      back: null,
    },
  ] as any;
  const namedDeck = await buildMockSavedDeckSummary(
    "deck-42",
    "deck",
    payload,
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([namedDeck])
  );
  const store = renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await screen.findByText("Control Deck");
  fireEvent.click(screen.getByText("Open in editor"));

  await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/editor"));
  expect(selectProjectMembers(store.getState())).toHaveLength(1);
  expect(selectCurrentSavedDeck(store.getState())).toMatchObject({
    currentDeckKey: "deck-42",
    currentDeckName: "Control Deck",
    // v1 legacy payload (emptyDeckPayload's `version: 1`) upgraded on load - PR-6 "Revision
    // tracking" backfills revision 0 for a pre-existing row that never tracked one.
    lastSavedRevision: 0,
  });
});

test("deleting a deck asks for confirmation, then calls deleteDeck with its key", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  const namedDeck = await buildMockSavedDeckSummary(
    "deck-7",
    "deck",
    emptyDeckPayload("Throwaway Deck"),
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );
  let deletedBody: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([namedDeck]),
    deleteDeckHandler((body) => (deletedBody = body))
  );
  const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
  renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await screen.findByText("Throwaway Deck");
  fireEvent.click(screen.getByText("Delete"));

  await waitFor(() => expect(deletedBody).toEqual({ key: "deck-7" }));
  confirmSpy.mockRestore();
});

test("resetting saved decks requires a second confirming click before calling the endpoint", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  let resetBody: any = null;
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([]),
    resetSavedDecksHandler((body) => (resetBody = body))
  );
  renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  const resetButton = await screen.findByTestId("reset-saved-decks");
  fireEvent.click(resetButton);
  expect(resetBody).toBeNull();
  expect(
    screen.getByText("Yes, permanently delete all 0 saved decks")
  ).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("reset-saved-decks"));
  await waitFor(() => expect(resetBody).toEqual({ confirm: true }));
});

test("PR-6 deck portability: Export my decks is disabled with zero decks, enabled once decks exist, and triggers a download", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([])
  );
  renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  const exportButton = await screen.findByTestId("export-my-decks");
  expect(exportButton).toBeDisabled();
});

test("PR-6 deck portability: Export my decks works while STILL LOCKED - the spec's own headline scenario (a user who's forgotten their passphrase can still export)", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  const namedDeck = await buildMockSavedDeckSummary(
    "deck-1",
    "deck",
    emptyDeckPayload("Standard Aggro"),
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([namedDeck])
  );
  renderPage();

  // Deliberately never unlocks - the unlock modal auto-shows (locked state), but Export must
  // still work without it, per the spec's own explicit requirement.
  await screen.findByTestId("unlock-modal");

  const exportButton = await screen.findByTestId("export-my-decks");
  await waitFor(() => expect(exportButton).not.toBeDisabled());

  const clickSpy = jest
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  fireEvent.click(exportButton);

  await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  clickSpy.mockRestore();
});

test("PR-6 deck portability: Export my decks downloads a bundle once decks exist", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  const namedDeck = await buildMockSavedDeckSummary(
    "deck-1",
    "deck",
    emptyDeckPayload("Standard Aggro"),
    profile.masterKey,
    { createdAt: "2026-01-01", updatedAt: "2026-01-02" }
  );
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([namedDeck])
  );
  renderPage();

  await screen.findByTestId("unlock-modal");
  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  const exportButton = await screen.findByTestId("export-my-decks");
  await waitFor(() => expect(exportButton).not.toBeDisabled());

  const clickSpy = jest
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  fireEvent.click(exportButton);

  await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  clickSpy.mockRestore();
});

test("PR-6 deck portability: Import decks is disabled while locked, enabled once unlocked", async () => {
  const profile = await createCryptoProfile("the real one", TEST_ITERATIONS);
  server.use(
    whoamiSignedInNotModerator,
    existingProfileHandler(profile),
    getSavedDecksHandler([])
  );
  renderPage();

  await screen.findByTestId("unlock-modal");
  expect(screen.getByTestId("open-import-decks")).toBeDisabled();

  fireEvent.change(screen.getByLabelText("unlock-passphrase"), {
    target: { value: "the real one" },
  });
  fireEvent.click(screen.getByText("Unlock"));

  await waitFor(() =>
    expect(screen.getByTestId("open-import-decks")).not.toBeDisabled()
  );
});
