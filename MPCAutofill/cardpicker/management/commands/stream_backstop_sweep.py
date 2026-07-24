"""
Stage E Phase 2 - the cron backstop sweep (docs/proposals/stage-e-streaming.md §3 decision (1)'s
"low-frequency cron sweep as a correctness backstop, not the primary path"). Re-runs the SAME
eligibility selectors the event-driven trigger (`cardpicker/stage_e_signals.py`) and the conveyor's
own backlog-fill (`cardpicker/stage_e_dispatch.py`'s `_select_micro_batch`) already use, catching
anything a lost/never-fired django-q dispatch missed - django-q2's own delivery guarantee is
at-least-once-ATTEMPTED, not exactly-once-DELIVERED (§3 decision (1)'s own reasoning), and this
project has no audited "no dispatch was ever silently dropped" property.

DEFAULT-OFF, same gate as every other Phase 2 entry point (`settings.STAGE_E_STREAMING_ENABLED`) -
this command exits immediately, doing nothing, whenever that flag is False, matching the "ships the
mechanism, never turns it on" posture the whole of Phase 2 follows (see `stage_e_dispatch.py`'s own
module docstring). Not scheduled anywhere by this change either - a django-q `Schedule` row that
actually runs this on a cadence is a live-DB write this change deliberately does not make (NOT IN
SCOPE per the phase-2 task brief: "actually enabling the trigger in prod settings... turning it on
is the phase-3 shakedown's polled owner action").

Drives repeated `dispatch_micro_batch(card_ids=None, ...)` calls - `card_ids=None` lets
`_select_micro_batch` fill each batch entirely from the backlog, no seed card. Two backlogs, tried
in order per batch: (a) the Stage C backlog (cards with no CURRENT full-manifest `ImageEvidence` row
- catches a lost card-create dispatch), (b) once (a) is empty for a given batch, the Stage D
join-key-eligible backlog (cards with current evidence that have never received a join-key vote OR
scan-log row - catches a lost evidence-change dispatch; `_select_micro_batch` itself deliberately
does not fill from this backlog, see its own docstring, so the sweep covers it here instead). Stops
when both backlogs come back empty, when the envelope trips ("halted-new-trip"/"halted-open-trip" -
the sweep does not retry past a halt; the next scheduled sweep invocation picks up where this one
stopped, exactly like a re-invoked BULK command would), or when `--max-batches` is reached (a safety
bound for a single invocation, not a design limit).

IDEMPOTENCE: every batch this command dispatches goes through the exact same `dispatch_micro_batch`
conveyor the event trigger uses - Stage C's own resume filter and Stage D's own
anonymous_id-exclusion eligibility queries are what make a RE-RUN of this same command produce zero
additional writes once the backlog is genuinely exhausted (the conveyor's own idempotence, not a new
mechanism this command adds).
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_calculate_verdicts import (
    _eligible_cards_queryset as _stage_d_eligible_cards_queryset,
)
from cardpicker.stage_e_dispatch import DEFAULT_MICRO_BATCH_SIZE, dispatch_micro_batch

DEFAULT_MAX_BATCHES = 1000

_HALT_STATUSES = ("halted-open-trip", "halted-new-trip")


def _next_stage_d_backlog_ids(batch_size: int) -> list[int]:
    """
    The Stage-D-only backlog `_select_micro_batch` (`stage_e_dispatch.py`) deliberately does NOT
    fill from (see that function's own docstring) - cards whose Stage C evidence is already
    complete but that have never had a join-key pass at all. Reuses
    `local_calculate_verdicts._eligible_cards_queryset` UNSCOPED (`card_ids=None`) - the exact same
    pool `run_join_key_calculator`'s own BULK-mode invocation would consider - sliced to
    `batch_size`, never materializing the whole backlog. A module-private helper reused here rather
    than duplicated, the same "reuse, never re-derive" convention `cardpicker/tests/
    test_local_calculate_verdicts.py` already establishes for testing it directly.
    """
    return list(
        _stage_d_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).order_by("pk").values_list("pk", flat=True)[:batch_size]
    )


class Command(BaseCommand):
    help = (
        "Stage E Phase 2 cron backstop sweep (docs/proposals/stage-e-streaming.md §3 decision (1)) "
        "- a correctness backstop for the event-driven trigger, not the primary dispatch path. "
        "No-op unless settings.STAGE_E_STREAMING_ENABLED is True. See this command's own module "
        "docstring and docs/features/stage-e-operations.md's 'Phase 2' section."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--max-batches",
            type=int,
            default=DEFAULT_MAX_BATCHES,
            help=f"Safety bound on how many micro-batches one invocation will dispatch before "
            f"exiting, even if the backlog isn't exhausted yet (default {DEFAULT_MAX_BATCHES}).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Override settings.STAGE_E_MICRO_BATCH_SIZE for this invocation only.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
            self.stdout.write("STAGE_E_STREAMING_ENABLED is False - backstop sweep is a no-op.")
            return

        max_batches: int = options["max_batches"]
        batch_size: int = options["batch_size"] or getattr(
            settings, "STAGE_E_MICRO_BATCH_SIZE", DEFAULT_MICRO_BATCH_SIZE
        )
        run_id_prefix = f"stage-e-backstop-{timezone.now().strftime('%Y%m%dT%H%M%SZ')}"

        batches_dispatched = 0
        total_stage_c = 0
        total_stage_d_votes = 0
        halted_status = None

        for batch_num in range(max_batches):
            outcome = dispatch_micro_batch(
                card_ids=None,
                trigger_reason="backstop-sweep",
                run_id=f"{run_id_prefix}-{batch_num}",
                batch_size=batch_size,
            )
            if outcome.status in _HALT_STATUSES:
                halted_status = outcome.status
                self.stdout.write(f"Envelope halt ({outcome.status}, trip_id={outcome.trip_id}) - stopping sweep.")
                break

            if outcome.status == "empty":
                # Backlog (a) exhausted for this pass - try backlog (b) before concluding the whole
                # sweep is done (module docstring).
                stage_d_backlog_ids = _next_stage_d_backlog_ids(batch_size)
                if not stage_d_backlog_ids:
                    self.stdout.write("Backlog exhausted - nothing left to dispatch.")
                    break
                outcome = dispatch_micro_batch(
                    card_ids=stage_d_backlog_ids,
                    trigger_reason="backstop-sweep-stage-d",
                    run_id=f"{run_id_prefix}-{batch_num}-d",
                    batch_size=batch_size,
                )
                if outcome.status in _HALT_STATUSES:
                    halted_status = outcome.status
                    self.stdout.write(f"Envelope halt ({outcome.status}, trip_id={outcome.trip_id}) - stopping sweep.")
                    break
                if outcome.status == "empty":
                    self.stdout.write("Backlog exhausted - nothing left to dispatch.")
                    break

            batches_dispatched += 1
            total_stage_c += outcome.stage_c_completed
            total_stage_d_votes += (
                outcome.stage_d_join_key_votes + outcome.stage_d_fallback_votes + outcome.stage_d_slow_path_routed
            )

        self.stdout.write(
            f"DONE batches_dispatched={batches_dispatched} stage_c_completed={total_stage_c} "
            f"stage_d_votes_or_routes={total_stage_d_votes} halted={halted_status}"
        )
