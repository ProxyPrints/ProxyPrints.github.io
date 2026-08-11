"""
2026-08-11 - backfills `CardScanLog.survivor_pks` / `evidence_types_used` on the Stage D fallback
calculator's OWN historical rows (`local_calculate_verdicts.STAGE_D_FALLBACK_ANONYMOUS_ID`) that
predate the fix that made `run_fallback_calculator` persist both fields (#764). That fix only
changed what a NEW `CardScanLog` row carries going forward - a row written before it still carries
`evidence_types_used=[]` / `survivor_pks=None` regardless of what the calculator actually computed
at the time, because the write path simply never put the values on the row. This command reaches
the existing corpus of such rows.

RIDES THE SAME STREAMING CONVEYOR `stream_full_catalog.py` DOES
(`cardpicker.stage_e_dispatch.dispatch_micro_batch`) - one conveyor, not a second one. Batch
sizing (`resolve_micro_batch_size`/`MODE_BULK`), the halt/throttle statuses
(`stream_backstop_sweep._HALT_STATUSES`/`_THROTTLED_STATUS`) and the exit-code contract are
imported from `stream_full_catalog`, not redeclared, for the same reason `run_pipeline.py` already
imports `EXIT_ENVELOPE_HALT`/`run_stage_zero_freshness` from it rather than keeping its own copies:
so all three commands agree, structurally, on what "the conveyor" means and how it ends.

NO NEW CALCULATOR. This command computes nothing about a card's printing candidates. It chooses
WHICH cards to re-dispatch and drives that dispatch through the conveyor; `dispatch_micro_batch`
calls `stage_e_dispatch._run_stage_d`, which calls `local_calculate_verdicts.run_fallback_calculator`
exactly as every other Stage D pass does. That function (unchanged by this command) recomputes
`calculate_fallback_verdict` off the card's own already-persisted `ImageEvidence` and writes the
two fields onto whatever `CardScanLog` row IT produces - the same call, the same fields, the same
code #764 already shipped. This command's only job is the cohort and the drive loop.

STAGE 0 / NO NETWORK STAGE: deliberately absent. Every card in the cohort already has a CURRENT
`ImageEvidence` row with a `collector_line_ocr` extraction (that is a precondition of the
`CardScanLog` row this command targets even existing - `run_fallback_calculator` never reaches
`calculate_fallback_verdict`, let alone writes a skip row carrying a `skip_reason` this command
selects on, for a card with no such evidence). `dispatch_micro_batch` still runs Stage C first
(`_run_stage_c`) exactly as every other dispatch does, and its own already-done manifest check
makes that a no-op for a card whose evidence is current - the ordinary conveyor behaviour, not
something this command adds or suppresses. Nothing here therefore depends on Scryfall reference
data being fresh, so unlike `stream_full_catalog`/`run_pipeline` there is no stage-0 freshness
gate to run or skip.

WHY A RE-PASS DOES NOT RE-CAST OR CORRUPT ANY EXISTING VOTE (established by reading the calculator
itself, not assumed - see `local_calculate_verdicts._eligible_cards_queryset`'s own "RUN-SCOPED
SELF-SUPPRESSION" docstring section). A fresh `run_id` only self-suppresses THIS run's own
output; it does not exclude a card because some EARLIER run already voted on or scanned it. So
every card in the cohort below is eligible again under a fresh `run_id`, and what happens next
splits into exactly two cases:

  * A card whose prior fallback pass reached a SKIP - "no-sub-check-evidence" / "eliminated" /
    "ambiguous", the three `CardScanLog` rows this command's cohort selects on - never cast a
    `CardPrintingTag` vote in the first place; `run_fallback_calculator` only ever appends a
    `CardScanLog` row on a skip, never a vote. Re-running appends a NEW `CardScanLog` row under
    the new `run_id`, this time carrying both fields (the fix is already live). The OLD, field-less
    row is left exactly where it is - `CardScanLog` is an append-only audit trail by design (see
    that model's own docstring: "the scan_log table itself is a append-only audit trail like the
    vote tables are"), never updated or deduplicated in place - which is harmless here: every
    reader of these two fields wants the CURRENT/latest row for a card, and after this command runs
    the latest row is the complete one. This is the ENTIRE cohort this command touches.
  * A card whose prior fallback pass reached a MATCH (cast a real `CardPrintingTag` vote) is safe
    from a double-cast for a structural reason, not a hope: since this command never re-extracts
    evidence, the recomputed verdict is IDENTICAL to the stored one, and
    `local_calculate_verdicts._split_new_printing_tag_votes` skips - counts as `already_voted`,
    never purges or rewrites - any proposed vote whose `(printing_id, is_no_match)` already matches
    what is stored for that `(card_id, anonymous_id)` pair (see that function's own docstring).
    No card in this command's own cohort exercises this path (a matched card never has the
    skip-reason `CardScanLog` row the cohort query requires), but it is the reasoning that makes a
    fresh-`run_id` re-pass safe for Stage D in general, and it is why this command does not need
    to (and does not) special-case matched cards out of the walk.

COHORT (`backfill_cohort_queryset` below): every `Card` carrying a `stage-d-fallback-v1`
`CardScanLog` row whose `skip_reason` is one `calculate_fallback_verdict` can reach WITH a computed
survivor set (`no-sub-check-evidence` / `eliminated` / `ambiguous` - never `no-evidence`, which
never reaches that function at all and correctly stays `survivor_pks=None` forever, evidence
missing, nothing to backfill) and whose `survivor_pks` is still NULL, EXCLUDING any card that
already carries some OTHER row for that same anonymous_id with `survivor_pks` populated. That
exclusion is the self-terminating half: the moment a batch backfills a card, that card carries a
complete row and drops out of the very next cohort query, so the pass runs to genuine exhaustion
rather than re-selecting cards it already fixed on every subsequent invocation.

RESUME: `cardpicker.models.StageEFullCatalogCursor`, the SAME resume model `stream_full_catalog`
uses - reused rather than reinvented, under its own scope key (`RESUME_SCOPE` below) so this
command's progress can never collide with or be corrupted by a full-catalog or `--source` pass's
own mark (see that model's own "KEYED BY SCOPE" docstring for why one shared mark across differently
walked cohorts would be actively dangerous - the same reasoning applies here: this command's pk
walk is over a DIFFERENT, shrinking cohort, not the full catalog).

STOP CONDITIONS / EXIT CODES: identical contract to `stream_full_catalog` - an envelope halt is a
hard stop with no retry, ever (`EXIT_ENVELOPE_HALT`, exit 3); a concurrency-cap throttle is
transient and gets a bounded exponential backoff-and-retry of the same chunk before giving up
(`EXIT_THROTTLE_BUDGET_EXHAUSTED`, exit 4); genuine cohort exhaustion is `EXIT_OK` (0). See that
command's own module docstring for the full reasoning; this command imports the codes rather than
re-deriving them so the two can never drift apart.

`--dry-run` IS A REAL PASS THAT WITHHOLDS THE WRITE, not a plan: it walks the cohort, sizes it and
reports how many rows would gain each field, then exits 0 without dispatching a single batch and
without reading or writing the resume mark.
"""

