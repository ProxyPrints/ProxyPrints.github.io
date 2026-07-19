# CORR-0003: newly-added `.claude/agents/*.md` and hook config aren't hot-reloaded

- **Date**: 2026-07-19
- **Trigger / wrong premise**: assumed a running session could
  immediately spawn a subagent from a `.claude/agents/*.md` file it
  had just written in the same session, and that a newly-committed
  `.claude/settings.json` hook would immediately start firing in the
  same already-running session.
- **How caught**: both by direct failure, not inference. (1) Spawning
  `worker-backend` right after creating `.claude/agents/worker-backend.md`
  failed outright: `Agent type 'worker-backend' not found`. (2) This
  session's own `git merge --ff-only origin/master` on the main
  checkout (current branch master at the time) should have been
  denied by `guard_master.py`'s unconditional git-merge-into-master
  rule — the newly-committed `.claude/settings.json` simply wasn't
  active yet in the already-running session, so it silently didn't
  fire.
- **Blast radius**: no unsafe action resulted (the ff-only merge that
  slipped through was itself benign — see CORR note in
  `docs/infrastructure.md`'s ff-only exception, which was added for an
  unrelated reason and independently makes this specific command safe
  regardless). But the finding is structurally important: any
  automation that assumes "I just wrote a new gate, it's live now" is
  wrong within the session that wrote it.
- **Systemic fix**: no code fix possible (this is a session-lifecycle
  property of the harness, not a bug in this repo). Documented as an
  explicit deploy-order fact for the Phase 3 daemon design: restart or
  version-check workers after any roster/hook change, never assume a
  hot update takes effect on an already-running dispatch loop. Also
  drove the worker-loop proof being explicitly split into two steps
  (step 1: prove the mechanism this session via an instructed
  general-purpose agent; step 2: prove native registry pickup +
  harness-level allowlist enforcement in a fresh session).
- **Disposition**: `prose` (recorded as a standing fact; not
  gate-able, since there's no code path to test against — it's a
  property of when a new session starts, not of this repo's code).
