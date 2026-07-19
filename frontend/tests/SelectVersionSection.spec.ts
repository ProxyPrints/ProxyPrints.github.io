import { expect } from "@playwright/test";

import { localBackendURL } from "@/common/test-constants";
import {
  cardDocumentsSelectVersionMixedResults,
  defaultHandlers,
  searchResultsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

const selectVersionHandlers = [
  cardDocumentsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  searchResultsSelectVersionMixedResults,
  // The Attributes rail section fetches tag consensus the moment a slot is selected regardless
  // of whether it's ever opened - see DisplayPage.spec.ts's own identical comment.
  tagConsensusTwoUnresolvedTags,
  submitTagVoteResolvesToApply,
  ...defaultHandlers,
];

// Issue #167 - the unified Select Version section
// (docs/proposals/proposal-h-unified-display-page.md §4.4′), mounted as the display page rail's
// "Choose Image" accordion body. cardDocumentsSelectVersionMixedResults/
// searchResultsSelectVersionMixedResults (mocks/handlers.ts) cover all three of the spec's
// groups in one result set - see those fixtures' own comments for the exact shape.
test.describe("SelectVersionSection (issue #167)", () => {
  test.describe.configure({ timeout: 60_000 });

  const openSelectVersionSection = async (
    page: import("@playwright/test").Page
  ) => {
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Display (beta)" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    // Compressed view (the real, hardcoded default) hides per-card header text - same precedent
    // as DisplayPage.spec.ts's own tests.
    await page.getByText("Compressed").click();
  };

  test("groups candidates into canonical (by printing), non-canonical (by reason tag), and unknown sections", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    await expect(page.getByTestId("select-version-section")).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-canonical")
    ).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-non-canonical")
    ).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-unknown")
    ).toBeVisible();

    // Two distinct printings in this result set (sv-001 suggested, sv-002 resolved) -> two
    // canonical printing groups.
    await expect(
      page.locator('[data-testid^="select-version-printing-group-"]')
    ).toHaveCount(2);
    // One reason-tag group (custom-art).
    await expect(
      page.getByTestId("select-version-reason-group-custom-art")
    ).toBeVisible();
  });

  test("shows resolved printings before suggested printings, each with a representative and a '+N more of this printing' expander", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const printingGroups = page.locator(
      '[data-testid^="select-version-printing-group-"]'
    );
    // sv-002 (resolved, single copy) sorts before sv-001 (suggested, two copies) - resolved
    // printings sort ahead of suggested ones per the spec.
    await expect(printingGroups.nth(0)).toHaveAttribute(
      "data-status",
      "resolved"
    );
    await expect(printingGroups.nth(1)).toHaveAttribute(
      "data-status",
      "suggested"
    );

    // The suggested printing (sv-001) has two copies (cardDocument13/14) - one representative
    // (the higher-DPI copy, cardDocument14) plus a "+1 more" expander for the other.
    const suggestedGroup = printingGroups.nth(1);
    await expect(
      suggestedGroup.getByText("+1 more of this printing")
    ).toBeVisible();
    await suggestedGroup.getByText("+1 more of this printing").click();
    await expect(suggestedGroup.getByText("Show fewer")).toBeVisible();
  });

  test("a suggested-printing representative carries the Confirm affordance; a resolved printing does not", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const printingGroups = page.locator(
      '[data-testid^="select-version-printing-group-"]'
    );
    const resolvedGroup = printingGroups.nth(0);
    const suggestedGroup = printingGroups.nth(1);

    // Exact testid, not a prefix match - DeckbuilderConfirmAffordance's own internal badge/yes/no
    // controls all also start with "deckbuilder-confirm-" (see its own component), so a prefix
    // regex here would over-match those too.
    await expect(
      suggestedGroup.getByTestId(
        "deckbuilder-confirm-1hH2iI3jJ4kK5lL6mM7nN8oO9pP0qQ"
      )
    ).toHaveCount(1);
    await expect(
      resolvedGroup.getByTestId(/^deckbuilder-confirm-/)
    ).toHaveCount(0);
  });

  test("the filter-chip bar filters the whole section, and 'More like this' seeds it from a card's own resolved tags", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    // cardDocument18 (in the unknown group) has a resolved "Full Art" tag - its "More like this"
    // button should activate the Full Art filter chip.
    const unknownGroup = page.getByTestId("select-version-group-unknown");
    await unknownGroup
      .getByTestId(/^select-version-more-like-this-/)
      .first()
      .click();

    await expect(
      page.getByTestId("select-version-filter-chip-Full Art")
    ).toHaveAttribute("data-active", "true");
    // Filtering down to Full Art should still show cardDocument18 (it has the tag) and hide the
    // custom-art-only / unknown cards that don't.
    await expect(
      page.getByTestId("select-version-group-non-canonical")
    ).toHaveCount(0);
  });

  test("selecting a card while a filter tag is active but only 'suggested' (not resolved) on that specific card shows a one-tap confirm chip", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    // Manually activate the "Old Border" filter chip - cardDocument18 carries a *suggested* (not
    // resolved) Old Border vote, so it should still be filtered in (per this task's documented
    // resolved-OR-suggested filter semantics) and its selection should surface the confirm chip.
    await page.getByTestId("select-version-filter-chip-Old Border").click();

    const tile = page.getByTestId(
      "select-version-tile-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU"
    );
    await expect(tile).toBeVisible();
    await tile.locator(".mpccard").click();

    const confirmChip = page.getByTestId(
      "select-version-confirm-chip-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU-Old Border"
    );
    await expect(confirmChip).toBeVisible();

    await page
      .getByTestId(
        "select-version-confirm-chip-yes-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU-Old Border"
      )
      .click();
    await expect(confirmChip).not.toBeVisible();
  });
});
