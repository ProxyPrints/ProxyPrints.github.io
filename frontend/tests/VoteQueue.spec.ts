import { expect } from "@playwright/test";

import {
  cardDocument1,
  cardDocument8,
  cardDocument9,
} from "@/common/test-constants";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  defaultHandlers,
  printingCandidatesTwoResults,
  printingConsensusUnresolved,
  printingTagQueueOneResult,
  voteQueueArtistOneTagOneResults,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("Vote queue kind switcher", () => {
  test("switching tabs drives all three queue modes", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      printingCandidatesTwoResults,
      printingConsensusUnresolved,
      voteQueueArtistOneTagOneResults,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    // Printings tab is the default - unchanged existing behavior
    await expect(page.getByTestId("planeswalker-queue")).toBeVisible();
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();

    // switch to Artists - cardDocument8 has a confidently-known canonicalArtist, so this
    // also incidentally exercises the "wrong?" collapsed view via real queue data
    await page.getByRole("tab", { name: "Artists" }).click();
    await expect(page.getByTestId("vote-queue")).toBeVisible();
    await expect(page.getByAltText(cardDocument8.name)).toBeVisible();
    await expect(page.getByTestId("artist-vote-picker")).toBeVisible();
    await expect(
      page.getByTestId("artist-vote-picker").getByText("Alpha Artist")
    ).toBeVisible();

    // switch to Tags
    await page.getByRole("tab", { name: "Tags" }).click();
    await expect(page.getByTestId("vote-queue")).toBeVisible();
    await expect(page.getByAltText(cardDocument9.name)).toBeVisible();
    await expect(page.getByTestId("queue-tag-question")).toBeVisible();
    await expect(page.getByText("Does Borderless apply?")).toBeVisible();
  });

  test("artist mode's 'wrong?' affordance reveals the full picker", async ({
    page,
    network,
  }) => {
    network.use(
      printingTagQueueOneResult,
      voteQueueArtistOneTagOneResults,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    await page.getByRole("tab", { name: "Artists" }).click();

    const picker = page.getByTestId("artist-vote-picker");
    await expect(picker).toBeVisible();
    // cardDocument8 has a confidently-known canonicalArtist (Alpha Artist) with
    // canonicalArtistIsFromVoteOnly left unset (falsy) - the picker should collapse behind
    // the pre-filled name + "wrong?" link rather than soliciting a vote outright
    await expect(picker.getByText("Alpha Artist")).toBeVisible();
    const wrongLink = page.getByTestId("artist-vote-wrong-link");
    await expect(wrongLink).toBeVisible();

    await wrongLink.click();

    // clicking "wrong?" reveals the full picker
    await expect(picker.getByTestId("artist-vote-consensus")).toBeVisible();
    await expect(
      picker.getByPlaceholder("Search for an artist...")
    ).toBeVisible();
  });
});
