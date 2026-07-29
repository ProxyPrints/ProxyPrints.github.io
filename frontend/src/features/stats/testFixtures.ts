/**
 * Shared `CatalogStatsResponse.participation` fixtures for /stats + the homepage participation
 * graph - used by both `src/mocks/handlers.ts` (MSW, for component/Playwright tests hitting a
 * real page load) and this feature's own Jest unit tests, so the two never drift apart.
 *
 * Two fixtures, not one - `CURRENT_RATIO` matches this task's own directive's real, measured
 * 2026-07-29 production numbers (0.05% human/machine vote ratio). `POST_SWEEP` models the world
 * after the pending full machine sweep the 2026-07-29 coordinator amendment describes:
 * `confirmable`/`contested` grow substantially (more machine work becomes human-actionable
 * candidate work), `humanVotes`/`distinctHumanVoters` are held FLAT - the amendment's own
 * instruction ("human votes unchanged at ~237") - so the ratio gets WORSE, not better. Any
 * component reading `participation` must read the same under both fixtures (see
 * ParticipationGraph.test.tsx's own "reads correctly against both fixtures" test) - if it
 * doesn't, that component has smuggled in a dependency on the ratio this task's directive
 * forbids rendering.
 *
 * A third fixture, `participationAtRevealThreshold` (2026-07-29 owner ruling,
 * `features/stats/humanProgressReveal.ts`) - a hypothetically much smaller catalog (2,370 cards)
 * carrying the SAME real 237 human votes, so `humanVotes.total / total` lands at exactly
 * `HUMAN_VOTE_REVEAL_PERCENT`'s default of 10%. Pinned to that default rather than computed from
 * the live `HUMAN_VOTE_REVEAL_PERCENT` export on purpose - a fixture that silently retargets
 * itself whenever the threshold constant changes would stop testing "exactly at the boundary" and
 * start testing "wherever the boundary currently is", which is not the same guarantee.
 */
import { Participation } from "@/common/schema_types";

// distinctCardsWithHumanVotes/distinctCardsRoutedToReview/distinctCardsRoutedToReviewWithHumanVotes
// (added by the catalog-stats-distinct-cards PR, not independently measured against production
// like the fields above) - illustrative placeholder figures only, chosen to satisfy the
// Participation shape while respecting its real invariants: distinctCardsWithHumanVotes <=
// humanVotes.total (votes can stack on one card), and
// distinctCardsRoutedToReviewWithHumanVotes <= min(distinctCardsWithHumanVotes,
// distinctCardsRoutedToReview) (it is that pair's intersection). Held flat across both fixtures,
// same as humanVotes/distinctHumanVoters above - this task does not model how a full machine
// sweep would move the review-routing counts, so it is deliberately not asserted here.
export const participationCurrentRatio: Participation = {
  total: 230_770,
  confirmable: 103_687,
  contested: 6_307,
  fresh: 120_776,
  humanVotes: { printingTag: 125, artist: 6, tag: 106, total: 237 },
  distinctHumanVoters: 11,
  distinctCardsWithHumanVotes: 218,
  distinctCardsRoutedToReview: 42_000,
  distinctCardsRoutedToReviewWithHumanVotes: 9,
  md5Groups: {
    groupsWithMultipleCards: 16_957,
    cardsInMultiCardGroups: 34_095,
    largestGroupSize: 5,
  },
};

export const participationPostSweep: Participation = {
  total: 230_770,
  confirmable: 190_000,
  contested: 18_000,
  fresh: 22_770,
  humanVotes: { printingTag: 125, artist: 6, tag: 106, total: 237 },
  distinctHumanVoters: 11,
  distinctCardsWithHumanVotes: 218,
  distinctCardsRoutedToReview: 42_000,
  distinctCardsRoutedToReviewWithHumanVotes: 9,
  md5Groups: {
    groupsWithMultipleCards: 16_957,
    cardsInMultiCardGroups: 34_095,
    largestGroupSize: 5,
  },
};

// 237 / 2_370 = exactly 10% - see this file's own module comment for why the denominator is
// pinned to a literal rather than derived from the live HUMAN_VOTE_REVEAL_PERCENT export.
//
// distinctCardsWithHumanVotes/distinctCardsRoutedToReview/distinctCardsRoutedToReviewWithHumanVotes
// are pinned to exactly 10% on BOTH ratios this fixture can back - the current votes-over-cards
// one (humanVotes.total / total = 237 / 2_370) AND the card-denominated one the deferred consumer
// swap will move the gate onto (distinctCardsRoutedToReviewWithHumanVotes /
// distinctCardsRoutedToReview = 100 / 1_000). A future editor changing one set of numbers to
// retarget this fixture at a different percentage must keep the other consistent, or this
// fixture stops meaning "exactly at the reveal boundary" under one of the two ratios.
export const participationAtRevealThreshold: Participation = {
  total: 2_370,
  confirmable: 1_400,
  contested: 300,
  fresh: 670,
  humanVotes: { printingTag: 125, artist: 6, tag: 106, total: 237 },
  distinctHumanVoters: 11,
  distinctCardsWithHumanVotes: 218, // <= humanVotes.total (237)
  distinctCardsRoutedToReview: 1_000, // <= total (2_370)
  distinctCardsRoutedToReviewWithHumanVotes: 100, // 100 / 1_000 = exactly 10%
  md5Groups: {
    groupsWithMultipleCards: 169,
    cardsInMultiCardGroups: 340,
    largestGroupSize: 5,
  },
};