import logging
import time
from typing import Any, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet
from django.utils import timezone

from cardpicker.local_calculate_verdicts import (
    FALLBACK_AMBIGUOUS_SKIP_REASON,
    FALLBACK_ELIMINATED_SKIP_REASON,
    FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
)
from cardpicker.management.commands.stream_backstop_sweep import (
    _HALT_STATUSES,
    _THROTTLED_STATUS,
)
from cardpicker.management.commands.stream_full_catalog import (
    AUTO_BATCH_SIZE,
    DEFAULT_MAX_THROTTLE_RETRIES,
    DEFAULT_PROGRESS_EVERY_BATCHES,
    DEFAULT_PROGRESS_EVERY_SECONDS,
    DEFAULT_THROTTLE_BACKOFF_INITIAL_S,
    DEFAULT_THROTTLE_BACKOFF_MAX_S,
    EXIT_ENVELOPE_HALT,
    EXIT_MAX_BATCHES_REACHED,
    EXIT_OK,
    EXIT_STREAMING_DISABLED,
    EXIT_THROTTLE_BUDGET_EXHAUSTED,
    RUN_ID_TIMESTAMP_FORMAT,
    _sleep,
    parse_batch_size_option,
)
from cardpicker.models import Card, CardScanLog, StageEFullCatalogCursor
from cardpicker.stage_e_batch_sizing import MODE_BULK, resolve_micro_batch_size
from cardpicker.stage_e_dispatch import dispatch_micro_batch

