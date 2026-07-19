As of: 2026-07-18
What this is: Proposal I — DOCS-AS-SITE-SOURCE. **APPROVED, staged build
order.** Extends the existing `docs/` → wiki publish pipeline
(`.github/scripts/publish_wiki.py` + `.github/wiki-publish-map.json`,
documented in `docs/documentation-process.md`) with a second, parallel
target: the site itself consuming `docs/` the same single-source way the
wiki already does. Two concrete outputs — rendered site pages, and small
structured JSON "data extracts" — both build-time only, both driven by an
extended version of the existing publish map.

**PR-I-1 — shipped**: the pipeline itself (§1a's site-page mechanism, §2's
map schema extension, §4's `deploy-frontend.yml` trigger fix), proven
end-to-end against exactly one doc (`docs/overview.md`, live at `/guide`)
per the owner's own "prove the plumbing before widening it" scope — see
"Shipped vs. not yet built" below for the real detail. **PR-I-2+ — not yet
started**: the §0 source restructures (`catalog-completion-plan.md`'s
status prose → a marked table, `theory.md`'s constant citations → a marked
block), each landing as an ordinary docs PR that unlocks its own data
extract per §3's mechanism, which itself is not yet built (§1b).

## 0. Grounding: what actually exists today (read before the rest of this doc)

This spec corrects two assumptions baked into the task that produced it,
found by reading the actual files rather than assuming their shape:

- **`docs/features/catalog-completion-plan.md` has no status table.** Its
  `## Status` section (line 725 of 868) is nested bulleted prose — one
  entry per plan-part, bolding a state keyword inline ("**merged**",
  "HOLD #P3 cleared") with citations to PRs/reports — not a markdown
  table. It is **not** extraction-ready as-is; see §2's judgment call.
- **`docs/theory.md`'s weight/constant citations are inline in prose
  sentences**, not an isolated block (e.g. "machine weight 0.5 by
  default... `PRINTING_TAG_MIN_VOTES=2`" reads as running text under
  `## 4. Soundness mechanisms`). Same gap as above.

Both are real, useful extraction candidates in spirit — but §3's contract
(marked regions only, never prose-parsing) means neither ships day one
without a small content restructure first. Flagged here rather than
silently building around it or silently reshaping the task's premise.

Other facts this spec is built on, verified directly:

- **No markdown-rendering library exists in `frontend/package.json`**
  today (no `react-markdown`, `remark`, `marked`, `gray-matter`, MDX,
  `next-mdx-remote`). One new build-time dependency is required for §1(a).
- **`frontend/next.config.js` is already a static export**
  (`output: "export"`) — no server-side rendering, no ISR, no API routes
  at request time. Every page's content must be resolvable at `npm run build` time, full stop.
- **A build-time codegen precedent already exists**:
  `frontend/scripts/generate-keyrune-assets.js`, run today via
  `package.json`'s `postinstall` hook, parses a `node_modules` asset at
  install time and writes `frontend/src/common/generated/keyruneCodepoints.json`
  (gitignored, regenerated, consumed via a plain `import` elsewhere in the
  frontend). §1(b) reuses this exact shape — a script writing into
  `frontend/src/common/generated/` — for data extracts, but triggered
  differently (see §4, this can't hook `postinstall` since `docs/` doesn't
  change on `npm install`).
- **`frontend/src/pages/about.tsx` is hardcoded JSX**, not markdown-driven,
  but already establishes the `dangerouslySetInnerHTML` pattern for
  injecting pre-rendered HTML into a site-chrome page (there: backend-
  provided description text). §1(a) reuses this pattern for build-time-
  rendered markdown HTML rather than introducing a new one.
- **`.github/workflows/deploy-frontend.yml` does NOT trigger on `docs/**`today** — its`paths:`filter is`frontend/\*\*` and its own workflow file
  only. This is a real, required change for §4's "docs change → site
  rebuild" sequencing to actually fire; not an implementation detail to
  gloss over.
- **`docs/user-guide.md`** (36 lines, explicitly marked "skeleton, not all
  written yet") and **`docs/self-hosting.md`** (64 lines, filed as
  "Instance Admin Guide") are the two existing docs already closest in
  spirit to "site page" content — both already migrated wiki pages,
  both audience-facing rather than process-internal.

## 1. Architecture — SINGLE-TRANSFORM (owner-restructured before merge)

**This section describes the RESTRUCTURED design, superseding this doc's
own original two-mechanism draft** (a separate JS reimplementation of
link-rewrite logic, kept only as history in "Shipped vs. not yet built"
below). The owner's call, stated plainly: `.github/scripts/publish_wiki.py`
is the ONLY owner of link-rewrite/extraction logic, for both outputs.
Nothing in `frontend/` re-derives, re-parses, or reimplements any of it —
`frontend/` only ever reads Python's output and renders markdown to HTML,
a rendering concern kept deliberately separate from the transform concern
above it.

**The transform, one function, two modes**: `transform_links()`/
`rewrite_link()` (in `publish_wiki.py`) take an optional `repo_to_site`
map. Absent (`None`, the default) — this script's own wiki-publish mode —
it's exactly the original 2-way resolution (same-wiki link or GitHub blob
URL), unchanged. A real dict — site-emit mode — adds a 3rd resolution
branch (a link to a `"site"`-targeted page becomes that page's own route)
and changes how a wiki-only target resolves: an ABSOLUTE wiki URL rather
than a same-repo link, since the site doesn't host that page. Same
function, same regex, same fence/inline/image/anchor/external-link
gating logic — only the final link-formatting differs by mode.

**`.github/scripts/publish_site.py`** — a thin sibling script (not a
CLI flag on `publish_wiki.py` itself, to keep each script's own simple
positional-arg CLI simple) that imports `publish_wiki.py`'s functions
and, for every `"site"`-targeted page in the map: reads the source file,
calls `transform_links()` in site-emit mode, and writes
`{sourcePath, sitePath, title, markdown}` (link-rewritten MARKDOWN, not
HTML — rendering is `frontend/`'s job) to
`frontend/generated-docs/<slug>.json`, plus a `manifest.json` listing
every emitted page. Idempotent (rerunning with no doc changes produces
byte-identical output — verified, not just claimed) and fails
(non-zero exit, `::error::`-annotated) on the same class of problem
`publish_wiki.py` fails on: a missing mapped source file, a `"site"`
target with no `sitePath`, or any link resolving to neither a site/wiki
page nor a real file.

**`frontend/src/pages/guide/[[...slug]].tsx`** reads
`frontend/generated-docs/` directly (via
`frontend/src/features/guide/docsSite.ts`, kept in its own module — a
page file's exports get bundled for the client by Next's Pages Router,
and `fs` has no browser polyfill; only functions reachable exclusively
from `getStaticPaths`/`getStaticProps`, which Next strips from the client
bundle, are safe to touch `fs`). `getStaticPaths` builds routes from
`manifest.json`; `getStaticProps` reads the matching page JSON and calls
`marked.parse(markdown)` for the HTML, injected via `dangerouslySetInnerHTML`
— exactly `about.tsx`'s existing pattern for pre-rendered content it
doesn't own token-by-token. **Graceful degradation**: if
`frontend/generated-docs/manifest.json` is absent (a fresh checkout that
hasn't run the emit yet, or a `next dev`/`next build` in an environment
that skipped it), `getStaticPaths` logs a `console.warn` and returns zero
paths — `/guide` simply has no pages that build, never a crash.

**Local dev**: `npm run docs:generate` (from `frontend/`) shells directly
to `python3 ../.github/scripts/publish_site.py .. generated-docs` — no
Node-side generation step exists to wrap it.

**(b) Structured data extracts (§3) — not yet built, same owner (once it
exists)**: when PR-I-2+ makes a real marked-table source available (§0),
data extracts extend `publish_site.py` itself rather than a separate
script — keeping the "one Python owner" property this restructure exists
for, not reintroducing a second transform surface for a second output
shape.

## 2. The map decides what publishes where

Extends `.github/wiki-publish-map.json`'s existing per-page schema
(`{source, wiki}`) with an explicit `targets` array, so a page can name
any combination of `"wiki"`, `"site"`, `"data"` (a page can be more than
one — e.g. `user-guide.md` is legitimately both a wiki page today and a
future site page):

```json
{
  "source": "docs/user-guide.md",
  "wiki": "User-Guide",
  "targets": ["wiki", "site"],
  "sitePath": "/guide/using-it"
}
```

A `"data"` target additionally needs an `extracts` list naming which
marked regions in that source file to pull (§3) — a doc can carry more
than one marked region, and not every marked region in a doc needs to be
listed if only some are meant to feed the site.

**Proposed initial mapping** (illustrative starting point, not exhaustive
— the owner's actual call):

| Doc                                                                                                                                         | Targets                                                                  | Reasoning                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/user-guide.md`                                                                                                                        | `wiki`, `site`                                                           | Textbook user-guide content — this is exactly what a `/guide` route is for. Currently a skeleton; publishing it to the site sooner might create useful pressure to finish it, or might embarrass an unfinished page — **judgment call for the owner**, not resolved here.                                                      |
| `docs/self-hosting.md`                                                                                                                      | `wiki`, `site`                                                           | Same reasoning — instance-admin audience, but still an end-user-facing (self-hosting user) doc, not an internal process doc.                                                                                                                                                                                                   |
| `docs/overview.md`                                                                                                                          | `wiki`, `site`                                                           | Cold-reader orientation doc, explicitly written for an external audience already — a natural site landing page for "what is this fork."                                                                                                                                                                                        |
| `docs/theory.md`                                                                                                                            | `wiki`, `site` (+ `data`, once restructured per §0)                      | Already doubles as "the federation pitch's technical annex" per `CLAUDE.md` — audience-facing by design, arguably the single best case for a public site page of anything in `docs/`. Its constant citations are a real `data` candidate once given a marked table (§0) — not blocked on that to ship the `site` target alone. |
| `docs/federation-v1.md`, `docs/federation/public-export-v1.md`                                                                              | `wiki` only (unchanged) — **not** `site`                                 | These are protocol/spec docs for other _fork operators and tool authors_, not end users of this instance. Judgment call: technical-partner audience, not site-visitor audience — revisit if that audience assessment turns out wrong.                                                                                          |
| `docs/infrastructure.md`, `docs/troubleshooting.md`, `docs/lessons.md`                                                                      | `wiki` only (unchanged)                                                  | Explicitly operator/maintainer-facing — `documentation-process.md`'s own "Operating it" grouping. No site case.                                                                                                                                                                                                                |
| `docs/documentation-process.md`, `docs/upstreaming/*`, `docs/features/*.md` (process-shaped ones, e.g. `printing-tags.md`, `moderation.md`) | `wiki` only (unchanged)                                                  | Internal-process / contributor-facing, not end-user-facing — matches `documentation-process.md`'s own "Understanding the system" framing, which is written for a _contributor_ audience, not a site visitor.                                                                                                                   |
| `docs/features/catalog-completion-plan.md`                                                                                                  | `wiki` only today; `data` candidate **after** a status-table restructure | See §0 — not extraction-ready as prose.                                                                                                                                                                                                                                                                                        |
| `docs/proposals/`, `docs/reports/`, `docs/audits/`                                                                                          | none (unchanged)                                                         | Already explicitly excluded from the wiki for being drafts/point-in-time — doubly true for a public site, which shouldn't surface a HOLD spec or a session's internal report as if it were finished, published content.                                                                                                        |

**The map stays the single decision point** — same discipline
`documentation-process.md` already states for the wiki (`publish_wiki.py`
does not parse `docs/README.md`'s prose; the mapping is hand-maintained on
purpose). A doc's targets are a deliberate, reviewed choice each time,
never inferred from folder location alone beyond the blanket
proposals/reports/audits exclusion above.

## 3. Extraction contract

Data extracts come from **explicitly marked regions**, never from parsing
prose — matching this proposal's own §0 finding that today's two
candidate sources (`catalog-completion-plan.md`, `theory.md`) are prose
and therefore not yet valid sources at all, by this same contract.

**Marker syntax**, mirroring `publish_wiki.py`'s existing
`GENERATED_MARKER` convention rather than inventing an unrelated one:

```markdown
<!-- DATA-EXTRACT: catalog-status -->

| Part                  | Status      | Ref      |
| --------------------- | ----------- | -------- |
| 1 — Run-cohort safety | merged      | PR #41   |
| 2 — Phash backfill    | in progress | task #52 |

<!-- END DATA-EXTRACT -->
```

- The extract name (`catalog-status` above) is the contract between the
  doc and the map — `publish_site.py`, once extended to build this (§1b),
  looks for exactly the name(s) listed in that doc's `extracts` array
  (§2) and nothing else; an unlisted marked region in the same file is
  ignored (a doc can carry scratch/example marker blocks not meant for
  extraction, e.g. this very doc's own illustrative marker example two
  paragraphs up, which intentionally carries no real extract name and
  must never be picked up).
- **Only markdown tables are parsed** inside a marked region v1 — header
  row + separator row + data rows, straightforward and already
  battle-tested prior art in this repo (`docs_lint.py` and
  `publish_wiki.py` both already do line-oriented markdown parsing without
  a heavyweight AST library; this follows the same lightweight-regex
  philosophy rather than introducing a full markdown-table-parsing
  dependency for one narrow job). Output shape:
  `{extract: "catalog-status", headers: [...], rows: [[...], ...]}`,
  written alongside `publish_site.py`'s existing per-page markdown output
  in `frontend/generated-docs/` — same script, same output directory,
  per §1's "one Python owner" property; exact filename not resolved here
  since nothing has driven the decision yet.
- **A broken or missing marker is a hard build error**, exactly
  `publish_wiki.py`'s own link-resolution-error philosophy (fail the
  emit, never ship a wrong or empty page silently): an `extracts` entry
  in the map naming a marker that doesn't exist in the source file, a
  `<!-- DATA-EXTRACT: x -->` with no matching `<!-- END DATA-EXTRACT -->`,
  or a marked region that isn't a well-formed markdown table (per the
  narrow v1 parser above) all fail `publish_site.py` with a clear
  message naming the doc, the extract name, and what's wrong — the same
  `::error::`-annotated, non-zero-exit convention it already uses for
  broken links.
- **A doc edit outside the markers can never silently break a site
  component** — the whole point of markers over prose-parsing. Reordering
  paragraphs, adding a new subsection, rewording surrounding prose: none
  of it touches the extract, because the parser never looks outside the
  marker pair. Only an edit to the table rows themselves, or an edit that
  breaks the marker pair itself, has any effect on the JSON output — and
  the latter case is the hard-error path above, never a silent stale
  extract.

## 4. Sequencing — composing with the existing pipeline and the site deploy

Builds on `publish_wiki.py`'s established conventions directly: idempotent
(rerunning `publish_site.py` with no doc changes produces byte-identical
output — verified), fires on merge to `master`.

**What's genuinely new, not just "the same pipeline again"**:

1. `.github/workflows/deploy-frontend.yml`'s trigger `paths:` filter
   originally read `frontend/**` only — **extended** to include `docs/**`,
   `.github/wiki-publish-map.json`, `.github/scripts/publish_wiki.py`, and
   `.github/scripts/publish_site.py`, mirroring `docs-wiki-publish.yml`'s
   own trigger shape. Without this, a `docs/`-only PR would merge and the
   wiki would regenerate (existing pipeline) while the site silently
   would not.
2. **`publish_site.py` runs as a dedicated step in
   `deploy-frontend.yml`, BEFORE `npm ci`/`npm run build`** — Python is
   already on the `ubuntu-latest` runner (no `setup-python` step needed,
   matching `docs-wiki-publish.yml`/`docs-lint.yml`'s own existing
   convention of calling bare `python3`). This is a CI-workflow step, not
   an npm lifecycle hook (`prebuild`/`postinstall`) — there is no
   Node-side generation step left to hook one onto; `frontend/`'s only
   job is reading the already-emitted output. Local dev gets the
   equivalent via `npm run docs:generate`, a direct shell-out to the same
   script (§1).
3. **Graceful degradation, not a pre-merge CI check, is the chosen
   safety net for the site-page mechanism** (owner's restructure): rather
   than a separate pre-merge dry-run job, a missing `generated-docs/`
   simply yields zero `/guide` pages with a console warning (§1) — the
   real correctness check is `publish_site.py`'s own hard-error behavior
   inside the `deploy-frontend.yml` step itself (item 2), which fails the
   whole deploy on a broken link, and the link-rewrite parity fixtures
   (`.github/scripts/tests/test_publish_wiki_link_rewrite.py`, run via
   `docs-lint.yml`'s `link-rewrite-parity` job on every
   `.github/scripts/**` change) which catch a logic regression before
   it ever reaches a real doc.
4. **Full sequence, as built**: PR touching `docs/**` merges to
   `master` → `docs-wiki-publish.yml` regenerates the wiki (unchanged,
   existing) → `deploy-frontend.yml` fires (triggered by `docs/**` per
   item 1) → `publish_site.py` emits `frontend/generated-docs/` (fails
   the whole deploy on a broken link, per §1) → `npm ci` → `npm run build`
   statically renders every `site`-targeted doc via `getStaticProps` (§1)
   → `actions/upload-pages-artifact` + `deploy-pages`, identical to
   today. One Pages build, two publish targets (wiki, site) both current
   as of the same merge — verified end-to-end, not assumed.

## 5. What v1 explicitly is not

Stated so nothing here reads as more than it is:

- **No CMS.** Nothing is editable from a browser, nothing has a database
  row, nothing has a "publish" button outside `git push`. `docs/` is
  still the only place to write.
- **No runtime fetching of docs.** Every site page and every data extract
  is resolved at `npm run build` time via the filesystem, per the static-
  export constraint already governing this entire frontend (§0). No new
  API route, no client-side fetch of a doc's markdown, no server
  component (this app has none — static export only).
- **No editing on the site.** The site consumes `docs/`, one-directionally,
  the same as the wiki does today — reading this spec's own name
  literally, docs are the _source_, the site is a _target_, never the
  reverse.
- **No change to what the wiki already does.** This is a genuinely
  additive second target, not a replacement or a restructure of the
  existing wiki pipeline — `publish_wiki.py`'s own logic changes only to
  the extent §1(a) shares its link-rewrite helper functions (a refactor
  for reuse, not a behavior change to the wiki's own output).
- **The open calls this doc originally flagged (markdown library, route
  naming, §2's mapping table) were resolved during PR-I-1's build** —
  `marked` and `/guide`, specifically; see "Shipped vs. not yet built"
  below for what that build actually did and didn't decide.

## Shipped vs. not yet built

**PR-I-1, first pass — superseded before merge, kept here as real
history rather than erased**: the first working version of PR-I-1 shipped
a JS reimplementation of link-rewrite logic
(`frontend/scripts/generate-docs-site.js`, against `marked`) alongside
`publish_wiki.py`'s existing Python implementation, plus a
`pythonExpected`/`jsExpected`-labeled parity fixture set proving the two
stayed in sync. It worked, was fully tested (14 fixture cases, a full
`npm run build` producing a real `/guide` page, Jest passing), and shipped
as PRs #106 (spec)/#108 (build) — but the owner reviewed it before merge
and called for the restructure below instead, judging two independently-
drifting implementations of the same link-rewrite contract as more risk
than the alternative was worth, even with a fixture tether in place.
Superseded, not merged as-is; nothing from that version survives in the
current architecture (§1) except the fixture set itself, adapted.

**PR-I-1, restructured (this pass) — shipped, single-transform
architecture**: `.github/scripts/publish_wiki.py`'s `transform_links()`/
`rewrite_link()` extended with an optional `repo_to_site` parameter (§1) —
`None` preserves the original wiki-only behavior exactly (regression-
checked against the real `wiki-publish-map.json`, byte-identical output);
a real map adds site-mode resolution. `.github/scripts/publish_site.py`:
new sibling script, imports `publish_wiki.py`'s functions (no
reimplementation), emits `frontend/generated-docs/*.json` (link-rewritten
markdown, not HTML) + `manifest.json` — verified idempotent (two
consecutive runs, byte-identical output, diffed). `frontend/scripts/generate-docs-site.js` and its Jest mirror are DELETED, not merely
unused — there is no JS-side transform code anywhere in this repo anymore.
`frontend/src/features/guide/docsSite.ts`: new module owning the
`fs`-touching reads of `generated-docs/` (kept out of the page file
itself — a real build failure, `Module not found: Can't resolve 'fs'`,
is why: a page file's own exports get bundled for the Pages Router client
build, and only code reachable exclusively from
`getStaticPaths`/`getStaticProps` is safe to touch `fs`). `frontend/src/pages/guide/[[...slug]].tsx`: slimmed to routing + `marked.parse()` rendering
only. `package.json`: `prebuild` script removed (no Node-side generation
step left to hook); `docs:generate` added, shelling directly to
`publish_site.py`. `.github/workflows/deploy-frontend.yml`: the emit now
runs as a dedicated Python step before `npm ci`/`npm run build`, not an
npm lifecycle hook. Verified end-to-end, both paths: (1) `generated-docs/`
present → `npm run build` produces a real `/guide` page (confirmed via the
actual output HTML: correct title, real body, correctly-rewritten links);
(2) `generated-docs/` absent → build still succeeds, `console.warn` fires,
`/guide` has zero pages, confirmed via the actual build log line, not
assumed from the code.

**Link-rewrite parity fixtures — kept, relabeled, strengthened**: the
same 14-case fixture set (`.github/scripts/testdata/link_rewrite/`)
survives the restructure, since the WIKI-MODE/SITE-MODE divergence it was
already modeling (a wiki-only target's link format legitimately differs by
output target) is now a mode distinction on one function rather than an
implementation distinction between two — cases relabeled
`pythonExpected`/`jsExpected` → `wikiModeExpected`/`siteModeExpected`,
same values, same coverage.
`.github/scripts/tests/test_publish_wiki_link_rewrite.py` now runs every
case through BOTH modes of the single `transform_links()` (4 subTest-
covered test methods total, including the 2 regression guards for the
`site-only-doc.md`/`build_repo_to_wiki_map` bug this fixture set found
while first being built — see below). The Jest mirror is gone; in its
place, `frontend/src/features/guide/docsSite.test.ts` is a genuine
integration smoke test — it shells out to the real `publish_site.py` (via
`child_process.execFileSync`, into a scratch temp directory, never the
real `frontend/generated-docs/`) and asserts the real emitted artifacts
exist, parse, and render to non-empty HTML with a real `<h1>` — "emitted
artifacts exist and render," not a second copy of the fixture-case
coverage the Python suite already owns exclusively. Wired into CI:
`docs-lint.yml`'s `link-rewrite-parity` job (Python, triggered by
`.github/scripts/**`) is unchanged; `test-frontend.yml`'s trigger paths
were updated to reflect what the JS smoke test actually depends on now
(`publish_wiki.py`, `publish_site.py`, the map file) rather than the
retired fixture-mirror path. **The KeyError bug this fixture set found
while being built the first time** (`build_repo_to_wiki_map`/`main()`
both did `page["wiki"]` unconditionally, crashing the moment any
site-only page entered the mapping) is fixed in `publish_wiki.py` and
locked in by a dedicated regression test, unaffected by the restructure.

**Not yet built** (concrete next steps per the owner's staged order, not
silently dropped):

1. **§1(b)/§3 — data extracts.** Extends `publish_site.py` itself once
   built (not a separate script — see §1's "one Python owner" framing).
   Waits on PR-I-2+'s source restructures per §0 — building the extractor
   ahead of a real marked-table source to extract would mean testing it
   against nothing real.
2. **Widening §2's site-target list** beyond `overview.md` — `user-guide.md`,
   `self-hosting.md`, `theory.md` per this doc's own proposed initial
   mapping — deliberately deferred, per "prove the plumbing before
   widening it."
3. **A nav link to `/guide`** — no entry was added to `Navbar.tsx`; the
   route works and is reachable by direct URL, but isn't discoverable from
   the site's own chrome yet. Left out deliberately (a nav change is a
   real, visible UX decision this pass's "prove the plumbing" scope didn't
   ask for) rather than added silently.
4. **`readme.md` folded into the pipeline as a third (`readme`) emit
   mode** — audited (`docs/proposals/proposal-i-readme-pipeline.md`,
   HOLD, content merge map + architecture sketch only) but not built;
   gated on the owner reviewing that map's open items before any
   restructure of `readme.md` itself begins.
