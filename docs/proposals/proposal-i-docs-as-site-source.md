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

## 1. Architecture

Two independent build-time mechanisms, both reading the extended publish
map (§2), both composing with the existing pipeline rather than replacing
it:

**(a) Rendered site pages** — a new catch-all route,
`frontend/src/pages/docs/[...slug].tsx` (or `/guide/[...slug].tsx`; naming
is an owner call, not resolved here — "docs" risks reading as
developer-facing given the existing `docs/` repo convention, "guide"
matches `user-guide.md`'s own name more closely). Uses Next's standard
static-export SSG shape: `getStaticPaths` enumerates every doc in the map
with a `site` target; `getStaticProps` reads that doc's source file
directly off disk via Node's `fs` (the build runs inside the checked-out
repo, same as `generate-keyrune-assets.js` already does), converts
markdown to HTML with the new dependency from §0, and returns the HTML
string as a prop. The page component wraps it in normal site chrome
(`Layout.tsx`, Superhero styling — no new visual system) and injects the
HTML via `dangerouslySetInnerHTML`, exactly `about.tsx`'s existing pattern
for pre-rendered content it doesn't own token-by-token.

**Link rewriting is a real, separate problem here, not an afterthought.**
`publish_wiki.py`'s whole second half exists because copying a doc's `[[..]]`/
markdown links verbatim into a different target reinterprets them wrong —
the exact same problem recurs for site pages, with a third possible
resolution instead of two: a link inside a doc being rendered as a site
page must resolve to (i) another site page's route, if the target is also
mapped to `site`; (ii) a wiki page, if the target is `wiki`-only (arguably
correct to send a reader to the wiki rather than a GitHub blob for
another _doc_, unlike `publish_wiki.py`'s own blob-URL fallback, since the
site is now also a home for docs content); (iii) a GitHub blob URL,
identical to `publish_wiki.py`'s existing fallback, for anything unmapped
entirely. This is naturally a small, mostly-shared refactor of
`publish_wiki.py`'s existing `transform_links`/`rewrite_link` functions
into something both the wiki script and the new site build step import,
rather than a second, independently-drifting reimplementation — flagged
as the right shape, not designed in full here.

**(b) Structured data extracts** — a new Node script,
`frontend/scripts/generate-docs-data.js`, following
`generate-keyrune-assets.js`'s exact precedent: parses MARKED regions
(§3) out of specific `docs/` files per the map, and writes one small JSON
file per extract into `frontend/src/common/generated/docsData/<name>.json`
(gitignored, regenerated, never hand-edited — same convention as the
keyrune codepoints file). Site (and, if ever useful, editor-app)
components `import` these directly as ordinary static JSON — no runtime
fetch, no API route, consistent with the static-export constraint.

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
  doc and the map — `generate-docs-data.js` looks for exactly the name(s)
  listed in that doc's `extracts` array (§2) and nothing else; an
  unlisted marked region in the same file is ignored (a doc can carry
  scratch/example marker blocks not meant for extraction, e.g. this very
  doc's own illustrative marker example two paragraphs up, which
  intentionally carries no real extract name and must never be picked up).
- **Only markdown tables are parsed** inside a marked region v1 — header
  row + separator row + data rows, straightforward and already
  battle-tested prior art in this repo (`docs_lint.py` and
  `publish_wiki.py` both already do line-oriented markdown parsing without
  a heavyweight AST library; this follows the same lightweight-regex
  philosophy rather than introducing a full markdown-table-parsing
  dependency for one narrow job). Output shape: `{extract: "catalog-status", headers: [...], rows: [[...], ...]}`, written to
  `frontend/src/common/generated/docsData/catalog-status.json`.
- **A broken or missing marker is a hard build error**, exactly
  `publish_wiki.py`'s own link-resolution-error philosophy (fail the
  publish, never ship a wrong or empty page silently): an `extracts` entry
  in the map naming a marker that doesn't exist in the source file, a
  `<!-- DATA-EXTRACT: x -->` with no matching `<!-- END DATA-EXTRACT -->`,
  or a marked region that isn't a well-formed markdown table (per the
  narrow v1 parser above) all fail `generate-docs-data.js` with a clear
  message naming the doc, the extract name, and what's wrong — the same
  `::error::`-annotated, non-zero-exit convention `publish_wiki.py`
  already uses.
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
(rerunning with no doc changes produces byte-identical output — both
`generate-docs-data.js` and the new site-page build step must hold this
property the same way `publish_wiki.py` does), lint-guarded (see below),
fires on merge to `master`.

**What's genuinely new, not just "the same pipeline again"**:

1. `.github/workflows/deploy-frontend.yml`'s trigger `paths:` filter
   currently reads `frontend/**` only — **this must be extended** to
   include at minimum `docs/**` (or, more precisely, every path that could
   change a `site`/`data`-targeted doc or the map itself) plus
   `.github/wiki-publish-map.json`, mirroring `docs-wiki-publish.yml`'s own
   trigger shape exactly. Without this, a `docs/`-only PR would merge and
   the wiki would regenerate (existing pipeline) while the site silently
   would not — the "everything updates per-merge" goal in the task's own
   stated intent fails quietly unless this specific trigger gap is closed.
   Flagged concretely rather than assumed away, since it was found by
   reading the actual workflow file, not inferred.
