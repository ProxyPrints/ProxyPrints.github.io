import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { Card, PrintingTagStatus } from "@/common/schema_types";
import {
  cardDocument8,
  localBackend,
  localBackendURL,
} from "@/common/test-constants";
import { SearchQuery } from "@/common/types";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { DeckbuilderConfirmAffordance } from "./DeckbuilderConfirmAffordance";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

// Every test uses its own card identifier (derived from cardDocument8's fixture data, which
// already carries a canonicalCard) rather than sharing one - DeckbuilderConfirmAffordance
// tracks "resolved this session" in a module-level Set keyed by identifier (see its own
// comment for why that's not Redux state), so reusing one identifier across tests would leak
// a YES/NO resolution from an earlier test into a later one expecting the badge to still show.
let nextTestCardSuffix = 0;
function buildTestCard(overrides: Partial<Card> = {}): Card {
  nextTestCardSuffix += 1;
  return {
    ...cardDocument8,
    identifier: `${cardDocument8.identifier}-test-${nextTestCardSuffix}`,
    ...overrides,
  } as Card;
}

function renderAffordance({
  card,
  searchQuery,
  onOpenGridSelector = () => undefined,
}: {
  card: Card;
  searchQuery: SearchQuery | undefined;
  onOpenGridSelector?: () => void;
}) {
  const store = setupStore({
    backend: localBackend,
    cardDocuments: {
      cardDocuments: { [card.identifier]: card },
      status: "idle",
      error: null,
    },
  });
  render(
    <Provider store={store}>
      <DeckbuilderConfirmAffordance
        cardIdentifier={card.identifier}
        searchQuery={searchQuery}
        onOpenGridSelector={onOpenGridSelector}
      />
    </Provider>
  );
  return card;
}

const UNRESOLVED_SEARCH_QUERY: SearchQuery = {
  query: "card 8",
  cardType: "CARD" as SearchQuery["cardType"],
  expansionCode: "XYZ",
  collectorNumber: "001",
};

const REFERENCE_CANDIDATE = {
  identifier: "xyz-001-printing",
  canonicalId: "canonical-xyz-001",
  expansionCode: "xyz",
  expansionName: "XYZ Set",
  collectorNumber: "001",
  artist: "Some Artist",
  smallThumbnailUrl: "https://example.com/small-ref.png",
  mediumThumbnailUrl: "https://example.com/medium-ref.png",
  fullArt: false,
  isBorderless: false,
  frame: "2015",
  borderColor: "black",
  isShowcase: false,
  isExtendedArt: false,
  isEtched: false,
};

describe("DeckbuilderConfirmAffordance", () => {
  it("renders nothing when the slot wasn't imported with a canonical printing ID", () => {
    const card = renderAffordance({
      card: buildTestCard(),
      searchQuery: {
        query: "card 8",
        cardType: "CARD" as SearchQuery["cardType"],
      },
    });
    expect(
      screen.queryByTestId(`deckbuilder-confirm-${card.identifier}`)
    ).not.toBeInTheDocument();
  });

  it("renders nothing for a printing already Resolved to the imported set/collector-number", () => {
    const card = renderAffordance({
      card: buildTestCard({ printingTagStatus: PrintingTagStatus.Resolved }),
      searchQuery: UNRESOLVED_SEARCH_QUERY,
    });
    expect(
      screen.queryByTestId(`deckbuilder-confirm-${card.identifier}`)
    ).not.toBeInTheDocument();
  });

  it("renders the badge for an unresolved canonical import", () => {
    const card = renderAffordance({
      card: buildTestCard(),
      searchQuery: UNRESOLVED_SEARCH_QUERY,
    });
    expect(
      screen.getByTestId(`deckbuilder-confirm-${card.identifier}`)
    ).toBeInTheDocument();
    expect(screen.getByTestId("deckbuilder-confirm-badge")).toBeInTheDocument();
  });

  it("Y/N stay disabled until a compare has fired once", async () => {
    server.use(
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      )
    );
    renderAffordance({
      card: buildTestCard(),
      searchQuery: UNRESOLVED_SEARCH_QUERY,
    });

    expect(screen.getByTestId("deckbuilder-confirm-yes")).toBeDisabled();
    expect(screen.getByTestId("deckbuilder-confirm-no")).toBeDisabled();

    fireEvent.mouseEnter(screen.getByTestId("deckbuilder-confirm-badge"));

    await waitFor(() =>
      expect(screen.getByTestId("deckbuilder-confirm-no")).not.toBeDisabled()
    );
    await waitFor(() =>
      expect(screen.getByTestId("deckbuilder-confirm-yes")).not.toBeDisabled()
    );
    expect(screen.getByTestId("deckbuilder-compare-pin")).toBeInTheDocument();
  });

  it("YES submits a positive printing vote with voteSurface=deckbuilder, then hides", async () => {
    let submittedBody: Record<string, unknown> = {};
    server.use(
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        submittedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            resolvedPrinting: REFERENCE_CANDIDATE,
            isNoMatch: false,
            voteTally: [],
          },
          { status: 200 }
        );
      })
    );
    const card = renderAffordance({
      card: buildTestCard(),
      searchQuery: UNRESOLVED_SEARCH_QUERY,
    });

    fireEvent.mouseEnter(screen.getByTestId("deckbuilder-confirm-badge"));
    await waitFor(() =>
      expect(screen.getByTestId("deckbuilder-confirm-yes")).not.toBeDisabled()
    );
    fireEvent.click(screen.getByTestId("deckbuilder-confirm-yes"));

    await waitFor(() =>
      expect(
        screen.queryByTestId(`deckbuilder-confirm-${card.identifier}`)
      ).not.toBeInTheDocument()
    );
    expect(submittedBody.printingIdentifier).toBe(
      REFERENCE_CANDIDATE.identifier
    );
    expect(submittedBody.isNoMatch).toBe(false);
    expect(submittedBody.voteSurface).toBe("deckbuilder");
  });

  it("NO opens the grid selector, casts no printing vote, and hides", async () => {
    let printingTagSubmitted = false;
    server.use(
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [REFERENCE_CANDIDATE] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), () => {
        printingTagSubmitted = true;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        );
      })
    );
    let gridSelectorOpened = false;
    const card = renderAffordance({
      card: buildTestCard(),
      searchQuery: UNRESOLVED_SEARCH_QUERY,
      onOpenGridSelector: () => {
        gridSelectorOpened = true;
      },
    });

    fireEvent.mouseEnter(screen.getByTestId("deckbuilder-confirm-badge"));
    await waitFor(() =>
      expect(screen.getByTestId("deckbuilder-confirm-no")).not.toBeDisabled()
    );
    fireEvent.click(screen.getByTestId("deckbuilder-confirm-no"));

    expect(gridSelectorOpened).toBe(true);
    expect(
      screen.queryByTestId(`deckbuilder-confirm-${card.identifier}`)
    ).not.toBeInTheDocument();
    expect(printingTagSubmitted).toBe(false);
  });
});
