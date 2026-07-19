```
TASK: Catalog-completion Part 3 (HOLD #P3) + server-queue items A-D.
Worktree: catalog-completion-part2. PRs: #58 merged, #60 open
(unmerged), #61 merged, #62 draft (hard-gated, not yet started).

WHAT SHIPPED (backfilling the record per your ask):

1. 15-card content_phash backfill-failure probe verdict: SCATTERED
   across 6 distinct community Drive sources (CompC x1,
   Hathwellcrisping x4, LePoulpe_Dec_2023 x2, RustyShackleford x6,
   Trix_Are_For_Scoot x1, Trix_Are_For_Scoot_2 x1) - NOT concentrated
   in the owner's own WilfordGrimley source. Genuine dead/flaky Drive
   links, not an intentional exclusion. All 15 card ids logged in
   docs/features/catalog-completion-plan.md as a ready-made live test
   set for PR #35 / E-2 dead-link work.

2. HOLD #P3 content that never reached you:
   - OCR-refetch sample: 30/30 recovered (100%) on a 30-fetch
     validation sample - expected near-100%, this recovers an
     already-successful match, not a cold one.
   - Mechanism chosen: three recovery paths - phash (free, DB+
     arithmetic, zero fetch), OCR-refetch (1 CDN fetch + fresh OCR
     pass), fallback-refetch (1 CDN fetch + fresh border/artist/
     symbol pass) - plus a separate d=0 sibling artist-propagation
     path (987, corrected from an earlier scope-incomplete "0").
   - Expected vote counts: phash path already ran against the FULL
     980-card population (not a sample) - 750/980 recovered -> 750
     artist votes + 750 altered-frame tag votes would cast. d=0
     sibling: 987 artist votes would cast. OCR+fallback full-
     population numbers (~5,773 cards) are what the still-running
     fullrun container will produce - not yet in hand.
   - WHO issued the go for the write pass: NOBODY YET - correcting
     this rather than recording a go-ahead that wasn't given. Build +
     dry-run were authorized in-session (SERVER unified block item 2,
     and the mid-turn correction message, which itself ends "Hold
     before any write pass"). Every instruction touching this has
     explicitly held the write pass open. This report is what that
     hold requires before a go/no-go decision is possible.

3. PR #60 - "Part 3: shared frame-mismatch evidence-recovery module
   (HOLD #P3)": new local_residual_classify module + management
   command + 18 tests. Dual-yield frame-mismatch recovery (artist
   vote + altered-frame tag) across phash/OCR/fallback engines, plus
   d=0 sibling artist propagation. Defaults to dry-run, requires
   explicit --write. Status: OPEN, unmerged - CI failures confirmed
   pre-existing known-flake buckets (tesseract-missing + moxfield
   assert-decklist), gh pr merge blocked by the auto-mode classifier
   on my end, flagged for a manual merge.

4. Fullrun container: still running, ~65 min elapsed against the
   ~35 min fetch-only estimate - expected per your note (estimate
   priced fetches, not per-card CPU), not yet past the "well past 2x"
   threshold you set. No output since its dry-run start line (no
   intermediate logging by design). Will deliver the standard block
   (ledger row, final vote counts per path, zero-resolution assertion
   result) the moment it exits, then proceed straight into PR #62's
   pytest hard gate per its own checklist.

Also completed this window (queue items A, part of C):
- PR #61 (E-1, XML 2.0 import round-trip): frontend-only, CI 4/4 +
  Playwright green, no flake. Merged, deleted branch.
- PR #58 (funnel layout reconciliation): master had advanced past
  its base - merged master into the branch, resolved one prose-only
  conflict in docs/features/printing-tags.md (kept the branch's
  fuller Level-1+2 description), prettier-formatted, pushed. CI
  reproduced the documented QuestionFeed.test.tsx parallel-worker
  flake (matches troubleshooting.md's existing entry exactly), all
  else green. Merged, deleted branch. Pages deploy for master
  confirmed green.
- Found master's CI red after PR #57's earlier merge: un-prettier'd
  docs/proposals/proposal-f-public-stats-page.md. Fixed and pushed
  directly to master (11ccb042).

DEVIATIONS: none from the queue as given. Item 2 above is a
correction, not a deviation - avoiding recording a write-pass
go-ahead that doesn't exist.

VERIFICATION: PR #61 CI - 4/4 Frontend tests + Playwright merge, all
green. PR #58 CI - 3/4 Frontend tests green + 1 confirmed known-flake
(identical failing assertion pre- and post-merge-commit). PR #60 CI -
Backend tests failure confirmed against known tesseract-missing-in-CI
bucket via gh run view --log-failed, unrelated to the PR's diff.
Master Pages deploy - confirmed completed/success via gh run list.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #60 needs a manual `gh pr merge` from you - CI is clean modulo
   known flakes, blocked only by the auto-mode classifier on my end.
2. Write-pass go/no-go for HOLD #P3 is still outstanding - full
   frame-mismatch numbers land once the fullrun container completes;
   decision is yours once both paths' numbers are in front of you.

LIVE STATE: residual-classify-fullrun Docker container running
(dry-run only, no votes written, run_id part3-fullpass-dryrun-01),
background capture armed to grab its output before --rm deletes it.
WORKERS.md row updated to reflect current scope. PR #62's hard-gate
pytest run queued to start immediately after the container exits, per
your ratified CPU-contention sequencing.
```
