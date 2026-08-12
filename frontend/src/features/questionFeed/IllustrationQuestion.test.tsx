import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { QuestionFeedItem, Type } from "@/common/schema_types";
import { cardDocument1, localBackendURL } from "@/common/test-constants";
import {
  illustrationGroupCandidateA,
  illustrationGroupCandidateC,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { IllustrationQuestion } from "./IllustrationQuestion";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

// `cardDocument1` is typed as `common/types`'s `CardDocument` (the API-response shape used
// throughout the MSW fixtures), which is structurally close to but not identical to
// `schema_types.Card` (some fields optional there vs required here) - the same gap
// `handlers.ts` never hits since its usages flow through `HttpResponse.json` rather than a
// strictly-typed prop, so this cast is this file's own equivalent of that boundary.
const illustrationItem = {
  type: Type.Illustration,
  card: cardDocument1,
  illustrationCandidates: [
    illustrationGroupCandidateA,
    illustrationGroupCandidateC,
  ],
  tagConfidence: {},
} as unknown as QuestionFeedItem;

function renderComponent(
  onAnswered: () => void = () => undefined,
  item: QuestionFeedItem = illustrationItem
) {
  return render(
    <Provider store={setupStore()}>
      <IllustrationQuestion
        item={item}
        backendURL={localBackendURL}
        onAnswered={onAnswered}
      />
    </Provider>
  );
}

describe("IllustrationQuestion", () => {
  it("renders one tile per illustration candidate", () => {
    renderComponent();

    expect(
      screen.getByTestId("question-feed-illustration-illustration-shared")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("question-feed-illustration-illustration-unique-to-c")
    ).toBeInTheDocument();
  });

  it("renders nothing when the item carries no illustration candidates", () => {
    const { container } = renderComponent(() => undefined, {
      ...illustrationItem,
      illustrationCandidates: [],
    });

    expect(container).toBeEmptyDOMElement();
  });

  it("a positive tap calls the illustration vote endpoint with the real illustrationId, never the printing-tag endpoint", async () => {
    let votePayload: {
      identifier: string;
      anonymousId: string;
      illustrationId: string;
      isUnknown: boolean;
    } | null = null;
    let printingTagVoteWasCalled = false;
    server.use(
      http.post(
        buildRoute("2/submitIllustrationVote/"),
        async ({ request }) => {
          votePayload = (await request.json()) as typeof votePayload;
          return HttpResponse.json(
            {
              illustrationId: votePayload!.illustrationId,
              isUnknown: false,
              printingVoteCast: false,
              artistVoteCast: true,
            },
            { status: 200 }
          );
        }
      ),
      http.post(buildRoute("2/submitPrintingTagVote/"), () => {
        printingTagVoteWasCalled = true;
        return HttpResponse.json({}, { status: 200 });
      })
    );
    const onAnswered = jest.fn();
    renderComponent(onAnswered);

    fireEvent.click(
      screen.getByTestId("question-feed-illustration-illustration-shared")
    );

    await waitFor(() => expect(onAnswered).toHaveBeenCalledTimes(1));
    expect(votePayload).not.toBeNull();
    expect(votePayload!.illustrationId).toBe("illustration-shared");
    expect(votePayload!.anonymousId).toBeTruthy();
    expect(votePayload!.isUnknown).toBe(false);
    expect(printingTagVoteWasCalled).toBe(false);
  });

  it("the reject control calls the rejection endpoint with the real illustrationId, never the vote or printing-tag endpoint", async () => {
    let rejectPayload: {
      identifier: string;
      anonymousId: string;
      illustrationId: string;
    } | null = null;
    let voteEndpointWasCalled = false;
    let printingTagVoteWasCalled = false;
    server.use(
      http.post(
        buildRoute("2/submitIllustrationRejection/"),
        async ({ request }) => {
          rejectPayload = (await request.json()) as typeof rejectPayload;
          return HttpResponse.json(
            { illustrationId: rejectPayload!.illustrationId },
            { status: 200 }
          );
        }
      ),
      http.post(buildRoute("2/submitIllustrationVote/"), () => {
        voteEndpointWasCalled = true;
        return HttpResponse.json({}, { status: 200 });
      }),
      http.post(buildRoute("2/submitPrintingTagVote/"), () => {
        printingTagVoteWasCalled = true;
        return HttpResponse.json({}, { status: 200 });
      })
    );
    const onAnswered = jest.fn();
    renderComponent(onAnswered);

    fireEvent.click(
      screen.getByTestId(
        "question-feed-illustration-reject-illustration-unique-to-c"
      )
    );

    await waitFor(() => expect(onAnswered).toHaveBeenCalledTimes(1));
    expect(rejectPayload).not.toBeNull();
    expect(rejectPayload!.illustrationId).toBe("illustration-unique-to-c");
    expect(rejectPayload!.anonymousId).toBeTruthy();
    expect(voteEndpointWasCalled).toBe(false);
    expect(printingTagVoteWasCalled).toBe(false);
  });
});
