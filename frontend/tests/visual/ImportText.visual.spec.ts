import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import { cardDocument1 } from "@/common/test-constants";
import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
  openDisplayToolbarAddCardsDropdown,
} from "../test-utils";

// Proposal H parity port (2026-07-23, issue #272 wave 1): ported onto the unified /editor page.
// `ImportTextButton` (the classic dropdown-triggered Modal this test's aria snapshot targets,
// `data-testid="import-text"`) is unforked and only reachable once a project already has a
// member - DisplayPage's own empty-project landing mounts the bare `ImportText` form directly
// instead (no Modal chrome at all - see ImportText.spec.ts's own port). Seeding one card first via
// importTextOnEditorLanding gets to the populated toolbar, whose "Add Cards" dropdown
// (openDisplayToolbarAddCardsDropdown, test-utils.ts) opens the exact same, byte-for-byte
// unmodified modal this snapshot was always asserting against.

test.describe("ImportText visual tests", () => {
  test("import text modal structure", async ({ page, network }) => {
    network.use(
      cardDocumentsThreeResults,
      sourceDocumentsOneResult,
      searchResultsThreeResults,
      ...defaultHandlers
    );
    await page.addInitScript({ content: "Math.random = () => 1;" });
    await loadPageWithDefaultBackend(page);
    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );

    await openDisplayToolbarAddCardsDropdown(page);
    await page.getByRole("button", { name: " Text" }).click();

    await expect(page.getByTestId("import-text")).toMatchAriaSnapshot(`
      - text: Add Cards — Text
      - button "Close"
      - paragraph: Type the names of the cards you'd like to add to your order and hit Submit. One card per line.
      - heading "Syntax Guide" [level=2]:
        - button "Syntax Guide"
      - textbox "import-text":
        - /placeholder: "2x Card 1\\n1x Card 2\\n2x Card 3\\n2x Card 4\\n\\n2x t:Card 6\\n\\n1x b:Card 5"
      - paragraph: "Hint: Submit with Control+Enter."
      - button "import-text-submit"
      - button "import-text-close"
    `);
  });
});