logger = logging.getLogger(__name__)

TRIGGER_REASON = "survivor-backfill"

# `StageEFullCatalogCursor.scope` key this command's own resume mark lives under - never shared
# with `stream_full_catalog`'s own scopes (`resume_scope_for`'s `"full-catalog"` / `"source:..."`).
RESUME_SCOPE = "survivor-backfill"

# The three `calculate_fallback_verdict` skip reasons that carry a computed survivor set (this
# module's own docstring). Deliberately excludes `FALLBACK_NO_EVIDENCE_SKIP_REASON` ("no-evidence")
# - that skip is raised BEFORE `calculate_fallback_verdict` is ever called, so `survivor_pks` is
# correctly `None` forever for it and there is nothing to backfill.
SURVIVOR_COMPUTED_SKIP_REASONS = frozenset(
    {
        FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON,
        FALLBACK_ELIMINATED_SKIP_REASON,
        FALLBACK_AMBIGUOUS_SKIP_REASON,
    }
)


def backfill_cohort_queryset() -> "QuerySet[Card]":
    """
    THE cohort - see this module's own docstring for the full reasoning. Every `Card` carrying an
    INCOMPLETE `stage-d-fallback-v1` `CardScanLog` row (a computed-skip reason, `survivor_pks`
    NULL), excluding any card that already carries a COMPLETE row for that same anonymous_id -
    the self-terminating exclusion that makes the pass converge to nothing left rather than
    re-selecting a card it has already fixed.
    """
    incomplete_card_ids = CardScanLog.objects.filter(
        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
        skip_reason__in=SURVIVOR_COMPUTED_SKIP_REASONS,
        survivor_pks__isnull=True,
    ).values_list("card_id", flat=True)
    already_backfilled_card_ids = CardScanLog.objects.filter(
        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
        survivor_pks__isnull=False,
    ).values_list("card_id", flat=True)
    return (
        Card.objects.filter(pk__in=incomplete_card_ids)
        .exclude(pk__in=already_backfilled_card_ids)
        .order_by("pk")
        .distinct()
    )


def next_chunk_after(after_pk: int, batch_size: int) -> List[int]:
    """One keyset-paginated page of the cohort - same pk-index range-scan shape
    `stream_full_catalog.next_chunk_after` uses, issued fresh per batch rather than materialised or
    held open across the pass."""
    return list(backfill_cohort_queryset().filter(pk__gt=after_pk).values_list("pk", flat=True)[:batch_size])


