```
TASK: CLOUD session (upstream-readiness) — PR-I-1 RESTRUCTURE:
single-transform architecture (owner call, supersedes the dual-
implementation approach). Branch:
docs-as-site-source-restructure-v2-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/112 (against
current master directly - see DEVIATIONS for why this isn't PR #108).

WHAT SHIPPED:

1. .github/scripts/publish_wiki.py: transform_links()/rewrite_link()
   extended with an optional repo_to_site parameter. None (default)
   preserves the original wiki-only 2-way resolution exactly
   (regression-checked byte-identical against the real
   wiki-publish-map.json). A real dict adds a 3rd resolution branch
   (a "site"-targeted link becomes that page's own route) and changes
   wiki-only-target resolution to an ABSOLUTE wiki URL (not a
   same-repo link) since the site doesn't host that page - one
   function, two output shapes, per the owner's explicit design.
2. .github/scripts/publish_site.py: new sibling script (not a CLI
   flag on publish_wiki.py, to keep each script's simple positional
   CLI simple), imports publish_wiki.py's functions with zero
   reimplementation, emits frontend/generated-docs/*.json
   (link-rewritten MARKDOWN, not HTML) + manifest.json. Verified
   idempotent: two consecutive runs, byte-identical output, diffed.
3. frontend/scripts/generate-docs-site.js and its Jest mirror:
   DELETED outright - no JS-side transform logic exists anywhere in
   this repo anymore, exactly per instruction item 3.
4. frontend/src/features/guide/docsSite.ts: new module for the
   fs-touching reads, kept OUT of the page file itself after hitting
   a real build failure first (Module not found: Can't resolve 'fs') -
   a page file's own exports get bundled for the Pages Router's
   client build; only code reachable exclusively from
   getStaticPaths/getStaticProps is safe to touch fs. This was a real
   build-breaking discovery mid-implementation, not anticipated from
   reading the spec alone - fixed by extracting the fs-touching
   functions into their own non-page module.
5. frontend/src/pages/guide/[[...slug]].tsx: slimmed to routing +
   marked.parse() rendering only. Graceful degradation (item 5's
   "skip-with-warning") confirmed via the ACTUAL build log line, not
   just code inspection: a missing generated-docs/ produces a
   console.warn and zero /guide pages, build still succeeds.
6. frontend/package.json: prebuild script removed entirely (no
   Node-side generation step left to hook onto); npm run
   docs:generate added, shelling directly to
   `python3 ../.github/scripts/publish_site.py .. generated-docs` -
   item 5's local-dev requirement.
7. .github/workflows/deploy-frontend.yml: the emit now runs as a
   dedicated Python step before npm ci/npm run build (item 2) -
   Python is already on the ubuntu-latest runner, no setup-python
   step needed, matching docs-wiki-publish.yml/docs-lint.yml's
   existing bare-python3 convention.
8. Link-rewrite parity fixtures (item 4): kept all 14 cases, relabeled
   pythonExpected/jsExpected -> wikiModeExpected/siteModeExpected
   (same values, same coverage - now a mode distinction on ONE
   function, not an implementation distinction between two). Dropped
   the Jest mirror per instruction; kept the 2 KeyError regression
   guards, unaffected by the restructure. Added the requested "one
   Jest smoke" (docsSite.test.ts): shells out to the REAL
   publish_site.py via child_process.execFileSync into a scratch temp
   directory (never the real frontend/generated-docs/), asserts every
   emitted page exists, has a title, and renders to real HTML
   containing an <h1> - "emitted artifacts exist and render," exactly
   as specified, not a second copy of the Python suite's fixture-case
   coverage.
9. docs/proposals/proposal-i-docs-as-site-source.md §1 (Architecture)
   fully rewritten for the single-transform design (item 6);
   §3 (extraction contract) and §4 (sequencing) updated to match -
   data extracts will extend publish_site.py itself, not a separate
   script; the deploy-frontend.yml step, not an npm hook. "Shipped
   vs. not yet built" rewritten to record the FIRST PR-I-1 pass as
   real, superseded history (not erased) - it worked, was fully
   tested, and shipped as #108, but the owner reviewed it and called
   for this restructure before/around the time #108 merged.
   docs/documentation-process.md's site-pipeline section rewritten to
   match.

DEVIATIONS:
- **This PR (#112) targets master directly, not PR #108's branch,
  because #108 was merged (by the owner, at 2026-07-19T01:17:23Z,
  commit 11ffef2d) partway through this restructure work** - its
  branch (docs-as-site-source-pri1-cvq14g) was deleted as part of
  that merge, per normal merge-duty cleanup, before I could push the
  restructure onto it. Discovered when `git push` failed with
  "couldn't find remote ref" after I'd already built the restructure
  commit on top of what I believed was still an open PR's branch.
  Verified via pull_request_read (not assumed) that #108 was genuinely
  merged, not just closed. Treated this as the documented "PR merged
  mid-task -> fresh change against current master" case: created a
  NEW branch off current origin/master, cherry-picked the restructure
  commit onto it cleanly (no conflicts - the delta was self-contained
  relative to what #108 had shipped), re-verified the entire build/
  test suite against the ACTUAL current master (which had also
  gained unrelated merges from other sessions in the meantime - #104,
  #111, and more), and opened this as a genuinely new PR rather than
  trying to force it back onto a branch that no longer exists.
- Earlier in this task I built the restructure on a stale local
  branch and hit a real merge conflict against origin/master before
  realizing another session had ALREADY resolved that exact conflict
  (a concurrent "Fix prettier table alignment" commit, a different
  Claude Code session ID, appeared on the branch between my pushes).
  Caught this by fetching before pushing rather than force-pushing
  over it; fast-forwarded to pick up that work rather than discarding
  it, then re-derived the restructure against the updated tip. No
  data lost, no force-push used.
- Everything else matches the instruction's 6 numbered items exactly;
  no scope additions beyond what was asked.

VERIFICATION (all re-run against the FINAL branch, against current
master, not carried over from the earlier failed-push attempt):
- Full `npm ci` + Jest suite: 42 suites, 399/399 tests passing, zero
  regressions.
- Full `npm run build`, twice: once with `npm run docs:generate` run
  first (produces a real /guide page - verified actual output HTML:
  correct title "Overview - ProxyPrints Guide", real <h1>Overview</h1>
  body, a wiki-only link correctly resolved to the external wiki URL),
  once without (graceful skip - verified the actual console.warn line
  in the build log, zero /guide pages, build still succeeds).
- publish_wiki.py re-run against the REAL wiki-publish-map.json:
  output unchanged (still writes all 21 wiki pages + the pointer page
  correctly).
- publish_site.py run twice consecutively, output diffed byte-
  identical (idempotency, not just claimed).
- Python fixture suite: 4/4 tests (covering all 14 cases x 2 modes +
  2 regression guards) passing.
- docs_lint.py: clean. Pinned prettier@2.7.1, black 22.8.0, isort
  5.12.0, ruff 0.0.257: clean across every touched file (one file
  needed a black reformat, applied and reverified).
- ESLint on both new/changed TS files: zero errors.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #112 is open against master, awaiting the owner's merge-queue
   action.
2. PR-I-3 (audience routing + doc hints spec, sent mid-turn during
   this restructure work) has NOT been started yet - queued as the
   next task, separate from this one.

LIVE STATE: branch docs-as-site-source-restructure-v2-cvq14g pushed
to origin; PR #112 open against
ProxyPrints/ProxyPrints.github.io master, unmerged. PR #108 (the
original dual-implementation PR-I-1) is merged and closed - its
content is now fully superseded by #112's diff, which removes
everything #108 added that this restructure replaces. Stale local
branches cleaned up (docs-as-site-source-restructure-cvq14g deleted
after its content was cherry-picked forward). No uncommitted work or
leftover build artifacts (out/, .next/,
frontend/generated-docs/, frontend/node_modules/) left in the working
tree.
```
