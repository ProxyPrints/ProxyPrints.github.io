```
TASK: Upstream-readiness audit, Phase 2 (reduced scope) — branch
`claude/upstream-readiness-audit-cvq14g` (commit `346e91a4`, pushed),
plus new branch `upstream-feat-local-file-source` (commit `93874645`,
pushed to `origin`, this fork). No PR opened anywhere. Nothing pushed
to or otherwise touching `chilli-axe/mpc-autofill`.

WHAT SHIPPED, per the three decisions:
1. Minimal-investment continuation: no action required of me (P.S. is
   handled in the owner's own pitch document) — noted as satisfied at
   the top of `readiness-audit.md`.
2. Phase 2, ONE branch: `upstream-feat-local-file-source`, cut in an
   isolated worktree off `upstream/master` (tip `c3d10253`), cherry-
   picked from fork commit `5cb438b2` (already a single, clean,
   self-contained unit — no splitting needed). One merge conflict
   (a duplicate `import logging` line) resolved trivially. Two
   cross-commit dependency gaps found and hand-fixed: `views.py`'s new
   `logger.warning(...)` call needed `logger = logging.getLogger(__name__)`
   added (the fork's own copy came from an unrelated Sentry-removal
   commit, not portable); `admin.py`'s new admin action needed
   `HttpRequest`/`QuerySet` imports added (the fork's own copies came
   from unrelated later vote-system commits). Final commit: 8 files,
   +384/−4, exactly the audit's predicted Chunk-H scope. Verified clean
   against `git diff upstream/master` (nothing extraneous). Pushed to
   `origin` as `upstream-feat-local-file-source`. Draft PR description
   written to `docs/upstreaming/drafts/upstream-feat-local-file-source.md`
   (PR body + a separate internal "extraction notes" section) — NOT
   opened anywhere. Card DOM API and the dead-image/error-states pairing
   noted as deferred/next-up in `readiness-audit.md`'s new "Phase 2
   status" section, pending the maintainer's frontend-direction answer.
3. `vote-system.md`: added one header line pointing to
   `readiness-audit.md` as the current map; left otherwise as-is per
   the "remains historical-scope" decision.

DEVIATIONS from spec, each with reasoning:
- Amended the cherry-picked commit twice (once to add the
  `Co-Authored-By: Claude Sonnet 5` trailer per conventions.md, once to
  fold in the two hand-fixes and an isort formatting nit) rather than
  leaving them as separate commits — keeps the branch at one commit,
  matching PR #467's own precedent and conventions.md's "keep it to as
  few commits as practical, ideally one" guidance.
- Kept the original commit's author (`wilfordgrimley`) and message
  verbatim (plus the trailer) rather than rewriting either — the message
  never referenced "our fork"/fork-specific framing, so per the
  documented cherry-pick-vs-hand-reapply rule this qualified as a clean
  cherry-pick, not a hand-reapply.

VERIFICATION: what ran with results, what was deferred and why —
- `pre-commit`-equivalent (ruff 0.0.257, isort 5.12.0 `--profile black`,
  black 22.8.0, mypy 1.7.0 with upstream's exact `additional_dependencies`
  pin list) run directly against every touched file: clean, except one
  pre-existing mypy `QuerySet` type-arg warning in `admin.py` — confirmed
  by running the same mypy config against *unmodified* `upstream/master`
  files (`documents.py`, `search_functions.py`) that the identical
  warning already exists there, unrelated to this change (django-stubs
  version drift against upstream's own current code). Not something this
  branch introduced or is responsible for fixing.
- `end-of-file-fixer`/`trailing-whitespace` checked by hand (grep +
  `tail -c1`): clean.
- Full test suite: **could not run.** This sandbox has no Docker daemon
  (`docker.sock` missing) and upstream's own `conftest.py` gates its
  *entire* pytest session behind an `autouse=True`, session-scoped
  `elasticsearch` fixture backed by `testcontainers` — so even the 9 of
  15 new tests that touch neither DB nor ES could not be collected.
  Confirmed this is upstream's own existing test-harness design, not
  something this branch changed. Deferred, with a concrete substitute:
  hand-executed those 9 DB/ES-independent scenarios directly against
  real temp directories/symlinks outside pytest (path-traversal/symlink
  rejection, folder/image crawl including symlink exclusion and DPI
  derivation, thumbnail URL construction) — all passed, exercising the
  same assertions the real tests make. The remaining 6 (view-layer,
  needs a DB-backed `Card`/`Source`) and 2 (indexing, needs real ES)
  genuinely need live Postgres+ES and were not run; a quick SQLite
  substitution attempt was blocked by pre-existing, unrelated
  Postgres-specific model field usage failing Django's SQLite checks —
  not worth working around for this exercise. `django.setup()` +
  direct imports confirmed the whole app registry loads cleanly with
  this branch's code in place, at least ruling out import/syntax errors
  anywhere the diff touches.
- All of the above (including the two exact hand-fix locations and
  what wasn't run) is written up in the draft doc's "Extraction notes"
  section for whoever eventually sends this PR.

OPEN ITEMS / DECISIONS NEEDED:
1. Owner: before this PR is actually sent, re-run the full test suite
   against real Postgres+ES (or just let upstream's own CI do it once
   opened) to cover the 8 cases this sandbox couldn't run — flagged
   explicitly in the draft doc, not silently skipped.
2. Owner: when the maintainer's frontend-direction answer comes back,
   revisit `readiness-audit.md`'s "Phase 2 status" section to decide
   whether Card DOM API / dead-image-handling move forward or the
   whole program pauses further.

LIVE STATE: `upstream-feat-local-file-source` pushed to `origin` at
`93874645`, worktree cleaned up (branch persists, nothing lost).
`claude/upstream-readiness-audit-cvq14g` pushed to `origin` at
`346e91a4` with the updated audit doc, the draft PR doc, and
`vote-system.md`'s pointer line. No PR opened on either fork or
upstream repo. `upstream` remote was fetched from (needed to cut the
branch) but never pushed to — confirmed via reflog. Session holding
here.
```
