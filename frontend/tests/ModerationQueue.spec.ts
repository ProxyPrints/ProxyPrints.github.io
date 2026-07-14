import { expect } from "@playwright/test";

import {
  defaultHandlers,
  moderationQueueOneResult,
  submitTagVoteResolvesToApply,
  whoamiAnonymousDiscordEnabled,
  whoamiModerator,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

test.describe("moderation tab gating and auth links", () => {
  test("anonymous user with Discord disabled sees neither login link nor Moderation tab", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers); // defaultHandlers includes whoamiAnonymous
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(page.getByRole("tab", { name: "Printings" })).toBeVisible();
    await expect(page.getByTestId("auth-widget")).not.toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Moderation" })
    ).not.toBeVisible();
  });

  test("anonymous user with Discord enabled sees a login link that round-trips", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymousDiscordEnabled, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "printingQueue");

    const login = page.getByTestId("auth-widget-login");
    await expect(login).toBeVisible();
    const href = await login.getAttribute("href");
    expect(href).toContain("/accounts/discord/login/?next=");
    expect(href).toContain(encodeURIComponent("printingQueue"));
    await expect(
      page.getByRole("tab", { name: "Moderation" })
    ).not.toBeVisible();
  });

  test("signed-in non-moderator gets a logout link but no Moderation tab", async ({
    page,
    network,
  }) => {
    network.use(whoamiSignedInNotModerator, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "printingQueue");

    await expect(page.getByTestId("auth-widget-logout")).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Moderation" })
    ).not.toBeVisible();
  });
});

test.describe("moderation queue flow", () => {
  test("moderator reviews an item and Approve casts a privileged vote and advances", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      moderationQueueOneResult,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    // capture what Approve actually posts
    const voteRequestPromise = page.waitForRequest((request) =>
      request.url().includes("2/submitTagVote/")
    );

    await page.getByRole("tab", { name: "Moderation" }).click();
    const item = page.getByTestId("moderation-queue-current-item");
    await expect(item).toBeVisible();
    await expect(
      page.getByTestId("moderation-queue-report-count")
    ).toContainText("3 reports");
    await expect(page.getByTestId("moderation-queue-excerpts")).toContainText(
      "way too spicy"
    );

    await page.getByTestId("moderation-queue-approve").click();
    const voteRequest = await voteRequestPromise;
    expect(voteRequest.postDataJSON()).toMatchObject({
      tagName: "NSFW",
      polarity: 1,
    });

    // single-item queue: approving advances to the empty state
    await expect(page.getByTestId("moderation-queue-empty")).toBeVisible();
  });

  test("Reject posts polarity -1", async ({ page, network }) => {
    network.use(
      whoamiModerator,
      moderationQueueOneResult,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "printingQueue");

    const voteRequestPromise = page.waitForRequest((request) =>
      request.url().includes("2/submitTagVote/")
    );
    await page.getByRole("tab", { name: "Moderation" }).click();
    await expect(
      page.getByTestId("moderation-queue-current-item")
    ).toBeVisible();
    await page.getByTestId("moderation-queue-reject").click();
    const voteRequest = await voteRequestPromise;
    expect(voteRequest.postDataJSON()).toMatchObject({
      tagName: "NSFW",
      polarity: -1,
    });
  });
});
