# corrections/

A blameless ledger of caught mistakes — wrong premises, missed cases,
bugs shipped and found. Each entry is one `CORR-NNNN-slug.md` file,
six fields:

- **id** — `CORR-NNNN`, zero-padded, sequential, never reused.
- **date** — when it was caught (not when the underlying mistake was
  made, if those differ).
- **evidence** — usually a commit SHA. When no SHA exists (a fix that
  iterated inside a live container/session with no discrete commit),
  cite the report instead and say so explicitly — the correction is
  the fact being recorded; a commit is one kind of evidence for it,
  not the only kind (see `CORR-0008`).
- **trigger / wrong premise** — what was assumed that turned out
  false, stated plainly. No blame language; the point is the gap in
  the system, not the session that hit it.
- **how caught** — the actual mechanism: a test failure, a live repo
  state check that contradicted a report, a user correction, a hook
  firing. "How caught" matters as much as "what was wrong" — it's the
  detection signal a future gate can be built from.
- **blast radius** — what was actually affected. Distinguish "would
  have been bad but was caught before landing" from "shipped and had
  to be fixed after."
- **systemic fix** — what changed so the same mistake can't recur
  silently, plus a **disposition**:
  - `prose` — documented (CLAUDE.md, docs/troubleshooting.md,
    docs/lessons.md); relies on a future reader noticing it.
  - `gate` — became a hook, lint rule, CI check, or test that fires
    automatically. Strictly stronger than `prose`.
  - `eval` — became a test case in an existing suite (e.g. a
    fault-injection case in `.claude/hooks/test_guard_master.py`)
    without a standalone gate of its own.

## Why this exists, and its actual limits

The intent is to catch corrections at the moment they happen instead
of letting them evaporate once a session ends. `.claude/hooks/guard_master.py`
appends a stub entry here automatically whenever it denies a tool
call — that's a real, reliable signal (the same code path that
decides to block also decides to log). It is **not** a general
"whenever a human overrides the agent" logger: Claude Code's hook
system has no reliable event for "the user clicked deny on an
interactive permission prompt" as of 2026-07-19 (confirmed against
the current hooks docs before building this — `PermissionRequest`
fires before the human decides, `PermissionDenied` only fires for
auto-mode-classifier denials, and neither `Stop` nor `SubagentStop`
carry a reason for why a session ended). An auto-stubbed entry here
means "a gate in this repo's own tooling fired," not "a human
overruled the agent" — those still need a manual entry, same as any
correction that didn't come through a hook.

## Redaction rule

Corrections about _this repo's own contribution rules or code_ live
here, public. Corrections about _how the fleet/orchestration layer
operates_ (scheduling, budgets, credentials, dispatch mechanics) go to
the private orchestration repo instead — same public/private line as
everywhere else in this project.

## `.pending-stubs.jsonl`

`guard_master.py` appends one JSON line here every time it denies a
tool call — timestamp, which rule fired, the raw command, the cwd.
This is a queue, not the ledger itself: a stub is raw material, not a
CORR entry — it has no blast-radius or systemic-fix judgment in it,
because the hook can't know either of those at deny-time. Triage
(same ritual as `docs/lessons.md`'s promotion pass) periodically reads
this file and either promotes a real, worth-recording line into its
own `CORR-NNNN-slug.md`, or discards routine/expected denials (e.g. a
worker correctly getting blocked from `gh pr merge`, exactly as
designed, isn't an incident). Cleared as lines are triaged — it's a
working queue, not an archive.

## Disposition triage

A `prose`-disposition entry that recurs, or that reads as an
"always/never" rule, is a candidate for promotion to `gate` — see
`docs/lessons.md`'s own triage note for the mechanics of that
promotion.
