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
 *
 * 2026-07-29 owner ruling, GATED addition on top of the above (this task's own directive): bring
 * the original fill-bar sketch back, but only once `humanProgressRatioPercent` (the same
 * `humanVotes.total / total` ratio the paragraph above reasons about) clears
 * `HUMAN_VOTE_REVEAL_PERCENT` (`humanProgressReveal.ts`, adjustable there / via
 * `NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT`). This does NOT relax either rule above: rule (1) is
 * satisfied because the ratio is only ever rendered as a bar WIDTH/colour, never as digits or a
 * "%" character - `HumanProgressBar` below labels itself with real counts, same as everywhere
 * else on this page; rule (2) is satisfied because the fill amount is `humanVotes.total`, a human
 * quantity. Below `HUMAN_VOTE_REVEAL_PERCENT` this graph is byte-for-byte the same component
 * described above - see `useHumanProgressReveal`/`HumanProgressBar` and
 * `humanProgressReveal.ts`'s own module comment for the gate itself.
 */
import Link from "next/link";
import React from "react";

import { Participation } from "@/common/schema_types";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";
import {
  humanProgressRatioPercent,
  shouldRevealHumanProgress,
} from "@/features/stats/humanProgressReveal";
import { useRemoteBackendConfigured } from "@/store/slices/backendSlice";

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

const HUMAN_PROGRESS_BAR_WIDTH = 420; // matches HorizontalBarChart's CHART_WIDTH - same rhythm
const HUMAN_PROGRESS_BAR_HEIGHT = 22;

/**
 * The gated fill-bar itself - one axis (x/width), one series, no legend (house rule: a single
 * series needs no legend, its own caption already names it). Colour is `var(--bs-primary)`, the
 * SAME token `VoterDotMatrix`'s dots and every CTA button on this page already use for "a human
 * did this" - not a new hue. The fill amount is `humanVotes.total` (a human quantity, rule (2) in
 * this file's own module comment); `ratioPercent` (from `humanProgressRatioPercent`, computed
 * exactly once by the caller - see that function's own units caveat) only ever drives the bar's
 * WIDTH, never rendered as digits or a "%" anywhere here or in its accessible name.
 */
function HumanProgressBar({
  humanVotesTotal,
  ratioPercent,
}: {
  humanVotesTotal: number;
  ratioPercent: number;
}) {
  const clampedPercent = Math.min(100, Math.max(0, ratioPercent));
  const fillWidth = (clampedPercent / 100) * HUMAN_PROGRESS_BAR_WIDTH;
  return (
    <svg
      role="img"
      aria-label={`${humanVotesTotal.toLocaleString()} human confirmations logged so far, shown as a share of the catalog`}
      width="100%"
      viewBox={`0 0 ${HUMAN_PROGRESS_BAR_WIDTH} ${HUMAN_PROGRESS_BAR_HEIGHT}`}
      style={{ maxWidth: HUMAN_PROGRESS_BAR_WIDTH, overflow: "visible" }}
      data-testid="participation-graph-human-progress-bar"
    >
      <rect
        x={0}
        y={0}
        width={HUMAN_PROGRESS_BAR_WIDTH}
        height={HUMAN_PROGRESS_BAR_HEIGHT}
        rx={4}
        fill="var(--theme-divider)"
      />
      <rect
        x={0}
        y={0}
        width={fillWidth}
        height={HUMAN_PROGRESS_BAR_HEIGHT}
        rx={4}
        fill="var(--bs-primary)"
      >
        <title>
          {humanVotesTotal.toLocaleString()} human confirmations logged
        </title>
      </rect>
    </svg>
  );
}

/**
 * Derives the revealed/hidden state from `shouldRevealHumanProgress` (`humanProgressReveal.ts`).
 * `useGetCatalogStatsQuery` (this graph's only caller, `pages/index.tsx`) fetches once with no
 * polling, so in practice this resolves once per page load starting from `wasPreviouslyRevealed
 * = false` - but it is still written as real hysteresis (not hard-coded to the no-history case)
 * so it degrades correctly if that ever changes (e.g. a future refetch-on-focus). Deliberately
 * in-memory only (React state, reset on every fresh page load) rather than persisted (e.g.
 * localStorage) - this repo's own standing rule is that state which should be server-derived must
 * not be persisted client-side across a "clear site data"/incognito test (see
 * `cardbackDefaultPreference.ts`'s own comment for that precedent); a value sitting in the
 * hysteresis band is a genuinely open question until the NEXT real data fetch settles it, not
 * something this browser should remember on its own.
 */
function useHumanProgressReveal(ratioPercent: number): boolean {
  const [revealed, setRevealed] = React.useState(() =>
    shouldRevealHumanProgress(ratioPercent, false)
  );
  const nextRevealed = shouldRevealHumanProgress(ratioPercent, revealed);
  if (nextRevealed !== revealed) {
    setRevealed(nextRevealed);
  }
  return nextRevealed;
}

/**
 * The call-to-action after the hollow "you could be next" dot - pitched at ONE card, not a
 * commitment, per this task's directive. Gated on `remoteBackendConfigured`, the same condition
 * `Navbar.tsx` uses for its own What's That Card? link - a self-hosted instance with no backend
 * configured has nothing at `/whatsthat` to send anyone to. A plain Bootstrap `.btn` (not a new
 * style) gives it Bootstrap's own default visible focus ring for free, same as every other button
 * on this page.
 */
function StartWithOneCardButton() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  if (!remoteBackendConfigured) {
    return null;
  }
  return (
    <p className="mt-2 mb-0">
      <Link
        href="/whatsthat"
        className="btn btn-primary"
        data-testid="participation-graph-start-one-card"
      >
        Start with one card
      </Link>
    </p>
  );
}

