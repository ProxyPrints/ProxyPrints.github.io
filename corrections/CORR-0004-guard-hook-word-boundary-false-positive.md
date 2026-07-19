# CORR-0004: guard_master.py's regex blocked `git merge-base`/similar as if it were `git merge`

- **Date**: 2026-07-19
- **Trigger / wrong premise**: the original `guard_master.py` matched
  `git merge`/`git push` subcommands with a plain `\b` word-boundary
  regex (`\bgit\s+merge\b`). A `\b` boundary is satisfied by a
  trailing hyphen, so `git merge-base ...` (a real, unrelated,
  read-only git plumbing command) matched the same pattern as an
  actual `git merge`.
- **How caught**: this session's own `git merge-base master origin/worktree-x` call — used to verify a spawned worker's branch
  point while writing a report — was itself denied by the hook mid-task.
  Caught by direct failure, not by the test suite (the original 12
  fault-injection cases didn't include a subcommand-prefix-collision
  case).
- **Blast radius**: would have blocked any legitimate `git merge-base`,
  `git push-*`-shaped, or similarly-prefixed command from every
  session, indefinitely, until noticed — a real false-positive with no
  workaround short of editing the hook. Caught before this branch
  shipped; no session was blocked by it in production use.
- **Systemic fix**: regex tightened to require whitespace-or-end after
  the subcommand token (`(\s|$)` instead of `\b`) in both the
  `git merge` and `git push` checks. Two regression cases added to
  `.claude/hooks/test_guard_master.py` (`git merge-base` from both the
  main checkout and a worker-on-master) so this exact class of bug is
  now a permanent fault-injection case.
- **Disposition**: `gate` (the regex fix itself) + `eval` (regression
  test cases covering the exact false-positive).
