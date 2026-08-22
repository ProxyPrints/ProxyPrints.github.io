import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { localBackendURL } from "@/common/test-constants";
import { server } from "@/mocks/server";
import { AppStore, setupStore } from "@/store/store";

import { initialChipStates } from "./AttributeChipPanel";
import { BorderColorQuestion } from "./BorderColorQuestion";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

// mirrors AttributeChipPanel.test.tsx's Wrapper - QuestionFeed.tsx lifts chipStates the same
// way for BorderColorQuestion.
function Wrapper({ store }: { store: AppStore }) {
  const [states, setStates] = React.useState(initialChipStates());
  return (
    <Provider store={store}>
      <BorderColorQuestion
        backendURL={localBackendURL}
        cardIdentifier="card-1"
        tagConfidence={{}}
        chipStates={states}
        onChipStatesChange={setStates}
      />
    </Provider>
  );
}

describe("BorderColorQuestion", () => {
  // Regression for a served border question the owner hit live on Ashaya, Soul of the Wild:
  // the card's candidates shared `borderColor: "black"` and differed only on `isExtendedArt`,
  // so none of the four colours (nor Full Art) could describe the extended-art candidate. This
  // fails against the pre-fix answer set, which renders only BORDER_COLOR_GROUP + Full Art.
  it("offers an Extended Art answer that a plain black-border candidate doesn't have", () => {
    render(<Wrapper store={setupStore()} />);

    expect(screen.getByTestId("attribute-chip-Extended")).toBeInTheDocument();
    expect(
      screen.getByTestId("attribute-chip-Extended-yes")
    ).toBeInTheDocument();
  });

  it("offers a Showcase answer alongside Extended Art", () => {
    render(<Wrapper store={setupStore()} />);

    expect(screen.getByTestId("attribute-chip-Showcase")).toBeInTheDocument();
  });

  it("still renders the four colours and Full Art unchanged", () => {
    render(<Wrapper store={setupStore()} />);

    expect(
      screen.getByTestId("attribute-chip-Black Border")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("attribute-chip-White Border")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("attribute-chip-Silver Border")
    ).toBeInTheDocument();
    expect(screen.getByTestId("attribute-chip-Borderless")).toBeInTheDocument();
    expect(screen.getByTestId("attribute-chip-Full Art")).toBeInTheDocument();
  });

  it("tapping Extended Art casts a real user vote through the same tag-vote surface", async () => {
    const submitted: { tagName: string; polarity: number }[] = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
        };
        submitted.push({ tagName: body.tagName, polarity: body.polarity });
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
    render(<Wrapper store={setupStore()} />);

    fireEvent.click(screen.getByTestId("attribute-chip-Extended-yes"));

    await waitFor(() =>
      expect(
        screen
          .getByTestId("attribute-chip-Extended")
          .getAttribute("data-chip-state")
      ).toBe("positive")
    );
    expect(submitted).toEqual([{ tagName: "Extended", polarity: 1 }]);
  });

  it("Extended Art and Showcase are one exclusion group - a positive on one implies the other, without casting a vote on it", async () => {
    const submitted: string[] = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as { tagName: string };
        submitted.push(body.tagName);
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
    render(<Wrapper store={setupStore()} />);

    fireEvent.click(screen.getByTestId("attribute-chip-Extended-yes"));
    await waitFor(() => expect(submitted).toEqual(["Extended"]));

    expect(submitted).not.toContain("Showcase");
    expect(
      screen
        .getByTestId("attribute-chip-Showcase")
        .getAttribute("data-chip-state")
    ).toBe("untouched");
  });
});
