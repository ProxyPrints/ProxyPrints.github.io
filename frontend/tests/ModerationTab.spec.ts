import { expect } from "@playwright/test";

import {
  defaultHandlers,
  moderationDriveCardsOneResult,
  moderationDrivesTwoResults,
  moderationQueueOneResult,
  moderationRemoveCardSucceeds,
  moderationRemoveDriveSucceeds,
  questionFeedCaughtUp,
  questionFeedConfirmSuggestion,
  whoamiModerator,
  whoamiModeratorAfterDelay,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("Moderation tab gating", () => {
  test("non-moderator never sees the Moderation tab", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiSignedInNotModerator,
      questionFeedCaughtUp,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByRole("tab", { name: "Moderation" })
    ).not.toBeVisible();
  });

  test("moderator sees both tabs, Question Feed active by default", async ({
    page,
    network,
  }) => {
    network.use(whoamiModerator, questionFeedCaughtUp, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByRole("tab", { name: "Question Feed" })).toHaveClass(
      /active/
    );
    await expect(page.getByRole("tab", { name: "Moderation" })).toBeVisible();
  });

  test("the moderator flag flipping after mount does not remount the question feed", async ({
    page,
    network,
  }) => {
    let questionFeedRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/2/questionFeed/")) {
        questionFeedRequestCount += 1;
      }
    });
    network.use(
      whoamiModeratorAfterDelay,
      questionFeedConfirmSuggestion,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Anonymous-shaped first paint: the feed renders immediately, before whoami settles
    // and before the Moderation tab exists at all.
    await expect(
      page.getByTestId("question-feed-subject-art-title")
    ).toHaveText("Card 1");
    await expect(
      page.getByRole("tab", { name: "Moderation" })
    ).not.toBeVisible();

    // Snapshot the request count only after the first fetch has settled - dev mode's
    // React StrictMode double-invokes mount effects, which fires the feed's own fetch
    // twice before this point regardless of the bug under test; that's a StrictMode
    // artifact, not the remount this test exists to catch.
    const countBeforeFlip = questionFeedRequestCount;

    // whoami settles (~300ms mock delay) and isModerator flips true.
    await expect(page.getByRole("tab", { name: "Moderation" })).toBeVisible();

    // The same QuestionFeed instance must have survived the flip: same rendered question,
    // and no additional /2/questionFeed/ fetch fired from a remount.
    await expect(
      page.getByTestId("question-feed-subject-art-title")
    ).toHaveText("Card 1");
    await expect.poll(() => questionFeedRequestCount).toBe(countBeforeFlip);
  });
});

test.describe("Moderation tab: Reports sub-tab", () => {
  test("shows the pending pair, Reports is the default sub-tab", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedCaughtUp,
      moderationQueueOneResult,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("tab", { name: "Moderation" }).click();

    await expect(page.getByTestId("moderation-reports")).toBeVisible();
    await expect(
      page.getByTestId("moderation-reports-report-count")
    ).toContainText("3 reports");
  });
});

test.describe("Moderation tab: Drives sub-tab", () => {
  test("lists drives newest-first with per-drive counts", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedCaughtUp,
      moderationDrivesTwoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("tab", { name: "Moderation" }).click();
    await page.getByRole("tab", { name: "Drives" }).click();

    const rows = page.getByTestId("moderation-drives-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("Source 2");
    await expect(rows.last()).toContainText("Source 1");
  });

  test("drilling into a drive lists its cards, and Remove deletes one", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedCaughtUp,
      moderationDrivesTwoResults,
      moderationDriveCardsOneResult,
      moderationRemoveCardSucceeds,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("tab", { name: "Moderation" }).click();
    await page.getByRole("tab", { name: "Drives" }).click();
    await page
      .getByTestId("moderation-drives-row")
      .first()
      .getByTestId("moderation-drives-view-cards")
      .click();

    await expect(page.getByTestId("moderation-drives-card-list")).toBeVisible();
    const cardRow = page.getByTestId("moderation-drives-card-row");
    await expect(cardRow).toHaveCount(1);

    page.once("dialog", (dialog) => dialog.accept());
    const removeRequestPromise = page.waitForRequest((request) =>
      request.url().includes("2/moderationRemoveCard/")
    );
    await cardRow.getByTestId("moderation-drives-remove-card").click();
    await removeRequestPromise;

    await expect(cardRow).toHaveCount(0);
  });

  test("Remove drive deletes the whole drive after confirmation", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedCaughtUp,
      moderationDrivesTwoResults,
      moderationRemoveDriveSucceeds,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("tab", { name: "Moderation" }).click();
    await page.getByRole("tab", { name: "Drives" }).click();

    const rows = page.getByTestId("moderation-drives-row");
    await expect(rows).toHaveCount(2);

    page.once("dialog", (dialog) => dialog.accept());
    const removeRequestPromise = page.waitForRequest((request) =>
      request.url().includes("2/moderationRemoveDrive/")
    );
    await rows.first().getByTestId("moderation-drives-remove-drive").click();
    await removeRequestPromise;

    await expect(rows).toHaveCount(1);
  });

  test("cancelling the confirmation dialog removes nothing", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedCaughtUp,
      moderationDrivesTwoResults,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("tab", { name: "Moderation" }).click();
    await page.getByRole("tab", { name: "Drives" }).click();

    const rows = page.getByTestId("moderation-drives-row");
    page.once("dialog", (dialog) => dialog.dismiss());
    await rows.first().getByTestId("moderation-drives-remove-drive").click();

    await expect(rows).toHaveCount(2);
  });
});
