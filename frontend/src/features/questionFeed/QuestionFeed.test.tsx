import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, localBackendURL } from "@/common/test-constants";
import { submitTagVoteResolvesToApply, tagsNoResults } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { QuestionFeed } from "./QuestionFeed";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

function renderFeed() {
  server.use(tagsNoResults);
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <QuestionFeed />
    </Provider>
  );
  return store;
}

// jsdom never actually runs the CSS reveal animation (see cardPanel.tsx's revealAnimation),
// so RevealOverlay's onAnimationEnd handler - the only thing that flips `revealed` to true -
// never fires on its own the way it would in a real browser (Playwright covers that path).
// Manually dispatching the native event it listens for unblocks the candidate grid/chips for
// every test below, same as a real animation completing.
async function revealCard() {
  const overlay = await screen.findByTestId("question-feed-reveal-overlay");
  fireEvent.animationEnd(overlay);
}

const identifyPrintingItem = {
  type: "identify_printing",
  card: {
    identifier: "card-1",
    name: "Some Card",
    mediumThumbnailUrl: "https://example.com/card1.png",
    smallThumbnailUrl: "https://example.com/card1-small.png",
  },
  candidates: [
    {
      identifier: "printing-1",
      canonicalId: "canonical-1",
      expansionCode: "abc",
      expansionName: "A Big Cardset",
      collectorNumber: "1",
      artist: "Some Artist",
      smallThumbnailUrl: "https://example.com/small1.png",
      mediumThumbnailUrl: "https://example.com/medium1.png",
      fullArt: false,
      isBorderless: false,
      frame: "2015",
      borderColor: "black",
      isShowcase: false,
      isExtendedArt: false,
      isEtched: false,
    },
    {
      identifier: "printing-2",
      canonicalId: "canonical-1",
      expansionCode: "xyz",
      expansionName: "Another Cardset",
      collectorNumber: "42",
      artist: "Another Artist",
      smallThumbnailUrl: "https://example.com/small2.png",
      mediumThumbnailUrl: "https://example.com/medium2.png",
      fullArt: true,
      isBorderless: true,
      frame: "2003",
      borderColor: "borderless",
      isShowcase: true,
      isExtendedArt: false,
      isEtched: false,
    },
  ],
  tagConfidence: {},
};

function questionFeedOnce() {
  return http.get(buildRoute("2/questionFeed/"), () =>
    HttpResponse.json(
      {
        item: identifyPrintingItem,
        remainingEstimate: { total: 1, confirmable: 0, contested: 0, fresh: 1 },
      },
      { status: 200 }
    )
  );
}

