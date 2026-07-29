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
 * the original fill-bar sketch back, but only once `humanProgressRatioPercent` clears
 * `HUMAN_VOTE_REVEAL_PERCENT` (`humanProgressReveal.ts`, adjustable there / via
 * `NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT`). This does NOT relax either rule above: rule (1) is
 * satisfied because the ratio is only ever rendered as a bar WIDTH/colour, never as digits or a
 * "%" character - `HumanProgressBar` below labels itself with real counts, same as everywhere
 * else on this page; rule (2) is satisfied because the fill amount tracks
 * `distinctCardsRoutedToReviewWithHumanVotes`, a human quantity.
 *
 * 2026-07-29 CONSUMER SWAP (this task's own directive, items 1-3): the gate and the drawn series
 * both moved off the votes-over-cards approximation above and onto the exact, card-denominated
 * ratio `distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview` - see
 * `humanProgressRatioPercent`'s own comment in `humanProgressReveal.ts`. The old
 * `humanVotes.total / total` path (and its units-mismatch caveat) is gone entirely, not kept as
 * a fallback. Three consequences that show up directly in this file:
 *   - `humanProgressRatioPercent` can now return `null` (the LIVE production API will not carry
 *     these three fields until it's redeployed past PR #566 - see this task's own PR description,
 *     "the API will not have these fields yet"). `null` is treated as unconditionally
 *     below-threshold by `shouldRevealHumanProgress` - this component never needs its own
 *     null-check because that guard already lives in the single accessor.
 *   - The revealed headline FLIPS framing (below threshold: the `confirmable` opportunity/CTA
 *     framing, unchanged from today; at/above threshold: a "cards the machine routed to people"
 *     framing - see the two `<h2>`/`<p>` pairs below). This flip is driven by the same
 *     `humanProgressRevealed` boolean as the bar itself, which means it inherits that boolean's
 *     hysteresis but is NOT a one-way latch: `distinctCardsRoutedToReview` only ever grows (see
 *     its own doc comment in `common/schema_types.ts`), so the ratio CAN retreat below the
 *     hysteresis floor even while people are actively voting (denominator outrunning numerator) -
 *     if it does, the headline reverts to the below-threshold framing on the next load. Known,
 *     accepted limitation, not fixed this pass - tracked as orchestration issue #22 (a "once
 *     earned, stays earned" one-way latch was considered and deferred).
 *   - `ReviewedCardCount` below exists specifically because of that same denominator-growth
 *     property - see its own comment for why the bar alone would understate progress on a
 *     net-positive day.
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
import { useHasContributedThisSession } from "@/features/stats/sessionContributionSlice";
import { useRemoteBackendConfigured } from "@/store/slices/backendSlice";

const DOT_SIZE = 14;
const DOT_GAP = 6;
// Safety cap, not a tuned-to-the-fixture number - today's real distinctHumanVoters is 11 (see
// this task's own directive) and the whole point of this component is that a person-per-dot
// pictogram stays legible at this catalog's real, small human-contributor count. If that count
// ever grows past this cap, degrade to a "+N" label rather than silently drawing hundreds of
// circles into a fixed-height row.
const MAX_INDIVIDUAL_DOTS = 24;

/**
 * 2026-07-29 directive item 4 - the dashed "you could be next" mark becomes a filled, green,
 * "you're one of them" dot once THIS browser tab has cast a vote this session
 * (`hasContributedThisSession`, `sessionContributionSlice.ts`). Cross-session memory is
 * explicitly out of scope, on purpose - see that slice's own module comment for the two rejected
 * approaches (localStorage; a per-user "has this anonymous_id voted" endpoint). Colour is
 * `var(--bs-success)` - the site's existing status-good token (`colors.ts`'s
 * `STATUS_COLORS.completed`), not a new hue - and is never the ONLY signal: the accessible
 * name/title changes too, and a short thank-you paragraph renders alongside it, so the state
 * doesn't depend on colour perception alone.
 */
function VoterDotMatrix({
  distinctHumanVoters,
  hasContributedThisSession,
}: {
  distinctHumanVoters: number;
  hasContributedThisSession: boolean;
}) {
  const dotCount = Math.min(distinctHumanVoters, MAX_INDIVIDUAL_DOTS);
  const overflow = distinctHumanVoters - dotCount;
  const dots = Array.from({ length: dotCount });
  const joinDotIndex = dotCount; // drawn one slot after the last real dot
  const totalSlots = joinDotIndex + 1;
  const joinDotTitle = hasContributedThisSession
    ? "You're one of them - thank you"
    : overflow > 0
    ? `You could be next (+${overflow} more contributors not pictured)`
    : "You could be next";
  return (
    <>
      <svg
        role="img"
        aria-label={
          hasContributedThisSession
            ? `${distinctHumanVoters} distinct human contributors so far, including you`
            : `${distinctHumanVoters} distinct human contributors so far, plus one open spot for you`
        }
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
        {/* the "open spot" - dashed/hollow as an invitation until this client has voted, then a
            filled green "you're one of them" dot (see this function's own comment). */}
        <circle
          data-testid="participation-graph-join-dot"
          cx={joinDotIndex * (DOT_SIZE + DOT_GAP) + DOT_SIZE / 2}
          cy={DOT_SIZE / 2 + 2}
          r={DOT_SIZE / 2 - 1}
          fill={hasContributedThisSession ? "var(--bs-success)" : "none"}
          stroke={
            hasContributedThisSession
              ? "var(--bs-success)"
              : "var(--theme-muted)"
          }
          strokeWidth={1.5}
          strokeDasharray={hasContributedThisSession ? undefined : "3 2"}
        >
          <title>{joinDotTitle}</title>
        </circle>
      </svg>
      {hasContributedThisSession && (
        <p
          className="mt-2 mb-0 text-success"
          data-testid="participation-graph-thank-you"
        >
          <strong>Thanks</strong> - the card you voted on just moved one step
          closer to resolved.
        </p>
      )}
    </>
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
 * The always-rises reward count (2026-07-29 directive, item 3). `distinctCardsRoutedToReview` -
 * `humanProgressRatioPercent`'s own denominator - GROWS every time the machine sweep routes more
 * cards to review, so the ratio (and therefore `HumanProgressBar`'s width, right below this) can
 * FALL even on a day people are actively voting, simply because the denominator outran the
 * numerator. Read the bar's width alone on a day like that and the homepage would look like
 * ground is being LOST. `count` here is `distinctCardsRoutedToReviewWithHumanVotes` - the same
 * ratio's numerator - which never decreases (nothing un-votes a card), so it is the one number on
 * this page guaranteed to tell the true "is work accumulating" story. Do NOT remove this as
 * "redundant with the bar" - the bar and this count can legitimately move in opposite directions
 * at the same time.
 */
function ReviewedCardCount({ count }: { count: number }) {
  return (
    <p className="mb-1">
      <b data-testid="participation-graph-reviewed-count">
        {count.toLocaleString()}
      </b>{" "}
      routed cards carry a person&apos;s judgment now - a number that only ever
      goes up.
    </p>
  );
}

/**
 * The gated fill-bar itself - one axis (x/width), one series, no legend (house rule: a single
 * series needs no legend, its own caption already names it). Colour is `var(--bs-primary)`, the
 * SAME token `VoterDotMatrix`'s dots and every CTA button on this page already use for "a human
 * did this" - not a new hue. The fill amount is `reviewedWithHumanVotes`
 * (`distinctCardsRoutedToReviewWithHumanVotes`, a human quantity, rule (2) in this file's own
 * module comment); `ratioPercent` (from `humanProgressRatioPercent`, computed exactly once by the
 * caller - see that function's own comment) only ever drives the bar's WIDTH, never rendered as
 * digits or a "%" anywhere here or in its accessible name.
 */
function HumanProgressBar({
  reviewedWithHumanVotes,
  ratioPercent,
}: {
  reviewedWithHumanVotes: number;
  ratioPercent: number;
}) {
  const clampedPercent = Math.min(100, Math.max(0, ratioPercent));
  const fillWidth = (clampedPercent / 100) * HUMAN_PROGRESS_BAR_WIDTH;
  return (
    <svg
      role="img"
      aria-label={`${reviewedWithHumanVotes.toLocaleString()} routed cards carry a human vote, shown as a share of everything routed for review`}
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
          {reviewedWithHumanVotes.toLocaleString()} routed cards carry a human
          vote
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
 * something this browser should remember on its own. `ratioPercent === null` (the live-skew
 * guard, see `humanProgressRatioPercent`'s own comment) flows straight through
 * `shouldRevealHumanProgress` to `false`, with no special-casing needed here.
 */
function useHumanProgressReveal(ratioPercent: number | null): boolean {
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
  // hairline). May be `null` - the live-skew guard - if the API response doesn't (yet) carry the
  // three card-denominated fields; `useHumanProgressReveal` treats that as unconditionally
  // below-threshold, so nothing else in this component needs its own null-check.
  const ratioPercent = humanProgressRatioPercent(participation);
  const humanProgressRevealed = useHumanProgressReveal(ratioPercent);
  const hasContributedThisSession = useHasContributedThisSession();

  return (
    <div data-testid="participation-graph" className="my-4">
      {humanProgressRevealed ? (
        <>
          <h2>People are keeping up with what the machine routes to them</h2>
          <p className="text-muted">
            When the machine calculators can&apos;t confidently place a card on
            their own, the card gets routed to a person instead. Here&apos;s how
            much of that queue already carries someone&apos;s judgment -
            there&apos;s always more waiting on you.
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
      {humanProgressRevealed && ratioPercent != null && (
        <div className="mt-4" data-testid="participation-graph-human-progress">
          <ReviewedCardCount
            count={participation.distinctCardsRoutedToReviewWithHumanVotes}
          />
          <HumanProgressBar
            reviewedWithHumanVotes={
              participation.distinctCardsRoutedToReviewWithHumanVotes
            }
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
          hasContributedThisSession={hasContributedThisSession}
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