2. **`generate-docs-data.js` runs as part of `npm run build` itself**
   (a new step ahead of `next build` in `package.json`'s `build` script,
   or a `prebuild` script Next.js/npm already runs automatically before
   `build` — either works; `prebuild` is the more idiomatic npm hook and
   avoids editing the `build` script's own command string), **not**
   `postinstall` — `postinstall` only fires on dependency changes, and
   `docs/` changing has nothing to do with `npm install`. This is a
   deliberate divergence from the keyrune precedent's exact trigger, even
   though the output-location convention (`generated/`, gitignored) is
   kept identical.
3. **`docs_lint.py` already runs on every PR touching `docs/**`** — no change needed there, but its scope should extend to catch one new failure class for free: a `docs-wiki-publish.yml`-style dry run of `generate-docs-data.js`(or the script itself, run with a`--check`/no-write mode) added to CI on the same trigger, so a broken marker fails the PR check *before* merge, not only at the post-merge build step. This mirrors `docs-wiki-publish.yml`'s own posture (`publish_wiki.py`'s link-resolution errors currently only surface at
   the post-merge publish step, not pre-merge — an existing, accepted gap
   in the wiki pipeline this proposal doesn't need to fix, but shouldn't
   quietly repeat if a pre-merge check is cheap to add here).
4. **Full sequence once built**: PR touching `docs/**` merges to
   `master` → `docs-wiki-publish.yml` regenerates the wiki (unchanged,
   existing) → `deploy-frontend.yml` fires (newly triggered by the `docs/**`
   path per item 1) → `npm ci` → `prebuild` runs `generate-docs-data.js`
   (fails the whole build on a broken marker, per §3) → `next build`
   statically renders every `site`-targeted doc via `getStaticProps`
   (§1a) and every component that imports a `data` extract picks up the
   freshly regenerated JSON automatically, since it's a plain build-time
   `import` → `actions/upload-pages-artifact` + `deploy-pages`, identical
   to today. One Pages build, two publish targets (wiki, site) both
   current as of the same merge — matching the task's stated goal exactly,
   contingent on item 1's trigger fix actually landing.

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

**PR-I-1 (this pass) — shipped**: `.github/wiki-publish-map.json`'s schema
extended with `targets`/`sitePath` per §2 (every existing entry given an
explicit `targets: ["wiki"]`, `docs/overview.md` given
`targets: ["wiki", "site"], "sitePath": "/guide"` — the ONE doc this pass
proves the mechanism against, per the owner's own scope, not a wider
rollout). `frontend/scripts/generate-docs-site.js`: the §1(a) link-rewrite
mechanism, reimplemented in JS against `marked` (the open library-choice
call, resolved) rather than shared with `publish_wiki.py`'s Python — see
the script's own header comment for why that's a deliberate, precedented
divergence from this doc's original "shared refactor" framing, not an
oversight. `frontend/src/pages/guide/[[...slug]].tsx`: the SSG route (the
open `/docs` vs. `/guide` naming call, resolved as `/guide`), wired via a
new `prebuild` npm script (not `postinstall`, exactly per §4's reasoning).
`.github/workflows/deploy-frontend.yml`'s trigger `paths:` extended with
`docs/**` and the map file, per §4 item 1. Verified end-to-end: `npm run build` produces a real `/guide` page (title "Overview — ProxyPrints
Guide", real HTML body, zero new lint/type errors) whose links exercise
all three resolution branches this spec's §1(a) called for — a wiki-only
target (`theory.md` → the external wiki URL), a real-but-unmapped file
(`README.md` → a GitHub blob URL) — confirmed by inspecting the actual
built output, not assumed from the script's logic alone. The one branch
`overview.md` doesn't happen to exercise is a link to ANOTHER site-targeted
page, since it's currently the only one — untested for lack of a second
site page to link to, not skipped.

**Not yet built** (concrete next steps per the owner's staged order, not
silently dropped):

1. **§1(b)/§3 — data extracts.** `frontend/scripts/generate-docs-data.js`
   doesn't exist yet (still the ALLOWLIST-flagged path in `docs_lint.py`).
   Waits on PR-I-2+'s source restructures per §0 — building the extractor
   ahead of a real marked-table source to extract would mean testing it
   against nothing real.
2. **Widening §2's site-target list** beyond `overview.md` — `user-guide.md`,
   `self-hosting.md`, `theory.md` per this doc's own proposed initial
   mapping — deliberately deferred, per "prove the plumbing before
   widening it."
3. **A pre-merge CI check for the site-page mechanism** (mirroring
   `docs_lint.py`'s pre-merge posture rather than only failing at the
   post-merge `deploy-frontend.yml` build) — not built this pass; the
   existing wiki pipeline has this same accepted gap (§4's own text notes
   `publish_wiki.py`'s link-resolution errors also only surface post-merge)
   and PR-I-1 doesn't widen that gap, just doesn't close it either. Worth
   revisiting once §1(b) exists and there's more than one doc's worth of
   links to break.
4. **A nav link to `/guide`** — no entry was added to `Navbar.tsx`; the
   route works and is reachable by direct URL, but isn't discoverable from
   the site's own chrome yet. Left out deliberately (a nav change is a
   real, visible UX decision this pass's "prove the plumbing" scope didn't
   ask for) rather than added silently.
