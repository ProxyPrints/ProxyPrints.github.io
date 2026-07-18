# Question Feed double-asking fix — 2026-07-18

```
TASK: Fix Question Feed double-asking (singleton-candidate re-presented)
Branch: claude/questionfeed-double-ask-fix
Commit: 345d75c
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/101 (base master, open)

WHAT SHIPPED:
1. GENERAL RULE implemented: within a single question item's flow, a
   candidate the user has just rejected is never re-presented as a
   selectable answer at a later level. Level 1's NO now records the
   rejected suggestion's identifier client-side (`rejectedCandidateIds`
   state in QuestionFeed.tsx, reset every new item alongside all other
   per-question state) via a new `rejectSuggestion` handler, wired to
   the "No" button's onClick in place of the old bare
   `() => setStage("level2")`. NOT SURE is deliberately left unchanged
   (still `() => setStage("level2")` with no rejection recorded) - it's
   genuine uncertainty, not a rejection.
2. Level 1 NO where |candidates| = 1 (or where rejection empties the
   remaining set): the grid is skipped in effect - `visibleCandidates`
   computes to empty, a new `suggestionRejectedWithNoneLeft` flag drives
   contextual copy ("Got it - not that one. Is it any official printing
   at all?") in place of the generic "Which of these is it?" prompt, and
   a new grayed, non-interactive rejected-candidate context block
   (`data-testid="question-feed-rejected-context"`, "You said: not
   <SET> <NUM>") replaces the button that used to be there. The classified
   exit choices (None of these / Art matches, not an official printing /
   Skip) were ALREADY rendered unconditionally below the grid regardless
   of candidate count, so they fall through to visible with no new code -
   confirmed by reading the existing followUp==="none" block before
   writing anything.
3. Level 1 NO where other candidates remain: `nonRejectedCandidates`
   (all candidates minus rejectedCandidateIds) feeds the existing
   attribute-chip filter, so the grid shows the remaining candidates
   only, computed BEFORE the chip filter so "N hidden by your tags"
   still means only "hidden by your tags," not conflated with the
   rejection.
4. VOTE SEMANTICS AUDIT (done before coding, per the spec's own
   ordering): traced every call site of `selectCandidate` and confirmed
   Level 1's NO/NOT SURE cast ZERO votes today - there is no backend
   schema concept of "reject just this one candidate specifically," only
   a positive vote for one printing (`selectCandidate(candidate, false)`)
   or a generic `isNoMatch` for the whole set
   (`selectCandidate(undefined, true)`), cast only when the user
   eventually taps "None of these"/custom-art/skip. POST-FIX: identical -
   `rejectSuggestion` only ever changes what's DISPLAYED (adds to
   `rejectedCandidateIds`), never calls any vote-casting function itself.
   The one real negative vote per item still only happens once, at the
   same eventual exit tap as before this fix. No double-vote risk
   introduced by this change.
5. SIBLING SWEEP (owner's generalization, checked both):
   - Level 0 (`DeckbuilderConfirmAffordance.tsx`, in-context deckbuilder
     confirmation): NO calls `onOpenGridSelector()`, opening the slot's
     general `GridSelectorModal` search/browse UI. Judged CLEAN, not the
     same bug class - this is a different UI paradigm (open-ended search
     across all results for a query) from a guided funnel step; the
     rejected image being one of many results in a general browser is
     normal, expected browse behavior, not a re-ask of an already-answered
     question. No code change made here.
   - Level 3 (conditional open-attribute confirm): only ever renders
     questions for attribute groups `getOpenExclusionGroups` finds
     genuinely open on the CURRENTLY SELECTED candidate - it has no
     mechanism that could re-present an already-rejected option in the
     first place; "already answered" filtering is inherent to how it's
     scoped. Judged CLEAN. No code change made here.

DEVIATIONS from spec: none. All five numbered requirements in the
owner's spec were implemented/audited as specified.

VERIFICATION:
- Rewrote the one Playwright test whose assertion encoded the OLD buggy
  behavior (`tests/QuestionFeedConfirmSuggestion.spec.ts` - "NO drops to
  Level 2's candidate grid without casting a vote" asserted the rejected
  candidate WAS visible after NO; this was testing the bug, not a
  regression from the fix). Rewritten to assert: rejected candidate
  (printingCandidate1) no longer visible, the mock's other candidate
  (printingCandidate2) still visible, zero votes cast.
- Added `questionFeedConfirmSuggestionSingleton` mock
  (`frontend/src/mocks/handlers.ts`) - same shape as the existing
  `questionFeedConfirmSuggestion` mock but `candidates: [printingCandidate1]`
  only (matching `suggestedPrinting`), for exercising the exact bug
  the owner hit live.
- Added a new Playwright test using that mock: reject the only
  candidate -> candidate never becomes a selectable tile, contextual
  exit copy shown, grayed rejected-candidate context block visible,
  "None of these" (`question-feed-no-match`) reachable directly, zero
  votes cast.
- Full relevant Playwright suite run twice (once mid-fix, once after a
  prettier false-start was reverted - see below): `QuestionFeedConfirmSuggestion.spec.ts`, `QuestionFeedLevels.spec.ts`,
  `QuestionFeedArtistAndTag.spec.ts`, `QuestionFeedMobileLayout.spec.ts`,
  `QuestionFeedLayoutReconciliation.spec.ts` - final run: 21/21 passing,
  `--workers=1`.
- `npx jest QuestionFeed --runInBand`: 14/14 passing, unchanged - no
  unit test needed modification.
- `npx tsc --noEmit`: clean.
- `npx eslint` on all touched files: 0 errors, only pre-existing
  `<img>`-vs-`next/image` warnings (same warnings present before this
  change, unrelated).
- `npx prettier --check`: flagged all 5 touched files, but reproduced
  identically against unmodified master (git-stash-verified) - this is
  the repo's known, pre-existing prettier version/config drift (root
  3.8.1 vs frontend's own 3.7.4; see docs/lessons.md's prettier@2.7.1
  non-idempotency entry for the general shape of this class of issue).
  Ran `prettier --write` once to check whether it would produce a
  reviewable diff; it instead rewrote unrelated pre-existing code
  throughout the whole file (trailing commas, wrapping) with no relation
  to this change's own diff, so that write was reverted (git checkout +
  re-apply of only this task's own patch) rather than shipped - the
  final commit contains only this task's actual changes, no drive-by
  reformatting of unrelated lines.
- Deferred: no live-site check (cloud sandbox has no egress to
  proxyprints.ca - documented sandbox limitation, not specific to this
  task).

OPEN ITEMS / DECISIONS NEEDED:
1. PR #101 is open, unmerged - owner's call on merge timing.
2. Everything else remains queued per the owner's explicit priority
   ordering from earlier in this session: item (c) printing-info badge,
   /whatsthat branding integration, Artist Support Links v1 - none
   authorized to start yet. Standing pacing rule (from earlier this
   session) applies: stopping here to report rather than auto-starting
   the next queued item, since it's a new feature, not a follow-up to
   this fix.

LIVE STATE:
- Branch `claude/questionfeed-double-ask-fix` pushed to origin, PR #101
  open against master, not merged.
- This report's own branch `report-relay-6121bf36-5` (uniquely suffixed
  per the retired-bare-`report-relay` lesson) will be pushed immediately
  after this file is committed; not yet merged.
- No dev servers or other processes left running.
```
