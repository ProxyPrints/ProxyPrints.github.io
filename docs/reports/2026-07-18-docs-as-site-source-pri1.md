```
TASK: CLOUD session (upstream-readiness) — PROPOSAL I approved, staged
build order: PR-I-1 (pipeline + trigger fix + one site page,
end-to-end). Branch: docs-as-site-source-pri1-cvq14g, stacked on
docs-as-site-source-spec-cvq14g (PR #106, spec-only, unmerged). PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/108 (base =
PR #106's branch, NOT master yet — see LIVE STATE).

WHAT SHIPPED:

1. .github/wiki-publish-map.json: schema extended with a per-page
   targets array (wiki/site/data) + optional sitePath, per the spec's
   §2. Every existing entry got targets: ["wiki"] (verified
   publish_wiki.py still runs cleanly against the extended schema -
   it ignores the new keys); docs/overview.md additionally got
   targets: ["wiki", "site"], sitePath: "/guide" - the ONE doc this
   pass proves the mechanism against, per the explicit "prove the
   plumbing before widening it" scope.
2. frontend/scripts/generate-docs-site.js: new script, wired as an
   npm "prebuild" step (package.json) rather than "postinstall" -
   docs/ doesn't change on npm install, a deliberate divergence from
   the keyrune-assets precedent's exact trigger while keeping its
   output-location convention (frontend/src/common/generated/
   docsSite/, gitignored). Reads every "site"-targeted doc, rewrites
   its links across three resolution branches (another site route /
   an external wiki URL / a GitHub blob URL - never a raw docs/
   filename), converts markdown to HTML via a new `marked`
   devDependency, fails the whole build on any unresolvable link.
   Reimplemented publish_wiki.py's link-rewrite logic in JS rather
   than literally sharing it (impossible across Python/Node runtimes
   as originally floated in the spec) - documented as a deliberate,
   precedented divergence in the script's own header, matching
   docs/lessons.md's already-accepted frontend/backend sanitisation-
   logic duplication pattern.
3. frontend/src/pages/guide/[[...slug]].tsx: the SSG route, wrapped
   in existing site chrome (ProjectContainer/Footer, Layout.tsx's
   already-global Superhero styling via _app.tsx), injecting
   pre-rendered HTML via dangerouslySetInnerHTML - exactly
   about.tsx's existing pattern for build-time-trusted content, no
   new rendering approach introduced.
4. .github/workflows/deploy-frontend.yml: trigger paths extended
   with docs/** and the map file (previously frontend/** only) - the
   gap flagged in the spec's own §4, now closed.
5. Documentation updated to match reality: proposal-i's own header
   changed from "SPEC + HOLD, no build" to "APPROVED, staged build
   order," with a new "Shipped vs. not yet built" section (4 honest
   deferred items, including one I found only while building: no
   Navbar link to /guide yet - the route works by direct URL but
   isn't discoverable from site chrome). docs/README.md's status
   bumped HOLD -> BUILDING. docs/documentation-process.md got a new
   section describing the live site pipeline, mirroring how the wiki
   pipeline is already documented there.

VERIFICATION (all actually run, not just read):
- `npm run build` (full production build, not just tsc/dev) produces
  a real /guide page: verified the actual output HTML file
  (out/guide.html) has the correct title ("Overview - ProxyPrints
  Guide"), a real rendered <h1>Overview</h1> body, and confirmed by
  grep that a wiki-only link (theory.md) correctly resolved to the
  external wiki URL and an unmapped-but-real file (README.md)
  correctly resolved to a GitHub blob URL - the two link-resolution
  branches this specific doc's own links actually exercise. The
  third branch (site-to-site link) is untested for lack of a second
  site page to link to yet, not skipped or assumed working.
- Zero new ESLint errors/warnings from either new file (ran eslint
  directly against both, fixed one import-sort issue via --fix).
- Full Jest suite: 391/391 passing, confirmed zero regressions.
- docs_lint.py and pinned prettier@2.7.1 clean across every touched
  file, including the two new frontend files and the workflow YAML.
- Found and fixed one PRE-EXISTING, unrelated environment gap while
  testing (keyruneCodepoints.json missing because
  generate-keyrune-assets.js's postinstall step had never actually
  run in this sandbox) - confirmed unrelated to this change by
  checking file timestamps/emptiness before assuming it was
  something I broke; ran the existing script directly to fix it
  rather than working around the symptom.

DEVIATIONS:
- Split PR-I-1 into its OWN branch/PR (#108, stacked on #106) rather
  than committing it onto #106's own branch, which is what I did
  first before catching the mistake: the instruction's phrasing
  ("Merge #106's spec doc via the server queue first... PR-I-2+...
  each as a normal docs PR") implies #106 and PR-I-1 are meant to be
  separate, sequenced artifacts, not one combined PR. Caught before
  pushing anything (the first attempt was local-only), split cleanly
  via `git reset --hard` back to #106's already-pushed tip (safe,
  no force-push, no history rewrite of anything public) and a new
  branch for PR-I-1's commit. Flagging this correction explicitly
  rather than silently.
- publish_wiki.py's transform_links/rewrite_link functions were NOT
  literally shared with the new JS script, contrary to the spec
  doc's original "shared refactor" framing (§1a) - impossible as
  literally stated, since one runs in Python and the other in
  Node/the Next.js build. Reimplemented equivalent logic in JS
  instead; documented as a deliberate, precedented divergence (both
  in the script's own header comment and in the "Shipped vs. not yet
  built" section) rather than silently doing something different
  from what the spec said.
- Did not build a pre-merge CI check for the new site-page mechanism
  (mirroring docs_lint.py's pre-merge posture) - the spec's own §4
  flagged this as informing the DATA-EXTRACT mechanism specifically
  (§1b/§3), which PR-I-1 doesn't build at all (that's PR-I-2+ scope) -
  no gap actually opened by this pass that needs a check yet.
- Did not add a Navbar link to /guide - a real, visible UX decision
  ("prove the plumbing" didn't ask for site-chrome discoverability),
  left explicitly flagged rather than added unilaterally.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #108's base needs retargeting from docs-as-site-source-spec-
   cvq14g to master once #106 actually merges via the server queue -
   flagged in the PR body itself; whoever handles #106's merge should
   either retarget #108 first (the documented-safe order per
   docs/lessons.md's stacked-PR prevention note) or be aware #108
   will need it done as a fast-follow if #106 merges without that
   step.
2. Whether/when to add a Navbar link to /guide.
3. PR-I-2+'s two source restructures (catalog-completion-plan.md,
   theory.md) are still fully unstarted - this session did not touch
   them, per the owner's own staged sequencing.

LIVE STATE: branch docs-as-site-source-pri1-cvq14g pushed to origin;
PR #108 open, based on docs-as-site-source-spec-cvq14g (PR #106's
branch), NOT yet against master - by design, per the stacked
sequencing, but genuinely needs the retarget-before-merge step noted
above once #106 lands. PR #106 itself untouched by this task (still
spec-only, as originally shipped). All local build artifacts
(out/, .next/, frontend/src/common/generated/docsSite/) cleaned up
before every commit - nothing generated left in the working tree.
```
