/**
 * Editor-polish round, item 11 (EP11, SPEC-editor-polish.md §D.8/§D.9, amendment 3) -
 * `SharedDeckViewer.tsx`'s own consent gate for orphan (unindexed Google Drive) card faces. Jest/
 * RTL, not Playwright: this is the "recipient of a shared deck" surface identified in
 * `SharedDeckViewer.tsx`'s own module comment (the ONLY real one in this codebase - see that
 * comment for the full spec-vs-shipped-mechanics note), and it's a plain, local-state component
 * with no PagePreview sheet/rail chrome to drive through a full page-load Playwright flow; RTL
 * mounts it directly with a controlled `payload`/`shareId`, the same precedent
 * `SharedDeckPage.test.tsx` already uses for this feature area.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { CardType } from "@/common/schema_types";
import { localBackend, localBackendURL } from "@/common/test-constants";
import { resetConsentDecisionSessionFlag } from "@/features/consent/consentToast";
import { DeckPayloadV2 } from "@/features/savedDecks/deckPayload";
import { SharedDeckViewer } from "@/features/savedDecks/SharedDeckViewer";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

// A real, allowlist-passing (isLikelyDriveFileId, orphanCard.ts) Drive-shaped identifier that
// the mocked /2/cards/ response below never resolves - exactly Phase 1's own "orphan" definition
// (foreign-order-resilience.md), ported to this recipient-side surface.
const ORPHAN_IDENTIFIER_A = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345";
const ORPHAN_IDENTIFIER_B = "1ZzYyXxWwVvUuTtSsRrQqPpOoNnMmLl987";

function buildPayload(selectedImage: string | undefined): DeckPayloadV2 {
  return {
    version: 2,
    name: "A deck with an external card",
    members: [
      {
        front: {
          query: { query: "Some Card", cardType: CardType.Card },
          selectedImage,
        },
        back: null,
      },
    ],
    cardback: null,
    manualOverrides: {},
    finishSettings: { cardstock: "(S30) Standard Smooth", foil: false },
    revision: 1,
    modifiedAt: "2026-07-24T00:00:00.000Z",
  };
}

function payloadWithOrphan(identifier: string): DeckPayloadV2 {
  return buildPayload(identifier);
}

function renderViewer(identifier: string, shareId: string) {
  server.use(
    http.post(`${localBackendURL}/2/cards/`, () =>
      HttpResponse.json({ results: {} }, { status: 200 })
    )
  );
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <SharedDeckViewer
        backendURL={localBackendURL}
        name="A deck with an external card"
        sharedAt="1st January, 2026"
        payload={payloadWithOrphan(identifier)}
        shareId={shareId}
      />
    </Provider>
  );
}

beforeEach(() => {
  resetConsentDecisionSessionFlag(`shared-deck-orphans:${ORPHAN_IDENTIFIER_A}`);
  resetConsentDecisionSessionFlag("shared-deck-orphans:deck-1");
  resetConsentDecisionSessionFlag("shared-deck-orphans:deck-2");
});

test("a deck with no orphan faces shows no consent prompt and no banner", async () => {
  server.use(
    http.post(`${localBackendURL}/2/cards/`, () =>
      HttpResponse.json({ results: {} }, { status: 200 })
    )
  );
  const store = setupStore({ backend: localBackend });
  const payload = buildPayload("");
  // No selectedImage at all on the one member - nothing to flag as an orphan.
  render(
    <Provider store={store}>
      <SharedDeckViewer
        backendURL={localBackendURL}
        name="No externals"
        sharedAt="1st January, 2026"
        payload={payload}
        shareId="deck-clean"
      />
    </Provider>
  );
  await screen.findByText("No externals");
  expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
  expect(
    screen.queryByTestId("shared-deck-ext-banner")
  ).not.toBeInTheDocument();
});

test("a deck with an orphan face prompts for consent; declining leaves the image hidden behind the lock placeholder", async () => {
  renderViewer(ORPHAN_IDENTIFIER_A, "deck-1");

  const toast = await screen.findByTestId("consent-toast");
  expect(toast).toHaveTextContent("External images in this shared deck");

  fireEvent.click(screen.getByTestId("consent-toast-decline"));

  await waitFor(() =>
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument()
  );
  expect(screen.getByTestId("shared-deck-hidden-orphan")).toHaveTextContent(
    "External image hidden"
  );
  expect(
    screen.queryByTestId("shared-deck-orphan-image")
  ).not.toBeInTheDocument();
  // Deny-by-default is reflected in the banner too.
  expect(screen.getByTestId("shared-deck-ext-banner")).toHaveTextContent(
    "1 external image hidden"
  );
});

test("accepting the consent prompt reveals the orphan's direct-Google image immediately", async () => {
  renderViewer(ORPHAN_IDENTIFIER_A, "deck-1");

  await screen.findByTestId("consent-toast");
  fireEvent.click(screen.getByTestId("consent-toast-accept"));

  await waitFor(() =>
    expect(screen.getByTestId("shared-deck-orphan-image")).toBeInTheDocument()
  );
  expect(screen.getByTestId("shared-deck-ext-banner")).toHaveTextContent(
    "1 external image shown"
  );
});

test("the deck banner's Review/Hide toggle is reversible, independent of the toast's own one-shot decision", async () => {
  renderViewer(ORPHAN_IDENTIFIER_A, "deck-1");

  await screen.findByTestId("consent-toast");
  fireEvent.click(screen.getByTestId("consent-toast-decline"));
  await waitFor(() => screen.getByTestId("shared-deck-hidden-orphan"));

  // Reversible: the banner's own "Review" toggle can override the declined state without
  // touching the underlying stored toast decision (amendment 3(b) - the base
  // useConsentToast Promise<boolean> contract stays untouched).
  fireEvent.click(screen.getByTestId("shared-deck-ext-banner-toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("shared-deck-orphan-image")).toBeInTheDocument()
  );
  expect(screen.getByTestId("shared-deck-ext-banner-toggle")).toHaveTextContent(
    "Hide"
  );

  // And back again.
  fireEvent.click(screen.getByTestId("shared-deck-ext-banner-toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("shared-deck-hidden-orphan")).toBeInTheDocument()
  );
});

test("amendment 3(a) - consent is scoped per shared-deck id: a second deck's orphan gets its own independent prompt even after the first deck was declined", async () => {
  server.use(
    http.post(`${localBackendURL}/2/cards/`, () =>
      HttpResponse.json({ results: {} }, { status: 200 })
    )
  );
  const { unmount } = render(
    <Provider store={setupStore({ backend: localBackend })}>
      <SharedDeckViewer
        backendURL={localBackendURL}
        name="Deck one"
        sharedAt="1st January, 2026"
        payload={payloadWithOrphan(ORPHAN_IDENTIFIER_A)}
        shareId="deck-1"
      />
    </Provider>
  );
  await screen.findByTestId("consent-toast");
  fireEvent.click(screen.getByTestId("consent-toast-decline"));
  await waitFor(() =>
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument()
  );
  unmount();

  // A DIFFERENT deck, a DIFFERENT orphan identifier, a DIFFERENT shareId - must prompt again,
  // not silently inherit deck-1's decline.
  render(
    <Provider store={setupStore({ backend: localBackend })}>
      <SharedDeckViewer
        backendURL={localBackendURL}
        name="Deck two"
        sharedAt="1st January, 2026"
        payload={payloadWithOrphan(ORPHAN_IDENTIFIER_B)}
        shareId="deck-2"
      />
    </Provider>
  );
  await screen.findByTestId("consent-toast");
});
