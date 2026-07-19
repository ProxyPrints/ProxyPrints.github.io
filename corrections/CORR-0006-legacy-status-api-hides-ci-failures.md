# CORR-0006: legacy commit Status API silently hides real GitHub Actions failures

- **Date**: 2026-07-19
- **Trigger / wrong premise**: assumed `gh api repos/{owner}/{repo}/commits/<sha>/status` would report this repo's
  CI state, since it's a plausible-looking, commonly-referenced
  endpoint for "commit CI status."
- **How caught**: while building `session_context.sh`, this endpoint
  returned `"pending"` with zero total statuses for a commit whose
  actual GitHub Actions runs were known (from other checks made this
  same session) to include a real, completed failure. Switching to
  `.../commits/<sha>/check-runs` (the Checks API, which is what GitHub
  Actions actually posts to) immediately surfaced the true state:
  master HEAD's "Backend tests" check was genuinely `FAILING`, and had
  been for at least a week.
- **Blast radius**: any tool (this hook included, in its first draft)
  trusting the Status API for an Actions-only repo reports
  "pending"/empty forever, regardless of real CI outcome — the exact
  failure mode a SessionStart context hook exists to prevent (silently
  wrong premises about live repo state). Caught before the hook
  shipped in this form; no session was ever actually misled by the
  broken version in production use.
- **Systemic fix**: `session_context.sh` uses `.../check-runs` and
  aggregates conclusions itself (any non-success/skipped/neutral
  conclusion → reported as `FAILING -- <names>`), not the Status API.
- **Disposition**: `gate` (the hook now reports real CI state on every
  session start, structurally, not just when someone happens to
  double-check manually).
