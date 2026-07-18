```
TASK: Proposal H, Step 2 PR 2b - requested-printing badge + Confirm affordance
Branch: claude/proposal-h-2b-badge-confirm-04bam2
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/102 (open, against master)
Base commit at PR open: eee7c793 (master, includes PR 2a/#96 already merged)

WHAT SHIPPED:
1. Requested-printing badge, full degraded-state treatment (design doc's §2/§5):
   - EditorSearchResponse.degradedQueries (schema_types.ts) was already returned by the backend
     but discarded on the frontend before this PR - api.ts's APIEditorSearch only ever returned
     `content.results`. Changed APIEditorSearch/APIEditorSearchLegacy to return
     {results, degradedQueries}; the legacy 2/editorSearch/ endpoint predates this field
     entirely, so it always reports [] there.
   - searchResultsSlice.ts: doSearch() now accumulates degradedQueryHashKeys across paginated
     remote requests (client-side/local-folder search never reports degraded queries - only the
     remote backend can retry a printing filter unfiltered). fetchSearchResults.fulfilled merges
     new hash keys without duplicating (Set-deduped); clearSearchResults resets them alongside
     searchResults. New SearchResultsState.degradedQueryHashKeys field (common/types.ts).
   - New selectIsSearchQueryDegraded selector: true only when a query both carries a printing
     filter (expansionCode) and its hash key is in degradedQueryHashKeys.
   - DisplayPage.tsx's RailHeader: the badge switches from bg-secondary to bg-warning
     text-dark (plus a warning icon and explanatory title) when degraded.
2. Confirm? affordance mounted for real in the rail's always-visible header - the exact same
   DeckbuilderConfirmAffordance component CardSlot.tsx already mounts in the classic editor, not
   a fork. Only onOpenGridSelector is adapted: the rail has no modal to open, so N expands (or
   keeps expanded, if already open - "focus, if already open" per the design doc's §4.3) the
   Choose Image accordion section instead of opening GridSelectorModal.

DEVIATIONS from spec:
1. None from the explicit instruction. One judgment call: the degraded badge keeps the same
   "<SET> <NUM>" text (per the design doc's §2 ASCII diagram) and communicates degraded state
   via style + icon + title tooltip only, rather than changing the badge's text - this matches
   "degraded style when applicable" as written rather than inventing new copy.
2. Sheet-thumbnail-scale Confirm badges (design doc §4.3's "on the sheet's own thumbnail at
   small scale") are NOT built - PagePreview's slot thumbnails are plain <img> renders, not
   CardSlot/MemoizedEditorCard instances, so there's no existing mount point for
   DeckbuilderConfirmAffordance there. The instruction for this PR specified "the real
   DeckbuilderConfirmAffordance in the rail's always-visible header" specifically, which is what
   shipped; the sheet-thumbnail variant is out of this PR's explicit scope, not silently dropped.

VERIFICATION: what ran, with results
1. frontend/tests/DisplayPage.spec.ts - 13/13 passing (9 from PR 2a + 4 new this PR: plain-badge
   style, degraded-badge style with an actual getComputedStyle().backgroundColor check per the
   theming caveat below, Confirm-affordance YES vote, Confirm-affordance NO expanding Choose
   Image).
2. Theming caveat (from PR #91): Bootswatch's Superhero theme is known to hardcode some
   component colors past the CSS-variable layer, so a class name or CSS-variable-definition
   check alone doesn't prove what actually renders. The degraded-badge test reads the live
   badge's getComputedStyle().backgroundColor in the browser and asserts it's distinctly
   warm (blue channel meaningfully below red/green), not just that the bg-warning class is
   present.
3. frontend/src/store/slices/searchResultsSlice.test.ts - existing mergeSearchResults coverage
   unchanged (3 tests) + 3 new tests: fetchSearchResults.fulfilled dedup-merges degraded hash
   keys, clearSearchResults resets them, selectIsSearchQueryDegraded is true only for the exact
   degraded printing-filtered query (false for a different collector number, false with no
   printing filter at all).
4. npx tsc --noEmit - clean.
5. npx jest - 359/359 passing, 0 failures.
6. NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build - clean production build with the
   flag on (the standing verification bar from PR #90's build-failure lesson).
7. pre-commit run prettier (CI-pinned version) - reformatted 2 files on first run
   (searchResultsSlice.test.ts, DisplayPage.tsx), verified idempotent (zero changes) on rerun,
   then re-verified tsc + full jest still clean after formatting.
8. CardSlot.spec.ts / DeckbuilderConfirmAffordance.spec.ts regression - every individual test
   and several filtered subsets passed cleanly (search-result auto-selection, image switching,
   right-click context menu, Confirm-affordance shows/hides/YES/NO), confirming zero behavior
   change to the classic editor's own DeckbuilderConfirmAffordance mount. Full-*file* (unfiltered,
   all-tests-in-one-invocation) runs of these two files hit intermittent Playwright
   test-collection failures ("Playwright Test did not expect test.describe() to be called
   here") in this sandbox today - confirmed this is environmental, not a regression, by
   reproducing the identical failure on GridSelectorModal.spec.ts (a file untouched by this PR)
   under the same full-unfiltered-run condition, while every individually-run or filtered-subset
   test across all three files passed without exception. Recommend future sessions default to
   filtered/individual Playwright runs in this sandbox if full-file runs recur unreliably.

OPEN ITEMS / DECISIONS NEEDED: none - PR #102 is open and ready for review.

LIVE STATE:
- Branch claude/proposal-h-2b-badge-confirm-04bam2 pushed to origin, 1 commit ahead of the
  master it was forked from (36453c0e).
- PR #102 open against master, not draft, CI not yet observed (just opened).
- This report is on its own fresh branch claude/proposal-h-relay5-04bam2, forked directly from
  origin/master (not stacked on the PR 2b branch), per the report-relay convention.
- Remaining Step 2 work (PR 2c through 2f) not started this session - see the design doc's §6
  and the standing "After 2f: STOP" instruction (steps 3/4 remain withheld pending the owner's
  own hands-on trial).
```
