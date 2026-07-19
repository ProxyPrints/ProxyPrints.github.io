```
TASK: README restructure GO — readme emit mode build, per owner decisions
on PR #117's five open items (+ a desktop-tool-scope amendment) — branch
readme-emit-mode-cvq14g — PR #119 (open, awaiting review)

WHAT SHIPPED:
1. Releases/downloads badge — REMOVED from readme.md (zero releases
   exist per the audit's own verification).
2. Sponsors/SignPath — REMOVED. Per the amendment (ProxyPrints is
   web-only, does not ship the desktop tool), scope widened beyond just
   the SignPath credit: the desktop-tool-ci badge, the "check the
   Releases tab" download instruction, and the Sponsors section are all
   removed. One line now points to upstream's project
   (chilli-axe/mpc-autofill) for anyone looking for the desktop tool.
   The desktop-tool-ci.yml workflow itself is untouched — README scope
   only, per the amendment's own wording.
3. Code Signing Policy section — REMOVED entirely.
4. Header/tagline — REPLACED, seeded verbatim from
   docs/wiki-home-intro.md's existing identity/lineage paragraph (the
   ratified voice specified — no new copy written).
5. Emit mode — BUILT: new .github/scripts/publish_readme.py assembles
   readme.md (repo root) from README-REGION-marked prose regions:
   `identity` in docs/wiki-home-intro.md (existing content, now
   marker-wrapped, unchanged), and `license` /
   `documentation-pointer` / `desktop-tool-pointer` in a new
   docs/readme-sections.md. web-ci/cloudflare-workers-ci CI badges
   repointed to this repo (desktop-tool-ci badge dropped per item 2). A
   GPL-3 license notice was added — a real gap the audit found, closed
   as instructed (LICENSE.md exists but was never referenced from
   readme.md before this). Documentation link repointed to this fork's
   own wiki. Generated AND COMMITTED (not gitignored like the site
   emit) — readme.md has no build step between a commit and a reader
   seeing it. docs-lint.yml gained a readme-parity job: runs
   publish_readme.py's own unit tests, then regenerates readme.md into
   a scratch copy and fails the PR if it differs from the committed
   file.

DEVIATIONS (both documented in proposal-i-readme-pipeline.md §5, found
while building, not pre-planned):
1. Marker name is `README-REGION`, not the `DATA-EXTRACT` name the
   audit's §2 sketch proposed reusing. DATA-EXTRACT's own contract
   (proposal-i-docs-as-site-source.md §3) is explicitly table-only;
   these are prose regions, so reusing that name would misdescribe what
   gets parsed. Same mechanics (named HTML-comment pairs, hard error on
   a missing/unterminated marker), different, honestly-labeled name.
2. No link-rewriting is performed at all, where §2's sketch implied
   reusing publish_wiki.py's transform machinery. readme.md lives at
   the repo root; its source regions live in docs/. A relative link
   correct when a region is linted in place (relative to docs/) would
   resolve to something else entirely once copied verbatim into the
   root file. Rather than teach the script a second, output-relative
   link-resolution mode for a 3-region file, every region author uses
   an absolute https://github.com/... URL for any file reference — a
   dedicated test (test_no_relative_file_links_in_source_regions)
   guards this.
3. PR #117 (the audit) was NOT merged by this session — per this
   repo's standing no-self-merge policy (gh pr merge / the merge API
   is reserved for the owner/merge queue, not invoked directly by a
   session even on explicit instruction to "merge PR #117 first"). This
   build branch was instead built by cherry-picking #117's own commit
   onto current master, so the build didn't block on the literal merge.
   #117 merged independently (by the owner or the queue) partway through
   this task — confirmed live via `git fetch` showing it landed on
   master as commit f9c72f5e while this branch was in progress; rebasing
   onto the new master tip cleanly dropped the now-duplicate commit,
   leaving only this PR's own build commit. No conflict, no force-push
   needed.

VERIFICATION:
- Two consecutive runs of publish_readme.py produce byte-identical
  output (idempotent) — checked after every content change, including
  after the final prettier pass.
- python3 .github/scripts/docs_lint.py — clean.
- python3 .github/scripts/tests/test_publish_readme.py — 8/8 passing
  (region extraction, both hard-error paths, unlisted-region-ignored,
  a real-repo build-matches-committed-file parity check, idempotency,
  the no-relative-links guard).
- python3 .github/scripts/tests/test_publish_wiki_link_rewrite.py —
  4/4 passing, unaffected by this change.
- Real wiki publish (publish_wiki.py . <scratch dir>) still succeeds
  with the new marker comments present in wiki-home-intro.md — exit 0,
  Home.md generated correctly. GitHub hides HTML comments when
  rendering both normal repo pages and wiki pages, so the wiki Home
  page's visible content is unchanged by the added markers.
- black 22.8.0 / isort 5.12.0 / ruff 0.0.257 — clean on both new Python
  files.
- prettier@2.7.1 --check — clean on every touched markdown/YAML file,
  INCLUDING the generated readme.md itself: publish_readme.py's raw
  output was adjusted (one blank-line fix in the header) so the script's
  own output matches prettier's expected formatting exactly — the
  readme-parity CI check therefore compares like-for-like, not a
  pre-formatted committed file against unformatted raw script output.
- Rendered readme.md content eyeballed directly (full diff pasted into
  the PR body) — every owner decision item is visibly present/absent as
  specified.
- Deferred: no live GitHub Actions run (docs-lint.yml's new
  readme-parity job hasn't executed in CI yet — first real run happens
  when PR #119's checks fire).

OPEN ITEMS / DECISIONS NEEDED: none blocking — all five original open
items plus the desktop-tool-scope amendment are resolved and built. PR
#119 itself is the review gate now (owner review before merge, same as
every other PR in this repo).

LIVE STATE: branch readme-emit-mode-cvq14g pushed to origin, PR #119
open against master, unmerged, awaiting owner review — CI (docs-lint.yml
including the new readme-parity job) will run on the PR automatically.
PR #117 (the audit) is CONFIRMED MERGED (commit f9c72f5e on master,
discovered live via git fetch during this task, not assumed) — this is
itself new information since the prior report characterized #117 as
"open, awaiting review." This report committed to report-relay-cvq14g
and pushed.
```
