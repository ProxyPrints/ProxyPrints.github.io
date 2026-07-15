import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { localBackendURL } from "@/common/test-constants";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { AttributeChipPanel, initialChipStates } from "./AttributeChipPanel";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

// a thin controlled wrapper - mirrors how QuestionFeed.tsx actually owns chipStates, so the
// component under test exercises the same "lifted state" contract its real caller relies on
function Wrapper({ onSubmitted }: { onSubmitted?: (tagName: string) => void }) {
  const [states, setStates] = React.useState(initialChipStates());
  return (
    <Provider store={setupStore()}>
      <AttributeChipPanel
        backendURL={localBackendURL}
        cardIdentifier="card-1"
        tagConfidence={{}}
        chipStates={states}
        onChipStatesChange={setStates}
      />
    </Provider>
  );
}

describe("AttributeChipPanel", () => {
  it("cycles a chip untouched -> positive -> negative -> untouched, casting one vote per tap", async () => {
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
        };
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: body.polarity === 0 ? null : body.polarity,
            netPolarity: body.polarity,
            tally: [],
          },
          { status: 200 }
        );
      })
    );
    render(<Wrapper />);

    const chip = screen.getByTestId("attribute-chip-Full Art");
    expect(chip.getAttribute("data-chip-state")).toBe("untouched");

    // each click's optimistic state update lands synchronously, but the button stays
    // `disabled` (submitting) until the mocked request's promise resolves - wait for it to
    // re-enable before firing the next click, or a click on a still-disabled button is a
    // silent no-op in jsdom.
    const waitForSettled = async (expectedState: string) => {
      await waitFor(() => {
        const el = screen.getByTestId("attribute-chip-Full Art");
        expect(el.getAttribute("data-chip-state")).toBe(expectedState);
        expect(el).not.toBeDisabled();
      });
    };

    fireEvent.click(chip);
    await waitForSettled("positive");

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    await waitForSettled("negative");

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    await waitForSettled("untouched");
  });

  it("tapping one exclusion-group chip does not cast a vote on its siblings", async () => {
    const submittedTagNames: string[] = [];
    server.use(
      http.post(buildRoute("2/submitTagVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          tagName: string;
          polarity: number;
        };
        submittedTagNames.push(body.tagName);
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
    render(<Wrapper />);

    fireEvent.click(screen.getByTestId("attribute-chip-Black Border"));
    await waitFor(() => expect(submittedTagNames).toEqual(["Black Border"]));

    // sibling should render implied-negative (dimmed) without ever being submitted
    expect(submittedTagNames).not.toContain("White Border");
    expect(submittedTagNames).not.toContain("Silver Border");
    const sibling = screen.getByTestId("attribute-chip-White Border");
    expect(sibling.getAttribute("data-chip-state")).toBe("untouched");
  });

  it("reverts the explicit state on a failed submit", async () => {
    server.use(
      http.post(buildRoute("2/submitTagVote/"), () =>
        HttpResponse.json({ name: "Error", message: "failed" }, { status: 500 })
      )
    );
    render(<Wrapper />);

    fireEvent.click(screen.getByTestId("attribute-chip-Full Art"));
    await waitFor(() =>
      expect(
        screen
          .getByTestId("attribute-chip-Full Art")
          .getAttribute("data-chip-state")
      ).toBe("untouched")
    );
  });
});
