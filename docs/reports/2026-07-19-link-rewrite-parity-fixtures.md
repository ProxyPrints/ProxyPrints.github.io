```
TASK: CLOUD session (upstream-readiness) — parity fixtures for
publish_wiki.py's and generate-docs-site.js's link-rewrite
implementations, required before PR #108 merges. Same branch:
docs-as-site-source-pri1-cvq14g (stacked on PR #106, still unmerged).
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/108

WHAT SHIPPED:

1. .github/scripts/testdata/link_rewrite/: a synthetic fixture repo
   (5 real dummy markdown files: a wiki+site-targeted doc, a
   wiki-only doc, a site-only doc, a real-but-unmapped file, a nested
   subdirectory doc) plus a small, fixed, standalone map.json
   (deliberately NOT the real wiki-publish-map.json, so fixtures stay
   stable as real docs get added/removed) plus cases.json - 14 cases
   covering fence-block skip, inline-code skip, image-link skip
   (negative lookbehind), external-URL/mailto/anchor-only pass-
   through, the [[routes]]-non-path-literal skip, a wikilink to a
   wiki-only target, a markdown link with custom display text to a
   wiki-only target, a link to a real-but-unmapped file (blob URL,
   identical on both sides), a link to a genuinely nonexistent file
   (error case, both sides), subdirectory-relative path resolution,
   #fragment-dropping on a link to a mapped page, and a site-only
   target (no "wiki" key at all). Cases genuinely identical between
   both implementations assert one shared `expected`; cases that
   legitimately diverge by design (a wiki-only target: publish_wiki.py
   links to the same-wiki page name, generate-docs-site.js links to
   the external wiki URL since it isn't itself inside the wiki)
   assert a pythonExpected/jsExpected pair instead of pretending the
   divergence away - a fixture that claimed byte-identical output
   for a case that's supposed to differ would itself be wrong.
2. .github/scripts/tests/test_publish_wiki_link_rewrite.py: runs the
   fixture set against publish_wiki.py's real transform_links
   (stdlib unittest, no new pip dependency - matches publish_wiki.py's
   own zero-dependency convention).
3. frontend/scripts/generate-docs-site.test.js: runs the SAME fixture
   set against generate-docs-site.js's real transformLinks. Required
   refactoring generate-docs-site.js first: repoRoot was a module-
   level constant derived from import.meta.url, now a parameter on
   every exported function (matching publish_wiki.py's already-
   parameterized design); the exported functions
   (transformLinks/rewriteLink/resolveRepoRelative/buildTargetMaps/
   loadMapping/deriveTitle/slugFromSitePath) are now importable
   without triggering main()'s filesystem side effects, guarded
   behind an `if (process.argv[1] === thisFile)` entrypoint check.
   jest.config.mjs needed two changes: testMatch extended with a
   narrowly-scoped `frontend/scripts/**/*.test.js` (the script itself
   is plain JS, matching its sibling build scripts
   generate-keyrune-assets.js/copy-pdf-worker.js - tsconfig.json's
   allowJs: false rules out testing it via .test.ts, confirmed by
   actually hitting that exact error first), and marked added to
   transformIgnorePatterns' allowlist (ESM-only package, same fix
   already applied there for until-async/node-fetch/etc).
4. A REAL BUG FOUND AND FIXED while building the fixture, not
   invented for the exercise: publish_wiki.py's
   build_repo_to_wiki_map and main() both did page["wiki"]
   unconditionally - the moment map.json's fixture-required
   site-only-doc.md entry (no "wiki" key, per this proposal's own
   targets schema extension) was added, this would KeyError on
   EVERY fixture case, not just the one exercising it, since map
   loading happens once for the whole file. Fixed both call sites
   (page.get("wiki"), filtering falsy values in the dict
   comprehension; main()'s publish loop now skips a page with no
   wiki target rather than crashing trying to write one). A
   dedicated regression test
   (test_site_only_page_does_not_crash_the_wiki_map_build) locks
   this in. Re-ran publish_wiki.py against the REAL current
   wiki-publish-map.json afterward to confirm zero behavior change
   for the existing, all-wiki-key-present mapping.
5. Wired into CI: docs-lint.yml gets a new link-rewrite-parity job
   (Python side, triggered by .github/scripts/** changes, stdlib
   only - no pip install step needed). test-frontend.yml's trigger
   paths gained .github/scripts/testdata/link_rewrite/** (JS side
   runs via the existing sharded Jest sweep, already scoped to
   frontend/**, no new job needed since the test file lives under
   frontend/scripts/).
6. docs/proposals/proposal-i-docs-as-site-source.md's "Shipped vs.
   not yet built" section updated: parity fixtures documented as
   shipped with the bug-found story; the "no pre-merge CI check" item
   this pass previously left open (item 3) is now closed for the
   site-page mechanism specifically and removed from the list.

DEVIATIONS: none from the instruction as given - the fixture set
covers every category named ("doc-to-doc, anchors, images, external,
the edge cases publish_wiki.py's own comments mention" - the fence/
inline-code skip and the [[wiki]] vs. [[routes]] literal distinction
both trace directly to comments already in publish_wiki.py's own
docstring/header).

VERIFICATION (all actually run):
- python3 .github/scripts/tests/test_publish_wiki_link_rewrite.py -v:
  2/2 (covering all 14 fixture cases via subTest, plus the regression
  guard) passing.
- npx jest scripts/generate-docs-site.test.js: 16/16 passing.
- Full frontend Jest suite: 407/407 passing (391 prior + 16 new),
  zero regressions.
- Full `npm run build`: still produces the /guide page correctly,
  confirmed by re-checking the output HTML.
- python3 .github/scripts/publish_wiki.py . <tmp-dir> against the
  REAL wiki-publish-map.json: still produces all 21 pages + the
  pointer page correctly, confirming the bugfix didn't change
  existing behavior.
- docs_lint.py and pinned prettier@2.7.1 clean across every touched
  file; black 22.8.0 (had to reformat 2 files - accepted its
  formatting), isort 5.12.0 (already clean), ruff 0.0.257 (already
  clean) on the Python changes, all pinned to this repo's own
  .pre-commit-config.yaml versions.

OPEN ITEMS / DECISIONS NEEDED: unchanged from the prior relay - PR
#108's base still needs retargeting from docs-as-site-source-spec-
cvq14g to master once #106 actually merges via the server queue.

LIVE STATE: branch docs-as-site-source-pri1-cvq14g now has 2 commits
(the original PR-I-1 build, then this parity-fixture addition),
pushed to origin. PR #108 open, based on PR #106's branch (still
unmerged), description updated to cover the fixture work. No
uncommitted work or leftover build artifacts (out/, .next/,
frontend/src/common/generated/docsSite/) left in the working tree.
```
