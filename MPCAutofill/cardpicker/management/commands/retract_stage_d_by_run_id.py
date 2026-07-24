"""
Pre-pilot zeroing plan (board issue tracking that plan) - targeted retraction of Stage D's
`stage-d-join-key-v1` machine state (`CardPrintingTag` votes and non-rescannable `CardScanLog`
skip rows, both keyed by `local_calculate_verdicts.JOIN_KEY_ANONYMOUS_ID`), scoped to one or more
specific `run_id`(s) rather than the whole calculator's anonymous_id. `purge_machine_votes`
already does the equivalent thing for its OWN run_id-scoped purge, but always re-resolves every
affected card unconditionally; this command adds the ONE extra thing that purge doesn't need
(join-key retraction always feeds back into printing-consensus, purge's own generic domains -
printing/artist/tag - don't share a single safety gate the same way) - see the SAFETY GATE
paragraph below.

SCOPE per `--run-id`:
  - Every `CardPrintingTag` row with `anonymous_id=JOIN_KEY_ANONYMOUS_ID` and this `run_id`.
  - Every `CardScanLog` row with the same `anonymous_id`/`run_id` whose `skip_reason` is NOT in
    `local_calculate_verdicts.JOIN_KEY_RESCANNABLE_SKIP_REASONS` (imported, not duplicated - see
    that constant's own docstring for which skip reasons count as transient/re-selectable).
    Rescannable rows (today: `"no-evidence"`) are deliberately left alone entirely - a future
    `local_calculate_verdicts` invocation already re-selects a card carrying only a rescannable
    row on its own, so the pilot's own eligibility query handles that cohort natively; retracting
    them here would be a no-op at best and a spurious extra row of "work" at worst. Counted
    separately (`skipped_rescannable`) so a report never has to guess whether a run_id's silence
    on a given card means "already handled" or "genuinely nothing there".

SAFETY GATE (mirrors `reparse_collector_evidence`'s own gate exactly - same reasoning, same
function call): BEFORE deleting a card's vote/scan-log rows, `printing_consensus.resolve_printing
(card)` is re-checked LIVE. If it is not `None` (a RESOLVED printing OR a resolved `NO_MATCH`
consensus - `resolve_printing` returns the `NO_MATCH` sentinel, not `None`, for that case), the
card is skipped ENTIRELY - never force-retracted - and counted prominently
(`skipped_resolved_gate`) for human review. A live review ahead of this command's own build found
this expected to be 0 for the specific run_ids this plan targets, but the gate is mandatory
regardless of that expectation, not conditional on it - the whole point of a gate is that it
still fires on a case a prior review missed.

AFTER deleting a card's rows (write mode only), `printing_consensus.resolve_and_persist_printing
(card)` is called - the same consensus-demotion/materialized-status/ES-resync step
`purge_machine_votes.purge_run` calls for its own affected cards. Verified (not assumed) that
this function casts no votes of its own - it only ever reads `card.printing_tags.all()` and
writes `card.printing_tag_status`/`card.inferred_canonical_card`/(conditionally) the ES index,
never an `AbstractWeightedVote` subclass row - so this is a pure consensus-recompute-and-persist
step, not a second source of machine votes needing its own future retraction.
`printing_consensus.py` itself (PROTECTED CORE, docs/upstreaming/license-provenance.md) is
imported and called here, never modified.

IDEMPOTENCE: per-card, not per-run-id - a card whose vote/scan-log rows for this `run_id` have
already been deleted by an earlier, interrupted invocation of THIS command produces zero rows to
delete and is silently skipped on a re-run (no error, no double-count, no repeated
`resolve_and_persist_printing` call for it) - safe to re-run this command again after a mid-run
failure without first checking which cards were already processed.

DRY-RUN BY DEFAULT (matches `purge_machine_votes`/`local_calculate_verdicts`/
`reparse_collector_evidence`'s own convention): every counter below (`votes_deleted`/
`skips_deleted`/`skipped_resolved_gate`/`cards_resynced`... `cards_resynced` is always 0 in a dry
run, since nothing was actually deleted for `resolve_and_persist_printing` to react to) is
computed and reported in BOTH modes; only `--write` actually deletes anything or calls
`resolve_and_persist_printing`.

MULTI-RUN-ID CLI ERGONOMICS: `--run-id` is repeatable (`action="append"`) for the common case;
`--run-ids` (comma-separated) is also accepted for the rare case where a shell one-liner
repeating `--run-id` would overflow a reasonable line length - both may be combined and are
de-duplicated (order-preserving) into one target list. At least one `run_id`, from either flag,
is required.
"""

from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_RESCANNABLE_SKIP_REASONS,
)
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import Card, CardPrintingTag, CardScanLog, PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)
from cardpicker.printing_consensus import resolve_and_persist_printing, resolve_printing
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


