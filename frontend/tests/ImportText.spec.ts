import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  cardDocument1,
  cardDocument2,
  cardDocument3,
  cardDocument4,
  cardDocument5,
  cardDocument6,
  cardDocument12,
} from "@/common/test-constants";
import {
  cardbacksTwoOtherResults,
  cardDocumentsFourResults,
  cardDocumentsSixResults,
  cardDocumentsThreeResults,
  cardDocumentsWithResolvedPrintingMatch,
  defaultHandlers,
  dfcPairsMatchingCards1And4,
  sampleCards,
  searchResultsForDFCMatchedCards1And4,
  searchResultsOneResult,
  searchResultsResolvedPrintingMatch,
  searchResultsSixResults,
  sourceDocumentsOneResult,
  sourceDocumentsThreeResults,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  expectDisplaySheetSlotStates,
  expectDisplaySheetSlotToNotExist,
  importTextInline,
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page.
// DisplayPage mounts the same plain ImportText component verbatim on its empty-project landing
// (see loadPageWithDefaultBackend/importTextOnEditorLanding, test-utils.ts), and a non-empty
// project's toolbar mounts ImportText's own "inline" variant for adding more (importTextInline).
// Per-slot state assertions are ported via expectDisplaySheetSlotStates - see that helper's own
// comment for the one thing it deliberately doesn't check (selectedImage/totalImages counts,
// which the unified page's sheet has no inline readout for) and why that's still a faithful port
// of every test below's actual point (each result set in this suite gives every candidate its own
// distinct name, so the name check alone already proves the right one landed).

test.describe("ImportText", () => {
  test("importing one card by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "my search query");
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );
  });

  test("importing multiple instances of one card by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );

    // import two instances of a card
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "2x my search query");

    // two card slots should have been created
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
      ]
    );
  });

  test("importing multiple instances of one card without an x by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import two instances of a card without an x
    await importTextOnEditorLanding(page, "2 my search query");

    // two card slots should have been created
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
      ]
    );
  });

  test("importing multiple instances of one card with a capital X by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import two instances of a card with a capital X
    await importTextOnEditorLanding(page, "2X my search query");

    // two card slots should have been created
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument1.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
      ]
    );
  });

  test("importing multiple instances of one card by text into a non-empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // this used to preload the redux state, but with the shift to listeners,
    // we have to add the first card manually like this.
    await importTextOnEditorLanding(
      page,
      `1x my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );

    // import two instances of a card via the populated toolbar's inline search bar
    await importTextInline(page, "2x my search query");

    // two more card slots should have been created
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 2, name: cardDocument1.name },
        { slot: 3, name: cardDocument1.name },
      ],
      [
        { slot: 2, name: cardDocument2.name },
        { slot: 3, name: cardDocument2.name },
      ]
    );
  });

  test("importing one card of each type into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsSixResults,
      cardbacksTwoOtherResults,
      sourceDocumentsThreeResults,
      searchResultsSixResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import one card of each type
    await importTextOnEditorLanding(page, "query 1\nt:query 6\nb:query 5");

    // three card slots should have been created
    await expectDisplaySheetSlotStates(
      page,
      [
        { slot: 1, name: cardDocument1.name },
        { slot: 2, name: cardDocument6.name },
        { slot: 3, name: cardDocument5.name },
      ],
      [
        { slot: 1, name: cardDocument2.name },
        { slot: 2, name: cardDocument2.name },
        { slot: 3, name: cardDocument2.name },
      ]
    );
  });

  test("importing one DFC-paired card by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsFourResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsForDFCMatchedCards1And4,
      dfcPairsMatchingCards1And4,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import one instance of a double faced card
    await importTextOnEditorLanding(page, "my search query");

    // we should now have both sides of that DFC pair in slot 1
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument4.name }]
    );
  });

  test("importing an empty string by text into an empty project", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // the "import-text-submit" button requires non-empty input to submit at all (Form.Control
    // `required`) - unlike the classic modal, which stayed open and let this test observe "no
    // slot got created", the empty-landing page has nothing further to observe here besides
    // staying on the empty-state landing itself.
    await page.getByRole("textbox", { name: "import-text" }).fill("");
    await page.getByRole("button", { name: "import-text-submit" }).click();
    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    await expectDisplaySheetSlotToNotExist(page, 1);
  });

  test("the placeholder text of the text importer", async ({
    page,
    network,
  }) => {
    network.use(sampleCards, ...defaultHandlers);
    // Fix round (2026-07-23, this port): the pre-existing classic-editor version of this test
    // never `await`ed this call, racing addInitScript's own CDP registration against the very
    // next line's `page.goto()` - harmless there (empirically fine against the classic route in
    // whatever timing that page happened to hydrate on), but flaky against this page's own
    // hydration path, observed here as a genuinely real (non-1) Math.random() reaching
    // formatPlaceholderText. Awaiting it removes the race outright rather than papering over a
    // flake with a retry.
    await page.addInitScript({ content: "Math.random = () => 1;" });
    await loadPageWithDefaultBackend(page);

    await expect(page.getByTestId("display-empty-state")).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "import-text" })
    ).toHaveAttribute(
      "placeholder",
      `4x ${cardDocument1.name}\n4x ${cardDocument2.name}\n4x ${cardDocument3.name}\n4x ${cardDocument4.name}\n\n4x t:${cardDocument6.name}\n\n4x b:${cardDocument5.name}`
    );
  });

  test("the textbox should clear itself after submitting a list", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import a card
    await importTextOnEditorLanding(page, "my search query");

    // a card slot should have been created
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      []
    );

    // the populated toolbar's own inline search bar should be empty (onImportComplete clears
    // searchBarText - DisplayPage.tsx's own comment on the inline ImportText mount)
    await expect(
      page.getByRole("textbox", { name: "import-text-inline" })
    ).toHaveValue("");
  });

  test("the textbox should not clear itself until the form has been submitted", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // set some text without submitting
    await page.getByRole("textbox", { name: "import-text" }).fill("big test");

    // reloading the same landing page (still empty, nothing was submitted) keeps whatever the
    // uncontrolled textarea holds - the classic modal's own "close and reopen" affordance has no
    // equivalent here (there's no modal to close), so this just re-reads the same field.
    await expect(
      page.getByRole("textbox", { name: "import-text" })
    ).toHaveValue("big test");
  });

  test("pressing ctrl+enter while focused on the textarea should submit the form", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsThreeResults,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    // import a card, submitting the form with ctrl+enter
    await page.getByRole("textbox", { name: "import-text" }).click();
    await page
      .getByRole("textbox", { name: "import-text" })
      .fill("my search query");
    await page.keyboard.press("Control+Enter");

    // a card slot should have been created
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument1.name }],
      [{ slot: 1, name: cardDocument2.name }]
    );
  });

  test("importing a decklist line with a set code selects the community-resolved printing match and shows the indicator", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsWithResolvedPrintingMatch,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsResolvedPrintingMatch,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(page, "1 Lightning Bolt (2ED) 162");
    await expectDisplaySheetSlotStates(
      page,
      [{ slot: 1, name: cardDocument12.name }],
      []
    );
    // The classic grid's own "printing-match-indicator" badge (this test's other assertion,
    // pre-port) is rendered by Card.tsx's small-thumbnail CardImage path only - PagePreview's
    // sheet slots (this page's own image render, see this file's module comment) don't mount that
    // component, so there's no equivalent element to check here. The unified page's own signal for
    // this same condition (a resolved, non-degraded printing-specific import) used to be a static
    // "plain style" `requested-printing-badge` on the rail-head, but rail-delegacy's RD7
    // (SPEC-rail-delegacy.md §F item 4/§H O2) retired that: the badge now renders ONLY as a
    // requested≠resolved mismatch flag, never a static second copy of an identity the D14
    // confidence band already shows once - so a correctly-resolved import like this one renders
    // no badge at all. That's covered end-to-end by DisplayPage.spec.ts's "the rail-head shows no
    // mismatch flag for a resolved, non-degraded printing-specific import (the id already lives
    // once, in D14)" test - not duplicated here.
    await page.getByTestId("page-preview-slot").first().click();
    await expect(page.getByTestId("requested-printing-badge")).toHaveCount(0);
  });
});
