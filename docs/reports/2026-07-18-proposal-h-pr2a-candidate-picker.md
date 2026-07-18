```
TASK: Proposal H, Step 2 PR 2a - candidate/version picker in the display rail
Branch: claude/proposal-h-2a-candidate-picker-04bam2
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/96 (open, against master)
Base commit at PR open: be85b515 (master)

WHAT SHIPPED:
1. Extracted GridSelectorModal.tsx's filtering/sorting/search state machine verbatim into
   frontend/src/features/gridSelector/useGridSelectorSearch.ts (a hook; `show` renamed `active`).
2. Extracted the modal's filters-column + results-column body into
   frontend/src/features/gridSelector/GridSelectorResults.tsx, parameterized by
   `variant: "modal" | "embedded"` - "modal" keeps the existing OverflowCol-based layout
   byte-identical; "embedded" swaps in a plain Col (no forced overflow-y:scroll, since the
   display rail already provides its own scroll container - see DisplayPage.tsx's RailWrapper).
3. Refactored GridSelectorModal.tsx to consume both of the above instead of owning that logic
   directly. External behavior unchanged - proven by its own full existing Playwright suite.
4. Wired the display rail's "Choose Image" accordion section (previously a stub) to a new
   ChooseImageSection in DisplayPage.tsx: resolves the selected slot's candidates via the same
   selectSearchResultsForQueryOrDefault selector CardSlot.tsx uses, and dispatches the same
   setSelectedImages action on click, so the print-sheet preview updates immediately.
5. Fixed a real, pre-existing-in-this-PR's-own-work layout bug found while verifying: CardRow's
   (in CardResultSet.tsx) column-count props (xxl/xl/lg/md/sm/xs) key off *viewport* width via
   Bootstrap media queries. That's correct for the classic modal (spans close to full viewport
   width) but wrong once the same grid renders inside the rail's much narrower (~150-250px)
   results column - at a normal desktop viewport the viewport-driven breakpoints still picked
   4-6 columns, squeezing each candidate card to a few px wide (effectively zero-width,
   unusable). Added a `variant` prop threaded through CardResultSet -> CardsGroupedTogether /
   FacetedCards -> CardRow; "embedded" now pins a fixed 2-column layout that fits the rail
   regardless of viewport size. GridSelectorResults passes its own `variant` straight through.

DEVIATIONS from spec:
1. The design doc's Step 2 brief didn't anticipate CardResultSet's viewport-driven column count
   as a blocker for the embedded context - this was discovered empirically (see VERIFICATION),
   not predicted in advance. Fixed with a minimal, backward-compatible `variant` prop (default
   "modal", so every other CardResultSet-adjacent behavior is unchanged) rather than reworking
   the grid to be container-query-based, which would have been a larger, unrelated change.
2. None else - GridSelectorModal's modal behavior is unchanged, ChooseImageSection reuses
   CardSlot.tsx's exact selector/action pair rather than inventing a parallel path.

VERIFICATION: what ran, with results
1. frontend/tests/DisplayPage.spec.ts (9 tests) - full pass. 4 of these were initially failing
   for two independent, compounding reasons, both fixed in this PR:
   a. My new "Option N" assertions were missing the explicit Compressed-view toggle that
      CardSlot.spec.ts already established as required precedent (Card.tsx doesn't render its
      header/title text at all under the default compressed=true view setting) - added the
      same `await page.getByText("Compressed").click();` step to the 4 affected tests.
   b. Even after that fix, one test still failed with the "Option N" element resolving but
      reporting zero width - root-caused via a throwaway diagnostic test (deleted before this
      commit, never pushed) that dumped getBoundingClientRect()/getComputedStyle() up the
      ancestor chain: the actual DOM element was ~22px wide, one of ~6 columns Bootstrap's
      row-cols-xl-6 class was forcing at a 1280px viewport, inside a results column only
      ~140-190px wide. This is item 5 above - a real product bug, not a test artifact.
2. Full regression pass on every surface GridSelectorModal/CardResultSet touch:
   GridSelectorModal.spec.ts, GridSelectorModalAccessibility.spec.ts,
   GridSelectorModalMobile.spec.ts, CardSlot.spec.ts, DeckbuilderConfirmAffordance.spec.ts -
   55/55 passing, confirming zero behavior change to the classic modal/editor.
3. npx tsc --noEmit - clean.
4. npx jest - 345/345 passing.
5. NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build - clean production build with the
   flag on (the standing verification bar added to docs/lessons.md after PR #90's build
   failure; ran again here since this PR touches the same page).
6. pre-commit run prettier (CI-pinned version, not whatever `npx prettier` resolves locally) -
   passed with zero changes on the 3 files this commit touches.
Deferred: no manual browser click-through beyond what Playwright already exercises - the
Playwright suite's assertions (including the ancestor-chain diagnostic that found the column
bug) cover the same interactions a manual pass would.

OPEN ITEMS / DECISIONS NEEDED: none - PR #96 is open and ready for review.

LIVE STATE:
- Branch claude/proposal-h-2a-candidate-picker-04bam2 pushed to origin, 2 commits ahead of the
  master it was forked from (71d23e74 main PR 2a content, 9f355e17 this fixup).
- PR #96 open against master, not draft, CI not yet observed (just opened).
- This report is on its own fresh branch claude/proposal-h-relay4-04bam2, forked directly from
  origin/master (not stacked on the PR 2a branch), per the report-relay convention.
- Remaining Step 2 work (PR 2b through 2f) not started this session - see the design doc's §6
  and the standing "After 2f: STOP" instruction (steps 3/4 remain withheld pending the owner's
  own hands-on trial).
```
