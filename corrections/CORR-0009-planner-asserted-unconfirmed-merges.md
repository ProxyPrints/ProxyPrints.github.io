# CORR-0009: planner asserted PR #136/#137 were merged when they hadn't been

- **Date**: 2026-07-19
- **Trigger / wrong premise**: a directive stated "PR #136 + #137:
  owner merged via UI. Confirm both landed, verify master's CI green
  post-merge, delete branches per the precondition convention" — but
  no merge had actually happened. The "done" referred to two
  credential rotations (a GH PAT and `GOOGLE_DRIVE_API_KEY`), not the
  PR merges; the directive conflated the two.
- **How caught**: `gh pr view --json state` plus a direct
  `gh api repos/.../pulls/<n> -q '.state,.merged,.merged_at'` call
  (bypassing any `gh pr view`/GraphQL caching concern) both showed
  `state: OPEN`, `merged: false` for both PRs, and `git ls-remote`
  confirmed both feature branches still existed unmerged. Checked
  because the review doctrine ("check every verification section
  against git/CI reality before accepting it") applies to directives
  as much as to sub-agent reports — a directive claiming a fact about
  repo state is itself a claim to verify, not a premise to build on.
- **Blast radius**: would have been severe if not caught before
  acting — the directive's own next steps (delete both branches "per
  the precondition convention") would have deleted the only copies of
  unmerged, real work (the guard hook fixes, corrections ledger,
  tesseract CI fix) with no PR left to recover them from. Caught
  before any branch was deleted or any downstream state was claimed;
  zero actual damage.
- **Systemic fix**: none new shipped by this entry alone — this _is_
  the review doctrine (verify claims against git/CI reality, including
  the planner's own) working as designed. Worth noting as a concrete,
  positive example the next time someone asks whether that doctrine
  line is pulling its weight.
- **Disposition**: `prose` (this entry) — the mechanism that caught it
  (habitually verifying state-claims via `gh api`/`git ls-remote`
  before acting on them) is already a `gate`-strength habit via the
  constitution's review doctrine; no new gate needed specifically for
  this case.
