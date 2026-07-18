As of: 2026-07-18
Task: Part 4 (LANDS) build + HOLD #B prep, PR #78/#81 merges, session wrap-up
Branch/worktree: catalog-completion-part2

## What shipped this cycle

1. **PR #78** (Level 1's missing Scryfall reference-image fix, user-facing) —
   merged after fixing 2 real CI issues it inherited from a stale branch
   point: prettier drift (3 files, 2 pre-existing on master + its own new
   report) and a `docs_lint.py` false-positive on a deliberate historical
   reference (`PrintingTagQueue.tsx`, deleted in an earlier "Queue
   redesign" commit — added a one-line ALLOWLIST entry, the tool's own
   documented mechanism for exactly this case, and removed a now-stale
   ALLOWLIST entry from #56's earlier merge in the same edit). Verified
   the actual regression test (`QuestionFeed.test.tsx`, 14/14 pass,
   including the exact "shows the suggested printing's own reference
   image" case) before merging. Pages deploy confirmed.
2. **PR #79** (wiki review findings: publish-script link fix, Part 3
   status update, staleness pass) — merged clean. Verified
   `docs-wiki-publish` fired on the exact merge commit and succeeded, then
   cloned the live wiki repo directly and confirmed both the Part 3
   status text and the `[[../troubleshooting.md]]`→`[Troubleshooting] (Troubleshooting)` link rewrite are actually live, not just that the
   workflow exited 0.
3. **PR #83 — Part 4 (LANDS) module, HOLD #B prep** (the substantial new
   build): `cardpicker/local_lands_identify.py` + its management command
   - 16 tests, mirroring Part 3's exact shape (dry_run default, run_id,
     PilotRunLedger, verify_zero_resolutions gate). Confidence-tier split
     (0.85 singleton / 0.8 tiebreak) was genuinely ambiguous from the spec
     text alone — asked directly rather than picking the reading that
     sounded most coherent to me; owner resolved it (see the "Confidence
     split" answer). Caught and fixed two real bugs during my own review
     before shipping: an artist-extraction-rate denominator bug (would have
     divided by `sampled` instead of `fetch_attempted`, diluting the rate
     with budget-exhausted skips) and an OCR-confidence recomputation bug
     (was deriving confidence from `.detail` truthiness instead of using
     `EngineVote.confidence` directly). 16/16 new tests pass; full suite
     862 passed / 130 snapshots / only pre-existing known-bucket failures.
     Merged. **HOLD #B remains open**: the real volume-check numbers (land-
     pool size, artist-extraction rate, per-name candidate-count
     distribution) need someone with production DB access to run
     `manage.py local_lands_identify` — this session doesn't have that
     access (same denial class as three earlier Docker/DB attempts this
     session; not re-attempted a fourth way, per the established pattern).
     Full reasoning lives in the module's own docstring and
     `docs/features/catalog-completion-plan.md`'s Part 4 section.
4. **PR #81** (mass export-image-failure fix: pace full-res fetches to
   the shared CDN rate limit) — merged after the same stale-branch
   prettier-drift fix as #78 (3 files). Confirmed `bleedNormalize.test.ts`
   8/8 still pass despite the merge touching `bleedNormalize.ts`. Pages
   deploy confirmed.

## Deviations

- None beyond what's already flagged: #73 held (checkpoint-2, still
  applies), Part 4's constants left as the owner-clarified split rather
  than a guessed one.

## Verification

- Every merge checked via `gh api .../pulls/<n>` (mergeable_state) and
  `.../commits/<sha>/check-runs` at the actual current head SHA before
  merging — never on a stale check or a report's characterization.
- PR #83's own test suite run twice (once before, once after the mypy
  fix) via the real host pilot venv against a real Postgres/ES-backed
  test DB, not just `py_compile`.
- Both Pages deploys confirmed via the workflow-runs API against the
  exact merge commit SHA, not assumed.

## Open items / standing waits

1. **#73** ("Proposal B PR-2 + PR-3", task #135's hold) — the frontend
   session pushed a fresh commit (head now `c0eea626`, was `6fb8b414`)
   sometime in the last few minutes. CI has not started on it yet as of
   this report (`gh api .../actions/runs?head_sha=...` returns empty).
   Will re-check and merge if green per the standing authorization —
   not yet actioned since there's nothing to verify yet.
2. **PR #82** ("Bleed plan: promote dimension-derived measurement,
   demote probes to advisory-only") — a direct follow-up to task #134's
   own calibration findings (the bleed+border conflation / over-trim
   risk I flagged). Noting its existence since it's clearly responding
   to my report; not reviewed or touched by this session — appears to
   be the frontend session's own work.
3. **HOLD #B** (Part 4) — needs production DB access this session
   doesn't have. Command is built, tested, and ready
   (`manage.py local_lands_identify`, dry-run default,
   `--fetch-budget 0` gets the free pool-size/candidate-count numbers
   instantly with zero network cost).

## Live state

master deployed and live via Pages (confirmed twice this cycle, once
per merge). Open PRs: #73 (fresh push, CI not yet started), #82
(untouched, out of scope). No scratch clones left with uncommitted work.
