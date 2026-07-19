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
