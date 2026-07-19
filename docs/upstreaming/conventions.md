# Upstream PR conventions checklist

One page. What every `upstream-fix-*`/`upstream-feat-*` branch must
satisfy before it's PR-ready, derived from our one merged PR (#467) and
13 of `chilli-axe/mpc-autofill`'s own recently-merged human PRs. Companion
to `docs/infrastructure.md`'s "Upstreaming to chilli-axe/mpc-autofill"
section and `docs/upstreaming/readiness-audit.md`.

## The reference: PR #467

"Fix `toSearchable` to not strip mid-string 'the'" — merged 2026-07-18,
same-day-reviewed by maintainer Nicholas de Paola. One commit, 2 files
(`processing.ts` + its test, updated together), title is a plain
imperative sentence, body states the concrete broken example, the
correct output, references the completed companion backend PR (#460) by
number, and says exactly what the diff does. No conventional-commits
prefix. `Co-Authored-By: Claude Sonnet 5` trailer on the commit, nothing
AI-related in the PR body — this is the maintainer's explicitly stated
preference across all 5 of this fork's upstream PRs so far.

## Checklist

1. **Branch from `upstream/master` in an isolated `git worktree`**, never
   a plain checkout in the main tree and never from fork `master`.
   `git worktree add <path> upstream/master -b upstream-fix-<slug>` (or
   `upstream-feat-<slug>` for net-new capability).
2. **Re-verify before cutting**: `git fetch upstream master`, re-check
   `git merge-base upstream/master origin/master` (unshallow the clone
   first if it comes back empty — see readiness-audit.md §0, that's
   usually a shallow-clone artifact, not a real gap).
3. **Cherry-pick when the original commit's content and narrative both
   port cleanly; hand-reapply against upstream's current tree when they
   don't** (message references "our fork"/"our master", fork-specific
   framing). #467 itself was a hand-reapply of fork commit `206a0266`.
4. **Keep it to as few commits as practical** — one, ideally, matching
   #467. Upstream has no squash-merge policy (full PR history is
   preserved as-is), so what you push is what stays.
5. **`git diff upstream/master <branch>` before every push** — confirm
   it contains _only_ the intended change. No `CLAUDE.md`, no `docs/`,
   no branding, no fork CI/deploy files, no unrelated hunks from a
   shared file (e.g. `settings.py`, `views.py` — several fork chunks
   share these files with unrelated changes; hand-split, don't take the
   whole file diff).
6. **Update or add tests in the same commit.** Every sampled upstream PR
   (13 non-dependabot merges, from 2-file fixes to 3,000+-line overhauls)
   shipped test changes alongside its behavior change. None shipped
   without.
7. **Write the commit body by hand**: root cause, a concrete symptom
   (real before/after example where applicable), the origin issue/PR
   number if one exists, exactly what the diff changes. Keep the
   `Co-Authored-By: Claude Sonnet 5` trailer on the commit itself.
8. **`pre-commit run --all-files` clean, locally, before pushing.**
   Upstream's hook _versions_ already match this fork's — ruff
   `v0.0.257`, isort `5.12.0` (`--profile black`), `pre-commit-hooks`
   `v2.3.0`, black `22.8.0`, mypy `v1.7.0`, prettier `v2.7.1`, eslint
   `v8.24.0` — nothing to reconcile there. **Only the mypy hook's
   `additional_dependencies` pin list drifts**: carry only the pins the
   branch's own change actually needs (e.g. don't bring
   `django-allauth`/`pytesseract` pins for a PDF-preview fix), and
   **never silently drop `sentry-sdk~=1.30.0`** from that list unless the
   PR is itself proposing to remove upstream's own Sentry integration —
   this fork removed it for its own reasons, upstream hasn't.
9. **Run whichever of upstream's test suites the change touches**:
   `test-backend` (pytest + real Postgres, needs `GOOGLE_DRIVE_API_KEY` +
   `MOXFIELD_SECRET`), `test-frontend` (Playwright, 4-way sharded),
   `test-image-cdn`, `test-desktop-tool` — see `.github/workflows/` on
   `upstream/master` for the exact job graph.