class Command(BaseCommand):
    help = (
        "Backfill CardScanLog.survivor_pks / evidence_types_used on historical stage-d-fallback-v1 "
        "rows that predate #764, by re-dispatching the affected cards through the same Stage E "
        "streaming conveyor (cardpicker.stage_e_dispatch.dispatch_micro_batch) every other "
        "streaming driver uses. Computes nothing itself - run_fallback_calculator (unchanged) "
        "recomputes the verdict and writes the fields. No-op unless "
        "settings.STAGE_E_STREAMING_ENABLED is True. See this command's own module docstring."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=str,
            default=AUTO_BATCH_SIZE,
            metavar="N|auto",
            help="Micro-batch chunk size, same semantics as stream_full_catalog's own flag: a "
            f"positive integer pins it, '{AUTO_BATCH_SIZE}' (default) autoscales it.",
        )
        parser.add_argument(
            "--start-pk",
            type=int,
            default=None,
            help="Resume from this Card pk, EXCLUSIVE. Overrides and resets the stored high-water "
            "mark - --start-pk 0 genuinely restarts the whole pass.",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help="Safety bound on how many micro-batches ONE invocation will dispatch (default: "
            "unbounded - keep going until the cohort is exhausted or a stop condition fires).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the cohort size and the batch plan, then exit without dispatching "
            "anything and without reading or writing the resume mark.",
        )
        parser.add_argument(
            "--max-throttle-retries",
            type=int,
            default=DEFAULT_MAX_THROTTLE_RETRIES,
            help=f"Consecutive throttled-dispatch retry budget before giving up (exit 4). Default "
            f"{DEFAULT_MAX_THROTTLE_RETRIES}, same convention as stream_full_catalog's own flag.",
        )
        parser.add_argument(
            "--throttle-backoff-initial",
            type=float,
            default=DEFAULT_THROTTLE_BACKOFF_INITIAL_S,
            help=f"Seconds to wait after the first consecutive throttled attempt, doubling each "
            f"further one (default {DEFAULT_THROTTLE_BACKOFF_INITIAL_S}).",
        )
        parser.add_argument(
            "--throttle-backoff-max",
            type=float,
            default=DEFAULT_THROTTLE_BACKOFF_MAX_S,
            help=f"Ceiling on the exponential throttle backoff, in seconds (default "
            f"{DEFAULT_THROTTLE_BACKOFF_MAX_S}).",
        )
        parser.add_argument(
            "--progress-every-batches",
            type=int,
            default=DEFAULT_PROGRESS_EVERY_BATCHES,
            help=f"Emit a rolled-up progress summary every N completed batches (default "
            f"{DEFAULT_PROGRESS_EVERY_BATCHES}).",
        )
        parser.add_argument(
            "--progress-every-seconds",
            type=float,
            default=DEFAULT_PROGRESS_EVERY_SECONDS,
            help=f"Emit a rolled-up progress summary at least this often, in seconds (default "
            f"{DEFAULT_PROGRESS_EVERY_SECONDS}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        explicit_batch_size = parse_batch_size_option(options["batch_size"])
        batch_decision = resolve_micro_batch_size(explicit=explicit_batch_size, mode=MODE_BULK)
        batch_size: int = batch_decision.batch_size

        max_batches: Optional[int] = options["max_batches"]
        if max_batches is not None and max_batches <= 0:
            raise CommandError("--max-batches must be a positive integer.")
        start_pk: Optional[int] = options["start_pk"]
        if start_pk is not None and start_pk < 0:
            raise CommandError("--start-pk must be zero or a positive integer.")

        max_throttle_retries: int = options["max_throttle_retries"]
        if max_throttle_retries < 0:
            raise CommandError("--max-throttle-retries must be zero or a positive integer.")
        backoff_initial: float = options["throttle_backoff_initial"]
        backoff_max: float = options["throttle_backoff_max"]
        if backoff_initial <= 0 or backoff_max <= 0:
            raise CommandError("--throttle-backoff-initial and --throttle-backoff-max must be positive.")
        if backoff_max < backoff_initial:
            raise CommandError("--throttle-backoff-max must be >= --throttle-backoff-initial.")
        progress_every_batches: int = options["progress_every_batches"]
        progress_every_seconds: float = options["progress_every_seconds"]
        if progress_every_batches <= 0 or progress_every_seconds <= 0:
            raise CommandError("--progress-every-batches and --progress-every-seconds must be positive.")

        dry_run: bool = options["dry_run"]
        verbosity: int = options.get("verbosity", 1)

        pre_dispatch_resume_pk = (
            start_pk if start_pk is not None else StageEFullCatalogCursor.get_position(RESUME_SCOPE)
        )

        if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
            self.stdout.write("STAGE_E_STREAMING_ENABLED is False - backfill_survivor_pks is a no-op.")
            self._write_verdict(
                exit_code=EXIT_STREAMING_DISABLED,
                reason="streaming-disabled",
                detail="nothing was dispatched; the ENTIRE cohort remains unprocessed",
                resume_pk=pre_dispatch_resume_pk,
            )
            raise CommandError(
                "STAGE_E_STREAMING_ENABLED is False - dispatched nothing and the whole cohort "
                "remains. Enable the setting and relaunch.",
                returncode=EXIT_STREAMING_DISABLED,
            )

        uses_stored_mark = not dry_run
        if start_pk is not None:
            resume_pk = start_pk
            if uses_stored_mark:
                StageEFullCatalogCursor.reset_to(RESUME_SCOPE, start_pk)
            mark_source = "--start-pk"
        elif uses_stored_mark:
            resume_pk = StageEFullCatalogCursor.get_position(RESUME_SCOPE)
            mark_source = "stored high-water mark"
        else:
            resume_pk = 0
            mark_source = "dry-run (stored mark not consulted)"

        remaining = backfill_cohort_queryset().filter(pk__gt=resume_pk).count()
        planned_batches = (remaining + batch_size - 1) // batch_size
        if max_batches is not None:
            planned_batches = min(planned_batches, max_batches)

        self.stdout.write(
            f"Cohort: {remaining} cards remaining with incomplete stage-d-fallback-v1 "
            f"survivor_pks/evidence_types_used; resume_scope={RESUME_SCOPE}; "
            f"resume_pk={resume_pk} ({mark_source}); batch_size={batch_size}; "
            f"planned_batches={planned_batches}"
            + (f" (bounded by --max-batches={max_batches})" if max_batches is not None else "")
        )
        self.stdout.write(f"Batch sizing: {batch_decision.describe()}")

        if dry_run:
            self.stdout.write(
                f"DRY RUN - dispatching nothing. {remaining} row(s) would gain survivor_pks/"
                f"evidence_types_used across ~{planned_batches} batches, starting at pk>{resume_pk}."
            )
            self._write_verdict(
                exit_code=EXIT_OK,
                reason="dry-run-plan-only",
                detail=f"the plan for {planned_batches} batches was reported and nothing was dispatched or written",
                resume_pk=resume_pk,
            )
            return

        if not remaining:
            self.stdout.write(f"Nothing to do. resume_pk={resume_pk}")
            self._write_verdict(
                exit_code=EXIT_OK,
                reason="cohort-exhausted",
                detail="there was nothing left to dispatch",
                resume_pk=resume_pk,
            )
            return

        run_id_prefix = f"survivor-backfill-b{batch_size}-{timezone.now().strftime(RUN_ID_TIMESTAMP_FORMAT)}"

        cohort_size = remaining
        batches_dispatched = 0
        cards_done = 0
        total_fields_backfilled = 0
        halted_status: Optional[str] = None
        stopped_reason: Optional[str] = None
        started_at = time.monotonic()
        batch_num = 0
        consecutive_throttles = 0
        total_throttle_retries = 0
        throttle_budget_exhausted = False
        last_summary_at = started_at
        last_summary_cards = 0
        last_summary_batches = 0

        while max_batches is None or batch_num < max_batches:
            chunk = next_chunk_after(resume_pk, batch_size)
            if not chunk:
                stopped_reason = "cohort-exhausted"
                self.stdout.write("Cohort exhausted - every incomplete row has been re-dispatched.")
                break

            outcome = dispatch_micro_batch(
                card_ids=chunk,
                trigger_reason=TRIGGER_REASON,
                run_id=run_id_prefix,
                batch_size=len(chunk),
                ledger_run_id=f"{run_id_prefix}-{batch_num}",
            )

            if outcome.status in _HALT_STATUSES:
                halted_status = outcome.status
                stopped_reason = "envelope-halt"
                self.stdout.write(
                    f"[batch {batch_num}] Envelope halt ({outcome.status}, trip_id={outcome.trip_id}) "
                    "- stopping (do not retry, never self-resume). Resolve the trip with "
                    "resolve_envelope_trip (docs/features/stage-e-operations.md) and relaunch."
                )
                break

            if outcome.status == _THROTTLED_STATUS:
                if consecutive_throttles >= max_throttle_retries:
                    throttle_budget_exhausted = True
                    stopped_reason = "throttle-retries-exhausted"
                    self.stdout.write(
                        f"[batch {batch_num}] Dispatch slots still saturated after "
                        f"{consecutive_throttles} consecutive retries (--max-throttle-retries="
                        f"{max_throttle_retries}) - giving up."
                    )
                    break
                wait_s = min(backoff_initial * (2**consecutive_throttles), backoff_max)
                consecutive_throttles += 1
                total_throttle_retries += 1
                self.stdout.write(
                    f"[batch {batch_num}] Throttled (all concurrency-cap slots held) - backing off "
                    f"{wait_s:.1f}s and retrying the same chunk (attempt {consecutive_throttles}/"
                    f"{max_throttle_retries})."
                )
                logger.info(
                    "backfill_survivor_pks: throttled on batch %s, backing off %.1fs (attempt %s/%s)",
                    batch_num,
                    wait_s,
                    consecutive_throttles,
                    max_throttle_retries,
                )
                _sleep(wait_s)
                continue

            consecutive_throttles = 0

            batch_low, batch_high = chunk[0], chunk[-1]
            batches_dispatched += 1
            cards_done += len(chunk)
            # THE MEASURE OF PROGRESS THIS COMMAND ACTUALLY CARES ABOUT: how many of the cards just
            # dispatched dropped out of the cohort (i.e. got a complete row written). Re-queried
            # rather than inferred from DispatchOutcome, which carries fallback vote/route counts
            # but not "rows that gained these two specific fields".
            still_incomplete = set(backfill_cohort_queryset().filter(pk__in=chunk).values_list("pk", flat=True))
            total_fields_backfilled += len(chunk) - len(still_incomplete)
            resume_pk = max(resume_pk, batch_high)
            StageEFullCatalogCursor.advance(RESUME_SCOPE, resume_pk, cards_dispatched=len(chunk))

            elapsed = time.monotonic() - started_at
            batch_line = (
                f"[batch {batch_num}] pk {batch_low}-{batch_high} ({len(chunk)} cards) "
                f"status={outcome.status} backfilled={len(chunk) - len(still_incomplete)} "
                f"| done={cards_done} elapsed={elapsed:.1f}s "
                f"rate={(cards_done / elapsed) if elapsed > 0 else 0.0:.3f} cards/s"
            )
            logger.debug("backfill_survivor_pks: %s", batch_line)
            if verbosity >= 2:
                self.stdout.write(batch_line)

            batch_num += 1

            now = time.monotonic()
            if (
                batches_dispatched - last_summary_batches >= progress_every_batches
                or now - last_summary_at >= progress_every_seconds
            ):
                self._emit_progress_summary(
                    cards_done=cards_done,
                    cohort_size=cohort_size,
                    elapsed=now - started_at,
                    window_cards=cards_done - last_summary_cards,
                    window_seconds=now - last_summary_at,
                    throttle_retries=total_throttle_retries,
                    resume_pk=resume_pk,
                )
                last_summary_at = now
                last_summary_cards = cards_done
                last_summary_batches = batches_dispatched

        if stopped_reason is None:
            work_remains = bool(next_chunk_after(resume_pk, 1))
            if work_remains:
                stopped_reason = "max-batches-reached"
                self.stdout.write(
                    f"--max-batches={max_batches} reached with rows still incomplete - stopping. "
                    "This is the bound you asked for, not a fault, but the pass is INCOMPLETE: "
                    f"relaunch to continue from the resume pk below."
                )
            else:
                stopped_reason = "cohort-exhausted"
                self.stdout.write(
                    f"--max-batches={max_batches} reached exactly as the cohort ran out - every "
                    "incomplete row has been re-dispatched."
                )

        final_now = time.monotonic()
        self._emit_progress_summary(
            cards_done=cards_done,
            cohort_size=cohort_size,
            elapsed=final_now - started_at,
            window_cards=cards_done - last_summary_cards,
            window_seconds=final_now - last_summary_at,
            throttle_retries=total_throttle_retries,
            resume_pk=resume_pk,
        )

        elapsed = time.monotonic() - started_at
        self.stdout.write(
            f"DONE batches_dispatched={batches_dispatched} cards_done={cards_done} "
            f"fields_backfilled={total_fields_backfilled} elapsed={elapsed:.1f}s "
            f"rate={(cards_done / elapsed) if elapsed > 0 else 0.0:.3f} cards/s "
            f"throttle_retries={total_throttle_retries} "
            f"halted={halted_status} stopped_reason={stopped_reason}"
        )
        self.stdout.write(
            f"RESUME scope={RESUME_SCOPE} resume_pk={resume_pk} "
            f"(relaunch with the same flags to continue, or --start-pk {resume_pk})"
        )

        if throttle_budget_exhausted:
            exit_code = EXIT_THROTTLE_BUDGET_EXHAUSTED
            failure = (
                f"Stopped after {total_throttle_retries} throttled dispatch attempts "
                f"({consecutive_throttles} consecutive) - the concurrency cap did not clear. "
                f"Resume with --start-pk {resume_pk} once dispatch slots are free."
            )
            detail = "the concurrency cap never cleared; work REMAINS in the cohort"
        elif halted_status is not None:
            exit_code = EXIT_ENVELOPE_HALT
            failure = (
                f"Stopped on an envelope halt ({halted_status}) with rows still incomplete. Do "
                "NOT relaunch until a human has acknowledged the trip with resolve_envelope_trip "
                f"(docs/features/stage-e-operations.md); then resume with --start-pk {resume_pk}."
            )
            detail = f"envelope trip {halted_status} hard-stopped the pass; work REMAINS in the cohort"
        elif stopped_reason == "max-batches-reached":
            exit_code = EXIT_MAX_BATCHES_REACHED
            failure = (
                f"Stopped on the --max-batches={max_batches} bound with rows still incomplete. "
                "This is the bound you asked for, not a fault - but the pass is INCOMPLETE, so it "
                f"cannot exit 0. Relaunch to continue, or resume with --start-pk {resume_pk}."
            )
            detail = "the operator's --max-batches bound ended the invocation; work REMAINS in the cohort"
        else:
            exit_code = EXIT_OK
            failure = None
            detail = "the whole cohort was re-dispatched; no incomplete row remains"

        self._write_verdict(
            exit_code=exit_code,
            reason=stopped_reason or "cohort-exhausted",
            detail=detail,
            resume_pk=resume_pk,
        )
        if failure is not None:
            raise CommandError(failure, returncode=exit_code)

    def _write_verdict(self, *, exit_code: int, reason: str, detail: str, resume_pk: int) -> None:
        """THE final stdout line of every terminating path - same convention as
        `stream_full_catalog._write_verdict`: the exit code and the human-readable output may
        never disagree, so this is the one place that states in words whether the pass COMPLETED
        or STOPPED EARLY, fixed-prefixed so it stays greppable out of a truncated log."""
        if exit_code == EXIT_OK:
            self.stdout.write(
                f"PASS COMPLETE exit_code={exit_code} reason={reason} - {detail}. "
                f"scope={RESUME_SCOPE} resume_pk={resume_pk}"
            )
            return
        self.stdout.write(
            f"PASS STOPPED EARLY exit_code={exit_code} reason={reason} - {detail}. "
            f"scope={RESUME_SCOPE} resume_pk={resume_pk} "
            f"(relaunch with the same flags to continue, or --start-pk {resume_pk})"
        )

    def _emit_progress_summary(
        self,
        *,
        cards_done: int,
        cohort_size: int,
        elapsed: float,
        window_cards: int,
        window_seconds: float,
        throttle_retries: int,
        resume_pk: int,
    ) -> None:
        cards_remaining = max(cohort_size - cards_done, 0)
        cumulative_rate = (cards_done / elapsed) if elapsed > 0 else 0.0
        window_rate = (window_cards / window_seconds) if window_seconds > 0 else 0.0
        self.stdout.write(
            f"PROGRESS done={cards_done}/{cohort_size} remaining={cards_remaining} "
            f"elapsed={elapsed:.1f}s rate_now={window_rate:.3f} rate_avg={cumulative_rate:.3f} cards/s "
            f"throttle_retries={throttle_retries} resume_pk={resume_pk}"
        )
