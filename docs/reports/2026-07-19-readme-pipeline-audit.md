```
TASK: README-into-the-docs-pipeline audit (Proposal I follow-on) — branch
proposal-i-readme-audit-cvq14g — PR #117 (open, awaiting review)

WHAT SHIPPED:
1. CONTENT AUDIT — read readme.md as it stands, produced a 7-row merge map
   in docs/proposals/proposal-i-readme-pipeline.md §1: header/logo/tagline
   (stale, remove — seeded from docs/wiki-home-intro.md), CI badges (stale
   but mechanically fixable — verified desktop-tool-ci/web-ci/
   cloudflare-workers-ci workflow names genuinely match this repo's own
   .github/workflows/ files), releases/downloads badge (open question —
   verified via list_releases that this repo has zero GitHub releases, so
   the badge points at nothing real, not just a stale URL), Buy Me A
   Coffee (stale, remove), sponsors/SignPath mention (open question, NOT
   simply stale — verified SignPath.io code-signing is genuinely live in
   desktop-tool-ci.yml via signpath/github-action-submit-signing-request@v2),
   Code Signing Policy section (stale, remove/replace), documentation→wiki
   link (stale, mechanical replace).
2. ARCHITECTURE (post-review, not built) — §2 sketches a third `readme`
   emit mode on the existing single-transform pipeline, assembling
   readme.md from marked source regions in docs/ via the same marker
   mechanics as site extraction. Generated AND COMMITTED (unlike the
   gitignored site emit) since GitHub renders readme.md directly with no
   build step; correctness gate is a CI parity check (diff emit vs.
   committed file), same pattern as the existing docs-lint parity checks.
3. NON-NEGOTIABLES — §3 confirms LICENSE.md (GPL-3.0) and
   frontend/package.json's "license": "GPL-3.0-only" both exist but
   neither is currently referenced from readme.md — a real gap the
   eventual restructure closes, not a new requirement invented here.
4. AUDIENCE fit — §4 checked readme.md's actual content against the
   user-facing-belongs-on-site flag from Proposal I's (not-yet-built)
   audience routing; found zero end-user-facing content in the current
   file, so nothing needs to move to the site.
   Cross-links added: proposal-i-docs-as-site-source.md gained a "not yet
   built" item 4 pointing at this doc; docs/README.md's Plans & proposals
   table gained a row (Status: HOLD).

DEVIATIONS: none — followed the 4-point instruction as given. Per its own
"DELIVERABLE at HOLD" line, no restructure of readme.md itself was
started; this PR is audit + map only.

VERIFICATION: python3 .github/scripts/docs_lint.py — clean. npx
prettier@2.7.1 --check on all three touched files — clean (one --write
pass needed on the new file before the check passed). No code changed, so
no build/test suite run was applicable.

OPEN ITEMS / DECISIONS NEEDED (from the audit doc's own closing list):
1. Releases/downloads badge — keep pointing at a currently-empty releases
   page, or remove until releases exist?
2. SignPath enrollment status for this fork specifically (owner-only
   knowledge — CI config alone can't confirm enrollment, only that the
   step exists).
3. Is a fork-specific code-signing policy worth writing, or drop the
   section entirely?
4. Exact final wording for the replacement header/tagline/badges.
5. The `readme` emit mode's CLI shape and source-region marker layout —
   sketched in §2, not settled.

CORRECTION TO A PRIOR REPORT: PR #112 (PR-I-1 single-transform
restructure) was last reported to you as "open, awaiting review." That is
now stale — verified via `git log --oneline --all | grep -i 112` (commit
efa71eb9 "PR-I-1 RESTRUCTURE: single-transform architecture (owner call)
(#112)") and `git merge-base --is-ancestor efa71eb9 HEAD` returning "IS
ancestor" against current master tip. PR #112 is MERGED, not open. This
was discovered incidentally during this task's own git verification step,
not through any new action on #112 itself.

LIVE STATE: branch proposal-i-readme-audit-cvq14g pushed to origin, PR
#117 open against master, unmerged, awaiting owner review — no CI
required (docs-only diff, no code touched). PR #112 confirmed merged
(see correction above). This report committed to report-relay-cvq14g and
pushed.
```