10. **Write the PR description by hand**, not AI-generated, using
    `.github/pull_request_template.md`'s `# Description` / `# Checklist`
    structure on `upstream/master`, filled with real specifics — the
    maintainer has asked for this explicitly, every time, across all 5
    PRs opened so far.
11. **`gh pr create -R chilli-axe/mpc-autofill`** when the owner actually
    sends it — GitHub/`gh` already default a fork's PR base to the
    upstream parent, but confirm the flag explicitly anyway.
12. **Check in with the owner before pitching, every time** — upstreaming
    is currently deprioritized (chilli-axe has signaled plans to drop the
    Node.js frontend). A chunk sitting ready on a branch is not the same
    thing as permission to open the PR.

## CI for the ladder

Two small GitHub Actions workflows keep every cut `upstream-fix-*`/
`upstream-feat-*` branch honest without ever writing or fixing code
themselves: `upstream-branch-verification.yml` mirrors upstream's own
`test-pre-commit.yml`/`test-backend.yml` recipes against each branch
(weekly cron, plus a manual `workflow_dispatch` right after cutting or
updating one — GitHub can't fire a native `on: push` for these branches
since a clean extraction never carries the workflow file itself, so
`workflow_dispatch` is the real substitute; see the file's own header
comment), and `upstream-drift-monitor.yml` runs a no-commit trial merge
(`git merge-tree`) of each branch onto the current `upstream/master` tip
weekly and rewrites `docs/upstreaming/drift-log.md` in place with
whether it still applies cleanly, how far upstream has moved past the
branch's fork point, and whether any of those new upstream commits touch
the same files. Both relay a short note per the standing report-relay
convention (`docs/reports/<date>-*.md` on `report-relay`); the
verification workflow's per-branch pre-commit/test output and the drift
monitor's always-current table are the durable artifacts, the relay note
is just the pointer. Neither workflow decides pass/fail for you — a real
test failure caused only by this fork's own CI missing
`GOOGLE_DRIVE_API_KEY`/`MOXFIELD_SECRET` secrets is expected noise, not
a regression, so each branch's own draft doc under `docs/upstreaming/drafts/`
should record its expected-green baseline to check the run's output
against. The drift monitor never rebases, merges, or otherwise touches a
branch — automation's job stops at detecting rot; a human or a worker
session decides what "still upstream-shaped" means and whether/when a
rebase is worth doing, the same separation of concerns the entrypoint/
migrate composition lesson in `docs/troubleshooting.md` argues for
(steps that look independently automatable can already be fused if you
let them chain unsupervised). Once a branch's PR actually merges or
closes upstream, delete the `origin` copy — both workflows discover
branches by name pattern alone, with no way to know a PR's status, so a
stale branch just keeps getting harmlessly re-checked forever otherwise.

**Back-absorption is a tracked task, not an assumption.** A fix born on
an `upstream-fix-*` branch merging upstream doesn't mean _our_ fork picked
it up — author ≠ absorbed; check explicitly (cross-layer, not just the
one file the PR touched) rather than assuming parity, the same discipline
`upstream-fix-frontend-searchable-the`/#467's own absorption check
required.

## Style notes from the wider PR sample

- No enforced title prefix. PR titles are short descriptive noun phrases,
  usually matching the source branch name closely.
- External contributors bring their own commit style unenforced (one
  sampled PR used `feat(pdf):`/`fix(pdf):` conventional-commit prefixes,
  another used plain lowercase sentences) — since #467 used neither a
  prefix nor multiple commits and passed cleanly, that's the safest
  default to replicate.
- The maintainer's own day-to-day commits are informal and occasionally
  jokey (`draw the rest of the owl`, `missed a spot`) — don't over-format
  relative to that norm, but our own PRs should stay closer to #467's
  more explanatory style since that's what's been reviewed and accepted
  from us specifically.
- Full-stack features are commonly split into sibling backend/frontend
  PRs merged same-day rather than one combined PR (e.g. #441 backend /
  #442 frontend, ~3 hours apart) — replicate this shape for any
  full-stack fork feature that reaches PR stage.
