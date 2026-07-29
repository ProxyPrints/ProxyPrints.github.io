import { Participation } from "@/common/schema_types";

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
 *
 * 2026-07-29 consumer swap: this module's ratio moved from the votes-over-cards approximation
 * (`humanVotes.total / total`) onto the card-denominated
 * `distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview` - see
 * `humanProgressRatioPercent`'s own comment below. `HUMAN_VOTE_REVEAL_PERCENT`/
 * `HUMAN_VOTE_REVEAL_HYSTERESIS_PP` keep their existing meaning and values unchanged - only what
 * they're compared against moved.
 */
export const HUMAN_VOTE_REVEAL_PERCENT = Number(
  process.env.NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT ?? 10
);

/**
 * Hysteresis band, in percentage points, around `HUMAN_VOTE_REVEAL_PERCENT`: once revealed, the
 * series only hides again after the ratio drops below `HUMAN_VOTE_REVEAL_PERCENT -
 * HUMAN_VOTE_REVEAL_HYSTERESIS_PP`. Without this, a ratio sitting right on the boundary (e.g.
 * `distinctCardsRoutedToReview` ticking up as the sweep routes one more card) would flip the
 * homepage layout on and off from one load to the next. See `shouldRevealHumanProgress` below
 * for the actual rule, and `ParticipationGraph.tsx`'s `useHumanProgressReveal` for how the
 * "previously revealed" side of that rule is tracked (in-memory only, per this repo's own
 * standing rule against persisting client-side state that should be server-derived - see
 * `cardbackDefaultPreference.ts`'s own comment for that precedent).
 */
export const HUMAN_VOTE_REVEAL_HYSTERESIS_PP = 1;

/**
 * The single named accessor for "how much of the reviewed-to-a-human-being-needed queue actually
 * has a human's judgment on it" - the ONE place this ratio is computed. Both the reveal gate
 * (`shouldRevealHumanProgress`) and the drawn series (`ParticipationGraph.tsx`'s
 * `HumanProgressBar`) must call this same function on the same `participation` object, never
 * recompute it separately - otherwise the series could unlock while still rendering as a
 * hairline, which is the exact failure this feature exists to prevent.
 *
 * `distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview` - cards over cards,
 * not votes over cards (the prior `humanVotes.total / total` approximation this replaces, and
 * its units-mismatch caveat, are gone: the numerator here is a proper SUBSET of the denominator
 * by construction - see `Participation.distinctCardsRoutedToReviewWithHumanVotes`'s own comment
 * in `common/schema_types.ts` - so this ratio has no equivalent caveat to carry).
 *
 * Returns `null`, never `NaN`/a fabricated number, when the three card-denominated fields are
 * not ALL present, finite numbers on the given object. This is not merely defensive - it is
 * expected, guaranteed-to-happen input during this feature's own rollout window:
 * `Participation`'s TS type declares these fields as required, but the LIVE production API
 * (`GET 1/catalogStats/`) will not actually send them until the backend is redeployed past PR
 * #566 - `frontend/src/store/api.ts`'s `getCatalogStats` endpoint trusts the fetch response's
 * shape directly (no runtime validation), so a real response genuinely missing these fields
 * reaches this function exactly as typed, just without the fields existing at runtime. `null`
 * means "not revealed yet, the same truthful state as today" - callers (`shouldRevealHumanProgress`)
 * must treat it as unconditionally below-threshold, never divide-by-undefined into NaN.
 */
export function humanProgressRatioPercent(
  participation: Partial<
    Pick<
      Participation,
      | "distinctCardsRoutedToReview"
      | "distinctCardsRoutedToReviewWithHumanVotes"
    >
  >
): number | null {
  const {
    distinctCardsRoutedToReview,
    distinctCardsRoutedToReviewWithHumanVotes,
  } = participation;
  if (
    typeof distinctCardsRoutedToReview !== "number" ||
    !Number.isFinite(distinctCardsRoutedToReview) ||
    typeof distinctCardsRoutedToReviewWithHumanVotes !== "number" ||
    !Number.isFinite(distinctCardsRoutedToReviewWithHumanVotes)
  ) {
    return null;
  }
  if (distinctCardsRoutedToReview <= 0) {
    return 0;
  }
  return (
    (distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview) *
    100
  );
}

/**
 * Pure hysteresis rule: reveal once `ratioPercent` reaches `HUMAN_VOTE_REVEAL_PERCENT`; once
 * revealed, only hide again once it falls below `HUMAN_VOTE_REVEAL_PERCENT -
 * HUMAN_VOTE_REVEAL_HYSTERESIS_PP`. `ratioPercent === null` (the live-skew guard - see
 * `humanProgressRatioPercent`'s own comment) is unconditionally treated as hidden, regardless of
 * `wasPreviouslyRevealed`: "the fields aren't there this load" is never a reason to keep showing
 * a series computed from data that no longer exists. `wasPreviouslyRevealed` is the caller's own
 * last decision for this same ratio source - a fresh evaluation with no prior state (the common
 * case: this component's data query runs once, with no persisted cross-load memory) always
 * starts from `false` and so applies the plain `>= HUMAN_VOTE_REVEAL_PERCENT` rule.
 * Deterministic: calling this twice with the same two arguments always returns the same result,
 * so a ratio sitting exactly at either boundary never flips between consecutive evaluations of
 * identical inputs.
 */
export function shouldRevealHumanProgress(
  ratioPercent: number | null,
  wasPreviouslyRevealed: boolean
): boolean {
  if (ratioPercent == null) {
    return false;
  }
  if (wasPreviouslyRevealed) {
    return (
      ratioPercent >=
      HUMAN_VOTE_REVEAL_PERCENT - HUMAN_VOTE_REVEAL_HYSTERESIS_PP
    );
  }
  return ratioPercent >= HUMAN_VOTE_REVEAL_PERCENT;
}
