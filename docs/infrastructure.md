# Infrastructure

Backend deployment, secrets, CI/CD, and telemetry details. See CLAUDE.md for
the short, standing rules; this file has the reasoning and history behind
them.

## Docker / backend deploy

- `docker/` is built with `sudo docker compose -f docker-compose.prod.yml ...` (v2, space). docker-compose v1 (hyphen) is installed on the host but
  has a fatal `ContainerConfig` recreate bug — never use it.
- `MPCAutofill/drives.csv` is baked into the django image at build time.
  Editing the host file requires `up --build -d`, which runs
  `manage.py import_sources` automatically on every boot (cheap, local CSV
  read, no network calls) to pick up the change. The file is gitignored and
  untracked (matches upstream, which also tracks no drives.csv content) —
  see "History rewrite" below for why this matters. If this machine is
  ever rebuilt, the real file must be placed at `MPCAutofill/drives.csv`
  manually before `docker compose up --build`; it does not come from git.
  Indexing catalog content (`manage.py update_database`) no longer needs a
  manual invocation after a rebuild — see "Startup vs. scheduled catalog
  sync" below; run it manually only if you want synchronous confirmation
  the catalog is populated before considering a rebuild done.
- Server clock: UTC (confirmed via `timedatectl` — `Etc/UTC`, `+0000`).
  All container logs, cron/`qcluster` schedules, and DB timestamps are
  UTC — no per-session guessing needed.
