```
TASK: PRIORITY BUG — editor -> /display false-positive unsaved-work
guard. Branch: claude/priority-fix-display-nav-unsaved-guard-04bam2
(PR #124, ready for merge). This report:
claude/priority-fix-relay-04bam2.

WHAT SHIPPED:

1. Diagnosis (the owner's explicit ask - determines whether any user
   could have actually lost work): the primary editor -> /display path
   (Navbar.tsx's `Nav.Link as={Link} href="/display"`) is ALREADY a
   genuine client-side next/link transition that correctly preserves
   the Redux store. Verified directly with Playwright: click the nav
   link, no dialog appears, waitForURL confirms a real client-side
   route change (not a hard reload), and the same deck (8 slots)
   renders on /display. This part of the reported symptom did not
   require a code change - it already works correctly.

   The real, narrower trigger: useChunkErrorRecovery.ts's existing
   routeChangeError handler. If the target route's JS chunk fails to
   fetch during a client-side transition (a stale deploy - GitHub
   Pages doesn't version chunk hashes across deploys - or a plain
   transient network blip; isChunkLoadError doesn't distinguish the
   two), it calls reloadOnceForChunkError(), a genuine
   window.location.reload(). Since the failed transition never
   actually left the current page, ProjectEditor's beforeunload
   listener was still mounted, and correctly-per-its-own-narrow-logic
   (but unhelpfully here) intercepted that reload as the user
   abandoning their work - producing exactly the native "leave site"
   dialog the owner described.

   VERDICT: yes, real data loss was possible - but only for a user who
   clicked through (confirmed leaving) past this false-positive prompt
   during an actual chunk-load failure, not on every normal click. The
   normal click path was never broken.

2. Fix: reloadOnceForChunkError() (chunkErrorRecovery.ts) now flags
   itself in flight via a new isRecoveryReloadInFlight() export,
   immediately before calling window.location.reload().
   ProjectEditor.tsx's beforeunload handler checks that flag and skips
   its confirmation for this one deliberate, app-initiated recovery
   reload. Every genuine exit (tab close, address-bar navigation, a
   manual refresh) still warns exactly as before - beforeunload
   carries no destination/cause information at all, by browser design,
   so this flag is the only mechanism available to distinguish "the
   app's own recovery" from "the user is actually leaving."

3. Playwright tests (tests/UnsavedWorkGuard.spec.ts, new file):
   - Editor -> /display with cards selected: no dialog, waitForURL
     confirms real navigation, same 8-slot deck renders.
   - Inverse: a genuine page reload while the project has cards still
     shows the native beforeunload dialog - confirms the guard itself
     is otherwise unchanged for real exits.

4. Jest test (chunkErrorRecovery.test.ts): isRecoveryReloadInFlight()
   defaults to false. The flag-flip itself isn't unit-tested beyond
   that - see DEVIATIONS.

DEVIATIONS from spec, each with reasoning:

- Did NOT build a "route-aware exemption" (skip the guard specifically
  when navigating to /display) even though the bug report's framing
  suggested one ("exempt internal same-store routes... from the
  unsaved-work guard"). beforeunload structurally cannot support this
  - the event carries zero information about navigation destination,
  by deliberate browser design (privacy/security) - so there is
  nothing for a route-aware mechanism to key off, and building one
  would be solving a problem the browser API doesn't expose a hook
  for. The chunk-recovery-reload flag is the only real, addressable
  trigger found during diagnosis; documented this reasoning directly
  in ProjectEditor.tsx's own comment so a future reader doesn't
  reintroduce the idea without hitting the same wall.

- Did not unit-test the flag-flip inside reloadOnceForChunkError()
  itself (only its default-false state). This repo's jsdom
  (jest-fixed-jsdom) makes window.location.reload non-configurable at
  every level tried - Object.defineProperty throws "Cannot redefine
  property" on both window.location wholesale and location.reload
  directly. This is exactly why chunkErrorRecovery.test.ts's
  PRE-EXISTING tests already only ever exercised the pure
  shouldAttemptReload helper, never the real side-effecting
  reloadOnceForChunkError function - I followed that established
  precedent rather than fighting jsdom. The flag's real effect is
  covered at the integration level by UnsavedWorkGuard.spec.ts
  instead (the same handler, exercised via a real Playwright reload).

- Self-caught branch-management error, fixed before pushing: initially
  committed this fix directly on top of the still-unmerged Item 3
  branch (claude/proposal-h-3c-flat-scroll-virtualization-04bam2, PR
  #115) - a genuinely different, unrelated concern that shouldn't ship
  bundled with that PR or be blocked by its review. Caught this before
  pushing, `git reset --hard` on the Item 3 branch back to its correct
  prior state (the extra commit was never pushed, so no remote cleanup
  needed), and re-committed via `git cherry-pick` onto a fresh branch
  off current origin/master - clean, no conflicts. Re-ran the FULL
  verification bar again on the fresh branch rather than trusting the
  first branch's results, since a fresh checkout off a newer master
  could plausibly behave differently.

VERIFICATION:

- npx tsc --noEmit: clean
- npx jest: 43/43 suites, 402/402 tests
- NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build: succeeds
  (one real failure hit and fixed along the way: `Error: Run autofix
  to sort these imports! simple-import-sort/imports` on
  ProjectEditor.tsx's new import - fixed via `npx eslint --fix`,
  verified the autofix only reordered the import line, no behavior
  change)
- npx playwright test tests/UnsavedWorkGuard.spec.ts: 2/2, run twice
  for stability
- npx playwright test tests/UnsavedWorkGuard.spec.ts
  tests/DisplayPage.spec.ts: 17/17 together
- npx playwright test tests/ProjectEditorMobileScroll.spec.ts (touches
  ProjectEditor.tsx directly): all passing, unaffected

Unrelated flakiness observed, NOT caused by this change: 
tests/AddCardToProjectForm.spec.ts failed consistently (3/3) in this
sandbox - a loading spinner intercepting a click on a card image, then
the element detaching from the DOM. That test's fixtures reference
real external CDN image URLs (img.proxyprints.ca), not MSW-mocked
ones - this sandbox's outbound network proxy has already shown
transient failures elsewhere in this task sequence (a directly-
observed ERR_TUNNEL_CONNECTION_FAILED during an earlier diagnostic
run, unrelated to this bug). This PR's diff has zero overlap with
CardGrid/card-detail-view code, and ProjectEditorMobileScroll.spec.ts
(which DOES touch ProjectEditor.tsx) passed cleanly - confident this
is pre-existing environmental flakiness, not a regression. Attempted
to verify against a clean origin/master baseline via `git worktree`
but the baseline run inadvertently reused this session's
already-running dev server (port collision, `reuseExistingServer:
true`), so that specific comparison is inconclusive - noting this
rather than overclaiming a clean-baseline confirmation.

OPEN ITEMS / DECISIONS NEEDED:

1. PR #124 (this fix) is ready for merge - no open questions.
2. PR #115 (Item 3, flat scroll + virtualization) is still open and
   unaffected by this task - unrelated branches throughout.
3. Recommend someone with real GitHub Pages deploy access spot-check
   whether stale-chunk 404s after a deploy are a frequent real-world
   occurrence for this app (the module comment in chunkErrorRecovery.ts
   suggests they were, historically, the original motivation for that
   file) - if so, this fix closes a real, periodically-recurring
   data-loss risk, not just a theoretical one.

LIVE STATE:

- Pushed: claude/priority-fix-display-nav-unsaved-guard-04bam2 ->
  origin. PR #124 open against master, not yet merged.
- Pushed: this report's branch, claude/priority-fix-relay-04bam2 ->
  origin.
- claude/proposal-h-3c-flat-scroll-virtualization-04bam2 (PR #115) is
  unchanged by this task - the accidental commit there was reset out
  locally before ever being pushed, confirmed via git log comparison
  against its already-pushed remote state.
- No sandbox-only Playwright executablePath overrides left in the
  working tree on any branch - each application was reverted via
  `git checkout --` and verified empty via `git diff --stat`/`git
  status --short` before every commit in this task, including after
  the mid-task diagnostic worktree detour.
- Task list: #33 (this bug) marked completed.
```
