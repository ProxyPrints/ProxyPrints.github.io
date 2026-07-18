```
TASK: PR #82 rebase (post-#73 merge) + type-tightened useCardDocumentsByIdentifier
      + ExportImages.tsx twin-bug fix
Branch: claude/bleed-dimension-basis-134 -> PR #82 (base: master, updated)
Commits: b523f3c (merge), 18379f1 (type-tightening + fix)

WHAT SHIPPED:
1. Rebased PR #82 onto master after PR #73 (Proposal B PR-2+PR-3) merged.
   Real merge required (docs/lessons.md + bleedNormalize.test.ts both
   touched by both PRs) - resolved: lessons.md kept both entries (non-
   overlapping content), bleedNormalize.test.ts kept both the new
   TRIM_ASPECT_RATIO import (this PR) and willLikelyGenerateBleed import +
   its test block (PR #73), verified the merged file actually contains
   both (not just import-list resolution).
2. Type-tightened useCardDocumentsByIdentifier's (and its underlying
   selectCardDocumentsByIdentifiers selector's) declared return type from
   `{[id]: CardDocument}` to `{[id]: CardDocument | undefined}` - it's
   keyed by every project member identifier, including ones whose
   CardDocument hasn't finished loading yet, but the old type hid this
   from every caller's type-checker (exactly how BleedOverrideSettings's
   crash in task #135 went uncaught by tsc).
3. Let tsc find every real call site needing a guard, fixed each:
   - ExportImages.tsx (the actual twin bug): guarded the eligibility
     filter with a type-predicate (`cardDocument != null && ...`),
     matching the pattern already used correctly elsewhere in the
     codebase (fastPreviewEligibleIdentifiers, BleedOverrideSettings).
   - CardResultSet.tsx: a local annotation claimed `CardDocument | null`
     when the actual type (and its own `!= null` guard, unchanged) was
     `| undefined` - a type-only correction, zero behavior change.
   - PDF.tsx, SCMPDF.tsx, PDFGenerator.tsx (BleedOverrideSettingsProps),
     clientSearchService.ts (getFileHandlesByIdentifier): widened
     cardDocumentsByIdentifier's type through the render pipeline to
     match reality. All of these already filtered out undefined entries
     safely at runtime before this change (paginate* functions'
     `.filter((d): d is CardDocument => d !== undefined)`, SCMPDF's own
     `resolve()` returning `CardDocument | undefined`,
     getFileHandlesByIdentifier only ever calling Object.keys on the
     map) - purely type-annotation corrections, no new logic anywhere
     in this group.
4. New regression test (ExportImages.test.tsx): renders ExportImages
   with a Redux store where one project member's identifier has no
   corresponding CardDocument loaded yet, clicks "Card Images", asserts
   no crash and that only the loaded card gets queued. Verified the test
   actually catches the regression - temporarily reverted the guard
   (git stash) and confirmed the SAME test run crashes with the exact
   pre-fix TypeError, then restored the fix and re-confirmed green.

DEVIATIONS: none from the explicit instruction ("tighten the type so the
compiler enforces guards at every call site, guard both sites, add the
test") - the type-tightening's downstream cascade (PDF.tsx/SCMPDF.tsx/
PDFGenerator.tsx/clientSearchService.ts) wasn't explicitly named but is
the direct, mechanical consequence of "every call site" - all fixes in
that cascade were confirmed pre-existing-safe-at-runtime, type-only.

VERIFICATION:
- npx tsc --noEmit: clean (0 errors) after all fixes.
- npx jest --runInBand: 30 suites / 334 tests passing (up from 333 pre-
  this-task, +1 for the new ExportImages regression test).
- npx eslint on all touched files: 0 errors, 3 pre-existing unrelated
  warnings (2 jsx-a11y/alt-text on PDF.tsx/SCMPDF.tsx already flagged in
  earlier reports this session, 1 react-hooks/exhaustive-deps on
  CardResultSet.tsx unrelated to the touched line).
- npx prettier --write on all touched files: clean, no unexpected diffs.
- PR #82 updated (title unchanged, body extended with the rebase
  section): https://github.com/ProxyPrints/ProxyPrints.github.io/pull/82
  - mergeable_state: "clean" against current master.

OPEN ITEMS / DECISIONS NEEDED: none.

LIVE STATE: PR #82 pushed and updated, open against master, not merged.
No local dev servers or background processes running.
```
