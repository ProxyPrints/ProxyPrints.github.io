"""
Shared PilotRunLedger lifecycle rails (Phase 0 of the owner-approved post-harvest sequence -
docs/features/catalog-completion-plan.md, GitHub milestone "Pipeline: post-harvest", issues
#362/#153) - implemented ONCE here rather than duplicated across the five long-running write
commands that use it (local_calculate_verdicts, reparse_collector_evidence,
retract_stage_d_by_run_id, run_image_evidence_cohort, consensus_recompute). Three pieces:

1. `resilient_terminal_output` - counters-before-output hardening. Production incident
   2026-07-23: a client-side timeout severed a command's stdout AFTER every write for that run had
   already committed and its PilotRunLedger row had already been saved COMPLETED with its
   counters - the command's own final summary print then raised BrokenPipeError, which its
   `except Exception:` handler (with no idea completion had already happened) caught and used to
   flip the ALREADY-COMPLETE ledger row to FAILED. Every command below now (a) saves its ledger
   row COMPLETED with its counters BEFORE printing its terminal summary, and (b) wraps that
   terminal summary print in this context manager, so a BrokenPipeError/IOError there is
   swallowed rather than allowed to reach any enclosing `except Exception:`. Each command's own
   `except Exception:` is ALSO hardened at its own call site (a one-line change, not shared code -
   see each command's own comment there) to only flip a still-RUNNING row to FAILED, never a row
   this same invocation already marked COMPLETED - matching run_image_evidence_cohort's own
   pre-existing convention for its --max-rss-mb CommandError-after-completion path, now applied
   everywhere a terminal summary can raise.

2. `enforce_dry_run_precondition` - the forced-dry-run guard (issue #362, the code-enforced
   version of docs/features/catalog-completion-plan.md's "State-clear safety" runbook rule: "a
   dry-run of the EXACT same invocation is mandatory before its corresponding write"). A
   `--write`/`--apply` invocation of a big write command refuses to proceed unless a matching
   COMPLETED dry-run PilotRunLedger row for the SAME `command` (and, where the caller can cheaply
   compute one, the same `scope` - see each command's own call site for what "same" means there)
   exists within `window_hours` (default 48). `--skip-dryrun-check` bypasses this for a genuine
   emergency and is prominently logged - both to stdout immediately, and onto the run's own
   ledger row `counters["skip_dryrun_check_used"]` once that row is created - whenever used, never
   silently.

3. `add_dry_run_guard_arguments` - the shared `--skip-dryrun-check`/`--dry-run-window-hours` CLI
   flag pair, so every command's own `--help` text carries identical wording rather than five
   near-duplicate copies.

4. `mark_ledger_failed` - the shared FAILED-transition rail (docs/proposals/stage-e-streaming.md
   §3 decision (6)/§10, the "empty-failed-row gap" this brief's own live-DB verification pass
   found: `PilotRunLedger` id 71, `run_id=rescan-wave1-20260724`, persisted `status=failed` with
   an empty `counters` dict and no error detail - untriage-able at the granularity a streaming
   daemon issuing many small jobs per hour needs). Every one of the five commands this module's
   own docstring names (local_calculate_verdicts, reparse_collector_evidence,
   retract_stage_d_by_run_id, run_image_evidence_cohort, consensus_recompute) previously
   duplicated the exact same `except Exception: if ledger.status == RUNNING: ... FAILED ...`
   five-line block with no `failure_reason` recorded anywhere - collapsed here into one call site,
   and extended to always attach `counters["failure_reason"]` (the exception's type + message) to
   whatever counters already existed (e.g. `scope`) at the moment of failure, so a run that dies
   before its first flush still leaves an honest, triage-able row rather than a silent blank one.

SCOPE COMPATIBILITY is intentionally NOT one-size-fits-all: `command` name match is the mandatory
floor (a `reparse_collector_evidence` dry-run can never satisfy `retract_stage_d_by_run_id`'s own
guard - they're always filtered by `command=` first), and each command computes its OWN `scope`
string cheaply from its already-parsed CLI arguments - see each command's own call site. A command
whose invocations don't have a narrower target than "the whole command" (`local_calculate_verdicts`,
`consensus_recompute` - both always operate over whatever's currently eligible/voted, not a
caller-chosen cohort) passes `scope=None`, meaning ANY matching dry-run of that command, regardless
of its own arguments, satisfies the guard. `scope` is always computed from a command's INPUT
arguments (a card-ids-file path, a selector name, a sorted run-id list, a cohort limit) - never
from the RESOLVED target row/id set an invocation's dry-run and write mode might compute
differently in between, matching the docs' own "the EXACT same --selector/--stage-d-run-id/
--card-ids-file invocation" wording. This module never re-derives or re-runs a dry run itself -
purely a query against ledger rows a PRIOR invocation already wrote.
"""

