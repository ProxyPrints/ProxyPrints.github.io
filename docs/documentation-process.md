# Documentation process

The standing system this repo's documentation runs on, in one page. If
you're wondering "where does X go" or "why does the wiki look like that,"
this is the answer.

## The core rule: docs/ is source of truth, the wiki is generated

Everything durable about this fork lives in `docs/` and is committed
alongside the code it describes. The GitHub wiki
([ProxyPrints.github.io.wiki](https://github.com/ProxyPrints/ProxyPrints.github.io/wiki))
is a **generated view** of a curated subset of `docs/` — never a second
place to write documentation.

**Never hand-edit a wiki page this system manages.** Every generated page
carries a `<!-- GENERATED PAGE -->` marker at the top saying so, and naming
its `docs/` source. Edit the source instead; the page regenerates on the
next push to `master` that touches `docs/**` (or on-demand via
`workflow_dispatch`). A hand-edit to a generated page survives only until
the next regeneration, then silently vanishes — not a data-loss risk
(the source is what's real) but a wasted edit.

- **What's published**: exactly the files listed in
  [`.github/wiki-publish-map.json`](../.github/wiki-publish-map.json), a
  hand-curated mapping mirroring `docs/README.md`'s own audience groups
  ("Understanding the system" / "Using it" / "Operating it"). Update the
  mapping file whenever `docs/README.md`'s index changes — the publish
  workflow does not parse `docs/README.md`'s prose, by design (parsing
  markdown structure at runtime is fragile; a hand-maintained mapping is
  not).
- **Renames update the mapping in the same PR.** If a published doc's
  source path or its wiki page name changes, update
  `wiki-publish-map.json` in that same PR — a wiki page's URL is its
  identity, and **GitHub wikis have no redirects**: renaming a page in the
  mapping doesn't move the old URL, it abandons it. Prefer a stable wiki
  name once picked, even across a source-file rename or migration — e.g.
  `docs/self-hosting.md` still publishes as the wiki's existing
  `Instance-Admin-Guide` page (not a new `Self-Hosting` page) specifically
  so nothing that already links to it breaks.
- **What's excluded, always**: `docs/proposals/` (drafts/HOLD specs — not
  yet real, shouldn't read as if they are), `docs/reports/` (relayed
  session artifacts, not reference material), `docs/audits/` (point-in-time
  findings, same reasoning).
- **`pointer_pages`**: a page whose content has fully moved elsewhere (e.g.
  `Research-and-Proofs`, once its own placeholder, now superseded by
  `docs/theory.md`) becomes a small generated stub linking to the page
  that replaced it, rather than being deleted — same reasoning as the
  rename rule above: the URL stays alive even though the content doesn't
  live there anymore.
- **`legacy_pages`**: any wiki page that predates this system and has no
  `docs/` source yet goes here so it stays linked from the generated
  Home/Sidebar instead of going dark. Empty as of this writing — the 3
  pages that used to sit here (`User-Guide`, `Instance-Admin-Guide`,
  `Research-and-Proofs`) are now either migrated into `docs/` (the first
  two) or a `pointer_pages` entry (the third). The publish workflow never
  touches a page outside all three lists — it only ever deletes a page it
  can prove it generated, by checking for that page's own marker.
- **Mechanism**: [`.github/workflows/docs-wiki-publish.yml`](../.github/workflows/docs-wiki-publish.yml)
  together with [`.github/scripts/publish_wiki.py`](../.github/scripts/publish_wiki.py).
  Requires a `WIKI_PUSH_TOKEN` repo secret (a classic PAT — GitHub wikis
  are a separate git repo the default `GITHUB_TOKEN` can't push to); see
  that workflow's own header for exact setup steps.

## The site is a second generated target, same source, ONE transform

Per [`proposals/proposal-i-docs-as-site-source.md`](proposals/proposal-i-docs-as-site-source.md)
(APPROVED, staged build — PR-I-1 shipped, PR-I-2+ not yet started), the
same `docs/` files can also publish as real pages on the site itself, at
`/guide`, via a second per-page target (`"site"` in `wiki-publish-map.json`'s
`targets` array) alongside — not instead of — the existing wiki target.

**Single-transform architecture**: `.github/scripts/publish_wiki.py` is the
ONLY place link-rewrite logic exists, for both outputs. Its
`transform_links()`/`rewrite_link()` take an optional `repo_to_site` map —
absent (the default), it's exactly the original wiki-only 2-way resolution
(same-wiki link or GitHub blob URL); given a real map, it adds a 3rd
resolution branch (a link to a `"site"`-targeted page becomes that page's
own route) and changes how a wiki-only target resolves (an ABSOLUTE wiki
URL rather than a same-repo link, since the site itself doesn't host that
page). `.github/scripts/publish_site.py`, a thin sibling script, imports
this shared logic (no reimplementation) and writes pre-transformed
markdown for every `"site"`-targeted page into `frontend/generated-docs/`
(gitignored). `frontend/src/pages/guide/[[...slug]].tsx` has no transform
logic of its own — it only reads that markdown and renders it to HTML via
a JS markdown library at Next.js build time (a rendering concern, kept
separate from the transform concern above). Run locally via
`npm run docs:generate` (from `frontend/`); `next build`/`next dev` degrade
gracefully with a console warning, not a crash, if that hasn't been run
yet — `/guide` simply has no pages until it has.

Live for two docs so far — `docs/overview.md` (`/guide`) and
`docs/user-guide.md` (`/guide/using-it`, added as a widening pass after
PR-I-1); `docs/self-hosting.md` and `docs/theory.md` remain per this
proposal's proposed initial mapping. Widening the list is normal,
low-risk work (add `"site"` + `sitePath` to a `wiki-publish-map.json`
entry). A `Nav.Link` to `/guide` in `frontend/src/features/ui/Navbar.tsx`
ships alongside this widening (ungated, same as `Download` — `/guide` has
no backend dependency), closing proposal-i's "not yet built" item 3.

**Link-rewrite parity fixtures**: since one function now serves two output
shapes (wiki mode vs. site mode) rather than two separate implementations,
[`.github/scripts/tests/test_publish_wiki_link_rewrite.py`](../.github/scripts/tests/test_publish_wiki_link_rewrite.py)
runs a shared fixture set
([`.github/scripts/testdata/link_rewrite/cases.json`](../.github/scripts/testdata/link_rewrite/cases.json))
through both modes and pins which cases are expected to produce identical
output versus legitimately diverge by mode — a future edge-case fix that
doesn't also update the fixture fails this test, rather than silently
diverging. Same rationale as the federation hash tool's permanent parity
test.

## `readme.md` is a third generated target — assembled, not transformed

Per [`proposals/proposal-i-readme-pipeline.md`](proposals/proposal-i-readme-pipeline.md)
(SHIPPED), the repo-root `readme.md` is generated by a third script,
[`.github/scripts/publish_readme.py`](../.github/scripts/publish_readme.py)
— but it's a different kind of generation from the wiki/site targets
above. Those two TRANSFORM whole `docs/` pages (link rewriting, one page
in → one page out). `readme.md` ASSEMBLES one output file from several
small, hand-authored prose regions scattered across `docs/`, each marked:

```markdown
<!-- README-REGION: license -->

...

<!-- END README-REGION -->
```

Deliberately a different marker name from `DATA-EXTRACT` (the site
pipeline's own extraction contract, table-only by design) — these regions
are prose, and reusing the table-only contract's name would misdescribe
what gets parsed. A marked region is copied **verbatim, never
link-rewritten**: `readme.md` lives at the repo root, not in `docs/`, so
a relative link correct for a region's actual location in `docs/` would
resolve to something else entirely once copied into the root file. Every
region therefore uses an absolute GitHub URL for any file reference —
guarded by a dedicated test
(`.github/scripts/tests/test_publish_readme.py`) — rather than teaching
the script a second, output-relative link-resolution mode.

**Generated AND COMMITTED, not gitignored** — the one real structural
difference from the wiki/site outputs. GitHub renders `readme.md`
directly from the default branch with no build step in between, so the
committed file has to actually be current at all times. The correctness
gate is therefore a CI **parity check**, not a build-time regenerate:
`docs-lint.yml`'s `readme-parity` job reruns `publish_readme.py` into a
scratch copy and fails the PR if it differs from the committed file —
same generate-and-diff shape as the link-rewrite parity job above,
applied to a whole generated file instead of a fixture set.
Regenerating, mechanically, means running the script and committing the
result — no different from hand-editing any other tracked file.

## Lint catches mechanical rot

[`docs-lint.yml`](../.github/workflows/docs-lint.yml) runs
[`docs_lint.py`](../.github/scripts/docs_lint.py) on every PR touching
`docs/**` and weekly regardless. Its original, always-hard checks are two,
mechanical (the interconnection rules below are newer and soft by default):

1. Every `[[wiki-link]]` and markdown `[text](path)` link resolves to a
   real file.
2. Every backtick-quoted, path-shaped reference in prose (e.g.
   `` `frontend/src/features/card/Card.tsx` ``) exists in the repo (or is
   a known-gitignored file, or an explicit allowlist entry with a stated
   reason).

Failures annotate the PR diff. **It never auto-fixes anything** — a
broken link/path is a fact worth a human's one-line correction, not a
silent rewrite.

**Known limitation, stated plainly**: this can only catch _broken_
links/paths. It cannot tell a stale **status claim** ("not yet built" for
something now shipped, a "current stage" claim a later section already
contradicts, a date stamp that's drifted) from a true one — resolving that
requires reading the doc's actual content and cross-checking it against
reality, which is exactly what the next section is for.

## Interconnection lint

The 2026-07-23 owner ruling abolished the letter/number decision-labeling
convention outright ("kill the lettering convention all together ... each
subject should have one document or they should at least reference each
other"). There is no central decisions register and no label grammar:
**a decision lives written out in prose in its own subject doc**, and the
subject doc is the source of truth. `docs_lint.py` enforces that model with
four soft rules on top of the mechanical link/path checks:

1. **No new D-number decision labels.** The abolished convention wrote a
   decision as a bold `D`-number marker or a "decision D-number" phrase (the
   sibling vote-weight decision stream used the same `D`-ledger plus
   `VW`-style refs). The lint flags any such definition-style label
   reintroduced in a living doc — write the decision out in prose instead.
   **Structural enumerations the sweep deliberately kept are NOT decision
   labels and are not flagged**: funnel steps (`F`), requirements (`R`),
   test scenarios (`T`), mappings (`M`/`C`/`S`/`I`/`L`), editor-spec items
   (`E`), file-change rows (`XF`), and license/PR tokens (`GPL-3.0`,
   `PR-5`). A historical aside in the `(formerly '...')` form is allowed;
   the archive buckets below are exempt; and a verbatim, self-declared
   decision-record doc that keeps its labels intentionally is allowlisted
   (today: [`reference/funnel-spec.md`](reference/funnel-spec.md) — the
   living, de-lettered authority for that surface is
   [`features/grid-selector.md`](features/grid-selector.md)).
2. **Orphan check.** Every `docs/*.md` must be reachable from
   [`README.md`](README.md) or [`MANIFEST.md`](MANIFEST.md), transitively,
   via markdown/wiki links or backtick-path references. The record/archive
   buckets index themselves by their own dated-listing convention and are
   excluded: `reports/`, `data/`, `audits/`, `proposals/mockups/`.
3. **Supersession pointer.** A line carrying a `SUPERSEDED`/`SUPERSEDES`
   marker must name what supersedes it (a link, a backtick path, a
   `§`section, a `#`ref, or a self-describing `SUPERSEDED-BY-X` status)
   somewhere in its own paragraph or the next one — so a multi-line
   "HISTORICAL — SUPERSEDED" banner that names its superseder a few lines
   away still passes.
4. **Same-subject cross-reference.** Two `proposals/proposal-<letter>-*.md`
   docs covering the same subject must reference each other — at least one
   direction, so a reader can navigate between them. This is the
   anti-fragmentation guarantee the "one doc per subject, or they reference
   each other" ruling asks for, replacing the old shared-label heuristic.

**Soft by default.** These four rules print as `::warning::` and do **not**
add to the exit code; the original link/path/tether checks are unchanged —
still hard, still counted. The de-lettering sweep (PR #357) has merged and
the whole corpus is now clean under these rules (`--strict` exits 0), so
the lint is **ready to flip to hard-fail at the owner's discretion**: add
`--strict` to [`docs-lint.yml`](../.github/workflows/docs-lint.yml)'s `Run docs lint` step (`python3 .github/scripts/docs_lint.py --strict`) or set
`DOCS_LINT_STRICT=1` in that job's env. In strict mode the same findings
become `::error::` and count toward the exit code. Left soft here so the
supersession/cross-reference heuristics stay warn-only until a maintainer
decides to promote them.

## The judgment coherence pass (quarterly)

Lint catches what's _broken_. It cannot catch what's _wrong but still
resolves_ — a Part header claiming "in progress" for something the same
file's own status section says merged, a cross-reference pointing at a
real file that no longer contains the claimed content, a "known gap"
that's actually long since fixed. That needs a human (or an agent
session) actually reading every doc and checking its claims, on a cadence
loose enough that rot has time to accumulate into something worth a
dedicated pass, but tight enough that it doesn't compound for years.
**Quarterly** is that cadence.

This checklist is derived directly from the first such pass (2026-07-18):

1. **Inventory every file in `docs/`.** For each: is its status language
   (dates, "planned"/"in progress"/"not yet built", "HOLD"/"DRAFT"
   markers) still accurate? Does it have cross-references, and do they
   still point somewhere real? Is it reachable from `CLAUDE.md`'s index
   or `docs/README.md` — or orphaned?
2. **Cross-check every status claim against something real**, not
   against another equally-stale doc: the same file's other sections, a
   sibling doc's own status section, the actual current codebase (grep/
   find for a referenced path or symbol), or `git log` for a cited PR
   number or date. A claim that can't be cheaply verified this way
   (an external PR's live open/closed state, a third party's stated
   intentions) gets flagged for a session with the access to check it —
   never guessed at.
3. **Watch for duplicate or colliding headings** within a long file (an
   anchor collision is a real navigation hazard, easy to miss by reading
   linearly).
4. **Watch for miscategorized content** — an item sitting under "Known
   gaps" that's actually resolved, a bullet under the wrong header
   entirely.
5. **Check `docs/README.md`'s own index for completeness** (every doc in
   a bucket it should be in) and `.github/wiki-publish-map.json` for
   drift from it (the mapping is hand-maintained specifically so this
   check has to be a deliberate step, not something that happens for
   free).
6. **Check `CLAUDE.md`'s flat docs index for parity** with `docs/README.md`
   — both should list the same "current" reference docs; a doc missing
   from one but not the other is exactly the kind of gap this pass
   exists to catch.
7. **Compile a migration/decision list before touching anything
   non-mechanical.** If a wiki-only page has no `docs/` source, or a
   fix would mean rewriting a doc's actual technical content (not just
   its status line or a cross-reference), that's a decision for the
   owner, not something to resolve unilaterally mid-pass.
8. **Fix only what's mechanical**: status lines, cross-references, stale
   paths, miscategorized bullets, duplicate headings. Leave technical
   content — and always leave `docs/theory.md`'s substance — untouched
   unless the fix is explicitly approved as its own, separate piece of
   work.

## Upstream wiki: linked and attributed, never mirrored

[`docs-upstream-wiki-drift.yml`](../.github/workflows/docs-upstream-wiki-drift.yml)
together with [`upstream_wiki_drift.py`](../.github/scripts/upstream_wiki_drift.py)
check weekly whether
[chilli-axe/mpc-autofill's wiki](https://github.com/chilli-axe/mpc-autofill/wiki)
has changed since the last check, and update
[`docs/upstreaming/upstream-wiki-drift.md`](upstreaming/upstream-wiki-drift.md)'s
table in place — which page changed, when, at which upstream commit.

This is **detection only**, deliberately: upstream's wiki text has no
clear license, so nothing from it is ever copied into this repo, in this
workflow or anywhere else. The correct response to a drift-log entry is
always a human decision — read the upstream page, and if it's worth
reflecting here, write **our own words**, linking to and crediting the
upstream page as the source, on review. A drift-log row is a prompt to
look, never content to paste.
