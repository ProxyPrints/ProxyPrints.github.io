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
 */
import { Participation } from "@/common/schema_types";

export const participationCurrentRatio: Participation = {
  total: 230_770,
  confirmable: 103_687,
  contested: 6_307,
  fresh: 120_776,
  humanVotes: { printingTag: 125, artist: 6, tag: 106, total: 237 },
  distinctHumanVoters: 11,
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
  md5Groups: {
    groupsWithMultipleCards: 16_957,
    cardsInMultiCardGroups: 34_095,
    largestGroupSize: 5,
  },
};
