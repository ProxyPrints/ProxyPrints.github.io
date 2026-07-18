```
TASK: Proposal G — merge fallout: PR #85/#86 merged, PR #88 auto-closed by
the stacked-PR base-deletion trap, recreated as PR #95.

WHAT HAPPENED:
1. PR #85 (schema+backend) and PR #86 (sign-in relocation) both merged to
   master (squash-merged as ad0ca752 and be85b515 respectively).
2. PR #88 (saved-decks API), stacked on PR #85's branch
   (claude/proposal-g-schema-backend) by design, was auto-closed when
   that branch was deleted on #85's merge — exactly the stacked-PR
   base-deletion trap docs/lessons.md documents, which #88's own
   description had already flagged as a risk and carried a merge-time
   checklist item to retarget before merging. The retarget didn't happen
   in time; GitHub closed #88 before I could act on the merge webhook.

WHAT SHIPPED (recovery):
1. Rebuilt the saved-decks-api branch (claude/proposal-g-saved-decks-api's
   2 unique commits — the model/backend commits from #85 that it was
   stacked on are now redundant, already in master) onto current master
   via `git rebase --onto origin/master 92fb60a7 ...` — a clean rebase,
   zero conflicts, since only the branch's own 2 commits replayed.
2. Verified the result byte-identical to the original #88 content
   (schema_types.ts, store/api.ts diffed exit 0) and identical diff stat
   (22 files, 1616 insertions, 18 deletions) — this is a lossless
   recreation, not a reconstruction from memory.
3. Re-verified fresh rather than just trusting the rebase: `manage.py
   check` clean, `makemigrations --check --dry-run` shows zero drift
   against current master's models, a live Django-test-client smoke
   script against real local Postgres exercising all 7 endpoints
   end-to-end (crypto profile create/read, deck save/list/delete,
   account reset) — all passed. black==22.8.0/isort==5.12.0 (pinned,
   matching .pre-commit-config.yaml)/mypy all clean.
4. Pushed as claude/proposal-g-saved-decks-api-v2, opened as PR #95
   against master directly (no stacking this time — nothing left to
   stack on), referencing #88's closure and this recreation explicitly
   in the PR body.
5. Updated PR #93's (the UI-wiring PR) description to reference #95
   instead of the now-dead #88 in its "carried-forward files" note, and
   to note #86 has already merged.

DEVIATIONS: none — this is a mechanical, content-preserving recovery of
already-designed, already-reviewed-shape work, not a new design decision.

VERIFICATION: see WHAT SHIPPED items 2-3 above — full backend
verification re-run fresh against current master's schema, not assumed
from the original PR's now-stale verification.

OPEN ITEMS / DECISIONS NEEDED:
1. None — PR #95 is a straightforward recreation, subscribed via
   subscribe_pr_activity, ~1-hour check-in scheduled.
2. Standing merge-time note (already in PR #93's body): once #89
   (crypto module) and #95 merge, rebase claude/proposal-g-ui-wiring
   onto master to drop its now-redundant carried-forward duplicate
   commits.

LIVE STATE:
  - master now has: PR #85 (schema+backend), PR #86 (sign-in
    relocation). PR #88 permanently closed (superseded, not reopened,
    per the do-not-reopen-a-closed-PR instruction — its content lives
    on in #95).
  - Open PRs: #89 (crypto module), #93 (UI wiring, description updated),
    #95 (saved-decks API, recreation of #88). All subscribed via
    subscribe_pr_activity with ~1-hour check-ins scheduled for #93/#95.
  - Branch claude/proposal-g-saved-decks-api (old, orphaned by #88's
    closure) left in place, untouched — not deleted, since it's not
    causing any harm and deleting branches wasn't asked for.
```
