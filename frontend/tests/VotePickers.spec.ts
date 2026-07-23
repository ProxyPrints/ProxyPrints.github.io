import { expect } from "@playwright/test";

import { SelectedImageSeparator } from "@/common/constants";
import {
  canonicalArtist1,
  canonicalArtist2,
  cardDocument1,
  printingCandidate1,
  printingCandidate2,
} from "@/common/test-constants";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  cardbacksTwoOtherResults,
  cardDocumentsOneResult,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  searchResultsOneResult,
  sourceDocumentsOneResult,
  submitArtistVoteResolvesToCanonicalArtist1,
  submitPrintingTagResolvesToPrintingCandidate1,
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
  tagsBorderlessWithDisplayName,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import {
  importTextOnEditorLanding,
  loadPageWithDefaultBackend,
} from "./test-utils";

// Proposal H switchover (2026-07-23, issues #231/#272) - /editor now serves the unified
// sheet+rail page (`DisplayPage.tsx`); the classic grid `ProjectEditor` this file's own setup
// depends on (via testids/interaction patterns like `front-slot`/`back-slot`/`common-cardback`/
// the "Add Cards" right-panel dropdown/the classic "Print!" tab, or a component with no rendered
// equivalent on the new page yet - see issue #272's own tracked parity gaps) is fully unrouted,
// not just delisted from the nav. Skipped here rather than deleted (component files themselves
// are untouched, per this swap's own scope) or silently left red - porting this coverage to
// DisplayPage's DOM is real, non-mechanical work tracked against #272, not done as part of the
// route swap itself (the owner's directive was to proceed with the swap regardless of the
// checklist's open items).
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(
    true,
    "Proposal H switchover (2026-07-23): tests classic /editor-only UI, now unrouted - see issue #272"
  );
});

// Shared by all three picker suites below (identical across their source files).
//
// Proposal H switchover (2026-07-23, issues #231/#272) note: /editor now resolves to the
// unified page, whose own left rail ALSO carries "Card details" text (offcanvas title, handle
// button) in addition to CardDetailedViewBody's own "Card Details" heading - a plain
// getByText("Card Details") (case-insensitive substring by default) matched all three and threw
// a strict-mode violation. The heading role disambiguates to the one that's actually
// CardDetailedViewBody's own content, which is what this helper always meant to assert on.
const openDetailedView = async (page: any, cardName: string) => {
  await page.getByAltText(cardName).click();
  await expect(
    page.getByRole("heading", { name: "Card Details" })
  ).toBeVisible();
};

test.describe("ArtistVotePicker tests", () => {
  test("shows the attribute-voting panel once printing consensus is unresolved, listing candidate artists", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    // longer than the default 5s: showing this panel is gated behind a chain of fetches
    // (printing consensus resolves -> CardDetailedViewModal re-renders -> the panel mounts
    // -> its own two children each fire their own fetch), which is slower than a single
    // round trip even against these MSW mocks.
    const panel = page.getByTestId("attribute-voting-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    const artistPicker = page.getByTestId("artist-vote-picker");
    await expect(artistPicker.getByText(canonicalArtist1.name)).toBeVisible();
    await expect(artistPicker.getByText(canonicalArtist2.name)).toBeVisible();
    await expect(artistPicker.getByText("Unknown artist")).toBeVisible();
  });

  test("submitting a vote for an artist updates the shown consensus", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      submitArtistVoteResolvesToCanonicalArtist1,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const artistPicker = page.getByTestId("artist-vote-picker");
    await expect(artistPicker.getByText("Not yet resolved")).toBeVisible();

    await artistPicker.getByText(canonicalArtist1.name).click();

    await expect(page.getByText("Vote submitted")).toBeVisible();
    await expect(
      page
        .getByTestId("artist-vote-consensus")
        .getByText(`Current consensus: ${canonicalArtist1.name}`)
    ).toBeVisible();
  });
});

