import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

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
