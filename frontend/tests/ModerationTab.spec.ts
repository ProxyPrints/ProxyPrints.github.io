import { expect } from "@playwright/test";

import {
  defaultHandlers,
  moderationDriveCardsOneResult,
  moderationDrivesTwoResults,
  moderationQueueOneResult,
  moderationRemoveCardSucceeds,
  moderationRemoveDriveSucceeds,
  questionFeedCaughtUp,
  whoamiModerator,
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