@dataclass
class RunIdRetractionResult:
    target_run_id: str = ""
    votes_deleted: int = 0
    skips_deleted: int = 0
    skipped_rescannable: int = 0
    cards_resynced: int = 0
    # the SAFETY GATE's own refusal list (module docstring) - kept as pks, not just a count, so
    # the command's own stdout output and the ledger's counters payload can both list exactly
    # which cards need a human look, mirroring reparse_collector_evidence's own
    # gate_refused_card_ids convention.
    skipped_resolved_gate_card_ids: list[int] = field(default_factory=list)

    @property
    def skipped_resolved_gate(self) -> int:
        return len(self.skipped_resolved_gate_card_ids)


def retract_run_id(target_run_id: str, write: bool = False) -> RunIdRetractionResult:
    """
    The actual per-run_id retraction logic (module docstring) - a plain, testable function,
    matching this codebase's own "keep Command.handle() thin" convention
    (`purge_machine_votes.purge_run` / `reparse_collector_evidence.reparse_and_retract`).
    """
    result = RunIdRetractionResult(target_run_id=target_run_id)

    vote_card_ids = set(
        CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=target_run_id).values_list(
            "card_id", flat=True
        )
    )
    skip_qs_all = CardScanLog.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=target_run_id)
    non_rescannable_skip_card_ids = set(
        skip_qs_all.exclude(skip_reason__in=JOIN_KEY_RESCANNABLE_SKIP_REASONS).values_list("card_id", flat=True)
    )
    result.skipped_rescannable = skip_qs_all.filter(skip_reason__in=JOIN_KEY_RESCANNABLE_SKIP_REASONS).count()

    affected_card_ids = sorted(vote_card_ids | non_rescannable_skip_card_ids)

    for card in Card.objects.filter(pk__in=affected_card_ids):
        votes_qs = CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=target_run_id)
        skips_qs = CardScanLog.objects.filter(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=target_run_id
        ).exclude(skip_reason__in=JOIN_KEY_RESCANNABLE_SKIP_REASONS)

        vote_count = votes_qs.count()
        skip_count = skips_qs.count()
        if vote_count == 0 and skip_count == 0:
            # IDEMPOTENCE (module docstring) - an earlier, interrupted invocation of this command
            # already retracted this card's rows for this run_id; nothing left to do or count.
            continue

        # SAFETY GATE (module docstring) - card-level, re-checked LIVE (resolve_printing, not a
        # cached status field) - covers BOTH a resolved printing and a resolved NO_MATCH
        # consensus. Checked BEFORE any deletion, in both dry-run and write mode, so a dry run's
        # own report already reflects exactly what a real run would refuse.
        if resolve_printing(card) is not None:
            result.skipped_resolved_gate_card_ids.append(card.pk)
            continue

        result.votes_deleted += vote_count
        result.skips_deleted += skip_count

        if not write:
            continue

        votes_qs.delete()
        skips_qs.delete()
        resolve_and_persist_printing(card)
        result.cards_resynced += 1

    return result


def retract_run_ids(target_run_ids: list[str], write: bool = False) -> dict[str, RunIdRetractionResult]:
    """Runs `retract_run_id` once per target run_id, in the order given - returns
    `{run_id: RunIdRetractionResult}`, one entry per target, so a caller can report per-run-id
    AND aggregate totals from the same call."""
    return {target_run_id: retract_run_id(target_run_id, write=write) for target_run_id in target_run_ids}


