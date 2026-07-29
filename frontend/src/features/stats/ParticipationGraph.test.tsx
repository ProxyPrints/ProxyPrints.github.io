/**
 * Regression guard for the 2026-07-29 coordinator amendment to this task's directive: the
 * homepage graph must never compute or render a percentage against `participation.total` (or any
 * other large denominator), under EITHER today's real ratio or the post-machine-sweep ratio the
 * amendment describes (where the ratio gets WORSE, not better). If this test passes against both
 * fixtures, the design is provably ratio-invariant - it was never reading a percentage in the
 * first place, so a worse ratio next week can't break it.
 *
 * All renders now go through a real Redux `Provider` (mirroring Navbar.test.tsx's own precedent)
 * - `ParticipationGraph` reads `useRemoteBackendConfigured` for the "Start with one card" CTA and
 * `useHasContributedThisSession` (`sessionContributionSlice.ts`) for the in-session green-dot
 * mechanic, both real store-backed selectors.
 *
 * 2026-07-29 consumer-swap directive additions: the gate/bar now read the card-denominated ratio
 * (`humanProgressRatioPercent` in `humanProgressReveal.ts`), so `justBelowThreshold`/
 * `justAboveThreshold` below nudge `distinctCardsRoutedToReview` (that ratio's own denominator),
 * not `total` (which the old votes-over-cards ratio depended on and the new one doesn't read at
 * all). Also covers: the always-rising `distinctCardsRoutedToReviewWithHumanVotes` count, the
 * live-skew guard (the three card-denominated fields absent entirely), and the in-session
 * green-dot/thank-you mechanic.
 */
import { act, render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { Participation } from "@/common/schema_types";
import { localBackend, noBackend } from "@/common/test-constants";
import {
  HUMAN_VOTE_REVEAL_PERCENT,
  humanProgressRatioPercent,
} from "@/features/stats/humanProgressReveal";
import { recordSessionContribution } from "@/features/stats/sessionContributionSlice";
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
// byte-for-byte the design covered by the guard above; at/above it, the series joins and the
// headline flips to the routed-to-review framing (2026-07-29 consumer-swap directive, item 2).
describe("ParticipationGraph - threshold-gated human-progress series", () => {
  // Derived from the shared participationAtRevealThreshold fixture (exactly at
  // HUMAN_VOTE_REVEAL_PERCENT's default of 10%, 100/1_000 card-denominated) by nudging
  // `distinctCardsRoutedToReview` - the new ratio's own denominator (the old `total`-nudging
  // trick no longer moves this ratio at all, since the card-denominated ratio never reads
  // `total`).
  const justBelowThreshold = {
    ...participationAtRevealThreshold,
    distinctCardsRoutedToReview: 1_001, // 100 / 1_001 ≈ 9.99% - just under 10%
  };
  const justAboveThreshold = {
    ...participationAtRevealThreshold,
    distinctCardsRoutedToReview: 999, // 100 / 999 ≈ 10.01% - just over 10%
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

  it("at exactly the threshold: the series joins the graph, one axis, no percentage/total text, and the headline flips to the routed-to-review framing", () => {
    const { container } = renderWithBackend(participationAtRevealThreshold);
    expect(
      screen.getByTestId("participation-graph-human-progress")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("participation-graph-human-progress-bar")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "People are keeping up with what the machine routes to them"
      )
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

  // 2026-07-29 consumer-swap directive, item 3 - the always-rises reward count beside the bar.
  it("the revealed state shows the always-rising distinctCardsRoutedToReviewWithHumanVotes count as a plain count, never a percentage", () => {
    const { container } = renderWithBackend(participationAtRevealThreshold);
    expect(
      screen.getByTestId("participation-graph-reviewed-count")
    ).toHaveTextContent(
      participationAtRevealThreshold.distinctCardsRoutedToReviewWithHumanVotes.toLocaleString()
    );
    expect(container.textContent).not.toMatch(/%/);
  });
});

// 2026-07-29 directive - "the API will not have these fields yet". A real `1/catalogStats/`
// response can, and on merge day WILL, omit `distinctCardsWithHumanVotes`/
// `distinctCardsRoutedToReview`/`distinctCardsRoutedToReviewWithHumanVotes` entirely, even though
// `Participation`'s TS type claims they're required (`store/api.ts` trusts the fetch response's
// shape directly, no runtime validation) - this is the guard for that guaranteed live-skew
// window.
describe("ParticipationGraph - live-skew guard: the three card-denominated fields absent entirely", () => {
  it("renders the below-threshold design unchanged - no NaN, no undefined, no thrown error, no percentage", () => {
    const participationWithoutCardFields = {
      ...participationAtRevealThreshold,
    } as Partial<Participation>;
    delete participationWithoutCardFields.distinctCardsWithHumanVotes;
    delete participationWithoutCardFields.distinctCardsRoutedToReview;
    delete participationWithoutCardFields.distinctCardsRoutedToReviewWithHumanVotes;

    const { container } = renderWithBackend(
      participationWithoutCardFields as Participation
    );

    expect(
      screen.getByText("The catalog needs human eyes")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("participation-graph-human-progress")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("participation-graph-human-progress-bar")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("participation-graph-reviewed-count")
    ).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/NaN/);
    expect(container.textContent).not.toMatch(/undefined/);
    expect(container.textContent).not.toMatch(/%/);
  });
});

// 2026-07-29 directive item 4 - the dashed "you could be next" dot becomes a filled green dot
// plus a thank-you once THIS client has cast a vote in-session (sessionContributionSlice.ts).
describe("ParticipationGraph - in-session 'you contributed' dot", () => {
  it("is dashed/hollow, with no thank-you, before this client has voted", () => {
    renderWithBackend(participationCurrentRatio);
    const joinDot = screen.getByTestId("participation-graph-join-dot");
    expect(joinDot).toHaveAttribute("stroke-dasharray", "3 2");
    expect(joinDot).toHaveAttribute("fill", "none");
    expect(
      screen.queryByTestId("participation-graph-thank-you")
    ).not.toBeInTheDocument();
  });

  it("becomes a filled green dot with a thank-you once a vote is submitted in-session", () => {
    const store = setupStore({ backend: localBackend });
    render(
      <Provider store={store}>
        <ParticipationGraph participation={participationCurrentRatio} />
      </Provider>
    );

    const joinDot = screen.getByTestId("participation-graph-join-dot");
    expect(joinDot).toHaveAttribute("fill", "none");

    // Simulates QuestionFeed.tsx's bumpSessionCount() dispatching this on a successful vote -
    // the SAME store instance this component tree reads from, no remount.
    act(() => {
      store.dispatch(recordSessionContribution());
    });

    expect(joinDot).toHaveAttribute("fill", "var(--bs-success)");
    expect(joinDot).not.toHaveAttribute("stroke-dasharray");
    expect(
      screen.getByTestId("participation-graph-thank-you")
    ).toBeInTheDocument();
    // Green is never the only signal - the accessible name/title changes too.
    expect(joinDot.querySelector("title")?.textContent).toMatch(/thank you/i);
  });
});
