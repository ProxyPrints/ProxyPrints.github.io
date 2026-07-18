import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { CardType } from "@/common/schema_types";
import { cardDocument1 } from "@/common/test-constants";
import { setupStore } from "@/store/store";

import { ExportImages } from "./ExportImages";

// Mirrors task #135's PDFGenerator.tsx fix (docs/lessons.md) - useCardDocumentsByIdentifier is
// keyed by every project member identifier, including ones whose CardDocument hasn't finished
// loading into the store yet (mapped to undefined). ExportImages.tsx had the same unguarded
// `cardDocument.sourceType` access as the bug fixed there, on the same sparse-map hook - this
// test reproduces the crash directly rather than only via a full PDF export flow.
const queueImageDownload = jest.fn();
jest.mock("../download/downloadImages", () => ({
  useDoImageDownload: () => queueImageDownload,
}));

function renderExportImages() {
  const store = setupStore({
    cardDocuments: {
      // Only card 1's document has loaded - card 2's identifier is a project member below but
      // absent here, the exact shape selectCardDocumentsByIdentifiers produces for a slot whose
      // fetch hasn't resolved yet.
      cardDocuments: { [cardDocument1.identifier]: cardDocument1 },
      status: "idle",
      error: null,
    },
    project: {
      members: [
        {
          id: "t-0",
          front: {
            query: { query: "card 1", cardType: CardType.Card },
            selectedImage: cardDocument1.identifier,
            selected: false,
          },
          back: null,
        },
        {
          id: "t-1",
          front: {
            query: { query: "card 2", cardType: CardType.Card },
            selectedImage: "not-yet-loaded-identifier",
            selected: false,
          },
          back: null,
        },
      ],
      nextMemberId: 2,
      cardback: null,
      mostRecentlySelectedSlot: null,
      manualOverrides: {},
    },
  });
  render(
    <Provider store={store}>
      <ExportImages />
    </Provider>
  );
}

test("ExportImages does not crash when a project member's CardDocument hasn't loaded yet, and only queues the loaded one", () => {
  renderExportImages();

  const item = screen.getByText("Card Images");
  expect(() => fireEvent.click(item)).not.toThrow();

  expect(queueImageDownload).toHaveBeenCalledTimes(1);
  expect(queueImageDownload.mock.calls[0][0]).toEqual(cardDocument1);
});
