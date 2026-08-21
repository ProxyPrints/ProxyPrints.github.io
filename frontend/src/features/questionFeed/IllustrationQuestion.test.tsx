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

import { QuestionFeedItem, Type } from "@/common/schema_types";
import { cardDocument1, localBackendURL } from "@/common/test-constants";
import { ILLUSTRATION_CROP_ASPECT_RATIO } from "@/features/printingTags/cardPanel";
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

  it("each tile declares the landscape art-crop aspect-ratio so the absolutely-positioned thumbnail has real height", () => {
    renderComponent();

    // Regression (fix/wtc-illustration-sliver): ZoomableThumbnail is absolutely positioned
    // (`inset: 0`, cardPanel.tsx) and contributes no in-flow height, so a tile with no
    // declared box size collapses to a ~0-height sliver regardless of how wide the grid slot
    // is. The tile's own aspect-ratio (the 584/444 art-crop frame, the same one the
    // IllustrationArtPlaceholder fallback renders in) is what gives the box its height.
    // The constant keeps its display spacing (`584 / 444`); cssstyle serializes the computed
    // value space-free (`584/444`), so compare against the normalized form.
    const artTile = screen.getByTestId(
      "question-feed-illustration-illustration-shared"
    );
    expect(artTile).toHaveStyle({
      "aspect-ratio": ILLUSTRATION_CROP_ASPECT_RATIO.replace(/\s+/g, ""),
    });

    // The art <img> must additionally sit inside the same crop-ratio'd frame (the
    // IllustrationArtPlaceholder wrapper, whose own `img { width: 100%; height: 100%;
    // object-fit: cover }` rules in cardPanel.tsx are what make the artwork actually fill
    // the tile) - without that wrapper the tile would have height but only show the img's
    // top-left corner at its intrinsic size. That frame is the img's grandparent, not its
    // parent: ZoomableThumbnail sits between them but is taken out of flow (`position:
    // absolute; inset: 0`) and declares no aspect-ratio of its own, so the ratio the img
    // is measured against lives on IllustrationArtPlaceholder one level up.
    const artImg = artTile.querySelector("img");
    expect(artImg).not.toBeNull();
    const artFrame = artImg?.parentElement?.parentElement;
    expect(artFrame).not.toBeNull();
    expect(artFrame).toHaveStyle({
      "aspect-ratio": ILLUSTRATION_CROP_ASPECT_RATIO.replace(/\s+/g, ""),
    });
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

  it("renders an artist support applet beneath each tile, outside the vote button", () => {
    renderComponent();

    const applets = screen.getAllByTestId("artist-support-applet");
    expect(applets).toHaveLength(2);

    for (const applet of applets) {
      // The compact-cluster applet: collapsed artist name carrying the MTGAC page link
      // (deterministic fallback URL - no remote backend in this render, so the RTK query
      // is skipped) plus the expand disclosure. Same ArtistCredit shell as the
      // illustration-group flow, incl. its 220px width cap.
      expect(within(applet).getByText("Some Artist")).toBeInTheDocument();
      expect(within(applet).getByTestId("artist-support-link")).toHaveAttribute(
        "href",
        "https://www.mtgartistconnection.com/artist/Some%20Artist"
      );
      expect(
        within(applet).getByTestId("artist-support-toggle")
      ).toHaveAttribute("aria-expanded", "false");
    }

    // Placed AFTER the tile's art and BEFORE the reject control, as siblings of the vote
    // button - never inside it (ArtistSupportLink renders an <a> and a disclosure <button>;
    // interactive-in-interactive is invalid HTML and would bubble their clicks into a vote).
    const artTile = screen.getByTestId(
      "question-feed-illustration-illustration-shared"
    );
    const wrapper = artTile.parentElement;
    expect(wrapper).not.toBeNull();
    const children = Array.from(wrapper!.children);
    expect(children[0]).toBe(artTile);
    expect(
      children[1].querySelector('[data-testid="artist-support-applet"]')
    ).not.toBeNull();
    expect(children[2].getAttribute("data-testid")).toMatch(
      /question-feed-illustration-reject-/
    );
  });

  it("the artist applet's expand toggle never submits a vote", () => {
    const onAnswered = jest.fn();
    renderComponent(onAnswered);

    const toggle = screen.getAllByTestId("artist-support-toggle")[0];
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("artist-support-expanded")).toBeInTheDocument();
    expect(onAnswered).not.toHaveBeenCalled();
  });
});