describe("QuestionFeed", () => {
  it("disables the No match button until a chip is explicitly set, then enables it", async () => {
    server.use(questionFeedOnce());
    server.use(submitTagVoteResolvesToApply);
    renderFeed();
    await revealCard();

    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    expect(noMatchButton).toBeDisabled();

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    await waitFor(() => expect(noMatchButton).not.toBeDisabled());
  });

  it("clicking No match while disabled never calls submitPrintingTag", async () => {
    server.use(questionFeedOnce());
    let submitCalled = false;
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () => {
        submitCalled = true;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: true, voteTally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    fireEvent.click(noMatchButton);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(submitCalled).toBe(false);
  });

  it("selecting a candidate auto-casts positive CardTagVotes for its own standalone attributes only", async () => {
    // first GET serves the item, every subsequent GET (post-advance) reports caught-up - a
    // second `server.use` for the same route would just override the first one outright
    // (MSW's handler stack is LIFO), so both states have to live in one handler.
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return feedFetchCount === 1
          ? HttpResponse.json(
              {
                item: identifyPrintingItem,
                remainingEstimate: {
                  total: 1,
                  confirmable: 0,
                  contested: 0,
                  fresh: 1,
                },
              },
              { status: 200 }
            )
          : HttpResponse.json(
              {
                remainingEstimate: {
                  total: 0,
                  confirmable: 0,
                  contested: 0,
                  fresh: 0,
                },
              },
              { status: 200 }
            );
      })
    );
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () =>
        HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        )
      )
    );
    const autoTagCalls: Array<{ tagName: string; polarity: number }> = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
        };
        autoTagCalls.push({ tagName: body.tagName, polarity: body.polarity });
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: body.polarity,
            netPolarity: body.polarity,
            tally: [],
          },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    const candidateButton = await screen.findByAltText("xyz 42");
    fireEvent.click(candidateButton);

    await waitFor(() =>
      expect(autoTagCalls.map((call) => call.tagName).sort()).toEqual(
        ["Borderless", "Full Art", "Showcase"].sort()
      )
    );
    expect(autoTagCalls.every((call) => call.polarity === 1)).toBe(true);
  });

  it("selecting a candidate with no true attributes casts zero auto-tag votes", async () => {
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return feedFetchCount === 1
          ? HttpResponse.json(
              {
                item: identifyPrintingItem,
                remainingEstimate: {
                  total: 1,
                  confirmable: 0,
                  contested: 0,
                  fresh: 1,
                },
              },
              { status: 200 }
            )
          : HttpResponse.json(
              {
                remainingEstimate: {
                  total: 0,
                  confirmable: 0,
                  contested: 0,
                  fresh: 0,
                },
              },
              { status: 200 }
            );
      })
    );
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () =>
        HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        )
      )
    );
    let autoTagCallCount = 0;
    server.use(
      http.post(buildRoute("2/submitTagVote/"), () => {
        autoTagCallCount += 1;
        return HttpResponse.json(
          { tagName: "x", resolvedPolarity: 1, netPolarity: 1, tally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    const candidateButton = await screen.findByAltText("abc 1");
    fireEvent.click(candidateButton);

    await waitFor(() =>
      expect(
        screen.getByText(
          "You're all caught up - no cards left to work on right now!"
        )
      ).toBeDefined()
    );
    expect(autoTagCallCount).toBe(0);
  });

  it("shows a distinct error state (not 'all caught up') on a fetch failure, with a working retry", async () => {
    let callCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        callCount += 1;
        return callCount === 1
          ? HttpResponse.json(
              { name: "Backend Error", message: "boom" },
              { status: 500 }
            )
          : HttpResponse.json(
              {
                item: identifyPrintingItem,
                remainingEstimate: {
                  total: 1,
                  confirmable: 0,
                  contested: 0,
                  fresh: 1,
                },
              },
              { status: 200 }
            );
      })
    );
    renderFeed();

    expect(await screen.findByTestId("question-feed-error")).toBeVisible();
    expect(screen.queryByTestId("question-feed-empty")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "You're all caught up - no cards left to work on right now!"
      )
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("question-feed-retry"));

    await waitFor(() =>
      expect(
        screen.getByTestId("question-feed-current-item")
      ).toBeInTheDocument()
    );
    expect(callCount).toBe(2);
  });

  it("badges a confirm_suggestion item as a suggested match", async () => {
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              ...identifyPrintingItem,
              type: "confirm_suggestion",
              suggestedPrinting: identifyPrintingItem.candidates[0],
            },
            remainingEstimate: {
              total: 1,
              confirmable: 1,
              contested: 0,
              fresh: 0,
            },
          },
          { status: 200 }
        )
      )
    );
    renderFeed();
    await revealCard();

    expect(
      await screen.findByTestId("question-feed-tier-badge")
    ).toHaveTextContent("Suggested match");
  });

  it("badges a fresh/contested identify_printing item as needing identification", async () => {
    server.use(questionFeedOnce());
    renderFeed();
    await revealCard();

    expect(
      await screen.findByTestId("question-feed-tier-badge")
    ).toHaveTextContent("Needs identification");
  });

  it("shows a submitting indicator only on the tapped candidate, not the others or 'No match'", async () => {
    server.use(questionFeedOnce());
    let resolveSubmit: () => void = () => undefined;
    const submitPromise = new Promise<void>((resolve) => {
      resolveSubmit = resolve;
    });
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), async () => {
        await submitPromise;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    const tappedCandidate = await screen.findByAltText("xyz 42");
    fireEvent.click(tappedCandidate);

    await waitFor(() =>
      expect(
        screen.getByTestId("question-feed-candidate-submitting-printing-2")
      ).toBeInTheDocument()
    );
    expect(
      screen.queryByTestId("question-feed-candidate-submitting-printing-1")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("question-feed-no-match-submitting")
    ).not.toBeInTheDocument();

    resolveSubmit();
    await waitFor(() =>
      expect(
        screen.queryByTestId("question-feed-candidate-submitting-printing-2")
      ).not.toBeInTheDocument()
    );
  });

  it("degrades gracefully instead of showing 'undefined cards' when the backend still returns the legacy remainingEstimate:number shape", async () => {
    // regression test - frontend and backend deploy independently, so this frontend build can
    // briefly be live against a not-yet-deployed backend still returning a plain number here
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          { item: identifyPrintingItem, remainingEstimate: 3 },
          { status: 200 }
        )
      )
    );
    server.use(submitTagVoteResolvesToApply);
    renderFeed();
    await revealCard();

    const headline = await screen.findByTestId("question-feed-headline");
    expect(headline.textContent).toBe("Still need help with: 3 cards");
    expect(headline.textContent).not.toMatch(/undefined/);
  });

  it("shows the rate-limit banner (not a toast) when a printing vote is rejected with 429", async () => {
    server.use(questionFeedOnce());
    server.use(submitTagVoteResolvesToApply);
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () =>
        HttpResponse.json(
          {
            name: "Rate limited",
            message: "Too many printing tag submissions - please slow down.",
          },
          { status: 429 }
        )
      )
    );
    const store = renderFeed();
    await revealCard();

    // the "No match" button stays disabled until a chip is explicitly set - see the dedicated
    // test for that behavior above
    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    await waitFor(() => expect(noMatchButton).not.toBeDisabled());
    fireEvent.click(noMatchButton);

    await waitFor(() =>
      expect(screen.getByTestId("question-feed-rate-limited")).toBeDefined()
    );
    expect(
      screen.getByTestId("question-feed-rate-limited").textContent
    ).toMatch(/take a short breather/i);
    expect(Object.values(store.getState().toasts.notifications)).toHaveLength(
      0
    );
  });

  it("surfaces the backend's own message in a toast for a non-429 printing vote failure", async () => {
    server.use(questionFeedOnce());
    server.use(submitTagVoteResolvesToApply);
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () =>
        HttpResponse.json(
          {
            name: "Bad Request",
            message: "This card has already been resolved.",
          },
          { status: 400 }
        )
      )
    );
    const store = renderFeed();
    await revealCard();

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    await waitFor(() => expect(noMatchButton).not.toBeDisabled());
    fireEvent.click(noMatchButton);

    await waitFor(() => {
      const notifications = Object.values(
        store.getState().toasts.notifications
      );
      expect(notifications).toHaveLength(1);
      expect(notifications[0].name).toBe("Bad Request");
      expect(notifications[0].message).toBe(
        "This card has already been resolved."
      );
    });
    expect(screen.queryByTestId("question-feed-rate-limited")).toBeNull();
  });

  it("clears a stale rate-limit banner once the next item loads", async () => {
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return HttpResponse.json(
          {
            item: {
              ...identifyPrintingItem,
              card: {
                ...identifyPrintingItem.card,
                identifier: `card-${feedFetchCount}`,
              },
            },
            remainingEstimate: {
              total: 2,
              confirmable: 0,
              contested: 0,
              fresh: 2,
            },
          },
          { status: 200 }
        );
      })
    );
    server.use(submitTagVoteResolvesToApply);
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), () =>
        HttpResponse.json(
          { name: "Rate limited", message: "slow down" },
          { status: 429 }
        )
      )
    );
    renderFeed();
    await revealCard();
    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    await waitFor(() => expect(noMatchButton).not.toBeDisabled());
    fireEvent.click(noMatchButton);
    await waitFor(() =>
      expect(screen.getByTestId("question-feed-rate-limited")).toBeDefined()
    );

    // Skip advances to a new item even while rate-limited (only vote submission is affected)
    fireEvent.click(screen.getByText("Skip"));
    await waitFor(() =>
      expect(screen.queryByTestId("question-feed-rate-limited")).toBeNull()
    );
  });
});