import hashlib
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator, Optional

from django.core.management.base import CommandError, CommandParser
from django.utils import timezone

from cardpicker.models import PilotRunLedger

DEFAULT_DRY_RUN_WINDOW_HOURS = 48.0


@contextmanager
def resilient_terminal_output() -> Iterator[None]:
    """
    Wrap a command's own TERMINAL summary print block (only that block - earlier, mid-run
    progress output is untouched, see this module's own docstring point 1) so
    BrokenPipeError/IOError raised while writing to a severed stdout never propagates to an
    enclosing `except Exception:`. By the time this block runs, the ledger row is already saved
    COMPLETED with its counters, so nothing about the command's own success/failure bookkeeping
    should be able to change on account of what happens to the terminal it's reporting to.
    """
    try:
        yield
    except (BrokenPipeError, IOError):
        pass


def scope_hash(*parts: Any) -> str:
    """
    A short, deterministic, order-preserving fingerprint of a command's own scope-defining INPUT
    arguments (e.g. a card-ids-file path, a selector name, a sorted run-id list) - cheap (one
    sha256 over a short joined string) and short enough to store and query comfortably inside
    `PilotRunLedger.counters`. `\\x1f` (unit separator) joins parts so e.g. `("a", "bc")` and
    `("ab", "c")` never collide.
    """
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def add_dry_run_guard_arguments(
    parser: CommandParser, write_flag: str = "--write", window_hours: float = DEFAULT_DRY_RUN_WINDOW_HOURS
) -> None:
    """
    Shared `--skip-dryrun-check`/`--dry-run-window-hours` flag pair (module docstring point 3).
    `write_flag` is cosmetic only, for the help text - it names the command's OWN existing
    write-mode flag (e.g. `--write` or `--apply`); this function never adds that flag itself.
    """
    parser.add_argument(
        "--skip-dryrun-check",
        action="store_true",
        default=False,
        help=(
            f"Emergency override: skip the forced-dry-run guard that otherwise refuses "
            f"{write_flag} unless a matching COMPLETED dry-run PilotRunLedger row for this exact "
            "command (and, where applicable, the same scope - see this command's own --help "
            "above) exists within --dry-run-window-hours. Prominently logged to stdout and onto "
            "this run's own ledger row counters whenever used - never a silent bypass."
        ),
    )
    parser.add_argument(
        "--dry-run-window-hours",
        type=float,
        default=window_hours,
        help=(
            "Recency window (hours) the forced-dry-run guard accepts a matching prior dry-run "
            f"within. Default: {window_hours:.0f}."
        ),
    )


def enforce_dry_run_precondition(
    command: str,
    write_mode: bool,
    skip_check: bool,
    window_hours: float,
    scope: Optional[str] = None,
    stdout_write: Callable[[str], None] = print,
) -> bool:
    """
    The forced-dry-run guard itself (module docstring point 2). Call this BEFORE creating the
    invocation's own RUNNING PilotRunLedger row (a refused invocation should never leave a row
    behind at all) and before any write occurs.

    Returns True iff `--skip-dryrun-check` was used to bypass a check that would otherwise apply
    (`write_mode` True, `skip_check` True) - the caller should fold this into its own ledger row's
    `counters["skip_dryrun_check_used"]` once that row is created (see `initial_counters` below),
    so the override is durably queryable, not just logged to a terminal that may never be read.
    Returns False in every other case (not in write mode at all; or a genuine matching dry-run was
    found).

    Raises `CommandError` iff `write_mode` is True, `skip_check` is False, and no COMPLETED
    dry-run PilotRunLedger row for `command` (matching `scope`, when given) has `finished_at`
    within `window_hours` of now.
    """
    if not write_mode:
        return False

    if skip_check:
        stdout_write(
            f"[SKIP-DRYRUN-CHECK] {command}: --skip-dryrun-check passed - proceeding to write "
            "WITHOUT a verified matching prior dry-run for this invocation. Recorded on this "
            "run's own PilotRunLedger row."
        )
        return True

    cutoff = timezone.now() - timedelta(hours=window_hours)
    queryset = PilotRunLedger.objects.filter(
        command=command,
        dry_run=True,
        status=PilotRunLedger.Status.COMPLETED,
        finished_at__gte=cutoff,
    ).order_by("-finished_at")

    if scope is not None:
        rows = [row for row in queryset if isinstance(row.counters, dict) and row.counters.get("scope") == scope]
    else:
        rows = list(queryset)

    if not rows:
        scope_clause = f" with scope={scope!r}" if scope is not None else ""
        raise CommandError(
            f"FORCED DRY-RUN GUARD: no COMPLETED dry-run PilotRunLedger row for command={command!r}"
            f"{scope_clause} found within the last {window_hours:.0f}h. Run this exact invocation "
            "as a dry-run first, or pass --skip-dryrun-check to override (prominently logged onto "
            "this run's own ledger row when used)."
        )
    return False


