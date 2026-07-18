As of: 2026-07-18
Task: PR #73 merge sequencing (task #135) — CI kick, conflict resolution, merge, deploy confirm
Branch/worktree: catalog-completion-part2

## What shipped

1. **CI kick investigation**: #73's fresh push (head `c0eea626`) showed
   zero check-runs after 10+ minutes. Ruled out a trigger-config problem
   first (workflow files on the branch were current; other branches were
   getting CI fine concurrently in the same window). Root cause found via
   `check-suites` API: only "GitHub Pages" and "Claude" app suites had
   registered for that SHA — no "GitHub Actions" suite at all, on two
   consecutive pushes. An empty-commit push didn't fix it (same
   symptom). Closing and reopening the PR did — the `reopened` event
   apparently forced GitHub to (re-)register the Actions check-suite,
   which then ran normally.
2. **Real merge conflict resolved** (authorized explicitly, since #73 was
   confirmed clear of the frontend session's queue — it was waiting on
   #73 to merge before touching the area again): two files, both
   additive-both-sides, not competing edits — verified this by reading
   every conflict block directly before touching anything:
   - `docs/proposals/proposal-b-bleed-normalization.md`: #73's own
     PR-3-shipped narrative (with its own now-stale "Not yet built" list)
     vs. my task #134 calibration-pass findings. Combined: kept #73's
     shipped narrative, corrected its "Not yet built" list down to just
     the XML field (the calibration item is now done), and appended the
     calibration findings + bleed-border tracking item from master.
   - `frontend/src/features/pdf/PDFGenerator.tsx`: PR-2's
     `BleedOverrideSettings` component vs. PR #81's
     `ImageFailureConfirmModal` component — two unrelated components
     git's diff happened to place adjacent. Kept both.
   - `bleedNormalize.ts` itself merged clean both times (no conflict) —
     confirms #82's rewrite of it isn't in master yet, as expected.
   - Verified before pushing: `tsc --noEmit` clean, `bleedNormalize. test.ts` 14/14, and — the actual point of task #135's hold —
     `PagePreview.spec.ts` 3/3 passing (this was the real render-crash
     failure flagged in checkpoint-2; now confirmed fixed, the frontend
     session's fix landed).
   - A third pre-existing unformatted file (`docs/reports/proposal-b- pr1-bleed-prior-batch-resolution.md`, untouched by either side's
     conflict but caught by the real CI's repo-wide prettier check) was
     found and fixed in a follow-up commit after the first CI run caught
     it — my own initial check only covered the two conflicted files,
     not the full repo; noting the gap so it doesn't repeat.
3. **Merged #73** (squash, branch deleted) at merge commit `5b2d08a4`.
   Pages deploy of that commit confirmed successful via the workflow-
   runs API (queued behind other concurrent sessions' runners for a
   bit, then ran and completed).

## Deviations

- None from the explicit authorization. The close/reopen kick was the
  second of the two mechanisms the instruction pre-authorized ("empty
  commit or close/reopen") — used after the first (empty commit) didn't
  work, not a third improvised mechanism.

## Verification

- CI anomaly root-caused via `check-suites` API comparison (this PR vs.
  concurrently-running other branches), not assumed from symptom alone.
- Both conflict resolutions verified via real `tsc`, real `jest`, and
  the real `PagePreview.spec.ts` Playwright suite locally before ever
  pushing — not just "no conflict markers remain."
- Final merge and Pages deploy both confirmed via `gh api` against the
  actual commit SHAs, not assumed from the merge action succeeding.

## For the frontend session's #82 rebase

Resolution landed across two commits on `claude/e4-bleed-preview-badge`
(now squash-merged into master as `5b2d08a4`):
`d6c955cd` (the conflict resolution itself) and `12d6a743` (a follow-up
prettier fix). #82 should rebase onto master at `5b2d08a4` or later —
`bleedNormalize.ts` is untouched by this merge (per above, #73 never
touched it), so #82's own rewrite of it should apply against master
cleanly; the proposal doc and `PDFGenerator.tsx` may need light
reconciliation against the "Not yet built"/`BleedOverrideSettings`
content this merge just landed.

## Open items

- HOLD #B (Part 4/LANDS) still needs someone with production DB access
  to run the real volume-check numbers — unchanged from the last report.
- #82 rebase is the frontend session's next step, per the standing
  sequencing.

## Live state

master deployed and live via Pages at commit `5b2d08a4`. Open PRs: #82
(untouched, queued for the frontend session's rebase). No scratch clones
left with uncommitted work.
