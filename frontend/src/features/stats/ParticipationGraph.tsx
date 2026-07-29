/**
 * Homepage front-page graph (Proposal F, item 4 - upgraded from a text strip to a real graph per
 * the 2026-07-29 coordinator amendment to this task's directive). Built from the SAME
 * `participation` panel the /stats page's own ParticipationPanel.tsx renders
 * (`useGetCatalogStatsQuery().data.participation`) - chart 1 (`resolutionProgress`) is still
 * absent from the backend this pass (see catalog_stats.py's own module docstring), so this graph
 * does NOT attempt the owner's original "human votes filling up toward the total database
 * number" sketch literally. That literal version is a `humanVotes.total / total` ratio -
 * measured 2026-07-29, 237 / 230,770 ≈ 0.1%, and the amendment's own stated concern is that this
 * ratio gets WORSE (not better) once the pending full machine sweep multiplies machine votes
 * 3-4x: at that scale a fill-toward-total bar (or even a fill-toward-`confirmable` bar - 237 /
 * 103,687 is still ≈ 0.2%) renders as a dead sliver regardless of which large denominator it's
 * measured against, and reads as "your contribution doesn't matter" - the opposite of a call to
 * action. See this task's PR description for the full reasoning; the two rules this component is
 * built to satisfy are: (1) never compute or render a percentage against `total` (or any other
 * large denominator) anywhere here, and (2) whatever visibly grows when a new person
 * contributes has to be a HUMAN quantity, not a machine one.
 *
 * Two separate, non-competing visuals instead (never sharing an axis, per house rule):
 *
 * - A small bar chart of `confirmable`/`contested` - both raw counts, no ratio, no `total` in
 *   sight - framing the machine sweep's actual output as RUNWAY it hands to people ("this many
 *   cards are ready for a person to look at"), not as a race the machine is winning.
 * - A dot-matrix ("unit chart") of `distinctHumanVoters` - real, individually-countable people,
 *   plus a dashed "join them" mark - this is the element that visibly grows one dot at a time as
 *   new contributors show up, which a shared-axis vote-count bar never could at this catalog's
 *   real ratio. `humanVotes.total` rides along as a supporting number, not a fill level.
 */
import Link from "next/link";
import React from "react";

import { Participation } from "@/common/schema_types";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";

const DOT_SIZE = 14;
const DOT_GAP = 6;
// Safety cap, not a tuned-to-the-fixture number - today's real distinctHumanVoters is 11 (see
// this task's own directive) and the whole point of this component is that a person-per-dot
// pictogram stays legible at this catalog's real, small human-contributor count. If that count
// ever grows past this cap, degrade to a "+N" label rather than silently drawing hundreds of
// circles into a fixed-height row.
const MAX_INDIVIDUAL_DOTS = 24;

function VoterDotMatrix({
  distinctHumanVoters,
}: {
  distinctHumanVoters: number;
}) {
  const dotCount = Math.min(distinctHumanVoters, MAX_INDIVIDUAL_DOTS);
  const overflow = distinctHumanVoters - dotCount;
  const dots = Array.from({ length: dotCount });
  const joinDotIndex = dotCount; // drawn one slot after the last real dot
  const totalSlots = joinDotIndex + 1;
  return (
    <svg
      role="img"
      aria-label={`${distinctHumanVoters} distinct human contributors so far, plus one open spot for you`}
      width="100%"
      viewBox={`0 0 ${(DOT_SIZE + DOT_GAP) * totalSlots} ${DOT_SIZE + 4}`}
      style={{ maxWidth: 360, overflow: "visible" }}
    >
      {dots.map((_, i) => (
        <circle
          key={`voter-dot-${i}`}
          data-testid="participation-graph-voter-dot"
          cx={i * (DOT_SIZE + DOT_GAP) + DOT_SIZE / 2}
          cy={DOT_SIZE / 2 + 2}
          r={DOT_SIZE / 2}
          fill="var(--bs-primary)"
        >
          <title>A ProxyPrints contributor</title>
        </circle>
      ))}
      {/* the dashed "open spot" - the invitation, not a real count */}
      <circle
        data-testid="participation-graph-join-dot"
        cx={joinDotIndex * (DOT_SIZE + DOT_GAP) + DOT_SIZE / 2}
        cy={DOT_SIZE / 2 + 2}
        r={DOT_SIZE / 2 - 1}
        fill="none"
        stroke="var(--theme-muted)"
        strokeWidth={1.5}
        strokeDasharray="3 2"
      >
        <title>
          {overflow > 0
            ? `You could be next (+${overflow} more contributors not pictured)`
            : "You could be next"}
        </title>
      </circle>
    </svg>
  );
}

function opportunityRows(participation: Participation): BarRow[] {
  return [
    {
      label: "Ready to confirm",
      segments: [
        {
          key: "confirmable",
          label: "Ready to confirm",
          value: participation.confirmable,
        },
      ],
    },
    {
      label: "Needs a tiebreaker",
      segments: [
        {
          key: "contested",
          label: "Needs a tiebreaker",
          value: participation.contested,
        },
      ],
    },
  ];
}

export function ParticipationGraph({
  participation,
}: {
  participation: Participation;
}) {
  return (
    <div data-testid="participation-graph" className="my-4">
      <h2>The catalog needs human eyes</h2>
      <p className="text-muted">
        The machine calculators do the heavy lifting of narrowing every card
        down to a short list - a person still has to make the call. Here&apos;s
        what&apos;s waiting on you right now.
      </p>
      <HorizontalBarChart
        title="Cards a person could act on right now"
        bars={opportunityRows(participation)}
        legendKeys={["confirmable", "contested"]}
        emptyMessage="Nothing queued for review just yet."
      />
      <div className="mt-4">
        <p className="mb-1">
          <b data-testid="participation-graph-human-votes-total">
            {participation.humanVotes.total.toLocaleString()}
          </b>{" "}
          confirmations logged so far by{" "}
          <b data-testid="participation-graph-distinct-voters">
            {participation.distinctHumanVoters.toLocaleString()}
          </b>{" "}
          people. It&apos;s a small crew - which means one more person makes a
          real difference.
        </p>
        <VoterDotMatrix
          distinctHumanVoters={participation.distinctHumanVoters}
        />
      </div>
      <p className="mt-3">
        <Link href="/stats" className="btn btn-outline-light me-2">
          See the full stats
        </Link>
        <Link href="/whatsthat" className="btn btn-primary">
          Join them
        </Link>
      </p>
    </div>
  );
}
