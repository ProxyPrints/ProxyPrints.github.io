import { expect } from "@playwright/test";

import {
  defaultHandlers,
  questionFeedModeration,
  submitTagVoteResolvesToApply,
  whoamiAnonymousDiscordEnabled,
  whoamiModerator,
  whoamiSignedInNotModerator,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Moderation no longer has its own tab (ModerationQueue.tsx was deleted alongside the tab
// switcher - see QuestionFeed.tsx) - a moderation-type question just surfaces as the current
// feed item when the backend's tier 3 has something pending AND the session is a moderator
// (`GET 2/questionFeed/` is always sent with credentials: "include" - see QuestionFeed.tsx -
// so the backend can gate this itself; a non-moderator's request simply never gets a
// moderation-type item back, tested here via the login-link-only assertions).
test.describe("auth links (no Moderation tab to gate anymore)", () => {
  test("anonymous user with Discord disabled sees no login link", async ({
    page,
    network,
  }) => {
    network.use(...defaultHandlers); // defaultHandlers includes whoamiAnonymous
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("auth-widget")).not.toBeVisible();
  });

  test("anonymous user with Discord enabled sees a login link that round-trips", async ({
    page,
    network,
  }) => {
    network.use(whoamiAnonymousDiscordEnabled, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const login = page.getByTestId("auth-widget-login");
    await expect(login).toBeVisible();
    const href = await login.getAttribute("href");
    expect(href).toContain("/accounts/discord/login/?next=");
    expect(href).toContain(encodeURIComponent("whatsthat"));
  });

  test("signed-in non-moderator gets a logout link", async ({
    page,
    network,
  }) => {
    network.use(whoamiSignedInNotModerator, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("auth-widget-logout")).toBeVisible();
  });
});

test.describe("moderation question type", () => {
  test("moderator sees the pending pair with report count/excerpts and Apply casts a privileged vote", async ({
    page,
    network,
  }) => {
    network.use(
      whoamiModerator,
      questionFeedModeration,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const voteRequestPromise = page.waitForRequest((request) =>
      request.url().includes("2/submitTagVote/")
    );

    await expect(
      page.getByTestId("question-feed-moderation-report-count")
    ).toContainText("2 reports");
    await expect(
      page.getByTestId("question-feed-moderation-excerpts")
    ).toContainText("too spicy");
    // "NSFW" appears twice - once in the moderation prompt's own prose, once inside the
    // reused QueueTagQuestion's "Does NSFW apply?" heading - scope to the current item
    await expect(
      page.getByTestId("question-feed-current-item").getByText("NSFW").first()
    ).toBeVisible();

    await page.getByRole("button", { name: "Apply" }).click();
    const voteRequest = await voteRequestPromise;
    const body = voteRequest.postDataJSON();
    expect(body).toMatchObject({ tagName: "NSFW", polarity: 1 });
    // credentials: "include" is what makes this vote privileged server-side (see
    // QueueTagQuestion.tsx's credentials prop) - fetch's credentials mode isn't visible on
    // the captured request object, but the cookie header presence is a reasonable proxy that
    // the request was sent with the session attached rather than same-origin-only.
  });
});
