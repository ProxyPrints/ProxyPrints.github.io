```
TASK: CI for the upstream ladder — branch
`claude/upstream-readiness-audit-cvq14g`, commit `8fab3232`, pushed to
`origin`. No PR opened; nothing touches `chilli-axe/mpc-autofill`.

WHAT SHIPPED, per the three items:
1. `.github/workflows/upstream-branch-verification.yml` — mirrors
   upstream's own `test-pre-commit.yml`/`test-backend.yml` recipes
   (same actions, same pinned versions: `actions/checkout@v6`,
   `actions/setup-python@v6`, `jsdaniell/create-json@v1.2.3`) against
   each `upstream-fix-*`/`upstream-feat-*` branch. Weekly cron
   (Mondays 07:00 UTC) + `workflow_dispatch` with an optional `branch`
   input. Relays a per-branch report to `report-relay` regardless of
   pass/fail — the workflow itself never hard-fails on a real test
   failure, since judging "regression vs. known environmental gap"
   needs the branch's own documented baseline (see item 3's doc
   update), not a blanket CI red X.
2. `.github/workflows/upstream-drift-monitor.yml` — weekly (Mondays
   08:00 UTC) no-commit trial merge (`git merge-tree --write-tree`) of
   each branch onto the current `upstream/master` tip; rewrites
   `docs/upstreaming/drift-log.md` in place (regenerated whole-table
   each run, not appended) with applies-clean?, upstream commits since
   the branch's fork point, and file-overlap with what upstream's
   moved since. Detection only — confirmed no rebase/merge/mutation of
   any branch anywhere in the workflow.
3. `docs/upstreaming/conventions.md` gained a "CI for the ladder"
   section covering both workflows plus the principle: automation
   detects rot, a human/worker decides what "still upstream-shaped"
   means and whether to rebase — explicitly grounded in the
   entrypoint/migrate composition lesson already in
   `docs/troubleshooting.md` (steps that look independently automatable
   can already be fused if left to chain unsupervised). Standing relay
   reporting applies to both workflows' own run notifications.

DEVIATIONS from spec, each with reasoning:
- **"On push" isn't literally achievable and isn't implemented as
  such** — GitHub only evaluates a workflow's triggers against the ref
  being pushed, and a clean `upstream-feat-*`/`upstream-fix-*`
  extraction branch by definition never carries this (or any) fork-only
  workflow file, so a native `push:` trigger scoped to those branches
  can never fire; there'd be nothing on that ref for GitHub to read a
  trigger from. Rather than ship a `push:` clause that looks correct
  but silently never runs, substituted `workflow_dispatch` (fired
  manually right after cutting/updating a branch) as the real
  equivalent, documented prominently in the workflow's own header
  comment and in conventions.md. Flagging this clearly rather than
  quietly delivering something that wouldn't have worked.
- Report-relay commits from the workflows use a fresh shallow clone +
  retry loop rather than `actions/checkout` for that step, to avoid
  colliding with the already-checked-out branch-under-test in the same
  job workspace.
- `drift-log.md` was seeded by hand today with real computed values
  (not left as an empty stub) since the workflow won't actually run
  until this branch merges to `master` (GitHub only schedules workflows
  present on the default branch) — noted explicitly in the file's own
  header so the discrepancy in format (hand-seeded version has PR-status
  annotations the automated version can't know) isn't surprising on the
  first real run.

VERIFICATION: what ran with results —
- Both workflow YAML files parsed successfully (`yaml.safe_load`).
- Every `run:` block extracted and checked with `bash -n` (syntax-only):
  all clean.
- Caught and fixed a real bug before committing: GitHub Actions `run:`
  steps default to `bash -eo pipefail`, so `pre-commit run --all-files |
  tee out.txt; echo exit_code=${PIPESTATUS[0]}` would have aborted
  before the exit-code line ever ran on any real failure (errexit kills
  the script at the first nonzero pipeline command). Fixed in both the
  pre-commit and pytest capture steps with an explicit `set +e` /
  capture / `set -e` bracket.
- Ran the actual drift-computation git plumbing (merge-base,
  `git merge-tree --write-tree`, commits-since, file-overlap) for real
  against all 6 `upstream-fix-*`/`upstream-feat-*` branches currently on
  `origin` (not synthetic data) — all report `applies clean: yes`,
  correct non-zero commits-since counts for the older branches, zero
  false conflicts. `drift-log.md` was seeded with this exact real
  output.
- Noticed and documented (not silently ignored): two of those six
  branches (`upstream-fix-frontend-searchable-the`, already merged as
  #467; `upstream-fix-pdf-canvas-preview`, closed upstream as
  not-a-bug) are stale and will keep getting harmlessly re-checked
  forever since neither workflow can see PR status, only branch
  existence — documented in `conventions.md` and `drift-log.md` that
  deleting the `origin` branch once its PR resolves is what makes it
  drop out.
- Deferred: an actual live GitHub Actions run. Can't trigger one from
  this sandbox — `workflow_dispatch` isn't available until this branch
  merges to `master`, and the weekly `schedule` only fires from
  whatever's on the default branch. Everything above is real
  verification of the logic and syntax, not a substitute for watching
  an actual run succeed.

OPEN ITEMS / DECISIONS NEEDED:
1. Owner: once this (and the rest of the upstream-readiness branch) is
   merged to `master`, manually fire `workflow_dispatch` on
   `upstream-branch-verification.yml` once to get a first real signal
   on `upstream-feat-local-file-source` before relying on the weekly
   cron.
2. Owner (low priority, optional cleanup): delete
   `origin/upstream-fix-frontend-searchable-the` and
   `origin/upstream-fix-pdf-canvas-preview` (already resolved upstream)
   so the drift monitor stops tracking them.
3. Both new workflows need `secrets.GOOGLE_DRIVE_API_KEY` /
   `secrets.MOXFIELD_SECRET` to exist in this repo's Actions secrets for
   the backend-test step to reach real parity with upstream's own CI —
   per earlier CI audit findings, this fork doesn't currently have them
   configured, so real runs will show the documented "expected"
   Google-Drive/Moxfield test failures until/unless that changes. Not
   blocking (the CI baseline doc already accounts for it), just noting
   for awareness.

LIVE STATE: `claude/upstream-readiness-audit-cvq14g` pushed to `origin`
at `8fab3232` with both workflow files, `drift-log.md`, and doc updates.
No PR opened. `upstream-feat-local-file-source` branch unchanged. Both
new workflows are inert until this branch is merged to `master` by the
owner. Session holding here.
```