def initial_counters(scope: Optional[str] = None, skip_dryrun_check_used: bool = False) -> Optional[dict[str, Any]]:
    """
    The counters payload to attach at ledger-row CREATION time (status=RUNNING) - `scope` (when
    given) must be visible on the row from the start so a LATER dry-run's own COMPLETED row can
    be matched against it by `enforce_dry_run_precondition` even if that run's own completion
    logic never otherwise touches `counters`. Returns `None` (not `{}`) when there's nothing to
    record, matching every other command's existing "counters is null until there's something
    real to say" convention.
    """
    payload: dict[str, Any] = {}
    if scope is not None:
        payload["scope"] = scope
    if skip_dryrun_check_used:
        payload["skip_dryrun_check_used"] = True
    return payload or None


def merge_counters(existing: Optional[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
    """
    Completion-time counters merge - preserves whatever `initial_counters` already stored at
    creation time (`scope`/`skip_dryrun_check_used`) rather than clobbering it with a fresh dict,
    while still letting each command report its own real completion counters under the same key
    space.
    """
    merged = dict(existing or {})
    merged.update(extra)
    return merged


# Truncated so one enormous exception message/traceback repr can never make a ledger row's own
# counters JSON payload unreasonably large - a triage-relevant identifying prefix survives either
# way, and the full traceback is already in the command's own stderr/logs.
_FAILURE_REASON_MAX_LEN = 2000


def mark_ledger_failed(ledger: PilotRunLedger, exc: BaseException) -> None:
    """
    Shared FAILED-transition rail (module docstring point 4, docs/proposals/stage-e-streaming.md
    §3 decision (6)/§10(a-d)'s cited observability gap) - call this from a command's own
    `except Exception as exc:` handler, in place of the five-line "only a still-RUNNING row gets
    marked FAILED" block every long-running pilot command previously duplicated.

    A no-op (returns without writing) when `ledger.status` is not RUNNING - matching every
    existing call site's own reasoning: a run this invocation already marked COMPLETED (e.g. the
    counters-before-output pattern, `resilient_terminal_output`'s own module docstring point 1)
    must never be overwritten by a LATER exception (a severed stdout on the terminal summary
    print, if `resilient_terminal_output` didn't already swallow it) - the run genuinely
    completed, and its ledger row should keep saying so.

    Otherwise: sets status=FAILED, finished_at=now, and merges
    `counters["failure_reason"] = "<ExceptionType>: <message>"` (truncated, see
    `_FAILURE_REASON_MAX_LEN`) onto whatever counters already existed at creation time (`scope`,
    `skip_dryrun_check_used`) via `merge_counters` - never clobbering them. This is the fix for
    the "empty-failed-row" gap: a run that crashes before its first flush/completion save
    previously left a FAILED row with no error detail at all (PilotRunLedger id 71,
    `run_id=rescan-wave1-20260724`, see this module's own docstring) - now every FAILED row
    carries at least a triage-able reason string, even when nothing else about the run's own
    counters was ever computed.
    """
    if ledger.status != PilotRunLedger.Status.RUNNING:
        return
    reason = f"{type(exc).__name__}: {exc}"[:_FAILURE_REASON_MAX_LEN]
    ledger.status = PilotRunLedger.Status.FAILED
    ledger.finished_at = timezone.now()
    ledger.counters = merge_counters(ledger.counters, {"failure_reason": reason})
    ledger.save(update_fields=["status", "finished_at", "counters"])
