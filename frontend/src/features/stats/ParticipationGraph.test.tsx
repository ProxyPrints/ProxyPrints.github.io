/**
 * Regression guard for the 2026-07-29 coordinator amendment to this task's directive: the
 * homepage graph must never compute or render a percentage against `participation.total` (or any
 * other large denominator), under EITHER today's real ratio or the post-machine-sweep ratio the
 * amendment describes (where the ratio gets WORSE, not better). If this test passes against both
 * fixtures, the design is provably ratio-invariant - it was never reading a percentage in the
 * first place, so a worse ratio next week can't break it.
 */
import { render, screen } from "@testing-library/react";
import React from "react";

import {
  participationCurrentRatio,
  participationPostSweep,
} from "@/features/stats/testFixtures";

import { ParticipationGraph } from "./ParticipationGraph";

describe("ParticipationGraph - renders correctly against both the current and post-sweep vote ratios, with no percentage ever computed against total", () => {
  it.each([
    ["current ratio (0.05% human/machine)", participationCurrentRatio],
    [
      "post-sweep ratio (worse, per the 2026-07-29 amendment)",
      participationPostSweep,
    ],
  ])("%s", (_label, participation) => {
    const { container } = render(
      <ParticipationGraph participation={participation} />
    );

    // The emphasized, human-scale numbers render correctly under either fixture.
    expect(
      screen.getByTestId("participation-graph-human-votes-total")
    ).toHaveTextContent(participation.humanVotes.total.toLocaleString());
    expect(
      screen.getByTestId("participation-graph-distinct-voters")
    ).toHaveTextContent(participation.distinctHumanVoters.toLocaleString());

    // The dot-matrix draws exactly one dot per distinct human voter (the element the amendment
    // requires to visibly grow with participation) - unchanged between the two fixtures, since
    // the amendment holds distinctHumanVoters flat post-sweep.
    expect(screen.getAllByTestId("participation-graph-voter-dot")).toHaveLength(
      participation.distinctHumanVoters
    );
    expect(
      screen.getByTestId("participation-graph-join-dot")
    ).toBeInTheDocument();

    // The opportunity chart shows confirmable/contested as raw counts - never `total`.
    expect(
      screen.getByText(participation.confirmable.toLocaleString())
    ).toBeInTheDocument();
    expect(
      screen.getByText(participation.contested.toLocaleString())
    ).toBeInTheDocument();

    // The hard constraint: no "%" character anywhere in the rendered output, under either
    // fixture - this component must never compute confirmable/total, humanVotes.total/total, or
    // any other ratio against the whole catalog.
    expect(container.textContent).not.toMatch(/%/);

    // Nor does it render `total` itself anywhere, which would invite a reader to compute that
    // forbidden ratio by hand from two numbers on the page.
    expect(
      screen.queryByText(participation.total.toLocaleString())
    ).not.toBeInTheDocument();
  });

  it("the confirmable/contested bars change between fixtures, but the voter dot count does not - proving the growing element is the human one, not the machine one", () => {
    const { unmount } = render(
      <ParticipationGraph participation={participationCurrentRatio} />
    );
    expect(screen.getAllByTestId("participation-graph-voter-dot")).toHaveLength(
      participationCurrentRatio.distinctHumanVoters
    );
    unmount();

    render(<ParticipationGraph participation={participationPostSweep} />);
    expect(screen.getAllByTestId("participation-graph-voter-dot")).toHaveLength(
      participationPostSweep.distinctHumanVoters
    );

    // Same dot count under a very different machine-vote-driven `confirmable`/`contested` -
    // machine work moving doesn't move the human dot-matrix at all.
    expect(participationCurrentRatio.distinctHumanVoters).toEqual(
      participationPostSweep.distinctHumanVoters
    );
    expect(participationCurrentRatio.confirmable).not.toEqual(
      participationPostSweep.confirmable
    );
  });
});
