TASK: SERVER session — mini merge sweep (7 PRs) checkpoint 2 + PR #73 hold
Branch/worktree: catalog-completion-part2

WHAT SHIPPED:

1. #77 (Proposal G bleed-override note) — merged, branch deleted.
2. #75 (chunk-load-error cache-transition recovery) — merged, branch deleted.
3. #74 (wiki+docs automation first-publish verify) — merged, branch deleted.
4. #76 (AI→machine terminology) — CI-decomposed: 14 failures all known-
   bucket (11 tesseract-missing/#123, 2 moxfield, 1 test_sources.py
   JSONDecodeError), 130/130 snapshots pass. Setting-rename shim
   CONFIRMED SHIPPED (PRINTING_TAG_AI_WEIGHT → PRINTING_TAG_MACHINE_WEIGHT,
   backward-compat env fallback), not deferred. Merged, branch deleted.

HOLD — #73 (B PR-3 WYSIWYG bleed badge): NOT MERGED.

Sequence: retargeted claude/e4-bleed-preview-badge from
claude/e3-bleed-override-ui to master (stacked-PR lesson, since #71/e3
was closed unmerged). This surfaced a real 7-file conflict. While
resolving it in a scratch clone, a collision warning fired ("another
worker touching the normalization") — investigated, confirmed it was my
own scratch clone's uncommitted state, reported that back. Was then told
the _frontend session_ had ALSO retargeted #73 and pushed its own
conflict resolution independently — i.e. the collision was real after
all (two sessions converging on the same conflict from opposite
directions), and told to discard mine and merge the frontend session's
pushed head as-is, described as "verified green (tsc/eslint/jest
306/306)".

Discarded my scratch-clone resolution as instructed (never pushed).
Checked the actual live state of #73 at its current head
(6fb8b414723cde805e192a61e5e2e0c8fe9805d) before merging, per standard
practice — this does NOT match "verified green":

- `mergeable_state`: "unstable" (not "clean") as of 18:05:16 UTC.
- "Formatting and static type checking": FAILED. Root cause: prettier
  hook flags 4 files as unformatted — 2 from this merge itself
  (docs/proposals/proposal-b-bleed-normalization.md,
  docs/reports/proposal-b-pr1-bleed-prior-batch-resolution.md) and 2
  apparently pre-existing (frontend/tests/PDFGenerator.spec.ts,
  docs/reports/cache-transition-resilience.md). Everything else in that
  job (ruff/isort/black/mypy/eslint) passed.
- "Frontend tests (3/4)": FAILED. 3 real Playwright failures, ALL in
  `PagePreview.spec.ts`'s "PDFGenerator - fast page preview (Proposal
  A)" describe block — every test in that block fails identically on
  `getByTestId("page-preview")` never becoming visible (5s timeout,
  "element(s) not found"), which reads as a render crash somewhere in
  the new preview-badge code path, not a flake (all three tests in the
  same describe block fail on the exact same symptom). A 4th failure
  (MatureContentToggle.spec.ts, unrelated area) may be a pre-existing
  flake — not cross-checked against a known bucket, no matching entry in
  docs/lessons.md or docs/troubleshooting.md for either.
- Everything else (Frontend tests 1/2/4, Lint docs/, Merge Playwright
  reports, assign-author) passed clean.

Not merging on the "verified green" characterization since direct
inspection of the live check-runs contradicts it. Filed as task #135.
Did not attempt to fix — branch is the frontend session's, just pushed;
avoided a third party pushing more changes to it right after a genuine
collision, to not compound the coordination risk.

DEVIATIONS: holding #73 despite the explicit "MERGE IT AS-IS" instruction
— reasoning above; treating "verify before merging red-looking state" as
higher priority than the instruction's characterization, since the
instruction's own premise (green CI) doesn't match what's observable
right now at the given head SHA.

VERIFICATION: `gh api repos/.../pulls/73` (mergeable_state), `gh api .../commits/<sha>/check-runs` (per-check conclusions at that exact head),
full failure logs pulled via `gh api .../actions/jobs/<id>/logs` for both
the formatting job and the Frontend tests (3/4) job — read in full, not
skimmed.

OPEN ITEMS / DECISIONS NEEDED:

1. #73: does the frontend session know about these 2 failures, or did
   their "green" check predate this specific push/run? Needs their
   attention (their branch) — prettier fix is trivial (4-file
   `npx prettier --write`), the PagePreview render failure needs real
   debugging in the badge component.
2. Once #73 is actually green at its head, re-verify and merge — will
   pick this back up.

LIVE STATE: #73 open, unmerged, red at head 6fb8b414723cde805e192a61e5e2e0c8fe9805d2.
#77/#75/#74/#76 merged and branches deleted. Continuing to #56, #19,
relay-7 consolidation, Pages deploy confirmation, then task #134's
calibration pass (unaffected — 30 real images + sharp staged, no
edits to bleedNormalize.ts made by this session).
