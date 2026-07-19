```
TASK: Proposal H pane migration + left-panel unification, with before/after
perf benchmark (public issue #164, milestone "Proposal H: unified display").
Branch: proposal-h-pane-migration. PR: #194 (draft, mergeable). Commit:
3de38382.

WHAT SHIPPED:
1. Required reading, done before any edit: docs/proposals/proposal-h-unified-
   display-page.md (full); docs/features/grid-selector.md; docs/features/
   print-export-page.md; docs/features/pdf-generator.md; located and read
   the scroll/virtualization benchmark landed by PR #178 (commit e00ed56b) -
   frontend/tests/perf/display-scroll.bench.spec.ts +
   playwright.perf.config.ts - and reused it unmodified as directed (it
   genuinely served; no new harness written).
2. Read frontend/src/features/display/DisplayPage.tsx directly before
   assuming the proposal doc's state matched reality - found most of
   Proposal H's step 1/2 (route shell #87, inline export #109, missing-
   image slot names #104, requested-printing badge #110/#102, candidate/
   version picker #96, flat-scroll+virtualization #115) already shipped
   across prior PRs; only 4 rail accordion sections remained labeled stubs.
   Scoped "left-panel unification" to exactly those 4 (cross-checked against
   the design doc's own §5 component-mapping table, which names each
   stub's eventual filler and confirms none needs new backend data or the
   Select Version rebuild):
   - Attributes: frontend/src/features/display/AttributesSection.tsx -
     fetches this slot's tag consensus (APIGetTagConsensus, same endpoint
     bleedPriorResolution.ts already uses), renders the attribute-chip
     taxonomy as a plain vertical stack. Extracted the tap/vote-submission
     logic out of AttributeChipPanel.tsx into a shared
     features/attributeChips/useTagVoting.ts hook, and the chip-render/
     styling logic into features/attributeChips/attributeChipRender.tsx
     (Chip/ChipRow/renderAttributeChip/hasAttributeLean), so both the
     question-feed's ring layout and the rail's stack layout vote through
     one real implementation, not two. AttributeChipPanel.tsx's own public
     behavior is unchanged (AttributeChipPanel.test.tsx passes unmodified).
   - Print Options: frontend/src/features/display/PrintOptionsSection.tsx -
     per-card bleed override (Auto/Force bleed/Force trimmed), reusing
     projectSlice's selectManualOverrides/setManualOverride directly.
     Exported PDF.tsx's isBleedNormalizationEligible (previously private)
     so PDFGenerator.tsx's classic BleedOverrideSettings panel and this
     new rail section share one eligibility rule instead of two that could
     drift; refactored BleedOverrideSettings to call it too (behavior-
     preserving - same sourceType-only filter as before).
   - Artist: frontend/src/features/display/ArtistSection.tsx - inherits
     ArtistSupportLink directly, exactly as docs/features/artist-support-
     links.md's own "not built in v1" note anticipated this surface would
     once built.
   - Slot Actions: frontend/src/features/display/SlotActionsSection.tsx -
     same getCardSlotMenuActions list CardSlot.tsx's 3-dot dropdown/context
     menu use (Change Query/Duplicate/[Unfilter Printing]/Delete), rendered
     as a plain action list per the design doc's own instruction for this
     section (not a dropdown overlay). Delete calls back to DisplayPage.tsx
     to clear the stale slot selection.
3. Docs updated in the same PR: docs/proposals/proposal-h-unified-display-
   page.md's own status line (was still "HOLD - zero feature code," despite
   6 PRs of real feature code having shipped since - corrected to name what
   shipped vs. what's still open); docs/README.md's Proposal H status row
   (HOLD -> PARTIAL); docs/features/artist-support-links.md (rail is now a
   real third surface, not an anticipated follow-on); docs/features/pdf-
   generator.md (notes the shared isBleedNormalizationEligible export);
   docs/features/printing-tags.md (corrected a stale Chip-location
   reference after the attributeChipRender.tsx extraction).
4. Benchmark, before AND after, per the owner condition: ran PR #178's
   existing harness on the untouched baseline FIRST (before any edit in
   this branch), recorded the numbers, then implemented, then re-ran
   identically. Both result sets are in PR #194's description (also
   restated in VERIFICATION below).

DEVIATIONS:
1. Ineligible-source (non-Google-Drive/local-file) Print Options coverage:
   no dedicated Playwright test added for the "doesn't support manual
   override" branch - every card fixture available in this repo's test-
   constants is Google-Drive-sourced, and constructing a new AWS-S3
   fixture just for this one branch felt out of proportion to the task's
   time budget. The branch itself is a 2-line conditional exercised
   indirectly by the pre-existing isBleedNormalizationEligible/
   BleedOverrideSettings coverage. Flagged, not silently dropped - see
   OPEN ITEMS.
2. Did not build or guess at §6 step 3 (switchover - making /display the
   default nav entry point over /editor) or step 4 (retiring /editor).
   "Left-panel unification" as a phrase doesn't name this step, and it's a
   materially higher-stakes, user-facing default-navigation change than
   filling in rail sections - reasoning surfaced as an open item rather
   than assumed either way.
3. Wiki: checked docs/documentation-process.md and .github/wiki-publish-
   map.json directly rather than assuming CLAUDE.md's generic wiki-
   maintenance rule applied as written. Finding: docs/proposals/ is
   explicitly excluded from every publish target (so the proposal doc edit
   needs no wiki action at all); docs/features/artist-support-links.md and
   docs/README.md aren't in the publish map either; docs/features/pdf-
   generator.md and docs/features/printing-tags.md ARE mapped and will
   auto-publish to the wiki via the existing docs-wiki-publish.yml CI on
   merge to master - no manual wiki edit or hand-authored page needed
   (docs/documentation-process.md: "Never hand-edit a wiki page this
   system manages"). Noted this finding in PR #194's body rather than
   adding a manual-edit checklist item that would contradict that rule.

VERIFICATION:
- `npx tsc --noEmit -p .` (frontend/) - clean, both immediately after the
  refactor and again after the full section build-out.
- `npx jest` (frontend/) - 43 suites / 402 tests passed, including
  AttributeChipPanel.test.tsx unmodified after the useTagVoting extraction.
- `npx playwright test tests/DisplayPage.spec.ts` - 19/19 passed (15
  pre-existing, updated for the new real Attributes content in place of
  stub-text assertions; 4 new, one per newly-built section).
- `npx playwright test` (QuestionFeed*.spec.ts, PDFGenerator.spec.ts,
  DisplayPageExport.spec.ts) - all passed, confirming the AttributeChipPanel
  refactor and PDF.tsx/PDFGenerator.tsx eligibility-check dedup didn't
  regress either surface.
- Full suite (`npx playwright test`, all 273 tests) - 272 passed, 1
  (tests/ImportCSV.spec.ts:31) failed under full-suite resource contention;
  re-ran that single spec file in isolation immediately after and it passed
  cleanly (6/6) - a pre-existing flake unrelated to this change (that test
  touches the classic editor's CSV import, nothing this PR modified).
- `npx prettier@2.7.1 --check` on every changed frontend file - clean
  (after one `--write` pass to fix import-sort ordering flagged by eslint
  first).
- Benchmark (frontend/tests/perf/display-scroll.bench.spec.ts via
  `npx playwright test --config=playwright.perf.config.ts`, 120-card/
  15-sheet deck, 4x CPU throttle):

  | Metric | Before (untouched baseline) | After (this PR) |
  |---|---|---|
  | Avg fps (target ~60) | 58.7 | 59.8 |
  | p95 frame time | 23.0ms | 22.7ms |
  | Peak JS heap | 256.5 MB | 256.5 MB |
  | Max simultaneously-mounted <img> tags (of 120) | 16 | 16 |
  | Long tasks (>50ms) during scroll | 1 (86.0ms) | 0 |

  No regression - numbers are flat within normal run-to-run noise. Caveat
  stated honestly in PR #194, not just claimed clean: this PR's changes are
  confined to the rail (mounted per-slot on selection), and the benchmark's
  own scroll flow never selects a slot - it exercises the sheet stack's
  virtualization, which this PR doesn't touch. The flat result confirms no
  sheet-scroll regression; it isn't evidence about the rail's own render
  cost, which this harness wasn't designed to measure.
- Manual UI click-through: not performed as a live headed-browser session
  in this task (sandboxed, no persistent dev-server browsing step beyond
  what the Playwright suites themselves drove) - the 4 new Playwright
  tests each exercise their section's real interaction (chip tap -> vote
  submit, bleed-override select change, artist link render, slot delete)
  against a real running dev server via Playwright's own browser automation,
  which is the closest available substitute for a manual click-through in
  this environment.

OPEN ITEMS / DECISIONS NEEDED:
1. Does #164 include flipping the default nav entry point from /editor to
   /display (design doc §6 step 3), or does that wait for a later,
   separately-scoped step? Not built here either way - "left-panel
   unification" doesn't name it, and it's a higher-stakes call than the
   rail-section work. Answerable with a yes/no plus, if yes, a target PR.
2. Is the missing ineligible-source (non-Google-Drive/local-file) Print
   Options Playwright test worth a follow-up, or is the existing indirect
   coverage (isBleedNormalizationEligible/BleedOverrideSettings) sufficient?
   Answerable; low stakes either way (2-line conditional, no user-facing
   risk beyond a wrong message string).

LIVE STATE: Branch proposal-h-pane-migration pushed to origin (commit
3de38382). Draft PR #194 open at
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/194, mergeable,
CI not yet checked post-push (not polled in this task - PR is draft, owner
reviews before any merge). Nothing left running; dev server processes
started for Playwright were the tool's own managed webServer, torn down
automatically at each run's end. WORKERS.md (main checkout root, gitignored)
checked directly - table was empty, no overlapping session found; no row
was added since this session's substantive work was already complete by
the time the check was corrected to look in the right place, and no row
was left behind to go stale.
```
