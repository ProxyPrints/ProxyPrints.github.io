import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { synthesizeOrphanCardDocument } from "@/common/orphanCard";
import { CardType } from "@/common/schema_types";
import { cardDocument1 } from "@/common/test-constants";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { setupStore } from "@/store/store";

import { Card } from "./Card";

// cardDocument1 is Google Drive-sourced, so Card.tsx's LocalFile-only branch never touches
// this - a real ClientSearchService isn't needed, just a value satisfying the context.
const stubClientSearchContext = {
  clientSearchService: {} as ClientSearchService,
  forceUpdate: () => undefined,
  forceUpdateValue: 0,
};

function renderCard(cardOnClick?: () => void) {
  const store = setupStore({});
  render(
    <Provider store={store}>
      <ClientSearchContextProvider value={stubClientSearchContext}>
        <Card
          maybeCardDocument={cardDocument1}
          cardHeaderTitle="Option 1"
          cardOnClick={cardOnClick}
          noResultsFound={false}
        />
      </ClientSearchContextProvider>
    </Provider>
  );
}

// Foreign-order resilience Phase 1 (issue #324): an orphan is a synthesized CardDocument for a
// Drive file ID this catalog has never indexed - "visually distinct treatment", no click-to-
// detailed-view (no tags/consensus surfaces), no fabricated DPI in the source line.
describe("orphan rendering (issue #324)", () => {
  const orphanId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
  const orphanCardDocument = synthesizeOrphanCardDocument(orphanId, {
    name: "Kharn",
    cardType: CardType.Card,
  });

  function renderOrphanCard() {
    const store = setupStore({});
    render(
      <Provider store={store}>
        <ClientSearchContextProvider value={stubClientSearchContext}>
          <Card
            maybeCardDocument={orphanCardDocument}
            cardHeaderTitle="Slot 1"
            noResultsFound={false}
          />
        </ClientSearchContextProvider>
      </Provider>
    );
    return store;
  }

  it("shows the 'Your file' badge", () => {
    renderOrphanCard();
    expect(screen.getByTestId("orphan-badge")).toHaveTextContent("Your file");
  });

  it("shows the sanitized stand-in name, not a fabricated DPI", () => {
    renderOrphanCard();
    expect(screen.getByText("Kharn")).toBeInTheDocument();
    // "Your file" appears twice (the corner badge, plus the source line) - both are correct,
    // this test is only checking the source line never fabricates "[0 DPI]".
    expect(screen.getAllByText("Your file").length).toBe(2);
    expect(screen.queryByText(/DPI/)).not.toBeInTheDocument();
  });

  it("clicking the image does not open the detailed-view modal (no tags/consensus surfaces)", () => {
    const store = renderOrphanCard();
    const image = screen.getByAltText("Kharn");
    fireEvent.click(image);
    expect(store.getState().modals.shownModal).not.toBe("cardDetailedView");
  });

  it("a single failed image fetch reaches the 'Image unavailable' placeholder, not a stuck spinner", () => {
    // Regression test for the bucket-validity-aware onError fix in useImageSrc: an orphan has
    // no bucket URL configured, so it's already loading its one-and-only direct-from-Google URL
    // from the very first render (just still internally labelled "loading-from-bucket", this
    // hook's fixed initial state) - a naive onError would relabel to "loading-from-fallback" and
    // re-render with the SAME src string, which browsers don't re-fetch, leaving the image
    // broken forever with the spinner never resolving.
    renderOrphanCard();
    const image = screen.getByAltText("Kharn");
    fireEvent.error(image);
    expect(
      screen.getByTestId("card-image-error-placeholder")
    ).toBeInTheDocument();
    expect(screen.getByText("Image unavailable")).toBeInTheDocument();
  });
});

describe("Card keyboard activation", () => {
  it("is focusable and has role=button when cardOnClick is provided", () => {
    renderCard(() => undefined);
    const card = screen.getByRole("button", { name: /Option 1/ });
    expect(card).toHaveAttribute("tabindex", "0");
  });

  it("is not focusable and has no button role when cardOnClick is absent", () => {
    renderCard(undefined);
    expect(
      screen.queryByRole("button", { name: /Option 1/ })
    ).not.toBeInTheDocument();
  });

  it("Enter activates cardOnClick", () => {
    const onClick = jest.fn();
    renderCard(onClick);
    const card = screen.getByRole("button", { name: /Option 1/ });
    fireEvent.keyDown(card, { key: "Enter" });
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Space activates cardOnClick", () => {
    const onClick = jest.fn();
    renderCard(onClick);
    const card = screen.getByRole("button", { name: /Option 1/ });
    fireEvent.keyDown(card, { key: " " });
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("an unrelated key does not activate cardOnClick", () => {
    const onClick = jest.fn();
    renderCard(onClick);
    const card = screen.getByRole("button", { name: /Option 1/ });
    fireEvent.keyDown(card, { key: "a" });
    expect(onClick).not.toHaveBeenCalled();
  });
});
