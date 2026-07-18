```
TASK: Proposal H — URGENT production build failure blocking /display
going live (deploy-frontend.yml #106/#107). Branch:
claude/proposal-h-urgent-build-fix-04bam2. PR: #90 (MERGED, commit
5f53901c → af88d9bc on master).

WHAT SHIPPED:
1. Diagnosed the real failure from actual CI job logs (deploy-frontend
   .yml runs #106 and #107), not just a local repro guess: both runs
   failed with the identical tsc error at DisplayPage.tsx:555 -
   `Type '{ [identifier: string]: Card | undefined; }' is not
   assignable to type '{ [identifier: string]: Card; }'`. Critically,
   run #106 (commit cba64b9c, PR #82's bleed dimension-basis change)
   failed BEFORE deploy-frontend.yml was even updated to set
   NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true - disproving the initial
   "the flag flip is the delta" framing before further time was spent
   chasing a prerender/browser-API hypothesis that wasn't the actual
   cause.
2. Root cause: `DisplayPage.tsx`'s `RailProps.cardDocumentsByIdentifier`
   was typed as `{ [id]: CardDocument }` (no undefined) when Step 1
   (this task's own earlier PR #87) was written. A same-day, unrelated
   PR (task #135, fixing a real crash in BleedOverrideSettings)
   correctly widened `useCardDocumentsByIdentifier()`'s own return
   type to `{ [id]: CardDocument | undefined }` - a project member's
   CardDocument genuinely can be unfetched, and the old type was
   hiding that. Once both PRs landed on master together, the
   (correctly widened) hook output no longer satisfied the (still
   narrow) prop type - a cross-PR interaction neither branch's own
   pre-merge CI could have caught alone, since each was internally
   type-correct against its own base commit.
3. Fix: widened `RailProps.cardDocumentsByIdentifier` to `{ [id]:
   CardDocument | undefined }`, matching the pattern already
   established elsewhere in this exact area of the codebase
   (`PDF.tsx`/`PDFGenerator.tsx` both already type this shape the
   same way, with `.filter((d): d is CardDocument => d !== undefined)`
   used wherever a flat array is built from it). Every actual field
   access in DisplayPage.tsx already used `?.` defensively - confirmed
   by reading every call site before concluding this was type-only,
   not a hidden runtime bug too.
4. Added a standing verification-bar lesson to docs/lessons.md: any
   flag-gated page needs a real `FLAG=true npx next build` before its
   PR ships, since a dev-server Playwright suite never exercises the
   production static-export type-check/prerender path. Also documents
   the cross-PR-interaction failure class itself (two independently
   correct PRs composing red) and the worktree-node_modules-copy false
   negative this task hit while diagnosing (see below).
5. Opened PR #90 (real PR, normal review flow, not draft), which the
   owner merged directly (this session did not merge it).

DEVIATIONS from spec, each with reasoning:
1. The task brief's initial hypothesis (prerender/browser-API
   incompatibility, e.g. window/document/localStorage access) was
   NOT the actual cause - disproven by comparing run #106 (flag still
   off) against run #107 (flag on): both failed identically, which a
   prerender-only bug gated behind the flag could not explain. Verified
   via actual GitHub Actions job logs before committing to a diagnosis,
   not by trusting the framing in the initial task description. A
   later message mid-task independently arrived at the same corrected
   diagnosis (Card | undefined type-tightening from PR #82) before this
   session's own fix was pushed - both arrived at the identical root
   cause and fix independently.
2. First local reproduction attempt gave a false negative: a git
   worktree with `node_modules` copied from another checkout (to skip
   a slow reinstall) built clean, because copying node_modules skips
   `npm install`'s postinstall step, which generates
   `frontend/src/common/generated/keyruneCodepoints.json` (gitignored,
   not committed - confirmed via `git check-ignore -v`). Running that
   generation script directly, and confirming the worktree was
   actually on the failing commit (93059f1b, not a stale earlier one -
   the worktree's initial checkout predated a same-day workflow-file
   commit), reproduced the real error. Documented in docs/lessons.md
   as its own trap, not just narrated in this report.

VERIFICATION:
- `NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build` - now
  succeeds (previously failed with the exact reported error,
  reproduced first, fix verified second).
- `npx next build` (flag off, default) - still succeeds, unaffected.
- `tsc --noEmit` - clean.
- Full Jest suite - 345/345 passing.
- `tests/DisplayPage.spec.ts` (7 Playwright tests against `next dev`,
  the sandbox's pinned-vs-available Chromium mismatch worked around
  with a LOCAL-ONLY, fully-reverted executablePath override exactly
  as in prior passes of this task - confirmed via git diff showing
  zero net change to global-setup.ts/playwright.config.ts beyond the
  one intentional env-var addition) - all still passing, confirming
  the type-only fix caused zero runtime behavior change.
- `eslint` on the changed file - clean, no new warnings.
- PR #90's own CI (GitHub Actions, not just local runs) confirmed
  green before this report was written: "Formatting and static type
  checking," all 4 "Frontend tests" shards, "Lint docs/," and
  "Merge Playwright reports" all reported conclusion=success.
- PR #90 has since been MERGED by the owner (af88d9bc on master) -
  confirmed via a fresh `git fetch origin master` before writing this
  report, not assumed from the merge-notification event alone.

OPEN ITEMS / DECISIONS NEEDED:
1. deploy-frontend.yml should re-fire automatically now that the fix
   is on master (per the owner's own note - workflow + variable
   already in place, nothing further needed from this session). Not
   independently re-checked from here after the merge - the owner's
   stated expectation is that it fires automatically; if it doesn't,
   that's a separate, new problem to report.
2. Proposal H Step 2 PR 2a (candidate/version picker) was in progress
   when this urgent task interrupted it - stashed cleanly on
   claude/proposal-h-2a-candidate-picker-04bam2, resuming next. That
   branch was forked from the now-fixed master commit's ancestor
   (93059f1b, pre-fix) - will need this fix's commit merged/rebased in
   before its own build-with-flag check can pass.

LIVE STATE:
- PR #90: MERGED. deploy-frontend.yml expected to re-fire
  automatically per the owner's note - not independently verified
  from this session post-merge.
- Branch claude/proposal-h-urgent-build-fix-04bam2: pushed, PR merged,
  safe to leave or delete per normal convention (not deleted from
  here).
- This report is being committed to a fourth relay branch,
  claude/proposal-h-relay3-04bam2 (forked fresh from the POST-MERGE
  origin/master, distinct from all three earlier relay branches per
  the bare-report-relay-name-retired lesson), which will be pushed and
  left for the owner to merge or discard.
- Resuming Proposal H Step 2 PR 2a (candidate picker) immediately
  after this report is relayed - stashed work is intact on its own
  branch, verified via `git stash list` before this report was
  written.
```
