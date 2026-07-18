```
TASK: License decision applied to public federation export v1 spec —
PR #92 (https://github.com/ProxyPrints/ProxyPrints.github.io/pull/92),
branch `federation-public-export-v1-spec`, commit `16046186`. No PR
against upstream. Nothing built.

WHAT SHIPPED:
1. §5 rewritten from "OWNER DECISION, not made here" to "DECIDED:
   ODbL 1.0", with the reasoning captured plainly: reciprocity chosen
   over CC0's maximal-adoption posture, accepting some consumer
   friction for a growing open commons.
2. Three consumer-calming clarifications added, stated as true-under-
   ODbL facts, not caveats: (a) using the data / displaying results in
   an app ("produced works") needs only attribution, never opens your
   code; (b) share-alike applies only to publicly redistributed
   derivative databases, internal use unencumbered; (c) exact
   attribution string ("Contains data from ProxyPrints.ca, made
   available under ODbL" + link).
3. One-line non-legal reciprocity invitation added, explicitly
   separated from the license's actual legal requirements.
4. Top-of-doc status updated: "SPEC DECIDED. Spec-doc hold lifted;
   BUILD hold remains" — the two holds now explicitly distinguished
   rather than one blanket HOLD label.
5. PR #92 title updated to reflect decided/ready status; a PR comment
   posted summarizing the change and explicitly handing off to
   whichever session/process owns the merge queue — this session did
   NOT attempt to merge it directly, per this repo's standing
   `gh pr merge` convention (CLAUDE.md).

DEVIATIONS from spec, each with reasoning:
- Found and removed a stale leftover sentence ("Recommendation left
  unstated deliberately — flag, don't choose...") at the end of the old
  §5 that would have directly contradicted the new "DECIDED" framing
  had it survived the edit — caught by rereading the full section after
  editing, not assumed clean from the diff alone.
- Master had moved since PR #92 opened, and another PR had added its
  own new row to the exact same `docs/README.md` "Plans & proposals"
  table my earlier commit also added a row to — a real conflict, not
  hypothetical (confirmed via `git diff` before merging, not assumed).
  Resolved by merging `origin/master` into the PR branch (not a rebase
  + force-push, per the standing no-routine-force-push rule) and
  combining both new table rows by hand.
- Kept a brief CC0-vs-ODbL comparison in §5 rather than deleting all
  mention of CC0 once ODbL was decided — the task's own reasoning
  ("chosen deliberately over CC0's maximal-adoption posture") is
  inherently comparative, and a reader landing on this section cold
  benefits from knowing what was traded away, not just what was picked.

VERIFICATION: what ran, with results —
- Re-ran `.github/scripts/docs_lint.py` after the merge (its own
  content had also changed on master since PR #92 opened — checked the
  diff, confirmed it was an unrelated allowlist-entry swap, not
  something that would affect this doc) — clean both before and after
  the §5 rewrite.
- Reread the entire §5 section top-to-bottom after editing to catch
  internal contradictions (found and fixed the stale "flag, don't
  choose" leftover this way) — not just spot-checked the specific
  hunks that changed.
- Grepped the whole doc for every other "§5" cross-reference and the
  top-of-doc status paragraph to confirm nothing else described the
  license as still-open after the rewrite.
- `git diff --name-only --diff-filter=U` after the master-merge —
  confirmed exactly one file conflicted (`docs/README.md`) and that it
  resolved clean with no leftover conflict markers, not assumed from
  the merge command's exit alone.

OPEN ITEMS / DECISIONS NEEDED:
1. Whoever/whatever owns the merge queue: PR #92 is ready — title and
   PR comment both reflect this. No further owner input needed on the
   spec-doc itself.
2. Owner: the BUILD hold is unchanged and separate — still needs an
   explicit, separate green-light before any implementation
   (management command, signing, cron, tooling) begins.

LIVE STATE: PR #92 open, title updated, comment posted, branch
`federation-public-export-v1-spec` at `16046186` — merged with current
`master`, conflict resolved, docs-lint clean. Not merged by this
session. `upstream-feat-local-file-source` and the upstream-ladder CI
workflows remain separately unmerged and unchanged. Session holding.
```