export function ParticipationGraph({
  participation,
}: {
  participation: Participation;
}) {
  // Computed exactly once, here, and threaded into both the gate below AND HumanProgressBar's
  // width - see humanProgressReveal.ts's own module comment for why that single-computation rule
  // matters (a mismatch is exactly how the series could unlock while still rendering as a
  // hairline).
  const ratioPercent = humanProgressRatioPercent(participation);
  const humanProgressRevealed = useHumanProgressReveal(ratioPercent);

  return (
    <div data-testid="participation-graph" className="my-4">
      {humanProgressRevealed ? (
        <>
          <h2>People are turning that into progress</h2>
          <p className="text-muted">
            The machine calculators still narrow every card down to a short
            list, but a real, growing share of the catalog now carries an actual
            person&apos;s judgment. Here&apos;s how far a small crew has taken
            it - and what&apos;s still waiting on you.
          </p>
        </>
      ) : (
        <>
          <h2>The catalog needs human eyes</h2>
          <p className="text-muted">
            The machine calculators do the heavy lifting of narrowing every card
            down to a short list - a person still has to make the call.
            Here&apos;s what&apos;s waiting on you right now.
          </p>
        </>
      )}
      <HorizontalBarChart
        title="Cards a person could act on right now"
        bars={opportunityRows(participation)}
        legendKeys={["confirmable", "contested"]}
        emptyMessage="Nothing queued for review just yet."
      />
      {humanProgressRevealed && (
        <div className="mt-4" data-testid="participation-graph-human-progress">
          <p className="mb-1">
            <b data-testid="participation-graph-human-progress-count">
              {participation.humanVotes.total.toLocaleString()}
            </b>{" "}
            human confirmations are on the board now, and it shows - growing
            every time someone new joins in.
          </p>
          <HumanProgressBar
            humanVotesTotal={participation.humanVotes.total}
            ratioPercent={ratioPercent}
          />
        </div>
      )}
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
        <StartWithOneCardButton />
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
