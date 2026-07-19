```
TASK: Proposal H, owner's first hands-on review - items 1 (missing-image
      slots) and 2 (inline PDF export, pulled forward per the owner's
      "classic Print tab is condemned" follow-up)
Branches: claude/proposal-h-3a-missing-image-name-04bam2 (item 1),
          claude/proposal-h-3b-inline-export-04bam2 (item 2)
PRs: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/104 (item 1, open)
     https://github.com/ProxyPrints/ProxyPrints.github.io/pull/109 (item 2, open)
Base commits at PR open: 71d35430 (item 1), 430a120a (item 2)

WHAT SHIPPED:
1. Item 1 - missing-image slots keep their card name. PagePreviewSlotContent
   gains an optional queryText field; PagePreview renders a slot's name +
   query text centered in the placeholder instead of a blank grey rectangle,
   but only for a slot that has real content and lacks an image (a position
   beyond the deck's actual slot count still renders empty, unchanged).
   DisplayPage.tsx computes queryText from the slot's own SearchQuery, same
   format CardSlot.tsx already uses for its change-query modal.
2. Item 2 - inline PDF export. "Generate PDF" on /display now runs the real
   export pipeline in-page instead of linking to the classic tab:
   useDownloadPDF/useSaveToDrivePDF/ImageFailureConfirmModal exported from
   PDFGenerator.tsx (not forked) and consumed directly, fed by this page's
   own toolbar settings (paper size via pageSize:"CUSTOM" + explicit
   landscape-swapped pageWidth/pageHeight, bleed edge, guides). A real
   determinate ProgressBar shows "Fetching images: N of ~M" during the #81
   paced fetcher's work, switching to an indeterminate "Assembling PDF…" bar
   once completed>=total (inferred - the pipeline has no separate
   "assembling" signal). Save to Google Drive rides along on the same
   pipeline. Failure handling (ImageFailureConfirmModal) is byte-identical
   to the classic tab's own.

DEVIATIONS from spec:
1. BRANCH-MANAGEMENT SELF-CORRECTION (worth flagging explicitly): item 2 was
   initially built on top of item 1's own branch (stacking on an unmerged
   base - PR #104 was still open), violating docs/lessons.md's stacked-PR
   lesson. Caught before pushing: committed item 2 on that branch, then
   created a fresh branch off origin/master and used `git cherry-pick` to
   land only item 2's commit cleanly (no conflicts - item 1 and item 2 touch
   different regions of DisplayPage.tsx). PR #109 is genuinely independent
   of PR #104's branch; verified via `git diff --stat origin/master...HEAD`
   showing only item 2's 3 files before pushing.
2. Google Drive save was listed as "rides along if cheap; if not, flag which
   one stays a deep link" - it rode along at no extra cost (same
   useSaveToDrivePDF/pipeline reuse as Download), so nothing stayed a deep
   link.
3. Sheet-thumbnail-scale Confirm badges (design doc's own §4.3, unrelated to
   items 1/2) remain out of scope, as noted in PR #102's own report -
   PagePreview's slots are plain <img> renders, no CardSlot mount point.

VERIFICATION: what ran, with results
Item 1:
  - PagePreview.test.tsx (2 new unit tests + 1 strengthened existing test).
  - DisplayPage.spec.ts (1 new end-to-end test, zero-search-result import
    shows query text on the sheet).
  - npx tsc --noEmit clean; npx jest - 393/393 passing;
    NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build clean.
Item 2:
  - New tests/DisplayPageExport.spec.ts (4 tests): non-default-settings
    export downloads cards.pdf without navigating off /display (verified via
    a captured full-resolution image request); real determinate progress bar
    appears mid-fetch - required a MutationObserver-based capture in-page
    rather than a polled Playwright assertion, since the "fetching" phase's
    own window can be narrower than an assertion's retry interval for a
    small (2-image) export, confirmed by direct debugging when the polled
    version flaked repeatedly; failure-modal cancel actually prevents the
    download; confirming despite failures still downloads.
  - tests/DisplayPage.spec.ts full regression: 14/14 passing (zero behavior
    change to Step 1/PR 2a/PR 2b surfaces).
  - tests/PDFGenerator.spec.ts full regression: 8/8 passing (zero behavior
    change to the classic tab, confirming the exported functions are
    genuinely shared, not diverged copies).
  - npx tsc --noEmit clean; npx jest - 391/391 passing (2 fewer than item
    1's own count since item 1 isn't merged into this branch's base);
    NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED=true npx next build clean.
Both: pre-commit run prettier (CI-pinned) - clean/no changes needed on
  first run for both PRs' file sets.
Sandbox note: this session hit intermittent Playwright full-file-run
  collection flakiness again mid-task (documented in PR #102's own report as
  environmental, reproducing on untouched files) - all runs in this task
  eventually passed cleanly on retry; no code-level cause found or expected.

OPEN ITEMS / DECISIONS NEEDED: none - both PR #104 and PR #109 are open and
ready for review, independent of each other (neither stacks on the other).

LIVE STATE:
- claude/proposal-h-3a-missing-image-name-04bam2 pushed, PR #104 open
  against master (1 commit, item 1 only).
- claude/proposal-h-3b-inline-export-04bam2 pushed, PR #109 open against
  master (1 commit, item 2 only, cherry-picked clean off origin/master -
  not stacked on PR #104).
- This report is on its own fresh branch claude/proposal-h-relay6-04bam2,
  forked directly from origin/master, per the report-relay convention.
- Remaining owner-ordered work (flat scroll + virtualization benchmark,
  three-pane layout migration, instrument parity 2c-2f into the left panel,
  staged classic-tab retirement) not started this session - see the design
  doc's §6 and the owner's revised work order for the full sequencing.
```
