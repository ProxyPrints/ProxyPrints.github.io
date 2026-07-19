```
TASK: CLOUD session (upstream-readiness) — DOCS-AS-SITE-SOURCE spec
(SPEC + HOLD, no build). Branch: docs-as-site-source-spec-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/106 (against
this fork's own master — never upstream).

WHAT SHIPPED: new docs/proposals/proposal-i-docs-as-site-source.md,
plus a docs/README.md Plans & proposals row and one docs_lint.py
ALLOWLIST entry.

- New section 0 ("Grounding"), added ahead of the 5 requested
  sections, because two of the task's own premises didn't hold on
  inspection: docs/features/catalog-completion-plan.md's status
  tracking (line 725) is nested bulleted prose, not a table (zero
  pipe-table rows anywhere in the file); docs/theory.md's weight/
  constant citations are inline prose sentences, not an isolated
  block. Neither is extraction-ready under the spec's own
  marked-region-only contract (item 3) without a content restructure
  first - flagged explicitly rather than silently building around it
  or silently reframing the task's own premise as correct.
- 1. ARCHITECTURE: a Next.js catch-all SSG route (getStaticPaths/
  getStaticProps reading docs/ files via fs at build time, converting
  markdown to HTML, reusing frontend/src/pages/about.tsx's existing
  dangerouslySetInnerHTML pattern for pre-rendered content) for site
  pages; a Node prebuild script mirroring
  frontend/scripts/generate-keyrune-assets.js's real, existing
  codegen-into-frontend/src/common/generated/ precedent for data
  extracts. Flagged link-rewriting as a genuine three-way problem
  (site route / wiki page / GitHub blob) beyond publish_wiki.py's
  existing two-way case, proposing its transform_links/rewrite_link
  functions get shared rather than reimplemented.
- 2. THE MAP: extends wiki-publish-map.json's {source, wiki} schema
  with a targets array (wiki/site/data). Proposed initial mapping
  with judgment calls named explicitly per instruction - e.g. whether
  to site-publish user-guide.md's current skeleton state now
  (possible useful pressure to finish it) or wait, and which docs are
  end-user-facing (user-guide, self-hosting, overview, theory) vs.
  contributor/operator-facing (federation specs, infrastructure,
  most of "Understanding the system").
- 3. EXTRACTION CONTRACT: <!-- DATA-EXTRACT: name --> / <!-- END
  DATA-EXTRACT --> markers around markdown tables only, mirroring
  publish_wiki.py's own GENERATED_MARKER convention. A broken/missing
  marker, or an extracts-list entry naming a marker that doesn't
  exist, is a hard build error - same fail-fast philosophy as
  publish_wiki.py's existing link-resolution errors, not a silent
  stale/empty extract.
- 4. SEQUENCING: found (by reading the actual workflow file, not
  assuming) that .github/workflows/deploy-frontend.yml does NOT
  currently trigger on docs/** at all - only frontend/** and its own
  workflow file. Flagged as a required, concrete fix for "docs change
  -> site rebuild" to actually fire, not an implementation detail to
  gloss over. Specced the data-extract script hooking into npm's
  prebuild (not postinstall, since docs/ doesn't change on npm
  install - a deliberate divergence from the keyrune precedent's
  exact trigger while keeping its output-location convention), and
  the full merge -> wiki regenerate -> site rebuild sequence once
  that trigger fix lands.
- 5. WHAT V1 IS NOT: no CMS, no runtime doc fetching (this app is a
  static export with no server/API routes, full stop), no site-side
  editing, build-time only.

DEVIATIONS:
- Added section 0 (not one of the 5 requested sections) specifically
  to surface the two premise corrections above before the rest of the
  spec, rather than either silently accepting the task's framing or
  quietly reshaping items 2/3 around a corrected premise the reader
  never sees stated. Judged this as strengthening the spec rather
  than deviating from the ask.
- Route naming (`/docs` vs `/guide`) and the exact initial-mapping
  table (section 2) are explicitly left as open owner calls rather
  than resolved - this is a HOLD spec awaiting review, not a decision
  document.

VERIFICATION:
- Every factual claim (frontend/package.json's dependency list,
  next.config.js's actual contents, about.tsx's rendering approach,
  deploy-frontend.yml's real trigger paths, generate-keyrune-
  assets.js's actual mechanism, catalog-completion-plan.md's and
  theory.md's actual structure, user-guide.md's/self-hosting.md's
  real line counts and content) verified directly against the repo
  via a dedicated Explore-agent research pass before writing the
  spec, not assumed from the task's own framing.
- python3 .github/scripts/docs_lint.py - clean.
- npx prettier@2.7.1 --check (pinned version) on both touched
  markdown files - clean (after one --write pass; only the intended
  content reformatted, not unrelated file content).
- python3 -m black --check --diff .github/scripts/docs_lint.py
  (pinned 22.8.0) - clean.

OPEN ITEMS / DECISIONS NEEDED (all explicitly flagged in the spec
itself, restated here):
1. Route naming: /docs vs /guide vs something else.
2. The initial mapping table (section 2) - is the proposed split
   (user-guide/self-hosting/overview/theory -> site; federation
   specs/operator docs -> wiki-only) the right one.
3. Whether to site-publish user-guide.md now while it's still a
   skeleton, or wait until it's finished.
4. catalog-completion-plan.md and theory.md both need a content
   restructure (an explicit marked table) before either can be a real
   data-extract source - not blocking the rest of the spec, but a
   real prerequisite for the two illustrative examples the task
   itself named.

LIVE STATE: branch docs-as-site-source-spec-cvq14g pushed to origin;
PR #106 open against ProxyPrints/ProxyPrints.github.io master,
unmerged, awaiting the owner's review. Separate from PR #100 and
PR #103, both also still open/unmerged. No uncommitted work left
behind.
```