test.describe("TagVotePicker tests", () => {
  test("lists every seeded tag as an unresolved toggle chip", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      tagConsensusTwoUnresolvedTags,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const tagPicker = page.getByTestId("tag-vote-picker");
    await expect(tagPicker.getByText("Borderless")).toBeVisible();
    await expect(tagPicker.getByText("Extended")).toBeVisible();
  });

  test("shows a tag's displayName when set, falling back to its name when not", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      tagConsensusTwoUnresolvedTags,
      tagsBorderlessWithDisplayName, // only "Borderless" has a displayName; "Extended" doesn't exist in this list at all
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const tagPicker = page.getByTestId("tag-vote-picker");
    // "Borderless" has displayName "Frameless Border" set - shown instead of the raw name
    await expect(tagPicker.getByText("Frameless Border")).toBeVisible();
    await expect(
      tagPicker.getByText("Borderless", { exact: true })
    ).not.toBeVisible();
    // "Extended" has no displayName - falls back to its raw name
    await expect(tagPicker.getByText("Extended")).toBeVisible();
  });

  test("clicking a tag chip submits a vote and updates that chip's state", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      tagConsensusTwoUnresolvedTags,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const tagPicker = page.getByTestId("tag-vote-picker");
    await tagPicker.getByText("Borderless").click();

    // the mock always resolves to APPLY regardless of which chip was clicked, so this proves
    // the click round-tripped through APISubmitTagVote and re-rendered from the response
    await expect(tagPicker.getByText("Borderless")).toBeVisible();
  });
});

test.describe("PrintingTagPicker tests", () => {
  test("shows unresolved consensus and lists candidate printings", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    await expect(
      page.getByTestId("detailed-view").getByText("What's That Card?")
    ).toBeVisible();
    await expect(page.getByText("Not yet resolved")).toBeVisible();

    const picker = page.getByTestId("printing-tag-picker");
    await expect(
      picker.getByText(
        `${printingCandidate1.expansionCode.toUpperCase()} ${
          printingCandidate1.collectorNumber
        }`
      )
    ).toBeVisible();
    await expect(
      picker.getByText(
        `${printingCandidate2.expansionCode.toUpperCase()} ${
          printingCandidate2.collectorNumber
        }`
      )
    ).toBeVisible();
    await expect(picker.getByAltText("None of these match")).toBeVisible();
    await expect(picker.getByText("No match")).toBeVisible();

    const candidateButton1 = picker.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-name",
      cardDocument1.name
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-set-code",
      printingCandidate1.expansionCode
    );
    await expect(candidateButton1).toHaveAttribute(
      "data-card-collector-number",
      printingCandidate1.collectorNumber
    );

    const candidateButton2 = picker.locator(
      `[data-card-identifier="${printingCandidate2.identifier}"]`
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-name",
      cardDocument1.name
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-set-code",
      printingCandidate2.expansionCode
    );
    await expect(candidateButton2).toHaveAttribute(
      "data-card-collector-number",
      printingCandidate2.collectorNumber
    );
  });

  test("submitting a vote for a printing updates the shown consensus", async ({
    page,
    network,
  }) => {
    network.use(
      cardDocumentsOneResult,
      cardbacksTwoOtherResults,
      sourceDocumentsOneResult,
      searchResultsOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page);

    await importTextOnEditorLanding(
      page,
      `my search query${SelectedImageSeparator}${cardDocument1.identifier}`
    );
    await openDetailedView(page, cardDocument1.name);

    const picker = page.getByTestId("printing-tag-picker");
    await expect(page.getByText("Not yet resolved")).toBeVisible();

    await picker
      .getByText(
        `${printingCandidate1.expansionCode.toUpperCase()} ${
          printingCandidate1.collectorNumber
        }`
      )
      .click();

    await expect(page.getByText("Vote submitted")).toBeVisible();
    await expect(
      page
        .getByTestId("printing-tag-consensus")
        .getByText(
          `Current consensus: ${printingCandidate1.expansionCode.toUpperCase()} ${
            printingCandidate1.collectorNumber
          }`
        )
    ).toBeVisible();
  });
});
