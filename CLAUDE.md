# ProxyPrints — context for Claude Code

## What this is

Fork of chilli-axe/mpc-autofill. MTG proxy card catalog. Frontend =
Next.js static export deployed via GitHub Pages. Backend = a separate
Django/Elasticsearch/Postgres API. See `CLAUDE.local.md` (local sessions
only) for deployment, hosting, and domain specifics.

## Never commit

- `docker/.env`, `docker/nginx/certs/`, `docker/django/env.txt`
- `MPCAutofill/drives.csv` (gitignored/untracked; real content only ever
  lives on-disk — see [[docs/infrastructure.md]] if this machine is rebuilt)
- Any literal secret VALUE (tokens, keys, passwords) in docs/ or CLAUDE.md —
  naming a secret's _location_ is fine, quoting its _contents_ is not
- `WORKERS.md`, `journal/`, `CLAUDE.local.md` (all gitignored, machine-local,
  never committed)

## Tooling rules

- **Docs convention**: task-end doc updates EDIT the relevant reference
  file in place — never append a dated section. If a blocker costs more
  than 15 minutes to resolve, add a symptom-first entry to
  `docs/troubleshooting.md` before the task closes (grep it first before
  re-deriving a fix — recurring blockers live there, not buried in a
  changelog).
- **Policy text dates**: any change to on-site policy text (Privacy
  Policy, Terms, etc. in `frontend/src/pages/about.tsx` and similar) must
  update that page's own "Last updated" date in the same change — it's
  hardcoded, not derived, so it goes stale silently otherwise.
- **Wiki maintenance**: task-end check — did this change what a USER sees
  or what an ADMIN does? If yes: server sessions update the wiki page in
  the same task; cloud sessions add "wiki: `<page>` needs `<change>`" to
  their PR's merge-time checklist. Wiki pages link to `docs/` for
  operational detail — never duplicate a fact that changes.
