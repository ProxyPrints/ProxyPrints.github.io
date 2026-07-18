As of: 2026-07-18
Task: Scryfall reference-image regression diagnosis + fix (amended: confirmed as a regression, not a missing feature)
Branch: `claude/level1-reference-image-fix` (based on `master`)

## Git archaeology findings

**(a) How the old implementation rendered the reference**: `frontend/src/features/printingTags/PrintingTagQueue.tsx`
(deleted in commit `9d71851`, "Queue redesign frontend") showed a Scryfall render for every
printing candidate in its grid, no gating, no exceptions - a plain `<img
src={candidate.mediumThumbnailUrl} alt="..." />` inside an `ArtPlaceholder`/`ZoomableThumbnail`
wrapper (hover-zoom, mystery-card placeholder backdrop). `mediumThumbnailUrl` is a field the
`PrintingCandidate` API response already carries - no special URL construction, just the field
straight into `<img src>`.

**(b) The exact commit where reference rendering stopped flowing for the case that broke**:
commit `b413252` (PR #49, "Funnel Levels 1+2+3: single-suggestion screen, collapsed candidate
filter, classified exits, conditional attribute confirm"). This is NOT the "Queue redesign"
commit the owner suspected first (`9d71851`) - that commit correctly carried the candidate image
forward (verified: `git show 9d71851:.../QuestionFeed.tsx` still has
`<img src={candidate.mediumThumbnailUrl}>` in its grid, and Level 2's grid on current `master`
still renders it correctly today). PR #49 introduced **Level 1** - an entirely new fast-path
screen for `confirm_suggestion` items with a `suggestedPrinting`, showing a single YES/NOT
SURE/NO/SKIP prompt instead of the full grid. Its confirmation prompt ("Is it this one?") was
built from scratch as **text only** (a `SetIcon` + expansion code + collector number) - the
`<img>` for `item.suggestedPrinting.mediumThumbnailUrl` was never added. This is a real
regression class: not an element carried over incorrectly, but a **new UI surface built without
inventorying what the screen it bypasses (Level 2's grid) actually shows**. Confirmed still
present on current `master` before this fix.

**(c) Was Level 0's compare built on the already-broken path?** No. `DeckbuilderConfirmAffordance.tsx`
(PR #50, `79933ed`, built after #49) does its own independent `APIGetPrintingCandidates` fetch
(searching by expansion code + collector number, `triggerCompare`) and correctly renders a real
`<img src={referenceCandidate.mediumThumbnailUrl}>` inside a `ComparePin` element. It was never
built on Level 1's pattern and doesn't share its bug. Level 0 works correctly, confirmed by
reading its full implementation - not affected by this fix.

## What shipped

Restored the missing reference image in `QuestionFeed.tsx`'s Level 1, using the exact same
mechanism Level 2's grid already uses correctly (no new URL construction, no new rendering
approach): `item.suggestedPrinting.mediumThumbnailUrl` into the same `ArtPlaceholder`/
`ZoomableThumbnail` wrapper components (`cardPanel.tsx`, already imported in this file), sized to
160px max-width and centered above the "Is it this one?" prompt.

## Verification

- `npx tsc --noEmit`: clean.
- `npx eslint`: 0 errors (1 new `no-img-element` warning, matching the file's 4 pre-existing ones
  for the same reason - no `next/image` usage anywhere in this file for candidate thumbnails).
- `npx jest --runInBand`: **285/285 passing** (1 new: asserts the reference image's `src`
  matches the suggested printing's `mediumThumbnailUrl` on Level 1). Zero regressions across the
  other 12 pre-existing `QuestionFeed.test.tsx` tests.
- Real-browser Playwright, `tests/QuestionFeedConfirmSuggestion.spec.ts` (5/5 passing at
  `--workers=1`), including the new assertion that the reference image is visible with the
  correct `src` on Level 1, plus confirmation the existing YES/NOT SURE/NO/SKIP and mobile-overlap
  tests still pass unaffected.
- Real-browser Playwright, the three other QuestionFeed suites this could plausibly have touched
  (`QuestionFeedLevels.spec.ts`, `QuestionFeedArtistAndTag.spec.ts`, `NoMatchReasonStrip.spec.ts`):
  **13/13 passing**, zero regressions.

## Deviations

None from the authorized scope for the git-archaeology and restoration itself. **The message's
"fix items (a)/(b)/(c) from the main block" are NOT addressed here** - that "main block" was
never received in this session's context (only this amendment message was). I completed the
self-contained parts of this message (archaeology with named findings, the mechanical restoration
per "restore the proven mechanism," the lessons.md entry) but did not guess at or implement
whatever else the missing main block specified. If there's more scope beyond restoring the
reference image itself, please relay it.

## Open items / decisions needed

1. What did "the main block"'s own fix items (a)/(b)/(c) actually ask for, beyond restoring the
   reference image itself? This session never received that message.

## Unrelated, time-sensitive finding surfaced while working on this

While checking PR states for this task, found several of this session's currently-open stacked
PRs were auto-closed by GitHub's base-branch-deletion behavior (already documented in
`docs/lessons.md`'s "A stacked PR's base branch gets deleted out from under it when the parent
merges" entry, hit for the first time on `claude/e2-bleed-prior-batch-resolution`/PR #69 earlier
in this session, and now recurring): PR #69 and PR #71 are permanently closed (GitHub 422s on
reopen once the base branch is gone), but PR #73 (head `claude/e4-bleed-preview-badge`) was still
open with its base branch (`claude/e3-bleed-override-ui`) not yet deleted - retargeted it to
`master` immediately (`gh pr edit --base master` equivalent) per the lesson's own documented
prevention, before it could suffer the same fate. PR #73 now carries the combined, previously-
"lost" work of PR-1 (batch prior resolution), PR-2 (manual override UI), and PR-3 (preview badge)
in one PR against `master`, and needs a conflict resolution pass (master has moved on since these
branches diverged) - tracked as a separate, immediate follow-up, not part of this task's own
scope.
