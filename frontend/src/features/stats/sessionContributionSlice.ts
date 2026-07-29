/**
 * In-session (memory only, never persisted) record of whether THIS browser tab has cast at
 * least one vote this session - drives `ParticipationGraph.tsx`'s dashed "you would be the Nth"
 * dot turning into a filled, green "thank you" dot once true (2026-07-29 directive, item 4).
 *
 * Two rejected approaches, on purpose (the repo's standing rule against persisting
 * server-derived state client-side - see `cardbackDefaultPreference.ts`'s own precedent):
 * `localStorage` (would keep claiming credit for a vote across reloads/new tabs/days after the
 * fact, well past the point the vote itself is just historical catalog state, not "you, right
 * now"), and a "has this anonymous_id voted" backend endpoint (per-user, effectively
 * uncacheable, and a standing way for anyone to probe whether an arbitrary anonymous_id has
 * contributed - a privacy leak with no offsetting benefit over the one browser tab that actually
 * cast the vote just remembering it locally for the rest of this session).
 *
 * Registered as a normal slice in the app's single Redux store (`store/store.ts`) - the same
 * "existing Redux wiring" every other cross-cutting piece of client state in this app already
 * uses (see `store/slices/*`) - so that a vote cast from the `/whatsthat` question feed
 * (`QuestionFeed.tsx`'s `bumpSessionCount`, which now also dispatches
 * `recordSessionContribution` alongside its existing per-vote counter) is visible back on the
 * homepage without either page needing to know about the other directly.
 */
import { createAppSlice, useAppSelector } from "@/common/types";
import { RootState } from "@/store/store";

interface SessionContributionState {
  hasContributedThisSession: boolean;
}

const initialState: SessionContributionState = {
  hasContributedThisSession: false,
};

export const sessionContributionSlice = createAppSlice({
  name: "sessionContribution",
  initialState,
  reducers: {
    // One-way for the session's lifetime (no "un-vote" case exists on the wire either) - once
    // true, stays true until a real page reload resets the in-memory store.
    recordSessionContribution: (state) => {
      state.hasContributedThisSession = true;
    },
  },
});

export const { recordSessionContribution } = sessionContributionSlice.actions;
export default sessionContributionSlice.reducer;

export const selectHasContributedThisSession = (state: RootState): boolean =>
  state.sessionContribution.hasContributedThisSession;

export const useHasContributedThisSession = (): boolean =>
  useAppSelector(selectHasContributedThisSession);
