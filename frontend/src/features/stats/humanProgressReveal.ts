/**
 * 2026-07-29 owner ruling on top of PR #558's ParticipationGraph.tsx (see that file's own module
 * comment for the full "why a literal fill-bar reads as a dead 0.74px stripe today" reasoning,
 * which still governs everything BELOW the threshold defined here): the owner's original
 * "progress bar" sketch is not wrong, it was just premature at today's ~0.1% human/total ratio.
 * This module is the gate that brings it back once - and only once - it would actually be
 * legible, plus the single accessor both the gate and the drawn series read from.
 *
 * `HUMAN_VOTE_REVEAL_PERCENT` is a real percentage (not a raw vote/card count), adjustable in
 * one line right here, and overridable at build time via the `NEXT_PUBLIC_` env var below so a
 * self-hoster running a smaller (or larger) catalog can tune when their own progress series
 * becomes legible without editing source. Next.js inlines `NEXT_PUBLIC_*` vars at build time, so
 * this is intentionally a module-level constant (read once, at import/build time) rather than a
 * function re-reading `process.env` on every call.
 */
export const HUMAN_VOTE_REVEAL_PERCENT = Number(
  process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT ?? 10
);

/**
 * Hysteresis band, in percentage points, around `HUMAN_VOTE_REVEAL_PERCENT`: once revealed, the
 * series only hides again after the ratio drops below `HUMAN_VOTE_REVEAL_PERCENT -
 * HUMAN_VOTE_REVEAL_HYSTERESIS_PP`. Without this, a ratio sitting right on the boundary (e.g.
 * `total` ticking up or down slightly as the catalog is re-crawled) would flip the homepage
 * layout on and off from one load to the next. See `shouldRevealHumanProgress` below for the
 * actual rule, and `ParticipationGraph.tsx`'s `useHumanProgressReveal` for how the "previously
 * revealed" side of that rule is tracked (in-memory only, per this repo's own standing rule
 * against persisting client-side state that should be server-derived - see
 * `cardbackDefaultPreference.ts`'s own comment for that precedent).
 */
export const HUMAN_VOTE_REVEAL_HYSTERESIS_PP = 1;

/**
 * The single named accessor for "how much of the catalog has human judgment on it" - the ONE
 * place this ratio is computed. Both the reveal gate (`shouldRevealHumanProgress`) and the drawn
 * series (`ParticipationGraph.tsx`'s `HumanProgressBar`) must call this same function on the same
 * `participation` object, never recompute it separately - otherwise the series could unlock
 * while still rendering as a hairline, which is the exact failure this feature exists to prevent.
 *
 * UNITS CAVEAT (deliberately not papered over): `participation.humanVotes.total` counts VOTES;
 * `participation.total` counts CARDS. One card can carry several human votes (a printing tag, an
 * artist vote, and a descriptor tag are all independent votes on the same card), so this ratio
 * over-counts relative to "distinct cards with at least one human vote" - it is an approximation
 * of catalog coverage, not an exact measure. Swapping to an exact backend field (distinct cards
 * carrying >= 1 human vote) later is a one-line change to this function's body only - see this
 * task's own report for the proposed field.
 */
export function humanProgressRatioPercent(participation: {
  total: number;
  humanVotes: { total: number };
}): number {
  if (participation.total <= 0) {
    return 0;
  }
  return (participation.humanVotes.total / participation.total) * 100;
}

/**
 * Pure hysteresis rule: reveal once `ratioPercent` reaches `HUMAN_VOTE_REVEAL_PERCENT`; once
 * revealed, only hide again once it falls below `HUMAN_VOTE_REVEAL_PERCENT -
 * HUMAN_VOTE_REVEAL_HYSTERESIS_PP`. `wasPreviouslyRevealed` is the caller's own last decision for
 * this same ratio source - a fresh evaluation with no prior state (the common case: this
 * component's data query runs once, with no persisted cross-load memory) always starts from
 * `false` and so applies the plain `>= HUMAN_VOTE_REVEAL_PERCENT` rule. Deterministic: calling
 * this twice with the same two arguments always returns the same result, so a ratio sitting
 * exactly at either boundary never flips between consecutive evaluations of identical inputs.
 */
export function shouldRevealHumanProgress(
  ratioPercent: number,
  wasPreviouslyRevealed: boolean
): boolean {
  if (wasPreviouslyRevealed) {
    return (
      ratioPercent >=
      HUMAN_VOTE_REVEAL_PERCENT - HUMAN_VOTE_REVEAL_HYSTERESIS_PP
    );
  }
  return ratioPercent >= HUMAN_VOTE_REVEAL_PERCENT;
}
