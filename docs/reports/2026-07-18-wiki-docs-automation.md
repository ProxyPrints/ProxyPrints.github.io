```
TASK: Wiki + docs automation (survey then build) — branch
claude/wiki-docs-automation, commit be914cd8, pushed to origin. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/70 (open, base
master). This branch is based on the already-merged-in-spirit tip of
claude/user-accounts-saved-decks-m8eyf5 (Proposal G + the earlier docs
coherence pass), cut fresh so this task's own PR stays scoped to its own
work.

ITEM 1 — SURVEY: existing wiki vs. docs/, migration list (reported before
building, per the standing rule; only the one item marked "done" below was
acted on without waiting — reasoning inline).

Cloned ProxyPrints.github.io.wiki.git read-only. 5 existing pages:

1. Home.md — friendly welcome copy (site link, "no account, no paywall",
   fork attribution) + a hand-written "Wiki contents" list pointing at the
   other 3 content pages. CONFLICT: item 2 explicitly requires Home to
   become generated from docs/README.md's audience groups, so this page
   WILL be overwritten by the new system regardless of the migration
   decision on the others. DONE (not held): migrated the distinctive
   framing paragraph verbatim into docs/wiki-home-intro.md, which the new
   generator uses as Home's preamble ahead of the generated link list.
   Nothing lost; flagged as the one migration this PR didn't wait on,
   because "leave Home unmanaged" wasn't an option consistent with item 2's
   own requirement.
2. User-Guide.md — end-user how-to (search, vote queue, PDF export, saving
   a project), explicitly "skeleton — not all written yet." NO docs/
   equivalent exists — docs/ is entirely developer/architecture-facing
   today; there's no "how do I use the site" bucket anywhere in it. NOT
   migrated, NOT deleted: listed in .github/wiki-publish-map.json's
   legacy_pages so it stays linked from the generated Home/Sidebar, and the
   publish workflow is built to never touch a page without its own
   generated-marker (verified in testing — see ITEM 2). RECOMMEND: migrate
   into docs/ (e.g. docs/user-guide.md, preserving the skeleton status —
   writing the actual guide content is out of scope for an automation
   task) so it becomes generatable, rather than staying permanently
   hand-maintained. Owner decision, not resolved here.
3. Instance-Admin-Guide.md — generic self-hosting guide for a third party
   running their OWN instance of this fork's code. Real overlap with
   docs/infrastructure.md, but a genuinely different audience (infra.md is
   this fork's own ops, not "how does a stranger stand this up"). NO
   docs/ equivalent. Same treatment as #2: listed in legacy_pages, not
   touched. RECOMMEND: migrate into docs/ (e.g. docs/self-hosting.md).
   Owner decision.
4. Research-and-Proofs.md — placeholder literally describing "the local
   (zero-API-cost) printing identification pipeline... still in active
   development... will be filled in once it reaches a stable, reportable
   result." That result already exists: docs/theory.md, reviewed and
   approved by the owner 2026-07-17. Same treatment: listed in
   legacy_pages, not touched, its note in the mapping states the overlap
   explicitly. RECOMMEND: replace this page's content with a pointer to
   the new generated Theory page (or fold it in outright), OR keep it as a
   distinct home for future non-theory.md research write-ups if more are
   planned. Owner decision.
5. _Sidebar.md — mirrors Home.md's link list; same treatment as Home
   (regenerated, since item 2 requires a generated sidebar too). No
   distinctive content of its own to migrate.

Net: 1 migration decision made (Home's framing text -> docs/wiki-home-intro.md,
forced by item 2's own requirement), 3 flagged for the owner (User-Guide,
Instance-Admin-Guide, Research-and-Proofs — real content, no docs/ source,
recommend migrate rather than delete, but not this PR's call), 0 deletions
proposed (nothing found that's actually obsolete/unwanted — Research-and-
Proofs is superseded-in-content but the owner may still want the page).

WHAT SHIPPED, items 2-5:

2. .github/workflows/docs-wiki-publish.yml + .github/scripts/publish_wiki.py
   + .github/wiki-publish-map.json (curated mapping, hand-maintained —
   does not parse docs/README.md's prose, per the task's own "curated
   mapping" wording). On push to master (paths: docs/**) + workflow_dispatch.
   Regenerates 17 pages (14 "Understanding the system" + 3 "Operating it",
   mirroring docs/README.md's own buckets) plus a generated Home + Sidebar.
   Every generated page carries a GENERATED PAGE marker; the script only
   ever deletes a page bearing that marker whose source left the mapping —
   verified this three ways against a real clone of the live wiki: (a)
   full regeneration produces the expected 17+2 files and leaves the 3
   legacy pages byte-for-byte untouched, (b) removing a page from a copy
   of the mapping correctly prunes only that generated page, (c) the 3
   legacy pages survive both runs. Requires a WIKI_PUSH_TOKEN secret
   (GITHUB_TOKEN cannot push to a repo's wiki — a platform limitation, not
   a missing permission); the workflow fails fast with a clear ::error::
   if it's unset rather than a confusing git-auth failure, and the
   workflow's own header spells out exact setup (classic PAT, public_repo
   scope, explicitly warns fine-grained PATs have no wiki support). Folded
   in a reminder about GOOGLE_DRIVE_API_KEY/MOXFIELD_SECRET, needed by the
   separately-unmerged upstream-ladder-ci workflows (found on
   claude/upstream-readiness-audit-cvq14g via report-relay), so the owner
   can do one settings visit instead of several.
3. .github/workflows/docs-lint.yml + .github/scripts/docs_lint.py. On PR
   (paths: docs/**) + weekly cron + workflow_dispatch. Checks internal
   link resolution ([[wiki-links]] and markdown links) and backtick-quoted
   repo-path existence. Gitignore-aware (skips paths like drives.csv,
   docker/django/env.txt, client_secrets.json that are correctly absent by
   design per CLAUDE.md's "Never commit" list) and allowlist-capable for
   genuine one-off exceptions (docs/audits/ui-content-audit.md, known
   pending on an unmerged branch). Annotates only, never auto-fixes.
   States its known limitation in its own docstring and in
   docs/documentation-process.md: it catches broken links/paths, never
   stale status claims — that's the quarterly pass's job, not a linter's.
4. .github/workflows/docs-upstream-wiki-drift.yml + .github/scripts/upstream_wiki_drift.py.
   Weekly. Clones chilli-axe/mpc-autofill.wiki.git read-only, diffs
   against the last-seen SHA stored as an HTML comment in
   docs/upstreaming/upstream-wiki-drift.md, updates that doc's table in
   place (per-page last-changed date + commit, not an appended narrative).
   DETECT ONLY — the workflow header and the doc itself both state plainly
   that upstream wiki text has no clear license, so nothing from it is
   ever copied; the only correct response to a drift row is a human
   reading the upstream page and, if it's worth reflecting here, writing
   original words with attribution. Seeded by hand with real data from an
   actual clone (10 real pages, real commit SHAs/dates, current HEAD
   43a8eedc) since the workflow can't run — and so can't self-seed —
   until it's on master. This pushes to OUR OWN repo (not a wiki), so
   plain GITHUB_TOKEN with contents:write suffices, no PAT needed here.
5. docs/documentation-process.md — the standing system in one page: docs/
   as source of truth, wiki as generated view (never hand-edit), what
   lint catches vs. what it can't, and an 8-item quarterly-pass checklist
   derived directly from this session's own earlier docs coherence pass
   (inventory -> cross-check against something real -> watch for
   duplicate headings/miscategorized content -> check both docs indexes
   for parity -> compile a migration/decision list before touching
   anything non-mechanical -> fix only what's mechanical).

DEVIATIONS, each with reasoning:
- Home's framing text migrated without waiting for the item-1 approval
  gate — explained above (item 2's own requirement leaves no "do nothing"
  option for Home specifically; the other 3 pages were held as designed).
- Added the 6 feature docs (grid-selector, image-cdn, local-file-source,
  pdf-generator, print-export-page, google-drive-connect) that were
  missing from docs/README.md's own audience buckets — found while
  building the mapping; needed fixing first so "everything the index
  lists" (the task's own phrasing for item 2) was actually everything,
  not everything-minus-six.
- Fixed 5 more stale-path bugs found by dogfooding docs-lint.py against
  the real docs/ tree before wiring it into a workflow: image-cdn.md's
  `frontend/src/components/Card.tsx` (moved to features/card/), three
  instances of `MPCAutofill/settings.py` missing its doubled directory
  (`MPCAutofill/MPCAutofill/settings.py` is the real path — a Django
  project-inside-repo-folder convention), and printing-tags.md's
  `frontend/src/common/anonymousId.ts` (no such file exists; the real
  anonymous-ID logic lives in `common/cookies.ts`). Small, squarely
  mechanical, same category of fix as the earlier docs coherence pass.
- Fixed two bugs in docs_lint.py itself before shipping it, both caught
  by running it against real docs/ content rather than trusting it after
  one clean pass: (a) inline single-backtick code spans containing
  illustrative link syntax (e.g. this doc's own explanation of what the
  checker does) were being parsed as real links — fixed by stripping
  inline code before the link-checking pass, keeping it intact for the
  path-existence pass which needs the backticks; (b) the fenced-code-
  block stripping step collapsed stripped content down to bare newlines,
  which shifts every later character offset and silently misreports line
  numbers on any finding after a code fence — fixed by preserving exact
  length/newline positions (space-padding instead of collapsing),
  verified with a targeted test (a finding after a fenced block now
  reports its true line number).
- Fixed two bugs in my own docs/documentation-process.md prose: a literal
  "+" at the start of a continuation line was parsed as a markdown list
  marker by prettier, splitting one bullet into a broken nested list, in
  two places. Reworded both to avoid a line-leading "+".

VERIFICATION: what ran with results —
- publish_wiki.py: full run against a real clone of the live wiki (17
  pages generated correctly, Home/Sidebar generated correctly, 3 legacy
  pages untouched); a second run with one mapping entry removed (correct
  single-page prune, legacy pages still untouched).
- upstream_wiki_drift.py: real clone of chilli-axe/mpc-autofill.wiki.git,
  no-drift run (idempotent — empty diff on repeat run) and a simulated
  4-page-drift run against a real older ancestor SHA (correct detection,
  correct table refresh, matches the hand-seeded baseline exactly).
- docs_lint.py: full run against the real docs/ tree — 14 initial
  findings, all triaged (5 real bugs fixed, 1 legitimate allowlist entry,
  8 gitignored-by-design false positives resolved by making the checker
  gitignore-aware rather than hardcoding each path); a negative test
  (3 deliberately-broken references) confirmed it still catches real
  breakage; a targeted fenced-code-block test confirmed the line-number
  fix.
- All 3 workflow YAML files parsed with `yaml.safe_load`; every `run:`
  block extracted and checked with `bash -n` (syntax-only): all clean.
  All 3 Python scripts passed `py_compile`. `.github/wiki-publish-map.json`
  is valid JSON. `npx prettier --check` clean across every touched file.
- Deferred: an actual live GitHub Actions run of any of the three
  workflows. Can't trigger one from this sandbox (workflow_dispatch isn't
  available until this branch merges to master, and schedule/push
  triggers only evaluate from the default branch) — everything above is
  real verification of the logic against real cloned data, not a
  substitute for watching an actual run succeed.

OPEN ITEMS / DECISIONS NEEDED:
1. Owner: create the WIKI_PUSH_TOKEN secret (classic PAT, public_repo
   scope) before docs-wiki-publish.yml can do anything beyond fail its
   own clear check. See that workflow's header for exact steps.
2. Owner: the 3 legacy-page migration recommendations above (User-Guide,
   Instance-Admin-Guide, Research-and-Proofs) — migrate into docs/, or
   decide to keep them permanently hand-maintained outside this system.
3. Owner: while in Settings -> Secrets for #1, also verify/add
   GOOGLE_DRIVE_API_KEY and MOXFIELD_SECRET if not already set — needed
   by the separately-unmerged upstream-ladder-ci workflows, per that
   branch's own report.
4. Once WIKI_PUSH_TOKEN exists and this PR merges, manually fire
   workflow_dispatch on docs-wiki-publish.yml once to get a first real
   signal before relying on the push trigger.
5. This PR's docs/reports/2026-07-18-wiki-docs-automation.md (this file)
   is the first real file to land in docs/reports/ — ahead of the
   report-relay/report-relay-2 branches it was originally expected to
   arrive with. Whichever merges second will see a trivial,
   already-anticipated directory-level overlap (per the merge-order note
   from the prior session).

LIVE STATE: branch claude/wiki-docs-automation pushed to origin at
be914cd8 (workflows/docs) + this report's own commit on top. PR #70 open
against master, not merged. Nothing pushes to the live wiki or to
chilli-axe/mpc-autofill anywhere in this change — both new wiki-facing
workflows are inert until WIKI_PUSH_TOKEN exists (publish) or the branch
merges to master (drift check, schedule-gated). Session holding here.
```
