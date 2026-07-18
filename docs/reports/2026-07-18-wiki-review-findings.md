```
TASK: Owner-initiated wiki review findings — two fixes + a targeted
staleness mini-pass. Branch claude/wiki-review-findings, commits
ce20eef2 (item 1) + 49410c15 (items 2+3), pushed to origin. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/79 (open,
base master).

Note on branch history: this work was originally developed on
claude/ai-to-machine-terminology (per the task's "one PR is fine"
instruction, coordinating with the already-open PR #76). PR #76 merged
mid-task (squash commit 0c7cf8ed). Per CLAUDE.md's merged-PR handling
convention, restarted onto a fresh branch off latest master
(claude/wiki-review-findings) rather than stacking on already-merged
history — item 1's work (uncommitted at the time) was stashed, carried
across, and verified clean against the new base before continuing.

WHAT SHIPPED, per the three numbered items:

1. **Publish-script link bug** (`.github/scripts/publish_wiki.py`,
   `.github/wiki-publish-map.json`): GitHub wiki's native `[[...]]`
   auto-linking was reinterpreting our own docs/ `[[file.md]]`
   convention out from under us on every generated page —
   `[[../troubleshooting.md]]` (parent-relative, from docs/features/*)
   became a dead literal slug "..-troubleshooting.md"; `[[printing-tags.md]]`
   linked the raw docs/ filename casing, not the published page name
   "Printing-Tags". Both bugs were visible live on the Catalog-Completion-Plan
   wiki page, per the owner's report.

   Fix: every internal link (both `[[wiki]]` and markdown `[text](path)`
   styles) is now resolved against its SOURCE file's real repo path,
   then mapped through wiki-publish-map.json — a target that's itself a
   published page becomes a same-wiki link using its REAL page name; a
   target that exists in the repo but isn't published becomes an
   absolute GitHub blob URL (never a guessed wiki slug); a target
   resolving to neither a wiki page nor a real repo file is a hard
   publish error rather than a silently-broken link. Fenced code blocks
   and inline code spans are protected from rewriting (critical for
   docs like documentation-process.md, which use `[[...]]`/`[text](path)`
   as illustrative examples inside backticks). docs_lint.py explicitly
   cannot catch this class of bug — it only checks that a link resolves
   inside the docs/ tree itself, not what the wiki-publish transform
   turns it into afterward; that's now a self-check inside the publish
   script itself, documented in its own module docstring.

   Side effect of dogfooding the fix: found `docs/documentation-process.md`
   and `docs/upstreaming/upstream-wiki-drift.md` listed in docs/README.md's
   index but entirely missing from wiki-publish-map.json — added both.

   Verified against real cloned wiki data: both original bugs fixed,
   idempotency confirmed (empty `git status --porcelain` on a clean
   second run), fail-fast error path confirmed against a deliberately
   injected broken link, no regression on any of the ~20 already-working
   published pages.

2. **catalog-completion-plan.md status update**: Part 3's heading
   ("built, HOLD #P3 — write pass pending" → "write pass complete,
   merged 2026-07-18"). Status section's Part 3 entry now records:
   `run_id=20260718T145157-a12b1387`, 13,275 total votes live (7,131
   CardArtistVote + 6,144 CardTagVote) — phash exactly 750 recovered
   (→1,500 combined votes), d=0 siblings exactly 987 artist votes, OCR
   4,804/4,804 recovered, fallback 590/595 recovered (→10,788 combined
   OCR+fallback votes, within the ≤11,546-vote ceiling) — all hard
   bounds passed. Zero-resolution assertion re-run at the FULL 7,124-card
   population (not just the command's own 14-card sample gate): 0
   violations. Pointer added to
   docs/reports/2026-07-18-part3-write-pass-complete.md for full detail.
   Filled the dangling "see the follow-up entry below for the completed
   numbers" reference with the actual OCR/fallback figures. Replaced the
   now-false "HOLD #P3 stands: no vote has been written to the live
   database" language with the completed-pass summary above. Part 4's
   heading gained "(confirmed unstarted 2026-07-18; HOLD #B prep queued)".

3. **Targeted staleness mini-pass** (not a full re-sweep — checked the
   minimum list the task named):
   - `proposal-b-bleed-normalization.md`: top summary line was
     self-contradictory — it listed "the prior-resolution batch fetch"
     as remaining work in the same paragraph where the file's own
     "Shipped vs. not yet built" section, two sections below, already
     says that exact batch fetch shipped as PR-1 (#72). Fixed the top
     line to match.
   - `proposal-c-context-menu-restyle.md`: checked — already accurate
     ("built this pass" / "Shipped", branch cited, matches merged PR #67
     and confirmed the named files exist on master). No edit needed.
   - `proposal-g-user-accounts-saved-decks.md`: Decision 1's build-order
     queue note ("after ... E-1, E-2, the Level-2 grid fix, the audit
     pass, GIS error UX ... and Proposal B's in-flight work finishes")
     was written when those were all still pending. Checked each against
     master's merge log: E-1 (#61), E-2 (#62), Level-2 grid fix (#63),
     audit pass (#64), GIS error UX (#65), Proposal B core (#66) + PR-1
     (#72), Proposal C part (a) (#67) — all merged. Added a dated note
     that the queue has fully cleared, nothing left ahead of G.
   - `docs/README.md`: the "Plans & proposals" table listed only
     proposal-f and proposal-g (both HOLD) — proposal-b.md and
     proposal-c.md exist as dedicated docs but were absent from the
     table entirely, contradicting the section's own stated policy
     ("This list is only the ones that got a dedicated doc" implies
     dedicated docs get a row). Added both, with accurate current
     status (BUILDING for B — core + PR-1 shipped, PR-2/PR-3 remain;
     PARTIAL for C — part (a) shipped, part (b) still HOLD).
   - `printing-tags.md`: checked Stage 8 status — the file correctly
     defers all Stage 8+ status to catalog-completion-plan.md ("this
     file is the live source of truth for it") and doesn't itself
     assert anything about the write pass. No changes needed.
   - `vote-system.md`: checked for AI-terminology or merged-PR
     staleness relevant to today's events — none found. Its one
     point-in-time fact (upstream/master position "as of 2026-07-13")
     is self-flagged as needing live re-verification before acting on
     it, not something this pass should silently update. No changes.

DEVIATIONS: branch restarted mid-task from claude/ai-to-machine-terminology
to claude/wiki-review-findings after PR #76 merged (see note above) —
not a deviation from the task's content, but from its originally-assumed
landing spot; the task's "one PR is fine" intent is preserved (all three
items land in one PR, #79), just not the same PR number originally
anticipated, since #76 closed out from under it.

VERIFICATION: `python3 .github/scripts/docs_lint.py` clean across all of
docs/ after every edit. `npx prettier@2.7.1 --check` clean across every
touched Markdown file (docs/README.md needed one `--write` pass for
table-column realignment after adding two rows, reverified clean).
publish_wiki.py re-tested against real cloned wiki data after the
branch restart to confirm nothing was lost in the stash/pop. No live
wiki-publish run yet — that fires automatically on merge; verification
of the live Catalog-Completion-Plan page is the next step once #79 merges.

OPEN ITEMS / DECISIONS NEEDED: none blocking.

LIVE STATE: branch claude/wiki-review-findings pushed to origin, PR #79
open against master. On merge, docs-wiki-publish.yml fires automatically
(this PR touches docs/**) — will verify the Catalog-Completion-Plan wiki
page shows both the fixed links and the updated Part 3 status once
merged, and report back with the live page URL.
```
