```
TASK: GitHub-native issue board migration — public-repo half. Build
real labels/milestone/issues on ProxyPrints/ProxyPrints.github.io from
the same-day reconciliation sweep's open items. Draft posted for owner
INTAKE confirmation before this migration is treated as the whole
ledger.

WHAT SHIPPED:
- 3 new labels: housekeeping, needs-owner-decision, hold (existing
  default set — bug, documentation, duplicate, enhancement, good first
  issue, help wanted, invalid, question, wontfix — left untouched).
- 1 new milestone: "Backlog cleanup — 2026-07-19 sweep".
- 6 issues, each referencing docs/reports/2026-07-19-reconciliation-sweep.md
  by open-item number rather than re-quoting it:
  - #140 PR #116 blocked on formatting/type-check failure [bug]
  - #141 Classify worktree-finish-upstream-460 [housekeeping]
  - #142 Spot-check report-relay branches before bulk deletion
    [housekeeping, needs-owner-decision]
  - #143 Delete 12 already-merged, no-longer-needed branches
    [housekeeping]
  - #144 Decide fate of 4 unlanded docs + 6 dormant upstream-*
    branches [needs-owner-decision]
  - #145 Lift BUILD hold on federation public-export-v1 spec [hold]

DEVIATIONS: none. Issue count and content map 1:1 to the reconciliation
sweep's 5 numbered open items plus the one standing HOLD item found
separately (#145) — no invented busywork beyond what the sweep already
surfaced.

VERIFICATION: `gh api repos/ProxyPrints/ProxyPrints.github.io/issues`
confirms all 6 issues exist with the expected labels and milestone,
checked directly against live state, not assumed from the creation
calls' own success output.

OPEN ITEMS / DECISIONS NEEDED:
1. This is a DRAFT — migration completes only once the owner confirms
   this board (plus its operator-layer counterpart, tracked separately
   — see this repo's own governance docs for where that lives) is the
   whole ledger, not a partial one.

LIVE STATE: 3 labels, 1 milestone, 6 issues live on
ProxyPrints/ProxyPrints.github.io right now. Nothing closed or merged.
```
