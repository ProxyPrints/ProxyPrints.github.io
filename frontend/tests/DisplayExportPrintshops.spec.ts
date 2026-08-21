import { expect } from "@playwright/test";

import {
  cardDocumentsOneResult,
  defaultHandlers,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  whoamiAnonymous,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// The three printshop ordering guides (PringlePrints/MakePlayingCards/NotMPC), relocated from
// the retired `/print` page's "Print!" tab into the editor's Export menu (DisplayExportPrintshops.tsx)
// - see that component's own module comment.
const oneCardHandlers = [
  cardDocumentsOneResult,
  sourceDocumentsOneResult,
  searchResultsOneResult,
  ...defaultHandlers,
];

test("Printshops item opens a modal with all three ordering guides and the home-printing scaling alert", async ({
  page,
  network,
}) => {
  network.use(whoamiAnonymous, ...oneCardHandlers);
  await loadPageWithDefaultBackend(page);
  await importTextOnEditorLanding(page, "my search query");
  await expect(page.getByTestId("display-page")).toBeVisible();

  const footer = page.getByTestId("display-finish-footer");
  await footer.getByTestId("display-export-menu-toggle").click();
  await footer.getByTestId("export-printshops-button").click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("tab", { name: /PringlePrints/ })
  ).toBeVisible();
  await expect(
    dialog.getByRole("tab", { name: /MakePlayingCards/ })
  ).toBeVisible();
  await expect(dialog.getByRole("tab", { name: /NotMPC/ })).toBeVisible();

  // The single placement for print-at-home scaling guidance - see this component's own module
  // comment's "Home-printing guidance" section.
  await expect(dialog.getByText(/100% \/ Actual Size/i)).toBeVisible();
  await expect(dialog.getByText(/Expansion/i)).toBeVisible();

  await dialog.getByRole("tab", { name: /MakePlayingCards/ }).click();
  await expect(
    dialog.getByRole("heading", { name: "Download Your Project" })
  ).toBeVisible();

  await dialog.getByRole("tab", { name: /NotMPC/ }).click();
  await expect(
    dialog.getByRole("heading", { name: "Export Your Card Images" })
  ).toBeVisible();
});
