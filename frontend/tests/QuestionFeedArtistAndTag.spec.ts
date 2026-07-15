import { expect } from "@playwright/test";

import { cardDocument8, cardDocument9 } from "@/common/test-constants";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  defaultHandlers,
  questionFeedArtist,
  questionFeedArtistConfidentlyKnown,
  questionFeedTag,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// One Playwright flow per question type, per the queue-redesign task spec's TESTS
// requirement - artist and tag types reuse ArtistVotePicker/QueueTagQuestion directly (no
// forks), so these assert the unified feed renders them correctly, not the pickers'
// internals (already covered by ArtistVotePicker.spec.ts/TagVotePicker.spec.ts elsewhere).
test.describe("question feed - artist question type", () => {
  test("renders ArtistVotePicker for an artist-type item", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtist,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByAltText(cardDocument8.name)).toBeVisible();
    await expect(page.getByTestId("artist-vote-picker")).toBeVisible();
    await expect(
      page.getByPlaceholder("Search for an artist...")
    ).toBeVisible();
  });

  test("a confidently-known artist collapses behind a 'wrong?' link", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtistConfidentlyKnown,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const picker = page.getByTestId("artist-vote-picker");
    await expect(picker.getByText("Alpha Artist")).toBeVisible();
    const wrongLink = page.getByTestId("artist-vote-wrong-link");
    await expect(wrongLink).toBeVisible();

    await wrongLink.click();
    await expect(picker.getByTestId("artist-vote-consensus")).toBeVisible();
    await expect(
      picker.getByPlaceholder("Search for an artist...")
    ).toBeVisible();
  });
});

test.describe("question feed - tag question type", () => {
  test("renders QueueTagQuestion for a tag-type item", async ({
    page,
    network,
  }) => {
    network.use(questionFeedTag, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByAltText(cardDocument9.name)).toBeVisible();
    await expect(page.getByTestId("queue-tag-question")).toBeVisible();
    await expect(page.getByText("Does Borderless apply?")).toBeVisible();
  });
});
