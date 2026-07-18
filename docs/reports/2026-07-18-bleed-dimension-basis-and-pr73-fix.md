```
TASK: (1) Task #134 dimension-basis bleed fix, (2) PR #73's red PagePreview.spec.ts
      + prettier (task #135)
Branches: (1) claude/bleed-dimension-basis-134 -> PR #82 (base: master)
          (2) claude/e4-bleed-preview-badge -> PR #73 (base: master, existing PR,
              pushed commit c0eea62)
Commits: (1) e38519a  (2) c0eea62

WHAT SHIPPED:

1. DIMENSION-BASIS FIX (task #134, live-harm priority) - PR #82, merged into
   claude/bleed-dimension-basis-134 off master (already includes the
   export-image-rate-limit-fix, PR #81, since merged to master as of this
   report).
   - resolveBleedPlan's plan-input hierarchy flipped per the owner's design
     decision: PRIMARY signal is now the source image's own pixel dimensions
     (new classifyBleedAspectRatio, mirroring the backend's classify_bleed_edge
     aspect-ratio method and constants exactly - TRIM_ASPECT_RATIO/
     BLEED_ASPECT_RATIO, 0.03 tolerance) via new dimensionDerivedBleedMM
     ((px_dim - trim_mm*dpi/25.4)/2, symmetric per axis).
   - Probes (measureCardBleedPx) demoted to two advisory-only roles, zero trim
     authority: per-side ambiguity still forces the prior/manual-override
     fallback (preserves original degenerate/full-art handling); new
     detectBleedAsymmetry (exported, unit-tested) flags a card for manual
     review without touching the plan - no UI consumer wired yet, same
     pattern as E-2's degradedQueries.
   - OVERSIZED_MULTIPLE keeps its bad-DPI-guard meaning, now checked in both
     directions (Math.abs()) since a dimension-derived value can go negative
     in a way a probe run length never could.
   - resolveBleedPlan gained sourceWidthPx/sourceHeightPx params; the one
     production call site (bleedExtension.ts's normalizeCardBleed) already
     has the decoded bitmap's own width/height in hand.
   - bleedNormalize.test.ts rewritten: 19 `it` blocks (up from 8) - a
     probes-demoted regression fixture, a real-dimension fixture using Evil
     Twin's actual 460dpi calibration numbers (near-no-op plan, ~0.08-0.19mm
     on every side vs. the ~2x overshoot the old design would have computed),
     axis-independence, bidirectional oversized-guard, and the preserved
     ambiguity-forces-fallback case.
   - docs/proposals/proposal-b-bleed-normalization.md + docs/lessons.md
     updated with the design decision, its rationale, and the generalized
     lesson (a measurement error invariant across a wide constant sweep
     points at the method, not the constant).

2. PR #73 RED-TEST FIX (task #135) - pushed directly to the existing PR #73
   branch (claude/e4-bleed-preview-badge), no new PR opened.
   - Root cause: BleedOverrideSettings's eligibility filter
     (PDFGenerator.tsx) accessed cardDocument.sourceType without a null
     check. useCardDocumentsByIdentifier's underlying selector
     (selectCardDocumentsByIdentifiers) maps EVERY project member
     identifier to its CardDocument, including identifiers whose document
     hasn't finished loading into the store yet (mapped to undefined) - the
     fast preview's own sibling eligibility filter in the same file
     (fastPreviewEligibleIdentifiers) already guarded against this; this one
     didn't, throwing "Cannot read properties of undefined (reading
     'sourceType')" the instant the panel rendered before every card had
     loaded - exactly what PagePreview.spec.ts's fast-preview tests do (no
     debounce, asserted on first paint).
   - Diagnosed via a saved Playwright error-context.md showing a Next.js
     dev-mode "Unhandled Runtime Error" overlay sitting on top of the
     (CSS-visible but never actually rendered) page-preview element
     underneath - reproducing exactly the false-positive-visible pattern
     already documented in docs/lessons.md from an earlier, unrelated bug
     this session (comlink DataCloneError).
   - Fix: one-line null guard in the filter (`cardDocument != null && (...)`),
     matching the already-correct sibling pattern.
   - Also reformatted tests/PDFGenerator.spec.ts (pre-existing formatting
     drift on this branch, unrelated content) - this + PDFGenerator.tsx were
     the "2 files" flagged.

DEVIATIONS:
- Did not tighten useCardDocumentsByIdentifier's declared return type to
  `CardDocument | undefined` (the type-system-level fix that would have
  caught this class of bug at compile time) - doing so surfaces the SAME
  unguarded-access bug at a second, pre-existing call site
  (ExportImages.tsx:19, `cardDocument.sourceType` with no null check) that
  is out of scope for "fix PR #73's red tests." Flagged as an open item
  below rather than silently expanded into.
- Did not update willLikelyGenerateBleed (the preview badge's fast hedge,
  PR-3) despite the earlier design-decision message's note that it "likely
  wants the same dimension basis" - confirmed by reading it that it never
  called resolveBleedPlan or touched pixel data in the first place (a
  categorical prior/manualOverride hedge only), so there is nothing in it
  for the dimension basis to supersede. Documented in the proposal doc;
  flagged as a candidate for a future pass if its accuracy ever needs
  tightening, not acted on here.

VERIFICATION:
- (1) npx tsc --noEmit clean. npx jest --runInBand: 28 suites / 301 tests
  (later 306 after (2)'s fix), all passing - bleedNormalize.test.ts +
  bleedExtension.test.ts: 21/21. npx eslint on all touched files: 0 errors.
- (2) Reproduced the crash directly (error-context.md), applied the fix,
  reran tests/PagePreview.spec.ts --workers=1: 3/3 passing (previously 3/3
  failing, identical error). npx tsc --noEmit clean. Full npx jest
  --runInBand: 27 suites / 306 tests passing. npx eslint on touched files:
  0 errors. npx prettier --check found exactly 2 files needing formatting
  (PDFGenerator.tsx, tests/PDFGenerator.spec.ts) - fixed, diff confirmed
  formatting-only (no logic change) on the test file.
- FULL Playwright suite (--workers=2, all spec files) run locally on the
  e4-bleed-preview-badge branch per the explicit instruction to "run the
  FULL suite including PagePreview this time": PagePreview.spec.ts passed
  cleanly; 25 OTHER tests failed across AddCardToFavorites.spec.ts,
  ArtistVotePicker.spec.ts, PrintingTagPicker.spec.ts, TagVotePicker.spec.ts,
  Toasts.spec.ts, GeneralUIAccessibility.spec.ts, and 2 visual-snapshot
  specs - none touching bleed/PDF/PagePreview code. Re-ran 5 of those spec
  files at --workers=1 (ruling out worker-concurrency interference): 16/20
  still failed identically, so not a concurrency artifact. Cross-checked
  against REAL GitHub Actions CI history (not this sandbox): the "Frontend
  tests" workflow (4 parallel shards, test-frontend.yml, triggers on
  pull_request against frontend/**) is ALL GREEN on master's current HEAD
  (d0fc7f5, includes PR #81) as of this report - i.e. the authoritative CI
  environment shows these exact test files passing right now. Conclusion:
  the 25 local failures are a sandbox-environment artifact (unconfirmed
  root cause - candidates are outbound-proxy interaction with MSW's mocked
  external-domain fetches, or backend-mock drift specific to those
  spec files), NOT a regression this session introduced and NOT specific to
  PR #73's branch. DEFERRED, not fixed: identifying the sandbox's exact
  root cause was out of scope for "fix PR #73's red tests" and would need
  its own investigation.
- COULD NOT verify PR #73's real CI status at the new head SHA (c0eea62) as
  of this report - test-frontend.yml's pull_request trigger should fire a
  synchronize run automatically, but no check-run had appeared for that SHA
  after ~10 minutes of polling (mcp__github__pull_request_read get_status
  returned total_count: 0 throughout). Not clear whether this is a real
  delay or specific to this session's git-proxy setup (pushes route through
  a local proxy at 127.0.0.1, not directly to github.com). This is the one
  "green claims cite the CI run" bar this report cannot yet satisfy - see
  open items.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #73's CI for commit c0eea62 had not reported back as of this report.
   Recommend checking https://github.com/ProxyPrints/ProxyPrints.github.io/pull/73
   directly once CI has had time to run, or firing a manual workflow_dispatch
   if it never triggers automatically in this environment.
2. ExportImages.tsx:19 has the SAME unguarded `cardDocument.sourceType`
   access as the bug just fixed in BleedOverrideSettings, on the same
   sparse-map hook (useCardDocumentsByIdentifier) - a real, live latent bug
   (would crash "Export Images" if clicked before all card docs load), just
   not exercised by any current test. Not fixed here (out of scope for this
   task); worth a follow-up.
3. The 25 sandbox-local Playwright failures' root cause is unidentified
   (see verification above) - flagging in case they recur or block a future
   session's "run the full suite" check; real CI is the authoritative
   signal until this sandbox's own cause is found.

LIVE STATE:
- PR #82 (dimension-basis fix): open against master, not merged.
- PR #73 (preview badge, now includes the red-test fix): commit c0eea62
  pushed to claude/e4-bleed-preview-badge, PR still open, CI status for
  this specific commit unconfirmed (see open item 1).
- PR #81 (export-image-rate-limit-fix, prior task): confirmed MERGED to
  master (d0fc7f5) since this report's investigation - no longer pending.
- No local dev servers or background processes left running; temporary
  /tmp/master-check git worktree (used to cross-check master's own test
  behavior) removed.
```
