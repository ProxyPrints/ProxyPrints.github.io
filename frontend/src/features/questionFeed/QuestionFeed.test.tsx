import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import {
  cardDocument9,
  localBackend,
  localBackendURL,
} from "@/common/test-constants";
import { AUTO_DERIVED_TAG_VOTE_SURFACE } from "@/features/attributeChips/attributeChips";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  questionFeedBorder,
  reportCardSuccess,
  submitArtistVoteResolvesToCanonicalArtist1,
  submitTagVoteResolvesToApply,
  tagsNoResults,
} from "@/mocks/handlers";
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
  it("the attribute-chip filter is shown automatically for identify_printing questions, and 'None of these' works without touching it", async () => {
    server.use(questionFeedOnce());
    renderFeed();
    await revealCard();

    expect(
      await screen.findByTestId("attribute-chip-Full Art")
    ).toBeInTheDocument();
    const noMatchButton = await screen.findByTestId("question-feed-no-match");
    expect(noMatchButton).not.toBeDisabled();

    fireEvent.click(screen.getByTestId("question-feed-filter-toggle"));
    expect(
      screen.queryByTestId("attribute-chip-panel")
    ).not.toBeInTheDocument();
  });

  it("identify_printing's contextual search reaches a printing outside the machine-ranked shortlist", async () => {
    server.use(questionFeedOnce());
    // Mirrors what get_ranked_printing_candidates actually emits (PrintingCandidate) - the
    // shortlist's own two candidates (printing-1/printing-2) never include this one, standing
    // in for a printing the CANDIDATE_RESULT_LIMIT-capped shortlist cut off.
    const outsideGridCandidate = {
      identifier: "printing-outside-grid",
      canonicalId: "canonical-1",
      expansionCode: "out",
      expansionName: "Outside The Grid",
      collectorNumber: "999",
      artist: "Some Artist",
      smallThumbnailUrl: "https://example.com/small-outside.png",
      mediumThumbnailUrl: "https://example.com/medium-outside.png",
      fullArt: false,
      isBorderless: false,
      frame: "2015",
      borderColor: "black",
      isShowcase: false,
      isExtendedArt: false,
      isEtched: false,
    };
    let submittedIdentifier: string | undefined;
    server.use(
      http.post(buildRoute("2/printingCandidates/"), () =>
        HttpResponse.json({ results: [outsideGridCandidate] }, { status: 200 })
      ),
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        const body = (await request.json()) as {
          printingIdentifier?: string;
        };
        submittedIdentifier = body.printingIdentifier;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    expect(screen.queryByAltText("out 999")).not.toBeInTheDocument();

    const searchInput = await screen.findByTestId(
      "question-feed-printing-search"
    );
    fireEvent.change(searchInput, { target: { value: "outside" } });

    const candidateTile = await screen.findByAltText("out 999");
    // A search replaces the shortlist grid rather than supplementing it.
    expect(screen.queryByAltText("xyz 42")).not.toBeInTheDocument();

    fireEvent.click(candidateTile);
    await waitFor(() =>
      expect(submittedIdentifier).toBe("printing-outside-grid")
    );
  });

  it("identify_printing's contextual search is present even with no machine-ranked shortlist at all (shape d)", async () => {
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: { ...identifyPrintingItem, candidates: [] },
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

    expect(
      await screen.findByTestId("question-feed-printing-search")
    ).toBeInTheDocument();
  });

  it("renders the shared report panel for the question's card and submits through the existing report flow", async () => {
    server.use(questionFeedOnce(), reportCardSuccess);
    renderFeed();

    // The WTC page reuses the card-detail modal's ReportCardPanel unchanged - the button
    // sits in the QPanel adjacent to the question's own action row (below Skip etc.), and
    // its accessible name is the component's visible label, same as on the legacy page.
    const reportButton = await screen.findByTestId("report-card-button");
    expect(reportButton).toBeInTheDocument();
    expect(reportButton).toHaveTextContent("Report this card");

    fireEvent.click(reportButton);
    expect(screen.getByTestId("report-card-panel")).toBeInTheDocument();
    expect(screen.getByTestId("report-chip-low_quality")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("report-chip-low_quality"));
    await waitFor(() =>
      expect(screen.getByTestId("report-card-thanks")).toBeInTheDocument()
    );
  });

  it("the feed's filter panel hides exclusion-group siblings of an explicit positive (context-dependent disqualification)", async () => {
    server.use(
      questionFeedOnce(),
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
        };
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: null,
            netPolarity: body.polarity,
            tally: [],
          },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();
    await screen.findByTestId("attribute-chip-Black Border");

    fireEvent.click(screen.getByTestId("attribute-chip-Black Border-yes"));
    await waitFor(() =>
      expect(
        screen
          .getByTestId("attribute-chip-Black Border")
          .getAttribute("data-chip-state")
      ).toBe("positive")
    );
    // the contradicted siblings are pruned from the feed's panel, not just dimmed
    expect(screen.queryByTestId("attribute-chip-White Border")).toBeNull();
    expect(screen.queryByTestId("attribute-chip-Silver Border")).toBeNull();
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
    const autoTagCalls: Array<{
      tagName: string;
      polarity: number;
      voteSurface?: string;
    }> = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
          voteSurface?: string;
        };
        autoTagCalls.push({
          tagName: body.tagName,
          polarity: body.polarity,
          voteSurface: body.voteSurface,
        });
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
    // printing-2's borderColor is "borderless" - none of Black/White/Silver match it, so no
    // "Black Border" auto-tag is derived (Borderless is its own Border Color chip instead) -
    // see attributeChips.test.ts's getAutoTagChips coverage.
    expect(autoTagCalls.map((call) => call.tagName)).not.toContain(
      "Black Border"
    );
    expect(autoTagCalls.every((call) => call.polarity === 1)).toBe(true);
    // issue #790: a candidate-pick auto-tag carries its own surface, distinct from
    // "question-feed" (which is reserved for a voter's own deliberate tag-question answer),
    // so the backend can recast these as VoteSource.IMPLICIT.
    expect(
      autoTagCalls.every(
        (call) => call.voteSurface === AUTO_DERIVED_TAG_VOTE_SURFACE
      )
    ).toBe(true);
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
    const autoTagVoteSurfaces: Array<string | undefined> = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          voteSurface?: string;
        };
        autoTagCalls.push(body.tagName);
        autoTagVoteSurfaces.push(body.voteSurface);
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
    expect(
      autoTagVoteSurfaces.every(
        (surface) => surface === AUTO_DERIVED_TAG_VOTE_SURFACE
      )
    ).toBe(true);
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

  it("confirm_suggestion's own question renders no chip panel and no candidate grid (composition contract)", async () => {
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
      await screen.findByTestId("question-feed-suggestion-yes")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("attribute-chip-panel")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("question-feed-candidate-grid-ungrouped")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("question-feed-illustration-groups")
    ).not.toBeInTheDocument();
  });

  it("'Not this art' summons the candidate-grid identification question, where a rejected suggestion stays reachable as a de-emphasised, re-selectable tile (issue #748)", async () => {
    // #748 - rejecting the suggested printing must not drop it from the surface: the
    // suggestion slot gives way to the "you said not this one" context, and the candidate
    // grid gains the rejected candidate as a de-emphasised (`data-rejected`) tile that stays
    // fully selectable - tapping it re-casts the candidate as a real pick.
    const confirmSuggestionItem = {
      ...identifyPrintingItem,
      type: "confirm_suggestion",
      suggestedPrinting: identifyPrintingItem.candidates[0],
    };
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: confirmSuggestionItem,
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
    let submittedIdentifier: string | undefined;
    server.use(
      http.post(buildRoute("2/submitPrintingTag/"), async ({ request }) => {
        const body = (await request.json()) as {
          printingIdentifier?: string;
        };
        submittedIdentifier = body.printingIdentifier;
        return HttpResponse.json(
          { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
          { status: 200 }
        );
      })
    );
    renderFeed();
    await revealCard();

    // Before "Not this art": no candidate grid at all (composition contract, tested above).
    expect(
      screen.queryByTestId("question-feed-candidate-grid-ungrouped")
    ).not.toBeInTheDocument();

    fireEvent.click(
      await screen.findByTestId("question-feed-suggestion-not-this-art")
    );
    expect(
      await screen.findByTestId("question-feed-rejected-context")
    ).toHaveTextContent("You said: not");
    const grid = await screen.findByTestId(
      "question-feed-candidate-grid-ungrouped"
    );
    expect(within(grid).getAllByRole("button")).toHaveLength(2);
    const rejectedNote = await screen.findByTestId(
      "question-feed-rejected-tile-note"
    );
    expect(rejectedNote).toHaveTextContent("you said no");
    const rejectedTile = rejectedNote.closest("button");
    expect(rejectedTile).not.toBeNull();
    expect(rejectedTile!.getAttribute("data-rejected")).toBe("true");

    // The reconsider path: tapping the rejected tile casts it as a real pick.
    fireEvent.click(rejectedTile!);
    await waitFor(() => expect(submittedIdentifier).toBe("printing-1"));
  });

  it("'Same art, but...' casts the suggested printing's illustration vote on tap, then summons the border/frame attribute chips", async () => {
    const suggested = {
      ...identifyPrintingItem.candidates[0],
      illustrationId: "22222222-2222-2222-2222-222222222222",
    };
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: {
              ...identifyPrintingItem,
              type: "confirm_suggestion",
              suggestedPrinting: suggested,
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
              illustrationId: suggested.illustrationId,
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

    fireEvent.click(
      await screen.findByTestId("question-feed-suggestion-same-art-but")
    );

    await waitFor(() => expect(illustrationVoteBody).toBeDefined());
    expect(illustrationVoteBody).toMatchObject({
      identifier: identifyPrintingItem.card.identifier,
      illustrationId: suggested.illustrationId,
      isUnknown: false,
    });
    expect(
      await screen.findByTestId("attribute-chip-Full Art")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("question-feed-candidate-grid-ungrouped")
    ).not.toBeInTheDocument();
  });

  it("'Not this art' submits the suggested printing's illustrationId to /2/submitIllustrationRejection/ and collapses the suggestion slot", async () => {
    const confirmSuggestionItem = {
      ...identifyPrintingItem,
      type: "confirm_suggestion",
      suggestedPrinting: {
        ...identifyPrintingItem.candidates[0],
        illustrationId: "illustration-rejected",
      },
    };
    server.use(
      http.get(buildRoute("2/questionFeed/"), () =>
        HttpResponse.json(
          {
            item: confirmSuggestionItem,
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
    let submittedBody:
      | { identifier?: string; illustrationId?: string }
      | undefined;
    server.use(
      http.post(
        buildRoute("2/submitIllustrationRejection/"),
        async ({ request }) => {
          submittedBody = (await request.json()) as typeof submittedBody;
          return HttpResponse.json(
            { illustrationId: "illustration-rejected" },
            { status: 200 }
          );
        }
      )
    );
    renderFeed();
    await revealCard();

    fireEvent.click(
      await screen.findByTestId("question-feed-suggestion-not-this-art")
    );

    await waitFor(() =>
      expect(submittedBody).toEqual({
        identifier: "card-1",
        anonymousId: expect.any(String),
        illustrationId: "illustration-rejected",
        voteSurface: undefined,
      })
    );
    // Same slot-collapse as the #770 answer set - "Not this art" reuses the rejected-context
    // rendering rather than inventing a separate transition.
    expect(
      await screen.findByTestId("question-feed-rejected-context")
    ).toHaveTextContent("You said: not");
  });

  it("shows the suggested printing's own reference image on the suggested-match question (regression: dropped when the suggestion slot was introduced in #49)", async () => {
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
      await screen.findByTestId("question-feed-suggestion-reference-image")
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
    server.use(submitTagVoteResolvesToApply);
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
    fireEvent.click(tappedCandidate.closest("button") || tappedCandidate);

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

    // identify_printing questions show the filter automatically now - set "Full Art" positive
    // directly, narrowing item 1's grid to printing-2 only.
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
    // the chip states themselves reset too, same as any other fresh item - the "Full Art"
    // chip (still auto-shown, item 2 is identify_printing too) is untouched again, not
    // carrying item 1's stale "positive" state forward.
    expect(
      await screen.findByTestId("attribute-chip-Full Art")
    ).toHaveAttribute("data-chip-state", "untouched");
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
      server.use(submitTagVoteResolvesToApply);
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

  // Issue #790 - a border chip must narrow WITHIN an illustration, never delete the
  // illustration outright, and a candidate that stays visible only because of that
  // narrowing must never have its own (chip-contradicting) attribute auto-tagged onto the
  // upload.
  describe("illustration-axis independence (issue #790)", () => {
    const sharedIllustrationId = "22222222-2222-2222-2222-222222222222";
    const whitePrinting = {
      ...identifyPrintingItem.candidates[0],
      identifier: "printing-white",
      borderColor: "white",
      illustrationId: sharedIllustrationId,
    };
    const silverPrinting = {
      ...identifyPrintingItem.candidates[1],
      identifier: "printing-silver",
      fullArt: false,
      isBorderless: false,
      isShowcase: false,
      isExtendedArt: false,
      isEtched: false,
      borderColor: "silver",
      illustrationId: sharedIllustrationId,
    };

    it("a border chip that matches no printing of an illustration keeps the illustration in the grid instead of removing it", async () => {
      server.use(
        http.get(buildRoute("2/questionFeed/"), () =>
          HttpResponse.json(
            {
              item: {
                ...identifyPrintingItem,
                candidates: [whitePrinting, silverPrinting],
              },
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
      server.use(submitTagVoteResolvesToApply);
      renderFeed();
      await revealCard();

      fireEvent.click(
        await screen.findByTestId("attribute-chip-Black Border-yes")
      );
      await waitFor(() =>
        expect(
          screen
            .getByTestId("attribute-chip-Black Border")
            .getAttribute("data-chip-state")
        ).toBe("positive")
      );

      // Neither printing is black-bordered - under the old filter the illustration would
      // vanish from the grid entirely. Both members must still be here, unnarrowed.
      const group = await screen.findByTestId(
        "question-feed-illustration-group"
      );
      expect(
        within(group).getByText("Same illustration - 2 printings")
      ).toBeInTheDocument();
    });

    it("reconsidering a rejected candidate that survived only via illustration-group preservation does not auto-tag the attribute that contradicted the active chip", async () => {
      const confirmSuggestionItem = {
        ...identifyPrintingItem,
        type: "confirm_suggestion",
        suggestedPrinting: whitePrinting,
        candidates: [whitePrinting, silverPrinting],
      };
      server.use(
        http.get(buildRoute("2/questionFeed/"), () =>
          HttpResponse.json(
            {
              item: confirmSuggestionItem,
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
      server.use(
        http.post(buildRoute("2/submitPrintingTag/"), () =>
          HttpResponse.json(
            { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
            { status: 200 }
          )
        )
      );
      server.use(
        http.post(buildRoute("2/submitIllustrationRejection/"), () =>
          HttpResponse.json(
            { illustrationId: sharedIllustrationId },
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

      fireEvent.click(
        await screen.findByTestId("question-feed-suggestion-not-this-art")
      );
      const rejectedNote = await screen.findByTestId(
        "question-feed-rejected-tile-note"
      );
      const rejectedTile = rejectedNote.closest("button");
      expect(rejectedTile).not.toBeNull();

      fireEvent.click(screen.getByTestId("question-feed-filter-toggle"));
      fireEvent.click(
        await screen.findByTestId("attribute-chip-Black Border-yes")
      );
      await waitFor(() =>
        expect(
          screen
            .getByTestId("attribute-chip-Black Border")
            .getAttribute("data-chip-state")
        ).toBe("positive")
      );

      // The rejected (white-bordered) tile is still reachable - kept alive by the same
      // illustration-group preservation exercised above - even though it contradicts the
      // active "Black Border" chip.
      fireEvent.click(rejectedTile!);

      // "Modern Border" (frame 2015) is derived too and doesn't contradict anything the
      // voter tapped - waiting for it proves the auto-tag batch actually ran before
      // asserting the contradicting chip was dropped from it.
      await waitFor(() => expect(autoTagCalls).toContain("Modern Border"));
      expect(autoTagCalls).not.toContain("White Border");
    });
  });

  // Issue #712 - "Not sure" and "Skip" used to be indistinguishable no-ops. confirm_suggestion's
  // new 4-answer set (Yes / Same art, but... / Not this art / Skip) folds "Not sure" into
  // Skip, which now records the abstention itself; identify_printing's own bottom-row Skip is
  // unrelated to this answer set and keeps writing nothing.
  describe("Skip records an abstention on confirm_suggestion (issue #712)", () => {
    const confirmSuggestionItem = {
      ...identifyPrintingItem,
      type: "confirm_suggestion",
      suggestedPrinting: identifyPrintingItem.candidates[0],
    };

    it("tapping confirm_suggestion's 'Skip' POSTs an abstention for this card and question type, then advances to the next question", async () => {
      let feedFetchCount = 0;
      server.use(
        http.get(buildRoute("2/questionFeed/"), () => {
          feedFetchCount += 1;
          return HttpResponse.json(
            {
              item: confirmSuggestionItem,
              remainingEstimate: {
                total: 1,
                confirmable: 1,
                contested: 0,
                fresh: 0,
              },
            },
            { status: 200 }
          );
        })
      );
      let abstentionBody: Record<string, unknown> | undefined;
      server.use(
        http.post(
          buildRoute("2/submitQuestionAbstention/"),
          async ({ request }) => {
            abstentionBody = (await request.json()) as Record<string, unknown>;
            return HttpResponse.json({ recorded: true }, { status: 200 });
          }
        )
      );
      renderFeed();
      await revealCard();

      fireEvent.click(
        await screen.findByTestId("question-feed-suggestion-skip")
      );

      await waitFor(() => expect(abstentionBody).toBeDefined());
      expect(abstentionBody).toMatchObject({
        identifier: confirmSuggestionItem.card.identifier,
        questionType: "confirm_suggestion",
      });
      await waitFor(() => expect(feedFetchCount).toBe(2));
    });

    it("identify_printing's own bottom-row 'Skip' never calls submitQuestionAbstention", async () => {
      server.use(questionFeedOnce());
      let abstentionCalls = 0;
      server.use(
        http.post(buildRoute("2/submitQuestionAbstention/"), () => {
          abstentionCalls += 1;
          return HttpResponse.json({ recorded: true }, { status: 200 });
        })
      );
      renderFeed();
      await revealCard();

      fireEvent.click(await screen.findByTestId("question-feed-skip"));
      await revealCard();

      expect(abstentionCalls).toBe(0);
    });
  });

  // Border question type (per-element question types branch): the answer surface is the four
  // BORDER_COLOR_GROUP chips plus the Full Art chip (the "No border — full art." answer, a
  // standalone toggle that co-occurs with every border value), rendered through the shared
  // useTagVoting machinery (see BorderColorQuestion.tsx) - a tap casts a real CardTagVote on
  // the existing /2/submitTagVote/ path with voteSurface "question-feed", not a new vote model.
  // The ActionRow's "Can't tell from this scan." answer records an abstention with reason
  // `cannot-tell` on the existing abstention write instead. And like the other non-candidate
  // question types (artist/tag), the subject card renders with no reveal treatment - no
  // revealCard() here.
  it("renders the border-colour chips for a border question and casts a tag vote on tap", async () => {
    server.use(questionFeedBorder);
    let tagVoteBody: Record<string, unknown> | undefined;
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        tagVoteBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            tagName: "Black Border",
            resolvedPolarity: 1,
            netPolarity: 1,
            tally: [{ polarity: 1, count: 1 }],
          },
          { status: 200 }
        );
      })
    );
    renderFeed();

    // the border question's answer surface is the four BORDER_COLOR_GROUP chips plus the Full
    // Art chip - "No border — full art." is a real answer here, cast through the same chip
    // machinery, because Full Art is an independent toggle that co-occurs with any border colour.
    expect(
      await screen.findByTestId("attribute-chip-Black Border")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("attribute-chip-White Border")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("attribute-chip-Silver Border")
    ).toBeInTheDocument();
    expect(screen.getByTestId("attribute-chip-Borderless")).toBeInTheDocument();
    expect(screen.getByTestId("attribute-chip-Full Art")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("attribute-chip-Black Border-yes"));

    await waitFor(() => expect(tagVoteBody).toBeDefined());
    expect(tagVoteBody).toMatchObject({
      identifier: cardDocument9.identifier,
      tagName: "Black Border",
      polarity: 1,
      voteSurface: "question-feed",
    });
    await waitFor(() =>
      expect(screen.getByTestId("attribute-chip-Black Border")).toHaveAttribute(
        "data-chip-state",
        "positive"
      )
    );

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art-yes"));

    await waitFor(() => expect(tagVoteBody?.tagName).toBe("Full Art"));
    expect(tagVoteBody).toMatchObject({
      identifier: cardDocument9.identifier,
      tagName: "Full Art",
      polarity: 1,
      voteSurface: "question-feed",
    });
    await waitFor(() =>
      expect(screen.getByTestId("attribute-chip-Full Art")).toHaveAttribute(
        "data-chip-state",
        "positive"
      )
    );
  });

  it("'Can't tell from this scan.' records the border abstention with reason and advances", async () => {
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return HttpResponse.json(
          {
            item: {
              type: "border",
              card: cardDocument9,
              tagConfidence: {
                "Black Border": 0.8,
                "White Border": 0,
                "Silver Border": 0,
                Borderless: 0,
                "Full Art": 0,
              },
            },
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
    let abstentionBody: Record<string, unknown> | undefined;
    server.use(
      http.post(
        buildRoute("2/submitQuestionAbstention/"),
        async ({ request }) => {
          abstentionBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ recorded: true }, { status: 200 });
        }
      )
    );
    renderFeed();

    fireEvent.click(await screen.findByTestId("question-feed-cant-tell"));

    await waitFor(() => expect(abstentionBody).toBeDefined());
    expect(abstentionBody).toMatchObject({
      identifier: cardDocument9.identifier,
      questionType: "border",
      reason: "cannot-tell",
    });
    await waitFor(() => expect(feedFetchCount).toBe(2));
  });

  it("'Continue' appears on border questions only after a chip vote, and advances carrying the vote without recording an abstention", async () => {
    // counting feed: the first fetch serves the border question, the second reports
    // caught-up so the advance's own re-fetch is observable.
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return feedFetchCount === 1
          ? HttpResponse.json(
              {
                item: {
                  type: "border",
                  card: cardDocument9,
                  tagConfidence: {
                    "Black Border": 0.8,
                    "White Border": 0,
                    "Silver Border": 0,
                    Borderless: 0,
                    "Full Art": 0,
                  },
                },
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
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as { tagName: string };
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: null,
            netPolarity: 1,
            tally: [],
          },
          { status: 200 }
        );
      })
    );
    let abstentionBody: Record<string, unknown> | undefined;
    server.use(
      http.post(
        buildRoute("2/submitQuestionAbstention/"),
        async ({ request }) => {
          abstentionBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ recorded: true }, { status: 200 });
        }
      )
    );
    renderFeed();

    expect(
      screen.queryByTestId("question-feed-border-continue")
    ).not.toBeInTheDocument();

    fireEvent.click(
      await screen.findByTestId("attribute-chip-Black Border-yes")
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("question-feed-border-continue")
      ).toBeInTheDocument()
    );

    fireEvent.click(screen.getByTestId("question-feed-border-continue"));

    await waitFor(() => expect(feedFetchCount).toBe(2));
    expect(abstentionBody).toBeUndefined();
  });

  it("'Confirm' appears on artist questions only after a vote lands, and advances carrying the vote without recording an abstention", async () => {
    let feedFetchCount = 0;
    server.use(
      http.get(buildRoute("2/questionFeed/"), () => {
        feedFetchCount += 1;
        return feedFetchCount === 1
          ? HttpResponse.json(
              {
                item: {
                  type: "artist",
                  card: cardDocument9,
                  confidentlyKnownArtistName: null,
                  scryfallIllustrationUrl: null,
                },
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
    server.use(artistCandidatesTwoResults, artistConsensusUnresolved);
    server.use(submitArtistVoteResolvesToCanonicalArtist1);
    let abstentionBody: Record<string, unknown> | undefined;
    server.use(
      http.post(
        buildRoute("2/submitQuestionAbstention/"),
        async ({ request }) => {
          abstentionBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ recorded: true }, { status: 200 });
        }
      )
    );
    renderFeed();

    expect(
      screen.queryByTestId("question-feed-artist-confirm")
    ).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Some Artist" }));

    // onVoteCast fires only after the vote POST resolves, so Confirm gates on the landed vote
    await waitFor(() =>
      expect(
        screen.getByTestId("question-feed-artist-confirm")
      ).toBeInTheDocument()
    );

    fireEvent.click(screen.getByTestId("question-feed-artist-confirm"));

    await waitFor(() => expect(feedFetchCount).toBe(2));
    expect(abstentionBody).toBeUndefined();
  });

  it("a stale in-flight fetch can never overwrite an already-rendered question (regression: WTC auto-skip)", async () => {
    // React's StrictMode intentionally double-invokes an effect with no cleanup on mount,
    // firing this effect's fetch twice - a real, reproducible way for two requests to be in
    // flight at once for the same question. Without a stale-response guard, whichever response
    // resolves LAST wins regardless of which request was newer - here the first (StrictMode-
    // discarded) request is the slow one, so an unguarded effect would silently swap the
    // already-rendered "Fresh Card" back to "Stale Card" moments later, with no user action.
    let feedFetchCount = 0;
    const remainingEstimate = {
      total: 1,
      confirmable: 0,
      contested: 0,
      fresh: 1,
    };
    server.use(
      http.get(buildRoute("2/questionFeed/"), async () => {
        feedFetchCount += 1;
        if (feedFetchCount === 1) {
          await delay(50);
          return HttpResponse.json(
            {
              item: {
                ...identifyPrintingItem,
                card: {
                  ...identifyPrintingItem.card,
                  identifier: "card-stale",
                  name: "Stale Card",
                },
              },
              remainingEstimate,
            },
            { status: 200 }
          );
        }
        return HttpResponse.json(
          {
            item: {
              ...identifyPrintingItem,
              card: {
                ...identifyPrintingItem.card,
                identifier: "card-fresh",
                name: "Fresh Card",
              },
            },
            remainingEstimate,
          },
          { status: 200 }
        );
      })
    );
    server.use(tagsNoResults);
    const store = setupStore({ backend: localBackend });
    render(
      <React.StrictMode>
        <Provider store={store}>
          <QuestionFeed />
        </Provider>
      </React.StrictMode>
    );

    await waitFor(() => expect(feedFetchCount).toBeGreaterThanOrEqual(2));
    await waitFor(() =>
      expect(
        screen.getByTestId("question-feed-subject-art-title")
      ).toHaveTextContent("Fresh Card")
    );

    // let the slower, superseded first request's response land and confirm it never applies.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(
      screen.getByTestId("question-feed-subject-art-title")
    ).toHaveTextContent("Fresh Card");
  });
});