- **Push policy**: commit and push straight to `master` for solo work on
  this repo, no PR needed. PRs (+ user approval before merge) are reserved
  for upstreaming to `chilli-axe/mpc-autofill`. Never `git push --force` as
  a routine action — always get fresh, specific confirmation first (see
  [[docs/infrastructure.md]] for why). When more than one Claude Code
  session is active for this repo, work in per-session branches/worktrees
  instead of pushing `master` directly, and let the user sequence merges.
  **Interactive vs. background sessions**: if you're conversing with the
  user in real time (they're reviewing diffs, requesting the push in chat),
  you're interactive — `git push origin master` on request is normal,
  expected, and needs no caveats. A genuine background/bg-job session where
  a harness-level constraint blocks pushing to `master` directly should
  still push its branch and ask the user to land it — never claim inability
  to help further just because of that constraint.
- **Journal/docs convention**: log session play-by-play to
  `journal/<date>-<topic>.md` (gitignored, local, never committed). At task
  end, distill any durable, reusable fact into the relevant `docs/` file
  below. Never append journal entries or historical narrative to this file
  — CLAUDE.md is orientation only.
- `gh pr create`/`gh pr merge` against this repo: pass
  `-R ProxyPrints/ProxyPrints.github.io` (GitHub's UI/CLI default the base
  repo to the upstream parent for a fork). `gh pr merge` is blocked by an
  auto-mode classifier absent unambiguous human review — don't work around
  it, offer the user the choice instead.
- **Merge-duty branch deletion**: never delete a branch in the same action
  as merging its PR. Precondition before deleting any branch:
  `gh pr list --base <branch>` must return empty (a stacked child PR
  targeting it would otherwise auto-close the moment the base disappears —
  this is exactly how PR #88 was lost). When in doubt, don't delete; leave
  the stale branch for a later, separate cleanup pass.
- **Before rebuilding a lost/auto-closed PR**: search for an existing
  recovery first (`search_issues`/`search_pull_requests` for the same
  topic, check open PRs and recent branches) rather than assuming none
  exists. Two independent sessions rebuilt #88 in parallel on the same day
  or the second, #95, rebuilt what #94 had already re-shipped and closed
  the duplicate.
- **Cloud/web sessions**: `WORKERS.md` and `CLAUDE.local.md` are
  server-local and won't exist in your clone — skip them. You're isolated:
  work on your named branch, push to origin, never to `master`; the owner
  sequences merges. No Docker, live DB/ES, or secrets are available — use
  mocks (MSW) for tests.

## Reporting convention (all sessions)

Every response that reports work (hold points, completions, status
updates, blocker reports) is ONE fenced plain-text code block, fully
self-contained — written for a reader who has NOT seen the session and
receives the block verbatim with zero surrounding context.

The block contains, in order:

1. TASK: name + branch(es) + PR/commit refs
2. WHAT SHIPPED: per numbered item of the instruction executed
3. DEVIATIONS from spec, each with reasoning (or "none")
4. VERIFICATION: what ran with results, what was deferred and why
5. OPEN ITEMS / DECISIONS NEEDED: numbered, answerable
6. LIVE STATE: anything running, deployed, pushed, or left behind

Rules: NO prose outside the block — no preamble, no postscript; the
block is the entire deliverable. Never reference session context ("as
discussed above") without restating the fact inside the block. Blocked/
partial work reports in the same structure ("WHAT SHIPPED: nothing —
blocked at step N because X"). Applies to every hold point, completion,
status update, and blocker report.

For any report longer than ~10 lines, or whenever normal message
delivery has been unreliable: commit the fenced block to a
`docs/reports/<date>-<topic>.md` file on a short-lived, **per-session
uniquely-suffixed** branch (never the bare `report-relay` — it's
retired; two independent sessions collided on it with no push
conflict to warn either one), push, and reply with only the branch
name, file path, **and the full GitHub blob URL to the pushed file**
(`https://github.com/ProxyPrints/ProxyPrints.github.io/blob/<branch>/<path>`)
plus one header line — a bare branch/path pair makes the reader
reconstruct the URL by hand; give them the working link. See
[[docs/lessons.md]] for the collision this prevents.

## docs/ index

This is a flat working index for Claude Code sessions. For an
audience-grouped map (including `docs/proposals/`, `docs/audits/`,
`docs/reports/`) see [`docs/README.md`](docs/README.md); for a cold
external reader's orientation to the whole fork, see
[`docs/overview.md`](docs/overview.md).

- [`docs/troubleshooting.md`](docs/troubleshooting.md) — symptom-first
  index of recurring blockers (grep your error text here first, before
  re-deriving a fix or reading anything else below).
- [`docs/infrastructure.md`](docs/infrastructure.md) — Docker build/deploy,
  secrets & credentials detail, telemetry removal, CI/CD state, push
  policy detail, upstreaming workflow, the drives.csv history-rewrite
  incident, testing-infra fixes.
- [`docs/lessons.md`](docs/lessons.md) — terse, reusable cross-session
  lessons (CI vs. local venv trust, worktree port collisions, debug-color
  verification, cyclic-animation sampling, verifying cross-session claims,
  ES mapping drift, test-factory isolation, sticky/overflow CSS gotchas,
  migration-vs-command tag seeding).
- [`docs/features/image-cdn.md`](docs/features/image-cdn.md) — the Worker +
  R2 bucket image CDN.
- [`docs/features/pdf-generator.md`](docs/features/pdf-generator.md) — PDF
  export tab: eager-WASM/preview/image-rendering bug fixes.
- [`docs/features/print-export-page.md`](docs/features/print-export-page.md)
  — the "Print!" export page's ordering tabs and flag icons.
- [`docs/features/printing-tags.md`](docs/features/printing-tags.md) — the
  "What's That Card?" printing-consensus tagging system, backend + frontend.
- [`docs/features/moderation.md`](docs/features/moderation.md) — Discord
  OAuth login, the `Moderators` group gate, sensitive-tag approval queue,
  card reports.
- [`docs/features/local-file-source.md`](docs/features/local-file-source.md)
  — backend `LOCAL_FILE` catalog source type.
- [`docs/features/card-dom-api.md`](docs/features/card-dom-api.md) —
  generic `data-card-*` attributes + `mpc:card-selected` event.
- [`docs/features/google-drive-connect.md`](docs/features/google-drive-connect.md)
  — Google Drive picker, Local Folder, and Save-PDF-to-Drive.
- [`docs/features/grid-selector.md`](docs/features/grid-selector.md) —
  the card-version-picker modal + `Card.tsx`'s image loading/error states.
- [`docs/features/artist-support-links.md`](docs/features/artist-support-links.md)
  — zero-crawl, deterministic link-out to MTG Artist Connection
  (`ArtistSupportLink.tsx` + its two surfaces).
- [`docs/features/homepage-panel.md`](docs/features/homepage-panel.md) —
  the "what is this, really?" landing panel (`HomepagePanel.tsx`), its
  gating, and the reserved-not-built catalog-stats chart slot.
- [`docs/upstreaming/vote-system.md`](docs/upstreaming/vote-system.md) —
  cherry-pick extraction manifest for the vote system (companion to the
  Upstreaming workflow in `docs/infrastructure.md`).
- [`docs/upstreaming/upstream-wiki-drift.md`](docs/upstreaming/upstream-wiki-drift.md)
  — weekly automated tracking of changes to chilli-axe/mpc-autofill's own
  wiki (detection only, never copied in).
- [`docs/federation-v1.md`](docs/federation-v1.md) — federation verdict
  exchange format v1 (spec, implementation pending).
- [`docs/federation/public-export-v1.md`](docs/federation/public-export-v1.md)
  — HOLD spec: publish-first federation export (signed verdict JSONL, no
  peer required), consumable by mpc-autofill forks and MIT-lineage proxy
  tools. Owner review pending; see `docs/README.md`'s Plans & proposals.
- [`docs/theory.md`](docs/theory.md) — the printing-identification
  pipeline as candidate-constrained decoding: false-accept bound,
  prior-art comparison, soundness mechanisms, Sybil/Dawid-Skene
  addendum. Doubles as the federation pitch's technical annex.
- [`docs/documentation-process.md`](docs/documentation-process.md) — docs/
  as source of truth, the wiki as a generated view of it, mechanical lint
  vs. the quarterly judgment pass, upstream wiki tracking.
