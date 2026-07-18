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
  ("Understanding the system" / "Operating it"). Update the mapping file
  whenever `docs/README.md`'s index changes — the publish workflow does
  not parse `docs/README.md`'s prose, by design (parsing markdown
  structure at runtime is fragile; a hand-maintained mapping is not).
- **What's excluded, always**: `docs/proposals/` (drafts/HOLD specs — not
  yet real, shouldn't read as if they are), `docs/reports/` (relayed
  session artifacts, not reference material), `docs/audits/` (point-in-time
  findings, same reasoning).
- **Legacy pages**: a few wiki pages (`User-Guide`, `Instance-Admin-Guide`,
  `Research-and-Proofs`, as of this writing) predate this system and have
  no `docs/` source yet. They're listed in the mapping's `legacy_pages`
  purely so they stay linked from the generated Home/Sidebar instead of
  going dark — the publish workflow never touches them (it only ever
  deletes a page it can prove it generated, by checking for that page's
  own marker). Migrating them into `docs/` (or deciding to keep them
  permanently hand-maintained) is a standing open item, not something this
  system resolves on its own.
- **Mechanism**: [`.github/workflows/docs-wiki-publish.yml`](../.github/workflows/docs-wiki-publish.yml)
  together with [`.github/scripts/publish_wiki.py`](../.github/scripts/publish_wiki.py).
  Requires a `WIKI_PUSH_TOKEN` repo secret (a classic PAT — GitHub wikis
  are a separate git repo the default `GITHUB_TOKEN` can't push to); see
  that workflow's own header for exact setup steps.

## Lint catches mechanical rot

[`docs-lint.yml`](../.github/workflows/docs-lint.yml) runs
[`docs_lint.py`](../.github/scripts/docs_lint.py) on every PR touching
`docs/**` and weekly regardless. It checks two things, mechanically:

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
