import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
// so MysteryCard's onAnimationEnd handler - the only thing that flips `revealed` to true -
// never fires on its own the way it would in a real browser (Playwright covers that path).
// Manually dispatching the native event it listens for unblocks the candidate grid/chips for
// every test below, same as a real animation completing.
async function revealCard() {
  const overlay = await screen.findByTestId("question-feed-reveal-overlay");
  // WTC rebuild (2026-07-24, SPEC-wtc-rebuild.md, owner ruling 1) - a regression guard for
  // the overlay's own "?" glyph: cardPanel.tsx's shared `MysteryCard` now renders it as a
  // plain, token-coloured `<span data-testid="mystery-card-glyph">` rather than the old
  // gold-gradient `whatsthat-mark.svg` `<img>` (that asset's fill is baked-in SVG, not
  // retintable onto the `--wtc-mystery-glyph` token - see that component's own comment).
  // Asserted here rather than only in Playwright since every caller of this helper already
  // exercises the overlay's pre-reveal moment; this fires before the fade
  // (fireEvent.animationEnd below) removes it from the DOM.
  expect(within(overlay).getByTestId("mystery-card-glyph")).toHaveTextContent(
    "?"
  );
  fireEvent.animationEnd(overlay);
  await waitFor(() =>
    expect(
      screen.queryByTestId("question-feed-reveal-overlay")
    ).not.toBeInTheDocument()
  );
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
  it("the attribute-chip filter is collapsed by default, and 'None of these' works without touching it", async () => {
    server.use(questionFeedOnce());
    renderFeed();
    await revealCard();

    expect(
      screen.queryByTestId("attribute-chip-panel")
    ).not.toBeInTheDocument();
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    expect(noMatchButton).not.toBeDisabled();

    fireEvent.click(screen.getByTestId("question-feed-filter-toggle"));
    expect(
      await screen.findByTestId("attribute-chip-Full Art")
    ).toBeInTheDocument();
  });

  it("clicking 'None of these' submits a no-match printing vote", async () => {
    server.use(questionFeedOnce());
    let submittedIsNoMatch: boolean | undefined;
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        const body = (await request.json()) as { isNoMatch?: boolean };
        submittedIsNoMatch = body.isNoMatch;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: true, voteTally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    fireEvent.click(await screen.findByTestId("question-feed-no-match"));
    await waitFor(() => expect(submittedIsNoMatch).toBe(true));
  });

  it("selecting a candidate auto-casts positive CardTagVotes for every attribute it derives, standalone plus matched exclusion-group values", async () => {
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
        ["Borderless", "Full Art", "Modern Border", "Showcase"].sort()
      )
    );
    // printing-2's borderColor is "borderless" - outside the Black/White/Silver taxonomy, so
    // no Border Color chip auto-fires for it (see attributeChips.test.ts's
    // getOpenExclusionGroups coverage - this is exactly what routes the feed to Level 3
    // instead of advancing, covered separately in QuestionFeed.spec.ts).
    expect(autoTagCalls.map((call) => call.tagName)).not.toContain(
      "Black Border"
    );
    expect(autoTagCalls.every((call) => call.polarity === 1)).toBe(true);
  });

  it("selecting a candidate derives only its matched exclusion-group chips when every standalone attribute is false", async () => {
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
    const autoTagCalls: string[] = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as { tagName: string };
        autoTagCalls.push(body.tagName);
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: 1,
            netPolarity: 1,
            tally: [],
          },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    const candidateButton = await screen.findByAltText("abc 1");
    fireEvent.click(candidateButton);

    // printing-1's border color and frame both match a taxonomy chip, so nothing is left
    // open - the feed advances straight to caught-up (no Level 3) once the two matched
    // exclusion-group votes are cast.
    await waitFor(() =>
      expect(
        screen.getByText(
          "You're all caught up - no cards left to work on right now!"
        )
      ).toBeDefined()
    );
    expect(autoTagCalls.sort()).toEqual(
      ["Black Border", "Modern Border"].sort()
    );
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

  it("shows the suggested printing's own reference image on Level 1 (regression: dropped when Level 1 was introduced in #49)", async () => {
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

    const referenceImage = within(
      await screen.findByTestId("question-feed-level1-reference-image")
    ).getByRole("img");
    expect(referenceImage).toHaveAttribute(
      "src",
      identifyPrintingItem.candidates[0].mediumThumbnailUrl
    );
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

    const stats = await screen.findByTestId("question-feed-stats");
    expect(stats.textContent).toBe("0 ready · 3 in catalog · 0 contested");
    expect(stats.textContent).not.toMatch(/undefined/);
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

    const noMatchButton = await screen.findByTestId("question-feed-no-match");
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

    const noMatchButton = await screen.findByTestId("question-feed-no-match");
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

  // The seam ParticipationGraph.test.tsx's own in-session green-dot tests can't see: those
  // dispatch `recordSessionContribution()` directly and prove the homepage dot responds to it,
  // but never prove a real vote is what fires that dispatch. THIS test is the other half - it
  // proves `bumpSessionCount()` (the single choke point every successful vote in this feed
  // already flows through) actually dispatches `recordSessionContribution()` into the real
  // store, via a real vote-casting call (`APISubmitPrintingTag`), not a mocked one. If a future
  // refactor drops that dispatch, or `bumpSessionCount` stops being the choke point, this is the
  // test that fails - and its name says what broke.
  it("casting a vote turns the homepage's in-session 'you contributed' dot green - a successful printing-tag vote dispatches recordSessionContribution", async () => {
    server.use(questionFeedOnce());
    let submittedIsNoMatch: boolean | undefined;
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        const body = (await request.json()) as { isNoMatch?: boolean };
        submittedIsNoMatch = body.isNoMatch;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: true, voteTally: [] },
          { status: 200 }
        );
      })
    );
    const store = renderFeed();
    await revealCard();

    expect(store.getState().sessionContribution.hasContributedThisSession).toBe(
      false
    );

    fireEvent.click(await screen.findByTestId("question-feed-no-match"));
    await waitFor(() => expect(submittedIsNoMatch).toBe(true));

    await waitFor(() =>
      expect(
        store.getState().sessionContribution.hasContributedThisSession
      ).toBe(true)
    );
  });

  it("a FAILED printing-tag vote does NOT turn the homepage's in-session dot green - recordSessionContribution is only dispatched on success", async () => {
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

    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    fireEvent.click(noMatchButton);

    // Wait on the failure's own observable side-effect (the existing toast assertion pattern
    // above) so this assertion isn't racing the rejected promise.
    await waitFor(() => {
      const notifications = Object.values(
        store.getState().toasts.notifications
      );
      expect(notifications).toHaveLength(1);
    });
    expect(store.getState().sessionContribution.hasContributedThisSession).toBe(
      false
    );
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
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
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

  it("resets stale chip filter state when the next item shares the same card identifier and type", async () => {
    // Real-device regression guard: chipStates/revealed/etc used to reset via a separate
    // useEffect keyed on [item?.card.identifier, item?.type] - which silently skips the reset
    // whenever two consecutive feed items share both values (the same card can carry more than
    // one pending question, or the same question can be re-served). A chip left "positive" from
    // the previous item then filters the new item's candidates against an unrelated attribute,
    // which can hide every candidate in the grid until the user happens to touch a chip
    // themselves (the only other thing that ever updates chipStates). This item's card
    // identifier and type are IDENTICAL between the two fetches on purpose, to reproduce that
    // exact condition.
    let feedFetchCount = 0;
    const itemOneCandidates = identifyPrintingItem.candidates; // printing-1 (fullArt: false), printing-2 (fullArt: true)
    const itemTwoCandidates = [
      {
        ...identifyPrintingItem.candidates[0],
        identifier: "printing-3",
        expansionCode: "def",
        collectorNumber: "3",
        fullArt: false,
      },
      {
        ...identifyPrintingItem.candidates[0],
        identifier: "printing-4",
        expansionCode: "ghi",
        collectorNumber: "4",
        fullArt: false,
      },
    ];
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return HttpResponse.json(
          {
            item: {
              ...identifyPrintingItem,
              candidates:
                feedFetchCount === 1 ? itemOneCandidates : itemTwoCandidates,
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
    renderFeed();
    await revealCard();

    // expand the filter and set "Full Art" positive - narrows item 1's grid to printing-2 only
    fireEvent.click(screen.getByTestId("question-feed-filter-toggle"));
    fireEvent.click(await screen.findByTestId("attribute-chip-Full Art-yes"));
    await waitFor(() =>
      expect(screen.queryByTestId("attribute-chip-Full Art")).toHaveAttribute(
        "data-chip-state",
        "positive"
      )
    );
    await waitFor(() =>
      expect(screen.queryByAltText("abc 1")).not.toBeInTheDocument()
    ); // printing-1, filtered out
    expect(screen.getByAltText("xyz 42")).toBeInTheDocument(); // printing-2, matches

    fireEvent.click(screen.getByTestId("question-feed-skip"));
    await revealCard();

    // both of item 2's candidates are fullArt: false - if the stale "Full Art: positive" state
    // survived, neither would render, reproducing the reported empty-grid symptom.
    expect(await screen.findByAltText("def 3")).toBeInTheDocument();
    expect(screen.getByAltText("ghi 4")).toBeInTheDocument();
    // the filter panel itself resets closed too, same as any other fresh item
    expect(
      screen.queryByTestId("attribute-chip-panel")
    ).not.toBeInTheDocument();
  });

  // Issue #503 (WTC phase C2) / #524 - wiring the illustration-grouped grid (C1) to
  // /2/submitIllustrationVote/.
  describe("illustration grouping (C2 - vote wiring)", () => {
    const sharedIllustrationId = "11111111-1111-1111-1111-111111111111";
    const groupedItem = {
      ...identifyPrintingItem,
      candidates: [
        {
          ...identifyPrintingItem.candidates[0],
          identifier: "printing-1",
          illustrationId: sharedIllustrationId,
        },
        {
          ...identifyPrintingItem.candidates[1],
          identifier: "printing-2",
          illustrationId: sharedIllustrationId,
        },
        {
          ...identifyPrintingItem.candidates[0],
          identifier: "printing-3",
          expansionCode: "def",
          collectorNumber: "3",
          illustrationId: null,
        },
      ],
    };

    function groupedQuestionFeedOnce() {
      return http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: groupedItem,
            remainingEstimate: {
              total: 1,
              confirmable: 0,
              contested: 0,
              fresh: 1,
            },
          },
          { status: 200 }
        )
      );
    }

    it("selecting a candidate inside an illustration group submits ONE illustrationId to /2/submitIllustrationVote/, never a printing list", async () => {
      server.use(groupedQuestionFeedOnce());
      let illustrationVoteBody: Record<string, unknown> | undefined;
      let printingTagCalled = false;
      server.use(
        http.post(
          buildRoute("2/submitIllustrationVote/"),
          async ({ request }) => {
            illustrationVoteBody = (await request.json()) as Record<
              string,
              unknown
            >;
            return HttpResponse.json(
              {
                illustrationId: sharedIllustrationId,
                isUnknown: false,
                printingVoteCast: false,
                artistVoteCast: true,
              },
              { status: 200 }
            );
          }
        )
      );
      server.use(
        http.post(buildRoute("2/submitPrintingTag/"), () => {
          printingTagCalled = true;
          return HttpResponse.json(
            { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
            { status: 200 }
          );
        })
      );
      renderFeed();
      await revealCard();

      const group = await screen.findByTestId(
        "question-feed-illustration-group"
      );
      const tile = within(group).getByAltText("abc 1");
      fireEvent.click(tile);

      await waitFor(() => expect(illustrationVoteBody).toBeDefined());
      expect(illustrationVoteBody).toMatchObject({
        identifier: groupedItem.card.identifier,
        illustrationId: sharedIllustrationId,
        isUnknown: false,
      });
      expect(illustrationVoteBody).not.toHaveProperty("printingIdentifier");
      expect(printingTagCalled).toBe(false);
    });

    it("selecting an ungrouped candidate (null illustrationId) still submits through /2/submitPrintingTag/ unchanged", async () => {
      server.use(groupedQuestionFeedOnce());
      let printingTagBody: Record<string, unknown> | undefined;
      let illustrationVoteCalled = false;
      server.use(
        http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
          printingTagBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json(
            { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
            { status: 200 }
          );
        })
      );
      server.use(
        http.post(buildRoute("2/submitIllustrationVote/"), () => {
          illustrationVoteCalled = true;
          return HttpResponse.json(
            {
              illustrationId: null,
              isUnknown: false,
              printingVoteCast: false,
              artistVoteCast: false,
            },
            { status: 200 }
          );
        })
      );
      renderFeed();
      await revealCard();

      const ungroupedGrid = await screen.findByTestId(
        "question-feed-candidate-grid-ungrouped"
      );
      fireEvent.click(within(ungroupedGrid).getByAltText("def 3"));

      await waitFor(() => expect(printingTagBody).toBeDefined());
      expect(printingTagBody).toMatchObject({
        identifier: groupedItem.card.identifier,
        printingIdentifier: "printing-3",
      });
      expect(illustrationVoteCalled).toBe(false);
    });

    it("renders exactly one representative tile per illustration group, preferring a member with an art crop; ungrouped tiles are unaffected", async () => {
      const withArtCrop = {
        ...groupedItem,
        candidates: [
          {
            ...groupedItem.candidates[0],
            artCropUrl: "https://example.com/art-crop-1.png",
          },
          { ...groupedItem.candidates[1], artCropUrl: null },
          groupedItem.candidates[2],
        ],
      };
      server.use(
        http.get(buildRoute("2/questionFeed/"), () =>
          HttpResponse.json(
            {
              item: withArtCrop,
              remainingEstimate: {
                total: 1,
                confirmable: 0,
                contested: 0,
                fresh: 1,
              },
            },
            { status: 200 }
          )
        )
      );
      renderFeed();
      await revealCard();

      const group = await screen.findByTestId(
        "question-feed-illustration-group"
      );
      expect(within(group).getByAltText("abc 1")).toHaveAttribute(
        "src",
        "https://example.com/art-crop-1.png"
      );
      expect(within(group).queryByAltText("xyz 42")).not.toBeInTheDocument();
      expect(
        within(group).getByText("Same illustration - 2 printings")
      ).toBeInTheDocument();

      const ungroupedGrid = await screen.findByTestId(
        "question-feed-candidate-grid-ungrouped"
      );
      expect(within(ungroupedGrid).getByAltText("def 3")).toHaveAttribute(
        "src",
        groupedItem.candidates[2].mediumThumbnailUrl
      );
    });

    it("falls back to the group's first member when no member has an art crop", async () => {
      server.use(groupedQuestionFeedOnce());
      renderFeed();
      await revealCard();

      const group = await screen.findByTestId(
        "question-feed-illustration-group"
      );
      expect(within(group).getByAltText("abc 1")).toHaveAttribute(
        "src",
        groupedItem.candidates[0].mediumThumbnailUrl
      );
      expect(within(group).queryByAltText("xyz 42")).not.toBeInTheDocument();
    });

    it("picks whichever group member has an art crop regardless of position, and still submits the group's shared illustrationId", async () => {
      const artCropOnSecondMember = {
        ...groupedItem,
        candidates: [
          { ...groupedItem.candidates[0], artCropUrl: null },
          {
            ...groupedItem.candidates[1],
            artCropUrl: "https://example.com/art-crop-2.png",
          },
          groupedItem.candidates[2],
        ],
      };
      server.use(
        http.get(buildRoute("2/questionFeed/"), () =>
          HttpResponse.json(
            {
              item: artCropOnSecondMember,
              remainingEstimate: {
                total: 1,
                confirmable: 0,
                contested: 0,
                fresh: 1,
              },
            },
            { status: 200 }
          )
        )
      );
      let illustrationVoteBody: Record<string, unknown> | undefined;
      server.use(
        http.post(
          buildRoute("2/submitIllustrationVote/"),
          async ({ request }) => {
            illustrationVoteBody = (await request.json()) as Record<
              string,
              unknown
            >;
            return HttpResponse.json(
              {
                illustrationId: sharedIllustrationId,
                isUnknown: false,
                printingVoteCast: false,
                artistVoteCast: true,
              },
              { status: 200 }
            );
          }
        )
      );
      renderFeed();
      await revealCard();

      const group = await screen.findByTestId(
        "question-feed-illustration-group"
      );
      const tile = within(group).getByAltText("xyz 42");
      expect(tile).toHaveAttribute("src", "https://example.com/art-crop-2.png");
      expect(within(group).queryByAltText("abc 1")).not.toBeInTheDocument();

      fireEvent.click(tile);

      await waitFor(() => expect(illustrationVoteBody).toBeDefined());
      expect(illustrationVoteBody).toMatchObject({
        identifier: groupedItem.card.identifier,
        illustrationId: sharedIllustrationId,
      });
    });
  });
});
