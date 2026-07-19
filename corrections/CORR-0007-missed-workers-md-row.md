# CORR-0007: orchestrating session skipped its own WORKERS.md row

- **Date**: 2026-07-19
- **Trigger / wrong premise**: CLAUDE.local.md requires adding a
  WORKERS.md row before starting substantive work on the main
  checkout, for any session (not just spawned workers). This session
  made substantial direct writes to the main checkout (`.gitignore`,
  `docs/infrastructure.md`, new files, a branch, a rebase) without
  reading or adding that row.
- **How caught**: self-flagged, prompted by an advisor review pass
  that pointed out the review doctrine this session had itself just
  drafted ("verify against committed state") should apply to the
  session's own conduct too, not only to sub-agents' reports.
- **Blast radius**: none in practice — WORKERS.md's table was checked
  and confirmed still empty throughout, so no other session collided
  with unrowed work. This is a process gap, not an incident with
  actual damage.
- **Systemic fix**: none shipped (this entry exists per the owner's
  explicit instruction to log it as a low-severity ledger example, not
  because a gate was built for it). A real gate would be a
  `PreToolUse`-style check that a WORKERS.md row exists before the
  first `Write`/`Edit` of a session touching the main checkout — not
  attempted here since it wasn't asked for beyond the ledger entry
  itself.
- **Disposition**: `prose` (this entry) — flagged as a `gate` candidate
  if this recurs.
