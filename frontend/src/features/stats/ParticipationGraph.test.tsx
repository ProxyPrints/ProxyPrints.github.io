/**
 * Regression guard for the 2026-07-29 coordinator amendment to this task's directive: the
 * homepage graph must never compute or render a percentage against `participation.total` (or any
 * other large denominator), under EITHER today's real ratio or the post-machine-sweep ratio the
 * amendment describes (where the ratio gets WORSE, not better). If this test passes against both
 * fixtures, the design is provably ratio-invariant - it was never reading a percentage in the
 * first place, so a worse ratio next week can't break it.
 *
 * All renders now go through a real Redux `Provider` (mirroring Navbar.test.tsx's own precedent)
 * - `ParticipationGraph` reads `useRemoteBackendConfigured` for the new "Start with one card" CTA
 * (2026-07-29 owner ruling) added alongside this guard.
 */
import { render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, noBackend } from "@/common/test-constants";
import {
  HUMAN_VOTE_REVEAL_PERCENT,
  humanProgressRatioPercent,
} from "@/features/stats/humanProgressReveal";
import {
  participationAtRevealThreshold,
  participationCurrentRatio,
  participationPostSweep,
} from "@/features/stats/testFixtures";
import { setupStore } from "@/store/store";

import { ParticipationGraph } from "./ParticipationGraph";

function renderWithBackend(
  participation: Parameters<typeof ParticipationGraph>[0]["participation"],
  backend: typeof localBackend | typeof noBackend = localBackend
) {
  return render(
    <Provider store={setupStore({ backend })}>
      <ParticipationGraph participation={participation} />
    </Provider>
  );
}

describe("ParticipationGraph - renders correctly against both the current and post-sweep vote ratios, with no percentage ever computed against total", () => {
  it.each([
    ["current ratio (0.05% human/machine)", participationCurrentRatio],
    [
      "post-sweep ratio (worse, per the 2026-07-29 amendment)",
      participationPostSweep,
    ],
  ])("%s", (_label, participation) => {
    const { container } = renderWithBackend(participation);

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
    const { unmount } = renderWithBackend(participationCurrentRatio);
    expect(screen.getAllByTestId("participation-graph-voter-dot")).toHaveLength(
      participationCurrentRatio.distinctHumanVoters
    );
    unmount();

    renderWithBackend(participationPostSweep);
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

// 2026-07-29 owner ruling: the "Start with one card" CTA after the hollow dot, gated on
// remoteBackendConfigured the same way Navbar.tsx gates its own What's That Card? link.
describe("ParticipationGraph - the 'Start with one card' CTA", () => {
  it("is shown when a remote backend is configured", () => {
    renderWithBackend(participationCurrentRatio, localBackend);
    expect(
      screen.getByTestId("participation-graph-start-one-card")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Start with one card" })
    ).toHaveAttribute("href", "/whatsthat");
  });

  it("is absent when no backend is configured (self-hosted, no /whatsthat to send anyone to)", () => {
    renderWithBackend(participationCurrentRatio, noBackend);
    expect(
      screen.queryByTestId("participation-graph-start-one-card")
    ).not.toBeInTheDocument();
  });

  it("is shown regardless of whether the human-progress series is revealed", () => {
    renderWithBackend(participationAtRevealThreshold, localBackend);
    expect(
      screen.getByTestId("participation-graph-start-one-card")
    ).toBeInTheDocument();
  });
});

// 2026-07-29 owner ruling: the threshold-gated human-progress series
// (features/stats/humanProgressReveal.ts). Below HUMAN_VOTE_REVEAL_PERCENT the page is
// byte-for-byte the design covered by the guard above; at/above it, the series joins.
describe("ParticipationGraph - threshold-gated human-progress series", () => {
  // Derived from the shared participationAtRevealThreshold fixture (exactly at
  // HUMAN_VOTE_REVEAL_PERCENT's default of 10%, 237/2_370) by nudging `total` - the same
  // humanVotes/distinctHumanVoters, only the ratio moves.
  const justBelowThreshold = {
    ...participationAtRevealThreshold,
    total: 2_371, // 237 / 2_371 ≈ 9.996% - just under 10%
  };
  const justAboveThreshold = {
    ...participationAtRevealThreshold,
    total: 2_369, // 237 / 2_369 ≈ 10.004% - just over 10%
  };

  it("just below threshold: the series does not exist - no placeholder, no teaser, unchanged headline/copy", () => {
    renderWithBackend(justBelowThreshold);
    expect(
      screen.queryByTestId("participation-graph-human-progress")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("participation-graph-human-progress-bar")
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("The catalog needs human eyes")
    ).toBeInTheDocument();
  });

  it("at exactly the threshold: the series joins the graph, one axis, no percentage/total text", () => {
    const { container } = renderWithBackend(participationAtRevealThreshold);
    expect(
      screen.getByTestId("participation-graph-human-progress")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("participation-graph-human-progress-bar")
    ).toBeInTheDocument();
    expect(
      screen.getByText("People are turning that into progress")
    ).toBeInTheDocument();
    // Same hard constraints as the below-threshold guard above: still no "%" and still no
    // `total` rendered as literal text, even with the series visible.
    expect(container.textContent).not.toMatch(/%/);
    expect(
      screen.queryByText(participationAtRevealThreshold.total.toLocaleString())
    ).not.toBeInTheDocument();
  });

  it("just above threshold: the series joins the graph too", () => {
    renderWithBackend(justAboveThreshold);
    expect(
      screen.getByTestId("participation-graph-human-progress")
    ).toBeInTheDocument();
  });

  it("the reveal gate reads the SAME ratio the series draws from (humanProgressRatioPercent), computed once", () => {
    expect(
      humanProgressRatioPercent(participationAtRevealThreshold)
    ).toBeCloseTo(HUMAN_VOTE_REVEAL_PERCENT);
  });

  it("below threshold, the rest of the design (opportunity bars + dot matrix) is untouched", () => {
    renderWithBackend(justBelowThreshold);
    expect(screen.getAllByTestId("bar-chart-row").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("participation-graph-voter-dot")).toHaveLength(
      justBelowThreshold.distinctHumanVoters
    );
    expect(
      screen.getByTestId("participation-graph-join-dot")
    ).toBeInTheDocument();
  });
});