- Hardware (confirmed via `nproc`/`free -h`/`lscpu`, 2026-07-19): 8 OCPU
  (`aarch64`, `Neoverse-N1` — matches Oracle's "Ampere" tier naming),
  23Gi total RAM. Any pipeline sizing (worker-process counts, batch
  sizes, thread-pool widths) should confirm against these live numbers
  rather than an assumed instance size — this box's own docker/host
  processes (live django/worker/nginx/postgres/elasticsearch, plus
  whatever pilot/backfill job is running) already share this ceiling.
- Node versions (2026-07-19): the system default is still `/usr/bin/node`
  v20.20.2 — unchanged, and a fresh login shell resolves to it
  (confirmed via `bash -lc 'which node; node --version'`). A second
  Node 22 LTS (v22.23.1) is installed alongside it via
  [nvm](https://github.com/nvm-sh/nvm) (`$HOME/.nvm`, sourced from
  `~/.bashrc` — the sourcing lines make `nvm` available in every new
  interactive shell, but do NOT switch which `node` binary is on PATH
  by default; that only happens if a shell explicitly runs `nvm use 22`/`nvm use default`). Reason: `wrangler` (image-cdn/, and the other
  two Worker projects) requires Node >=22 and silently refuses to run
  under v20 — confirmed fixed (`nvm use 22 && npx wrangler --version`
  now succeeds; it errors under the bare system node). Use `nvm use 22`
  in any shell/script that needs wrangler; everything else on this box
  (the frontend's own `npm run dev`/`npm run build`, pre-commit's
  eslint/prettier hooks, etc.) continues to run fine under the v20
  default and was not touched.

### Startup vs. scheduled catalog sync

`docker/django/entrypoint.sh` runs only `migrate` (fast, schema-blocking)
and `import_sources` (cheap, local) before binding gunicorn — a boot never
waits on a catalog rescan, and a per-source scan failure can't take the
API down. Actual content sync is scheduled work, not boot-time work:

- **Steady state**: a daily `update_database` schedule and weekly
  `update_dfcs`/`import_canonical_card_data` schedules (seeded via data
  migrations `0043_auto_20250529_0233.py`, `0048_auto_20260426_2140.py`)
  run via the `worker` container's `manage.py qcluster` process.
- **Fresh bootstrap only**: `import_sources` enqueues one immediate async
  `update_database` run, but only if `Source` rows exist with zero `Card`
  rows yet (a genuinely new instance) — steady-state restarts never
  trigger this.
- Per-source scan failures are caught/logged/skipped, not fatal to the
  whole rescan; the per-source loop is bounded-parallel
  (`MAX_SOURCE_WORKERS`), well within the Drive API's quota headroom.
- **Known monitoring gap**: `django_q.models.Success.result` is always
  `None` for these runs (`call_command` returns nothing) — "how much
  changed on the last scan" is only in worker/entrypoint stdout, not
  queryable.

Entrypoint previously gated this behind `migrate --check`, the wrong
proxy for "does content need rescanning" — see [[troubleshooting.md]]
("Boot-time migration triggers a multi-minute rescan") for the incident
this fixed and its follow-on hardening. Fixed by `eaece1fd` (#18,
2026-07-14).

- `docker-compose.prod.yml` builds all three services (`django`, `worker`,
  `nginx`) with the repo root as build context (`context: ..`). There was no
  `.dockerignore` at all until it was added — every rebuild was uploading
  the entire repo (`frontend/node_modules`, `image-cdn/node_modules`, etc.)
  regardless of which service changed. Added a denylist-style
  `.dockerignore` (frontend build artifacts, image-cdn `node_modules`,
  desktop-tool, github-release-reverse-proxy, cloudflare-static-site,
  schemas, mypy/ruff caches, test-results, `.git`, and **`.claude`** — the
  last one is the one that actually mattered: `.claude/worktrees/` is a
  **hidden** top-level directory, invisible to a plain `du -sh repo/*` sanity
  check, and was carrying a full `frontend/node_modules` per worktree
  (~1GB each). See [[lessons.md]] for the general `du` gotcha. Net effect: a
  rebuild that previously spent 25+ minutes uploading a ~2GB context now
  uploads single-digit megabytes and finishes in ~5 minutes.
- Postgres/ES: `docker-compose.yml` (dev, base file) publishes
  `127.0.0.1:5432`/`127.0.0.1:9200` deliberately - they were
  internet-exposed at one point. `docker-compose.prod.yml` overrides both
  services' `ports:` to `[]` (Compose replaces, not merges, list fields) -
  a fresh `docker compose -f docker-compose.prod.yml up` publishes neither
  port to the host at all, only `expose:` for container-to-container
  access. The containers actually running on this box (as of 2026-07-18)
  still answer on `127.0.0.1:5432`/`127.0.0.1:9200` regardless - they
  predate the `ports: []` override and haven't been recreated since
  (Docker doesn't retroactively apply a compose-file port change to an
  already-running container). Don't rely on this from a fresh script: if
  postgres/elasticsearch are ever recreated (version bump,
  `--force-recreate`, etc.) under the current prod compose file, host-port
  access silently disappears.
- **After `docker compose up -d django worker` (or any command that
  recreates the `django` container), also restart `nginx`** — see
  [[troubleshooting.md]] ("nginx 502s everything after a django container
  restart") for the mechanism and exact fix.

### Boot-time recovery

Every service in `docker-compose.prod.yml` has `restart: unless-stopped`
(`8b1ec5e5`). Additionally, a systemd unit —
**`/etc/systemd/system/mpcautofill-docker-compose.service`** (OS-level,
**not** git-tracked — this note is its only record), `WantedBy=multi-user.target`, enabled — runs `docker compose -f docker/docker-compose.prod.yml up -d` on boot, covering recovery paths
`restart: unless-stopped` alone doesn't (e.g. a fully-removed container).
Verified with a real `sudo reboot`: all 5 containers came back up
unattended, both `api.proxyprints.ca` and `proxyprints.ca` returned HTTP
200 shortly after (`ac6bb7e3`). If this box is ever rebuilt, recreate this
unit manually — it has no git-tracked source to restore from.

## Secrets and credentials

Never commit: `docker/.env` (holds `DJANGO_SECRET_KEY`, referenced as
`${DJANGO_SECRET_KEY}` in compose), `docker/nginx/certs/`,
`docker/django/env.txt`, `MPCAutofill/drives.csv`. GitHub Actions repo
secrets (not local files) additionally include `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID`, three `IMAGE_CDN_GOOGLE_*` secrets, and
`NEXT_PUBLIC_GOOGLE_DRIVE_CLIENT_ID`/`APP_ID` — see
[[features/google-drive-connect.md]] and [[features/image-cdn.md]].

Git credentials are per-repo isolated: this repo's push/fetch uses a
fine-grained PAT in `~/.git-credentials-proxyprints`, wired via this repo's
local `credential.helper` git config, scoped to
`ProxyPrints/ProxyPrints.github.io` only (cannot manage PRs against
upstream even with the right permissions granted — fine-grained PATs are
scoped per-repository). A second, unrelated project on this machine
(`~/PringlePrints.github.io`) has its own PAT in
`~/.git-credentials-pringleprints`, wired the same way, so the two can't
collide. Other machine-global auth — `wrangler`, `CLOUDFLARE_API_TOKEN`,
the `gh` keyring — is visible from every directory on this box regardless
of which repo you're in; Cloudflare deploys happen via GitHub Actions repo
secrets, not local `wrangler`, so keep any local Cloudflare token in a
gitignored `.env` loaded on demand, never in shell profiles.

`gh` needs the PAT passed as `GH_TOKEN` (read via
`grep -oP 'https://[^:]*:\K[^@]*|https://\K[^@]*' ~/.git-credentials-proxyprints`). It needs "Pull requests: Read and write"
for `gh pr create`/`merge`, and "Actions: Read and write" for `gh workflow run`. `gh secret list` 403s — the PAT has no `secrets: read` permission, so
whether a given repo secret is actually set can only be inferred
circumstantially (e.g. a gated UI section not rendering), not confirmed
directly.

## Telemetry: fully removed, don't add back

- **Sentry** — fully removed, frontend and backend, as a privacy decision.
  Backend removal: the `sentry-sdk` import/init in `settings.py`, the active
  `capture_message` call in `integrations/game/base.py` (replaced with
  `logging.getLogger`, not bare deletion — error visibility preserved), the
  dead commented-out `capture_exception` in `views.py` (converted to
  `logger.exception`), and the `requirements.txt`/pre-commit mypy
  `additional_dependencies` entries.
- **Google Analytics** — fully removed from the frontend: the
  `nextjs-google-analytics` dependency and its usage in `Layout.tsx`, the
  cookie-consent toast and its machinery (`Toasts.tsx`, `common/cookies.ts`,
  `GoogleAnalyticsConsentKey`), the Playwright tests for it, the "Google
  Analytics" section of the About page's privacy policy, and the dead
  `NEXT_PUBLIC_GA_MEASUREMENT_ID` CI plumbing (that env var was already
  dead code before this — `Layout.tsx` used a hardcoded GA4 ID literal
  instead of reading it). Added an `id="privacy-policy"` anchor on the
  About page and a footer "Privacy Policy" link to replace the removed
  toast's link as the way to reach that section.
- **`cloudflareinsights.com`/`beacon.min.js`** (flagged by ad blockers) has
  zero footprint anywhere in this repo (frontend code, `next.config.js`,
  `_document.tsx`, `image-cdn/`, nginx, every workflow — all checked). It
  was Cloudflare's zone-level "Web Analytics"/RUM auto-injection setting
  for the `proxyprints.ca` zone itself (dashboard: Analytics & Logs → Web
  Analytics — disable "Automatic Setup" / delete the Web Analytics site
  entry), not something a commit can fix. Confirmed gone from the live site
  after disabling it in the dashboard.
- As of this removal, the frontend ships with zero first-party telemetry of
  any kind.

## CI/CD state

- `deploy-frontend.yml` is the real, working GitHub Pages deployer
  (confirmed green repeatedly). `web-ci.yml`'s own `publish-*` jobs were
  removed since they targeted upstream's external repo/secrets this fork
  doesn't have.
- `.github/actions/publish-frontend-to-github/` and
  `.../publish-frontend-to-cloudflare/` are byte-identical to upstream but
  no longer invoked by any workflow (superseded by `deploy-frontend.yml`) —
  left in place in case upstream's approach needs re-adopting later, not
  dead code to clean up casually.
- `web-ci.yml`: `build-frontend`'s `needs:` deliberately drops
  `test-backend` — 4 backend tests fail in CI for missing fork secrets (2
  Moxfield, 2 Google Drive creds) — environmental, not code bugs.
- `web-ci` has `on: push` path filters — pure `.md`/workflow-only commits
  don't trigger it. Manual trigger: Actions → Web CI → Run workflow.
- `cloudflare-workers-ci.yml` deploys `image-cdn/` and
  `github-release-reverse-proxy/` on push to master touching those paths,
  or manually. Its `publish-github-release-reverse-proxy` job will
  **always** fail here — it deploys a Worker routed to
  `download.mpcautofill.com`, a domain this Cloudflare account doesn't own.
  Expected noise, not a regression.
- This repo is a fork; GitHub's compare/PR UI (and `gh pr create` without
  `-R`) defaults the base repo to the **upstream parent**, not this fork —
  always pass `-R ProxyPrints/ProxyPrints.github.io` to `gh pr create`, or
  check the base-repo dropdown, when the PR is meant to land on this repo.

## Push policy

**Standing convention: commit and push straight to `master` for solo work
on this repo — no PR needed.** PRs (with the user's explicit approval
before merge) are reserved for the upstreaming workflow below. `gh pr merge` is blocked by an auto-mode permission classifier unless there's an
unambiguous human review/approval, or the user explicitly acknowledges
bypassing review in chat — don't retry or work around it; offer the choice
and let the user merge themselves if they don't want to confirm a bypass.

**Never `git push --force`** (or `--force-with-lease`) as a routine/default
action — get fresh, specific confirmation for that exact operation even if
force-push was approved before. See "History rewrite" below for why.

**When more than one session is active** (WORKERS.md has other live rows),
work happens in per-session branches/worktrees, never directly on
`master`, and the user sequences merges one at a time. Solo sessions doing
small, well-understood changes may still push `master` directly.

**When a PR is actually opened** (multi-worker branch, or upstreaming),
use `.github/pull_request_template.md`'s exact structure — `# Description`
then `# Checklist` — rather than a free-form summary. The checklist items
(pre-commit hooks installed, tests updated, manual testing steps, docs
updated) should be filled in with real specifics, not left as placeholder
checkboxes. `gh pr create --body` and `gh pr edit --body` both accept this
directly; if `gh pr edit` fails with a GraphQL "Projects (classic)"
deprecation error (a known `gh` CLI bug unrelated to the edit itself), fall
back to `gh api repos/<owner>/<repo>/pulls/<n> -X PATCH -f body="..."`,
which hits the REST API directly and isn't affected.

## Deploy-freeze protocol (long-running batch runs)

A stated gate for a while with no written protocol behind it (public
issue #156) — this section is that protocol. It governs the
deploy/CI/push surface this file already covers; it does not restate
the run-lifecycle mechanics (run states, resume semantics) that live in
[[features/catalog-completion-plan.md]] — it points at them.

**Trigger — what counts as a long-running batch run.** Any invocation
that (a) creates a `PilotRunLedger` row (the run-cohort mechanism from
that doc's Part 1) and (b) is started as an unattended, multi-hour
`screen`/`tmux` session per that doc's own "documented manual step, not
an unattended trigger" convention (Part 2's backfill, Part 4's LANDS
write run, and the harvest-calculate pipeline's Stage E run — including
its soak test and any eventual full-catalog fire — are all instances of
this same shape). A short, attended command (a dry-run sample, a probe
like `probe_harvest_pipeline`/`probe_resolution_tiers`) is not a
trigger, regardless of whether it happens to also create a ledger row.

**What's frozen.** Everything below is frozen for the run's `run_id` for
the duration of the freeze window (defined next):

- **Deploys that recreate the persistent `django`/`worker` containers**
  (`docker compose -f docker-compose.prod.yml up -d --build`,
  `--force-recreate`, or any nginx restart that follows one — see
  "After `docker compose up -d django worker`..." above). The run's own
  job executes in a _separate_, one-off `docker compose run --rm worker ...` container per that same convention, so a persistent-
  container recreate doesn't kill the job directly, but it competes for
  the same host CPU/RAM ceiling documented above and risks a DB
  connection blip the run has no retry logic for.
- **Migrations of any kind** — not only the persistent-container-
  recreating path, but also the normally-safe one-off `docker compose run --rm django python manage.py migrate` pattern that Part 3's
  migration-deploy-sequencing note treats as safe "regardless of when
  it lands." That note's safety argument is about _other_ running
  containers surviving the migration; it says nothing about a schema
  change landing mid-batch under the very process that's writing to
  the affected tables. Land any migration a run depends on _before_ the
  freeze starts, never during it — this is a stricter rule than that
  existing note, deliberately, for this one case.
- **Any Cloudflare Worker redeploy touching `image-cdn/`** — the run's
  entire fetch path (`GOOGLE_IMAGE` in `harvest_fetch_limiter.py`)
  routes through this Worker's "full" tier; a redeploy mid-run can
  change or reset its own rate-limiter/backoff behavior underneath a
  run that has already established a `last_confirmed_safe_rate`.
- **ES reindexes** — the directive names this category explicitly;
  reasoning is that ES sits on shared DB-adjacent infra the run also
  depends on (Postgres/ES both live in the same `docker-compose.prod.yml`
  stack), not a specific measured interaction the way the two items
  above are.
- **Config changes to the run's own settings** (e.g.
  `harvest_fetch_limiter.py`'s `GOOGLE_IMAGE.rate_per_sec`/
  `max_concurrency`, currently the settled `8.0`/`6` values from the
  concurrency-raise probe) fall under "deploys that recreate the
  containers" above, not a separate item — a code/config change only
  takes effect through the same container recreate.

**Not frozen, explicitly**: docs-only PRs (`web-ci`'s own path filters
already skip these), read-only `git`/`gh` operations, and anything on a
branch/worktree that never touches `docker/`, `image-cdn/`, or a
migration file. Whether **frontend Pages deploys**
(`deploy-frontend.yml`) are in scope is an open question, deliberately
not decided here and flagged for the owner rather than assumed; the
default posture until the owner says otherwise is "not frozen" (a
separate static-export pipeline, no shared resource with the backend
run).

**When the freeze starts and lifts.** Starts the moment the run's
`PilotRunLedger` row is created with `status=RUNNING` — i.e. the same
moment the operator launches the `screen`/`tmux` session, so starting
the run and raising the freeze marker (below) is one operator action,
not two. Lifts when that run's ledger status reaches `COMPLETED`, or
reaches `FAILED` **and** the owner has confirmed no resume is intended
for that `run_id` (mirroring how Part 4's owner-stopped run was closed
`FAILED` deliberately rather than resumed). A `kill -9` performed as
part of the Stage E resume contract's own soak-test acceptance test
(catalog-completion-plan.md, task #147/#156) does **not** lift the
freeze — kill-and-resume is an in-freeze operation by design; the
freeze only lifts on a genuine finish or an owner-confirmed abandonment
of that `run_id`.

**Who can override.** The owner, always — this project escalates every
gate exception to the owner; no session grants itself an exception to a
live freeze. This is distinct from the soak test's own `kill -9`
above: that action is pre-authorized by the resume contract's own spec
(it's the acceptance test the gate itself requires), not a fresh
override to seek approval for each time — "override" here means
bypassing the freeze for something the frozen-actions list above
actually forbids (a deploy, a migration, a Worker redeploy, an ES
reindex) while a run is active, which always needs the owner's
explicit sign-off.

**How a freeze is signaled.** One canonical, repo-visible marker: a
GitHub label — `deploy-freeze-active` — applied to the tracking issue
for the run in progress (issue #156 during its own soak test; whichever
issue tracks a later full-catalog fire) by whoever starts the run, and
removed by whoever confirms the freeze lifts. Checked with:

```bash
gh issue list -R ProxyPrints/ProxyPrints.github.io --label deploy-freeze-active --state all
```

before any of the frozen actions above — a non-empty result means stop
and escalate to the owner rather than proceed. This is a manual check
(no hook/CI enforces it yet — see OPEN ITEMS below); it works
identically for a same-machine session and a cloud/worktree session,
unlike a gitignored file such as `WORKERS.md` would. A same-machine
session may additionally note the freeze in its own `WORKERS.md` row as
a courtesy, but the label is the check every session — including one
with no local filesystem access to this machine — can and must run.

**Not built here (documentation only)**: a `PreToolUse`-style hook or
docs-lint job that checks the label automatically before a session runs
a frozen command, and a `deploy-freeze-active` label pre-created on the
repo (`gh label create`) so the first real use isn't blocked on that
one-time setup step. Both are proposed follow-ups for a dedicated
issue, not built in this change.

## Branch protection (GitHub-side backstop)

No branch protection exists on `master` today (confirmed via
`gh api repos/ProxyPrints/ProxyPrints.github.io/branches/master/protection`
→ 404, 2026-07-19). The `.claude/hooks/guard_master.py` PreToolUse hook
(see "Push policy" above) blocks a worker session from pushing straight
to master or merging on its own, but it's a **local, in-process**
check — every session on this repo currently authenticates with the
same git/`gh` credential (`~/.git-credentials-proxyprints`), so
GitHub itself can't yet tell "the owner, interactively" from "a worker
session" apart by identity. Branch protection is the backstop for
"the hook has a bug or gets bypassed," not a redundant copy of it —
but only if configured with that gap in mind:

- **"Require a pull request before merging," admins NOT exempt**
  (i.e. leave "Do not allow bypassing the above settings" **checked**)
  is the only setting that's a _real_ backstop under the current
  single-credential setup: it rejects `git push origin master` outright
  for every credential, including the owner's own, so a hook bug can't
  silently land an unreviewed push. The cost: the owner's own solo
  workflow changes from `git push origin master` to
  `git push -u origin <branch> && gh pr create && gh pr merge --squash`
  — an explicit merge step every time, which is also exactly the
  owner-triggers-every-merge property the automation work above wants.
- **Leave "Require approvals" at 0** rather than 1 — this is a
  solo-maintained repo; there is no second human to satisfy a
  required-review count, and setting it to 1 with admins exempt from
  bypass would lock the owner out of merging their own repo entirely.
  Requiring a PR to exist (and CI to pass on it) is the real gate here,
  not a second reviewer.
- Also enable: **require status checks to pass** (pick the CI jobs that
  matter — e.g. `Formatting and static type checking`, `Backend tests`
  if the repo wants that enforced), and leave **"Allow force pushes"**
  and **"Allow deletions"** unchecked.
- If a future setup gives workers their own restricted, non-admin
  credential (rather than sharing the owner's), branch protection
  becomes meaningfully layered — until then, "admins exempt" versions
  of these settings provide no real protection against a worker using
  the same credential, only against accidental non-owner contributors.

This is a real workflow change (push-straight-to-master goes away for
everyone, owner included) traded for a protection that actually holds
under a hook bug — not a default to flip without a deliberate decision
on that trade-off.

## Upstreaming to chilli-axe/mpc-autofill

`upstream` remote = `https://github.com/chilli-axe/mpc-autofill.git`. Cut
upstream-bound branches from `upstream/master` in a separate `git worktree`
(`git worktree add <path> upstream/master -b <branch>`), not a plain
checkout in the main tree, to keep upstream-PR work isolated. Cherry-pick
(not rebase/merge) specific fix commits — master has diverged with 40+
fork-specific commits (branding, feature work, telemetry removal, this
fork's own CI) that must never leak into an upstream PR. Diff the resulting
branch against `upstream/master` before pushing to confirm scope.

Five PRs were opened this way (#463–467), all reviewed same-day by the
upstream maintainer (ndepaola): #463 (lazy-load PDFGenerator) and #465
(image-CDN CORS fix) are open (live-checked 2026-07-18, unchanged since);
#464 (pdf.js canvas preview) and #466 (bucket/worker thumbnail routing)
were closed after the maintainer explained the existing behavior was
deliberate design, not a bug; #467 (frontend toSearchable "the"-stripping
fix, completing backend PR #460) was opened 2026-07-13 and **merged
2026-07-18**. All reviews so far have asked for hand-written PR
descriptions going forward, not AI-generated ones — none of #463/#465/#467's
PR bodies contain an AI-disclosure paragraph; the actual AI-assistance
signal in this workflow is the Co-Authored-By trailer on the commit
itself, not PR body text.

#467 is also a variant on the cherry-pick convention above: our own fork
had already fixed the identical bug in its own processing.ts (commit
206a0266, merged as PR #20 / `121b5c06`, mirroring backend PR #460), but
that fork commit was not cherry-picked upstream — its message/context was
fork-specific (references "our fork", "our master"). Instead the same
two-line logical fix was hand-reapplied directly against upstream/master's
own current tree. Cherry-pick remains the right default when a fix
commit's content and narrative both port cleanly; hand-reapply when the
original commit's framing doesn't.

**Absorption check, done at #467's merge (2026-07-18)**: does merging
#467 upstream require anything on our side? No — verified, not assumed.
Our `master` already carries the identical frontend fix (`121b5c06`,
above), and cross-layer: the backend's `to_searchable()`
(`cardpicker/search/sanitisation.py`) stopped stripping "the" via the
literal shared upstream commit `4e960183` ("do not sanitise 'the' in card
names", PR #460), merged into our `master` around 2026-07-04 — _before_
our own frontend fix, which was written specifically to restore parity
with it. Confirmed today both layers still agree by running the actual
current `toSearchable`/`to_searchable` functions (Node + Python, not a
re-read of the source) against 8 names including substring-only "the"
cases ("Theros", "Bother") that a careless word-boundary bug could
mishandle differently per-layer — byte-identical output on every case.
Net: #467 merging upstream is upstream catching up to parity we already
had via a different path (an earlier backend sync + our own independent
frontend mirror); zero action required here. Recorded so this doesn't
need re-deriving from git archaeology next time — see
`docs/upstreaming/conventions.md`'s "back-absorption is a tracked task"
note for the general habit this is an instance of.

Notes if #463/#465 are revisited: #463's description incorrectly claimed a
`{show && <PDFGenerator/>}` gate in `PDFGeneratorModal.tsx` was pre-existing
— it was actually added by that PR (confirmed via diff against
`upstream/master`); don't repeat that claim if the description gets
rewritten. #465's reviewer is doing a heavier image-CDN refactor that will
likely also fix the same CORS bug and may close #465 to avoid conflicts; he
hasn't as of this writing, and hasn't replied on whether any of that
refactor will be cached locally vs. relying on Cloudflare.

**Upstreaming itself is currently deprioritized** —
chilli-axe has signaled plans to drop the Node.js frontend, which could
waste any further upstreaming effort; don't proactively pitch new upstream
PRs without checking in first.

An extraction manifest for one specific feature (the printing/artist/tag
weighted-vote system) lives at `docs/upstreaming/vote-system.md` — a
commit-by-commit cherry-pick classification for whoever eventually cuts
that upstream branch. See [[features/printing-tags.md]].

## History rewrite: drives.csv scrubbed from git

`MPCAutofill/drives.csv` was force-committed with real production data (54
sources, including other people's names and personal Google Drive IDs) in 3
commits despite being gitignored. This was later scrubbed from history via
`git filter-repo --path MPCAutofill/drives.csv --invert-paths`, scoped via
`--refs` to just the range after `merge-base(master, upstream/master)` on
the affected branches, done in an isolated mirror clone and verified
(ref-diffed against a pre-filter snapshot, grepped for the leaked strings)
before force-pushing. Commits at or before the merge-base kept their
original SHA (so cherry-picking against upstream still works); the
`upstream-fix-*` branches (cut directly from `upstream/master`) never
contained the sensitive commits and were untouched.

**This did not fully succeed at erasure, and can't via git alone**: two
merged, closed PRs on this repo have GitHub-side `refs/pull/N/head` refs
that freeze the pre-rewrite commits permanently, independent of anything
done to the branches themselves — GitHub creates these server-side and
they can't be force-pushed over. A GitHub Support request to purge those
refs was drafted for manual filing (requires being logged into the
account). Status not independently verifiable from a cloud/API session
(support-ticket state isn't exposed via `gh`/the GitHub API, and checking
whether the refs themselves were actually purged would require someone
logged into the account to attempt fetching them) — last confirmed status
is whatever the owner reports directly, not re-verified here as of
2026-07-18.

**If this ever needs to be done again for a different file**: never run
`git filter-repo` (or filter-branch/BFG) with no `--refs` scoping on a fork
of a large upstream project — it rewrites every commit's SHA back to the
project root, including everything shared with upstream, breaking the
cherry-pick-based upstreaming workflow entirely. Always scope to
`<merge-base-with-upstream>..<branch>` per affected branch. This incident
is also why force-push is banned as a routine action (see Push policy
above).

## Database footprint (baseline snapshot)

One-query snapshot, 2026-07-19, before `ImageEvidence` (Stage C of the
harvest-calculate pipeline, `docs/features/catalog-completion-plan.md`)
adds any rows — a known starting point so that table's future growth is
measured against something, not guessed:

```sql
SELECT pg_size_pretty(pg_database_size('mpcautofill'));
-- total_db_size: 427 MB

SELECT relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = 'public'
ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10;
```

| relation                               | total  | table  | index  |
| -------------------------------------- | ------ | ------ | ------ |
| `cardpicker_card`                      | 211 MB | 112 MB | 99 MB  |
| `cardpicker_cardscanlog`               | 85 MB  | 42 MB  | 43 MB  |
| `cardpicker_canonicalcard`             | 62 MB  | 36 MB  | 26 MB  |
| `cardpicker_cardprintingtag`           | 25 MB  | 10 MB  | 15 MB  |
| `cardpicker_cardtagvote`               | 17 MB  | 7.9 MB | 9.2 MB |
| `cardpicker_canonicalprintingmetadata` | 12 MB  | 9.8 MB | 2.5 MB |
| `cardpicker_cardartistvote`            | 2.5 MB | 1.0 MB | 1.4 MB |
| `cardpicker_canonicalartist`           | 784 kB | 272 kB | 512 kB |
| `cardpicker_canonicalexpansion`        | 752 kB | 184 kB | 568 kB |
| `cardpicker_tagaliassuggestion`        | 688 kB | 288 kB | 400 kB |

`cardpicker_card` (the fetch-target table, 218k rows) and
`cardpicker_cardscanlog` (abstention evidence, growing with every pilot
run) already dominate — a useful sanity check for `ImageEvidence`'s own
eventual size, since it will carry meaningfully more per-row data (OCR
TSV, multiple hashes, geometry) than either.

### Stage C migration state (updated 2026-07-20)

Migrations `0068`–`0072` are now applied to the **live production
Postgres**, taking it from `0067` (the baseline above) to `0072`:
`0068` creates the `ImageEvidence` table itself (Stage C's substrate,
`content_hash`/`extractor_versions`/`run_id`/fetch-health columns);
`0069`–`0071` add that table's geometry/bleed (issue #147),
geometry-group layout/crop (issue #148), and OCR-group (issue #149)
extractor fields respectively; `0072` adds `CardScanLog`'s
`evidence_types_used`/`survivor_pks` instrumentation fields from issue
#209's negative-vote work. All five are additive-only (`CreateModel`/
`AddField`, no column drops or type changes), matching every other
migration in this range's own stated additive-only property.

Applied ad hoc, 2026-07-20, during the first `ImageEvidence`
dataset-population run — a schema deploy step taken outside the
documented `docker compose run --rm django python manage.py migrate`
sequencing above, stated here as a factual departure, not silently
folded into the normal deploy narrative. The `ImageEvidence` table
itself, empty (0 rows) since the baseline snapshot above, now holds its
first real cohort from that same run: `run_id=stagec-cohort-20260720-full`,
~3,000+ rows and growing toward a 15,000-card target.

**Not covered by this note**: migration `0073`
(`imageevidence_symbol_crop_px_and_more`, the symbol-region extractor
from issue #160) also exists in the repo as of this writing — its own
production-deploy status is a separate, unconfirmed question, flagged
as an open item rather than assumed either way.

## Testing infrastructure fixes

- `tests/global-setup.ts` used to click a cookie-consent toast's "Opt out"
  button to seed a reusable storage state — broke every Playwright test
  with a 30s timeout once that toast was removed (see Telemetry above).
  Simplified to just produce an empty storage state.
- `tests/visual/SearchSettings.visual.spec.ts`'s aria snapshot expected
  stale DPI-filter copy that had been reworded in `FilterSettings.tsx`
  without updating the test. Re-baselined via `--update-snapshots`.
- A flaky `CardSlot.spec.ts` test (`route.continue: Route is already handled!`) is a known upstream bug in `@msw/playwright` 0.4.5
  (mswjs/playwright#35 — Playwright can terminate an in-flight route
  handler on navigation, and 0.4.5's route methods throw when that
  happens). Fixed upstream only via a breaking 0.6.0 rewrite, too large a
  migration for this fix alone — vendored the same guard onto the
  installed 0.4.5 via `patch-package`
  (`frontend/patches/@msw+playwright+0.4.5.patch`, wired into
  `postinstall`).
