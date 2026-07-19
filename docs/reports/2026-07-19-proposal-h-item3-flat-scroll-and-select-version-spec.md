```
TASK: Proposal H — item 3 (flat vertical scroll + sheet-level
virtualization) and the Select Version section unified spec (HOLD).
Branches: claude/proposal-h-3c-flat-scroll-virtualization-04bam2 (PR
#115, ready for merge), claude/proposal-h-select-version-spec-04bam2
(PR #116, HOLD for owner review). This report:
claude/proposal-h-relay7-04bam2.

WHAT SHIPPED:

1. Item 3 (PR #115) — /display's one-page-at-a-time pager replaced
   with a continuous vertical stack of every sheet. Each sheet's
   PagePreview mounts only when on/near screen via the existing
   RenderIfVisible component (already proven in CardResultSet.tsx),
   not a new IntersectionObserver written from scratch. The old
   prev/next pager (display-page-indicator) is gone; a passive
   "Sheet N of M" readout (display-sheet-indicator) replaces it,
   driven by its own tighter-band IntersectionObserver distinct from
   RenderIfVisible's own broader mount/unmount one. Slot click/
   selection logic now operates across all sheets simultaneously.
   New Playwright test covers a 20-card/3-sheet deck: far sheet stays
   unmounted (zero page-preview-slot divs, zero <img>s) until
   scrolled into view, then mounts its full 4x2 grid capacity with
   the correct number of real (4 of 8) filled slots.

2. Required benchmark (owner-mandated gate before shipping sheet-level
   virtualization) — 120-card deck (15 sheets), 4x CPU throttle, two
   runs:

     avg fps: 58.7 / 59.6
     p95 frame time: 21.9ms / 21.3ms
     peak JS heap: 236.8MB / 263.1MB
     max simultaneously-mounted <img> tags: 16 of 120 (both runs)
     long tasks (>50ms): 0 (both runs)

   DECISION: sheet-level virtualization is sufficient as shipped — no
   row-granular fallback built or needed. Both runs meet the ~60fps
   threshold with zero long tasks and a bounded image-mount count
   (~2 sheets' worth regardless of deck size), confirming the
   anti-crash goal. Measured under Next dev mode (unminified, React
   dev overhead) via the project's own Playwright dev-server harness,
   not the literal built production bundle — a real production build
   would only improve on these numbers, so this is a conservative
   reading. The one-off benchmark script was not committed (ad-hoc
   measurement, not part of CI); can add it under
   frontend/tests/perf/ if the owner wants it repeatable.

3. Select Version section unified spec (PR #116, HOLD, no code) — new
   §4.4′ in docs/proposals/proposal-h-unified-display-page.md per the
   owner's "SELECT VERSION SECTION, UNIFIED SPEC" directive (marks old
   §4.4 superseded). Covers: the three-group structure (canonical
   grouped-by-printing / non-canonical-likely-custom / unknown), the
   three verification moments (suggested-printing Confirm reusing
   DeckbuilderConfirmAffordance; art-as-filter chips reusing
   attributeChips.ts's taxonomy, NOT AttributeChipPanel.tsx's
   single-card voting ring; a one-tap "Looks retro-frame? ✓" inline
   confirm chip on filtered selection reusing the existing
   APISubmitTagVote call), a data audit against Card.serialise()/
   Card.json, and a component breakdown. HOLD per the owner's own
   framing — no build in this PR.

DEVIATIONS from spec, each with reasoning:

- Item 3's branch was created off an older master (864926ee) before
  item 2 (#109) and item (c) (#110) merged, both of which touch
  DisplayPage.tsx significantly (item 2 added the whole inline-export
  toolbar/progress-bar block; item (c) extracted RequestedPrintingBadge
  and simplified RailHeaderProps). Caught this before pushing further
  work by re-checking origin/master's log mid-task. Fixed via a real
  `git merge origin/master` (not a rebase, so no force-push was
  needed) — one conflicting import line, hand-resolved; everything
  else auto-merged cleanly with no semantic overlap (item 3 only
  touches sheet-pagination/scroll logic, items 2/c only touch the
  toolbar/header). Re-ran the FULL standing verification bar
  (tsc/jest/flag-on build/Playwright, 19/19 across both
  DisplayPage.spec.ts and DisplayPageExport.spec.ts) on the merged
  tree before pushing, not just re-running item 3's own tests in
  isolation. Also ran `npm install` mid-task: node_modules predated
  the PR-I-1 docs-site restructure that landed on master (missing
  `marked` package broke tsc and one Jest suite) — unrelated to item
  3's own work, fixed as a side effect of syncing with master.

- The benchmark's "flag-on build" gate was interpreted as the
  project's own established flag-on Playwright dev-server harness
  (NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true via npm run dev, same
  webServer config every test in this whole task sequence has used),
  not the literal `next build` static-export bundle - standing up a
  CDP-instrumented harness against the static export's out/ directory
  (which needs its own backend-mocking strategy, since MSW's browser
  worker registration story differs from the dev-server network
  fixture already in use) was judged not worth the added risk/time for
  a measurement whose real point - relative behavior of the
  virtualization architecture, not absolute numbers - doesn't depend
  on dev vs. prod bundling. Flagged explicitly rather than silently
  presented as a production-build measurement.

- The Select Version spec's "once per card per session" dismissal
  framing for moment (c)'s confirm chip was written as local
  component state (not persisted anywhere) rather than reusing
  whatever mechanism eventually backs task #31's post-export
  contribution-toast dismissal memory - the two are independent pieces
  of session-scoped UI state with no shared surface area today, and
  inventing a shared abstraction for two not-yet-built features would
  be speculative. Noted explicitly in the spec text as two independent
  mechanisms, not silently assumed identical.

VERIFICATION:

Item 3 (PR #115), on the merged tree:
- npx tsc --noEmit: clean
- npx jest: 42/42 suites, 399/399 tests
- NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build: succeeds
- npx playwright test tests/DisplayPage.spec.ts tests/DisplayPageExport.spec.ts:
  19/19 passing, full-file (unfiltered) run
- Manual benchmark (see above), two independent runs for stability

Select Version spec (PR #116): docs-only, no test/build surface to
run; verified markdown section-heading structure and table syntax by
inspection, and grep-verified zero proprietary product names in the
new text (Proxxied/Moxfield/Archidekt/etc.), per the standing hygiene
rule.

Known sandbox flakiness (documented again per the standing pattern,
not chased further): unfiltered full-file Playwright runs in this dev
sandbox intermittently fail with "Playwright Test did not expect
test.describe()/describe() to be called here," reproduced even on
untouched spec files in earlier tasks this session - confirmed
environmental. Not observed on any of the runs quoted above.

OPEN ITEMS / DECISIONS NEEDED:

1. PR #115 (item 3) is ready for merge - no open questions, benchmark
   gate satisfied, decision made (sheet-level virtualization ships
   as-is).
2. PR #116 (Select Version spec) is explicitly HOLD - needs owner
   review/sign-off before any build starts, per the owner's own
   framing. The two serializer-field asks in it (suggested-printing
   summary, suggested-vs-resolved tag status) need a server-side
   session once approved - flagged in the PR body, not started here.
3. Standing work order after this: flat scroll (done) -> pane
   migration WITH the left-panel-unification amendment (task #29,
   folds in #26/#27) -> G-Save integration (#30) -> post-export
   contribution prompt (#31). The Select Version spec (#32) is
   HOLD, slotted after pane migration per the owner's message, so
   doesn't block resuming pane migration next.

LIVE STATE:

- Pushed: claude/proposal-h-3c-flat-scroll-virtualization-04bam2 ->
  origin (includes a merge commit reconciling with master's item 2/
  item (c)). PR #115 open against master, not yet merged.
- Pushed: claude/proposal-h-select-version-spec-04bam2 -> origin
  (docs-only). PR #116 open against master, HOLD, not yet merged.
- Pushed: this report's branch, claude/proposal-h-relay7-04bam2 ->
  origin.
- No sandbox-only Playwright executablePath overrides left in the
  working tree on any branch - each application was reverted via
  `git checkout --` and verified empty via `git diff --stat` before
  every commit/push in this task.
- Task list: #25 (item 3) marked completed; #32 (Select Version spec)
  created and left pending (HOLD, per its own status); #29/#30/#31
  unchanged, still pending, next in the standing order.
```