class Command(BaseCommand):
    help = (
        "Pre-pilot zeroing plan: retracts Stage D's stage-d-join-key-v1 CardPrintingTag votes "
        "and non-rescannable CardScanLog skip rows, scoped to one or more specific --run-id "
        "value(s). Never retracts a card currently sitting under a RESOLVED printing_consensus "
        "outcome (printing or NO_MATCH) - such a card is skipped entirely and listed for human "
        "review. Dry-run by default; --write required to delete anything or resync any card. "
        "--write also requires a matching COMPLETED dry-run of the SAME target run_id set within "
        "--dry-run-window-hours (forced-dry-run guard, issue #362) - see --skip-dryrun-check to "
        "override."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-id",
            dest="run_id",
            action="append",
            default=None,
            help="Target run_id to retract. Repeatable (pass multiple times for multiple "
            "run_ids). At least one of --run-id/--run-ids is required.",
        )
        parser.add_argument(
            "--run-ids",
            dest="run_ids_csv",
            default=None,
            help="Comma-separated target run_ids - an alternative to repeating --run-id, for "
            "when that would overflow a shell one-liner. May be combined with --run-id; the "
            "final target list is the de-duplicated union of both.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually delete the scoped votes/scan-logs and resync each affected card's "
            "printing consensus. Default is dry-run: compute and report every counter below "
            "without deleting or resyncing anything. Requires a matching recent COMPLETED "
            "dry-run ledger row for the SAME target run_id set (forced-dry-run guard) unless "
            "--skip-dryrun-check is passed.",
        )
        add_dry_run_guard_arguments(parser, write_flag="--write")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        target_run_ids: list[str] = list(kwargs["run_id"] or [])
        if kwargs["run_ids_csv"]:
            target_run_ids.extend(part.strip() for part in kwargs["run_ids_csv"].split(",") if part.strip())
        # de-duplicate, order-preserving - a run_id repeated across --run-id/--run-ids should
        # never be processed (and reported) twice.
        seen: set[str] = set()
        deduped_run_ids: list[str] = []
        for run_id in target_run_ids:
            if run_id not in seen:
                seen.add(run_id)
                deduped_run_ids.append(run_id)
        target_run_ids = deduped_run_ids

        if not target_run_ids:
            raise CommandError("At least one --run-id (repeatable) or --run-ids (comma-separated) is required.")

        write = kwargs["write"]
        dry_run = not write
        mode = "WRITE" if write else "DRY RUN"
        self.stdout.write(f"[{mode}] retract_stage_d_by_run_id target_run_ids={target_run_ids}")

        # Forced-dry-run guard scope (issue #362): the target run_id set itself defines this
        # invocation's own cohort - "the SAME target run_id set" is the natural reading of "the
        # EXACT same invocation" for this command (module docstring's own MULTI-RUN-ID CLI
        # ERGONOMICS section already treats the de-duplicated, order-preserving list as the one
        # canonical target set regardless of which flag(s) built it).
        scope = scope_hash("target_run_ids", *target_run_ids)
        skip_used = enforce_dry_run_precondition(
            command="retract_stage_d_by_run_id",
            write_mode=write,
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=scope,
        )

        # this command's OWN operational run_id (its PilotRunLedger row) - distinct from, and
        # never to be confused with, the TARGET run_id(s) above being retracted (see the
        # AbstractWeightedVote.run_id docstring's own "NOT reused across invocations" note).
        ledger_run_id = generate_run_id()
        ledger = PilotRunLedger.objects.create(
            run_id=ledger_run_id,
            command="retract_stage_d_by_run_id",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(scope=scope, skip_dryrun_check_used=skip_used),
        )
        try:
            per_run_id = retract_run_ids(target_run_ids, write=write)

            totals = {
                "votes_deleted": 0,
                "skips_deleted": 0,
                "skipped_rescannable": 0,
                "skipped_resolved_gate": 0,
                "cards_resynced": 0,
            }
            counters: dict[str, Any] = {}
            for run_id, result in per_run_id.items():
                gate_ids = result.skipped_resolved_gate_card_ids
                counters[run_id] = {
                    "votes_deleted": result.votes_deleted,
                    "skips_deleted": result.skips_deleted,
                    "skipped_rescannable": result.skipped_rescannable,
                    "skipped_resolved_gate": len(gate_ids),
                    "skipped_resolved_gate_card_ids": gate_ids[:50],
                    "cards_resynced": result.cards_resynced,
                }
                for key in totals:
                    totals[key] += counters[run_id][key]

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the terminal summary prints below - a BrokenPipeError on
            # a severed stdout while printing that summary must never look like this run failed.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(
                ledger.counters, {"target_run_ids": target_run_ids, "per_run_id": counters, "totals": totals}
            )
            ledger.save(update_fields=["status", "finished_at", "counters"])

            with resilient_terminal_output():
                for run_id, result in per_run_id.items():
                    gate_ids = result.skipped_resolved_gate_card_ids
                    self.stdout.write(
                        f"  run_id={run_id}: votes_deleted={result.votes_deleted} "
                        f"skips_deleted={result.skips_deleted} skipped_rescannable={result.skipped_rescannable} "
                        f"skipped_resolved_gate={len(gate_ids)} cards_resynced={result.cards_resynced}"
                    )
                    if gate_ids:
                        self.stdout.write(
                            f"    HUMAN REVIEW NEEDED - run_id={run_id}: {len(gate_ids)} card(s) refused "
                            "retraction (currently a RESOLVED consensus - printing or NO_MATCH). Affected "
                            f"card pks: {gate_ids[:50]}" + (" (truncated)" if len(gate_ids) > 50 else "")
                        )

                self.stdout.write(
                    f"TOTALS: votes_deleted={totals['votes_deleted']} skips_deleted={totals['skips_deleted']} "
                    f"skipped_rescannable={totals['skipped_rescannable']} "
                    f"skipped_resolved_gate={totals['skipped_resolved_gate']} cards_resynced={totals['cards_resynced']}"
                )
                if dry_run:
                    self.stdout.write("Dry run - nothing deleted, no card resynced.")
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed,
            # docs/proposals/stage-e-streaming.md §3 decision (6)/§10) - a no-op if this invocation
            # already reached the COMPLETED save above (a later exception from the terminal print,
            # if resilient_terminal_output didn't already swallow it, must never overwrite that
            # completion), otherwise records a triage-able counters["failure_reason"] alongside the
            # FAILED status, closing the "empty-failed-row" gap that helper's own docstring cites.
            mark_ledger_failed(ledger, exc)
            raise
