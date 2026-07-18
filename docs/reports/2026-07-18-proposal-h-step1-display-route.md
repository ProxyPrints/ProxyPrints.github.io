```
TASK: Proposal H — BUILD GO with accordion-rail amendment, then Step 1
(the /display route shell behind a feature flag). Branches:
claude/proposal-h-display-design-04bam2 (amendment commit, PR #84,
now CLOSED as superseded) and claude/proposal-h-step1-display-route-04bam2
(Step 1 build, PR #87, open). Commits: 1a09b812 (amendment),
cab4ba0c + 11f3a33b (Step 1 build + prettier fixup).

WHAT SHIPPED:
1. AMENDMENT (one commit on the existing design branch, 1a09b812,
   pushed to PR #84 before it was superseded): reworked the design
   doc's §2 (new amendment subsection + ASCII diagram), §4.2-4.4
   (accordion-aware interaction wording), and §5's component-mapping
   table to reflect the owner's instruction — the rail's instruments
   are collapsible AutofillCollapse sections (the same component the
   classic PDF-export panel's settings groups already use), not a flat
   stack: an always-visible status header (identity, requested-
   printing badge, Confirm? affordance) outside the accordion, Choose
   Image open by default, Attributes/Print Options/Artist/Slot Actions
   collapsed by default. All 5 mockups + shared.css rebuilt to render
   real open/collapsed accordion sections; re-rendered with headless
   Chromium and visually verified before committing.
2. STEP 1 BUILD (docs/proposals/proposal-h-unified-display-page.md's
   §6, step 1) — new /display route, entirely gated behind
   NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED (off by default, mirrors the
   existing isGoogleDriveAppConfigured boolean-env-var pattern):
   - Top toolbar: page N of M pagination, a Fronts/Backs toggle
     (reuses the existing frontsVisible view setting), a small live
     subset of print settings (paper size, bleed edge, guides) that
     genuinely drives computeLayout(), and a working link to the
     classic editor's Print tab (full inline export is Step 3, not
     built here).
   - Live sheet: PagePreview/computeLayout reused as-is, paginated
     across the WHOLE deck (not just page 1) via a new
     displayPagination.ts helper that preserves (face, slot) identity
     per entry - CardSelectionModeToPaginator (PDF.tsx) discards that
     identity, which this page's click-to-select needs. Only the
     current page's slots are ever resolved to thumbnail URLs
     (mediumThumbnailUrl, the "mid resolution tier" the brief called
     for). PagePreview gained optional onSlotClick/selectedSlotIndex
     props (unused by existing callers - zero behavior change there)
     and loading="lazy"/decoding="async" on its <img>.
   - Rail: always-visible header (card identity, basic requested-
     printing badge) + the 5-section accordion from the amendment,
     each section a labeled stub naming exactly which Step 2 PR fills
     it in.
   - Moved the generic `chunk` helper from PDF.tsx to common/utils.ts
     (PDF.tsx re-exports it for its existing callers - PDFGenerator.tsx,
     SCMPDF.tsx - unaffected) - importing anything from PDF.tsx pulls
     in @react-pdf/renderer's ESM-only bundle, which Jest can't
     transform out of the box; this broke the new pagination helper's
     own unit test until moved. Confirmed no other test file imports
     directly from PDF.tsx (this was previously unexercised, not a
     regression).
   - Added a flagged "Display (beta)" navbar link (visible only when
     both a backend is configured and the flag is on).
3. Opened PR #87 (real PR, not draft - a real build step) against
   master, carrying the amendment + Step 1 code together (docs "ride
   with the flag" per instruction). Closed PR #84 with a comment
   pointing to #87 (no content lost - everything in #84, plus the
   amendment, is included in #87).

DEVIATIONS from spec, each with reasoning:
1. Tablet off-canvas drawer / mobile bottom-sheet overlay interaction
   patterns (design doc §3) are NOT built - below md the rail stacks
   in plain document flow below the sheet (usable, not the polished
   drawer/overlay). Explicitly out of Step 1's own scope ("page shell...
   rail skeleton"); noted in DisplayPage.tsx's module comment and PR
   #87's body as deliberate, not silently dropped.
2. The sheet paginates ONE face at a time (a Fronts/Backs toggle)
   rather than PDFGenerator's export-time front-then-distinct-back
   interleaving - simpler, reuses an existing toggle, and a full
   interleaved dual-face sheet is a separate concern flagged in the
   design doc's own component-mapping table, not silently dropped.
3. Confirm affordance and the printing badge's full degraded-state
   styling are NOT wired in Step 1 despite being "always-visible
   header" items per the amendment - they're explicitly Step 2's
   SECOND instrument-parity PR per the given build order (candidate
   picker first), so Step 1's header shows only a basic printing-badge
   label with no degraded logic yet.
4. Two real bugs found by this task's own Playwright suite, fixed
   before opening the PR (not shipped broken, not silently patched
   over without mention):
   a. The accordion's per-slot-reset `key` prop was originally placed
      on a <div> INSIDE the Rail component rather than on the <Rail>
      element itself in its parent's JSX - a key only affects
      remounting from the PARENT's perspective, so expandedSections
      state was silently persisting across slot selections instead of
      resetting to the documented default. The test asserting
      reset-on-reselect caught this directly.
   b. A duplicate-rail-render pattern (one Rail instance per Bootstrap
      d-none/d-md-none breakpoint utility class, meant to toggle
      sticky vs. static positioning) actually mounted BOTH instances
      simultaneously, doubling every testid/heading/interactive
      control in the DOM regardless of viewport. Fixed by rendering
      Rail exactly once, with sticky-vs-static switched via a single
      emotion-styled wrapper's own @media query - mirroring
      cardPanel.tsx's own established static-below-md/sticky-at-md-up
      precedent (docs/lessons.md's sticky/z-index entry), not a new
      pattern invented here.
5. `pre-commit` is not installed in this session's container (not a
   persistent server-local machine); ran prettier/eslint/tsc/jest/
   playwright manually instead of via the hook. Applied prettier's own
   formatting fixes as a separate follow-up commit (11f3a33b) after
   discovering the drift via `npx prettier --check`.

VERIFICATION:
- Full existing Jest suite: 315/315 passing after the `chunk` move and
  PagePreview prop additions - zero regressions.
- New unit tests: displayPagination.test.ts (4 tests - pagination +
  slot-identity preservation + edge cases), featureFlags.test.ts (3
  tests), PagePreview.test.tsx's 5 new click/selection/lazy-load cases
  (all passing alongside its 6 pre-existing tests).
- New Playwright suite tests/DisplayPage.spec.ts, 7 tests, all passing
  against the real dev server with real MSW-mocked network + a real
  imported deck: empty state + link back to editor, live sheet
  rendering + page-count indicator, slot-select swapping the rail from
  idle, accordion defaults (Choose Image open/rest collapsed),
  expand-on-click, reset-on-reselecting-a-different-slot, Fronts/Backs
  toggle, Guides toggle showing/hiding the cut-line overlay.
- Cross-section regression check via Playwright: PDFGenerator.spec.ts
  (5 tests), ProjectEditorMobileScroll.spec.ts (4 tests), ExportXML.spec.ts
  (3 tests) - all 12 still pass, confirming the PagePreview/PDF.tsx/
  common/utils.ts changes don't affect existing card-image-fetch,
  mobile-scroll, or XML-export behavior.
- tsc --noEmit clean; eslint clean (0 errors across every touched/new
  file - only 2 pre-existing warnings, both predating this task,
  confirmed via git diff that neither touched line introduced them).
- Environment note for whoever re-runs these Playwright specs in a
  similar sandbox: this container's pinned Playwright version (1.57.0)
  expects a chrome-headless-shell binary not present under
  /opt/pw-browsers (only chromium-1194's full Chrome binary is) -
  verification here used a LOCAL-ONLY, temporary executablePath
  override in tests/global-setup.ts and playwright.config.ts, fully
  reverted (confirmed via git diff showing zero net change to either
  file beyond the one intentional env-var addition) before every
  commit. Nothing about this workaround was committed.
- Grepped every file this task touched or created (design doc amendment,
  mockups, all Step 1 source/test files, both PR bodies, this report)
  case-insensitively for "proxxied"/"moxfield"/"archidekt" - zero hits.

OPEN ITEMS / DECISIONS NEEDED:
1. Tablet drawer / mobile bottom-sheet overlay - not built, needs its
   own future PR per the design doc's §3 (unchanged from the original
   HOLD's open decisions - see PR #84's superseded content, now folded
   into #87).
2. The remaining 5 rail instruments (candidate picker, printing-badge
   degraded-state + confirm affordance, attribute chips, slot actions,
   artist line) and the bleed-override section (blocked on Proposal B
   PR-2) are each their own follow-up PR per the given Step 2 order -
   none built here, all clearly stubbed and labeled in the rail.
3. PR #87 needs owner review/merge before Step 2 can start stacking on
   top of it.

LIVE STATE:
- PR #84: CLOSED (superseded, comment posted pointing to #87). No
  content lost.
- PR #87: OPEN against master, real PR (not draft) - carries the
  amendment + Step 1 build. No CI status checked from here (no gh/CI
  tool access in this session beyond the GitHub MCP server used to
  open/close these two PRs).
- Branches pushed: claude/proposal-h-display-design-04bam2 (final
  state: the amendment commit, now merged into #87's branch history
  via a git merge - see cab4ba0c's parents), claude/proposal-h-step1-display-route-04bam2
  (Step 1 build, HEAD = 11f3a33b, PR #87's head branch).
- This report is being committed to a THIRD, separate relay branch,
  claude/proposal-h-relay2-04bam2 (forked fresh from origin/master,
  distinct from both the design and relay-1 branches per the
  bare-report-relay-name-retired lesson), which will be pushed and left
  for the owner to merge or discard - it carries no code, only this one
  report file.
- No feature build has proceeded past Step 1. Nothing in this task
  touched the flag's default (still off), so no real user sees anything
  different on the live site as a result of this task.
```
